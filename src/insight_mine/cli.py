from __future__ import annotations
import argparse, logging, os, json, random, sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Tuple
from collections import defaultdict

from .utils.logging import setup_logging
from .utils.io import write_jsonl, write_txt
from .utils.text import dedupe_items
from .utils.cache import open_db, load_seen, upsert_many
from .models import Item

# Connectors
from .connectors import youtube as yt
from .connectors import reddit as rd
from .connectors import reddit_scrape as rds
try:
    from .connectors import ytti as ytti
except Exception:
    class _YTTIStub:
        def status(self): return (False, "transcripts provider not configured")
        def collect(self, *a, **k): return []
    ytti = _YTTIStub()  # type: ignore

try:
    from .connectors import x_api as xa
except Exception:
    class _XAStub:
        @staticmethod
        def status(): return (False, "not configured")
        @staticmethod
        def collect(): return []
    xa = _XAStub()  # type: ignore


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _as_dict(item: Item) -> dict:
    return {
        "platform": item.platform, "id": item.id, "url": item.url, "author": item.author,
        "created_at": item.created_at, "title": item.title, "text": item.text,
        "metrics": item.metrics, "context": item.context,
    }


def _sort_key_for_comment(it: Dict[str, Any]) -> int:
    m = it.get("metrics") or {}
    return int(m.get("likes") or m.get("score") or 0)


def apply_variety_guard(serial: List[Dict[str, Any]], yt_share: float | None, rd_share: float | None) -> List[Dict[str, Any]]:
    out = list(serial)
    if yt_share and 0.0 < yt_share < 1.0:
        yt_comments = [(i, it) for i, it in enumerate(out)
                       if it.get("platform") == "youtube"
                       and it.get("context", {}).get("videoId")
                       and (it.get("title") is None)]
        total = len(yt_comments)
        if total > 0:
            per_group_max = max(1, int(total * yt_share))
            groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
            for idx, it in yt_comments:
                groups[it["context"]["videoId"]].append((idx, it))
            for vid in groups:
                groups[vid].sort(key=lambda t: _sort_key_for_comment(t[1]), reverse=True)
            to_remove = set()
            for arr in groups.values():
                for j, (idx, _) in enumerate(arr):
                    if j >= per_group_max:
                        to_remove.add(idx)
            out = [it for i, it in enumerate(out) if i not in to_remove]

    if rd_share and 0.0 < rd_share < 1.0:
        rd_comments = [(i, it) for i, it in enumerate(out)
                       if it.get("platform") == "reddit"
                       and str(it.get("id", "")).startswith("t1_")]
        total = len(rd_comments)
        if total > 0:
            per_group_max = max(1, int(total * rd_share))
            groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
            for idx, it in rd_comments:
                pid = it.get("context", {}).get("post_id") or ""
                groups[pid].append((idx, it))
            for pid in groups:
                groups[pid].sort(key=lambda t: _sort_key_for_comment(t[1]), reverse=True)
            to_remove = set()
            for arr in groups.values():
                for j, (idx, _) in enumerate(arr):
                    if j >= per_group_max:
                        to_remove.add(idx)
            out = [it for i, it in enumerate(out) if i not in to_remove]
    return out


def _counts_by_kind(serial: List[Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = defaultdict(int)
    for it in serial:
        if it["platform"] == "youtube":
            if it.get("title") == "Transcript" or (isinstance(it.get("id"), str) and it["id"].endswith(":transcript")):
                c["youtube_transcript"] += 1
            elif it.get("title"):
                c["youtube_video"] += 1
            else:
                c["youtube_comment"] += 1
        elif it["platform"] == "reddit":
            if str(it.get("id", "")).startswith("t3_"):
                c["reddit_post"] += 1
            else:
                c["reddit_comment"] += 1
        else:
            c[f"{it['platform']}"] += 1
    return dict(c)


def _emit_progress(log: logging.Logger, overall: float, yt_pct: float | None = None, rd_pct: float | None = None) -> None:
    parts = [f"PROGRESS overall={int(overall)}"]
    if yt_pct is not None:
        parts.append(f"yt={int(yt_pct)}")
    if rd_pct is not None:
        parts.append(f"rd={int(rd_pct)}")
    log.info(" ".join(parts))


# --- New: robust status normalizer prevents unpack errors ---
def _status_tuple(name, mod):
    """
    Always return (name, ok, reason) regardless of what mod.status() returns.
    This prevents 'expected 3, got 2' when a connector returns a malformed shape.
    """
    try:
        if hasattr(mod, "status"):
            res = mod.status()
            if isinstance(res, tuple):
                if len(res) == 2:
                    ok, reason = bool(res[0]), (None if res[1] in ("", None) else str(res[1]))
                elif len(res) == 1:
                    ok, reason = bool(res[0]), None
                else:
                    ok, reason = bool(res[0]), (None if res[1] in ("", None) else str(res[1]))
            else:
                ok, reason = bool(res), None
        else:
            ok, reason = False, "status() missing"
    except Exception as e:
        ok, reason = False, f"status() error: {e}"
    return (name, ok, reason)


def main():
    setup_logging()
    log = logging.getLogger("insight-mine")

    ap = argparse.ArgumentParser(prog="insight-mine", description="Collect social content and write paste-ready files.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    dflt_since = (date.today() - timedelta(days=30)).isoformat()
    c = sub.add_parser("collect", help="Collect items for a topic.")
    c.add_argument("--topic", required=True)
    c.add_argument("--since", default=dflt_since)
    c.add_argument("--out", default="out", help="Output directory")
    c.add_argument("--explain", action="store_true", help="Print effective knobs resolved from preset + flags.")
    c.add_argument("--sample", type=int, default=0, help="Uniformly sample N items after filters/caps/dedupe (0=off).")

    c.add_argument("--preset", choices=["strict", "balanced", "wide"], default=None,
                   help="Apply a quality preset; explicit flags override preset values.")

    c.add_argument("--langs", default=os.environ.get("LANGS", ""), help="Comma-separated language codes (e.g., en,es). Empty = no filter.")
    c.add_argument("--dedupe", action="store_true", help="Enable text-based deduplication.")

    c.add_argument("--yt-videos", type=int, default=None)
    c.add_argument("--yt-order", choices=["viewCount", "date", "relevance"], default=None)
    c.add_argument("--yt-min-views", type=int, default=None)
    c.add_argument("--yt-min-duration", type=int, default=None)
    c.add_argument("--yt-max-comments", type=int, default=None)
    c.add_argument("--yt-min-comment-likes", type=int, default=None)
    c.add_argument("--yt-channel-allow", default="")
    c.add_argument("--yt-channel-block", default="")
    c.add_argument("--yt-max-comment-share", type=float, default=None)

    c.add_argument("--subreddits", default="")
    c.add_argument("--reddit-mode", choices=["auto", "api", "scrape", "off"], default="auto")
    c.add_argument("--allow-scraping", action="store_true")
    c.add_argument("--rd-fetch-budget", dest="rd_fetch_budget", type=int,
                   help="Soft cap on raw Reddit candidates when using fetch-until-keep (default: reddit_limit * 12).")
    c.add_argument("--reddit-limit", dest="reddit_limit", type=int, default=40,
                   help="Target number of KEPT reddit posts (after filtering).")
    c.add_argument("--limit", dest="reddit_limit_legacy", type=int,
                   help="Alias for --reddit-limit.")
    c.add_argument("--reddit-comments", type=int, default=None)
    c.add_argument("--reddit-min-score", type=int, default=None)
    c.add_argument("--reddit-min-comment-score", type=int, default=None)
    c.add_argument("--reddit-max-comment-share", type=float, default=None)

    c.add_argument("--yt-transcripts", choices=["off", "ytti"], default="off")
    c.add_argument("--yt-transcripts-limit", type=int, default=0)

    g = sub.add_parser("gui", help="Launch the Insight Mine desktop GUI.")
    g.add_argument("--env", default=None, help="Path to .env for the GUI")

    c.add_argument("--cache", default="", help="Path to SQLite cache file to skip previously seen items.")
    c.add_argument("--refresh", action="store_true", help="Ignore cache and process all items.")

    args = ap.parse_args()

    # Emit key env values at start (unmasked) to confirm what the process received.
    for k in ["YOUTUBE_API_KEY", "YTTI_API_TOKEN", "YTTI_WS_USER", "YTTI_WS_PASS", "IM_OUT_DIR"]:
        v = os.environ.get(k, "")
        log.info("ENV %s=%s", k, v)

    if args.cmd == "gui":
        from .guis.pywebview.app import main as gui_main
        sys.argv = [sys.argv[0]] + (["--env", args.env] if args.env else [])
        return gui_main()

    if args.allow_scraping:
        os.environ["ALLOW_SCRAPING"] = "1"

    if getattr(args, "reddit_limit", None) is None and getattr(args, "reddit_limit_legacy", None) is not None:
        args.reddit_limit = args.reddit_limit_legacy

    PRESETS = {
        "strict": {
            "yt_videos": 25, "yt_order": "viewCount",
            "yt_min_views": 50000, "yt_min_duration": 180,
            "yt_max_comments": 10, "yt_min_comment_likes": 5,
            "yt_max_comment_share": 0.15,
            "reddit_limit": 20, "reddit_comments": 6,
            "reddit_min_score": 5, "reddit_min_comment_score": 2,
            "reddit_max_comment_share": 0.25,
            "langs": "en",
        },
        "balanced": {
            "yt_videos": 25, "yt_order": "viewCount",
            "yt_min_views": 20000, "yt_min_duration": 120,
            "yt_max_comments": 12, "yt_min_comment_likes": 2,
            "yt_max_comment_share": 0.20,
            "reddit_limit": 20, "reddit_comments": 8,
            "reddit_min_score": 2, "reddit_min_comment_score": 1,
            "reddit_max_comment_share": 0.33,
            "langs": "en",
        },
        "wide": {
            "yt_videos": 25, "yt_order": "relevance",
            "yt_min_views": 1000, "yt_min_duration": 60,
            "yt_max_comments": 20, "yt_min_comment_likes": 0,
            "yt_max_comment_share": 0.40,
            "reddit_limit": 30, "reddit_comments": 12,
            "reddit_min_score": 0, "reddit_min_comment_score": 0,
            "reddit_max_comment_share": 0.50,
            "langs": "",
        },
    }
    p = PRESETS.get(args.preset or "", {})

    def _eff(name: str, current, fallback):
        return current if current is not None else (p.get(name) if name in p else fallback)

    langs = [s.strip() for s in ((_eff("langs", args.langs, os.environ.get("LANGS", "")) or "").split(",")) if s.strip()]
    yt_videos = _eff("yt_videos", args.yt_videos, 30)
    yt_order = _eff("yt_order", args.yt_order, "viewCount")
    yt_min_views = _eff("yt_min_views", args.yt_min_views, 10000)
    yt_min_duration = _eff("yt_min_duration", args.yt_min_duration, 120)
    yt_max_comments = _eff("yt_max_comments", args.yt_max_comments, 20)
    yt_min_comment_likes = _eff("yt_min_comment_likes", args.yt_min_comment_likes, 0)
    yt_max_comment_share = _eff("yt_max_comment_share", args.yt_max_comment_share, None)

    deprecated_limit = args.reddit_limit_legacy
    reddit_limit = _eff("reddit_limit", args.reddit_limit, deprecated_limit if deprecated_limit is not None else 40)
    reddit_comments = _eff("reddit_comments", args.reddit_comments, 8)
    reddit_min_score = _eff("reddit_min_score", args.reddit_min_score, 0)
    reddit_min_comment_score = _eff("reddit_min_comment_score", args.reddit_min_comment_score, 0)
    reddit_max_comment_share = _eff("reddit_max_comment_share", args.reddit_max_comment_share, None)

    yt_allow = [s.strip() for s in (args.yt_channel_allow.split(",") if args.yt_channel_allow else []) if s.strip()]
    yt_block = [s.strip() for s in (args.yt_channel_block.split(",") if args.yt_channel_block else []) if s.strip()]
    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    if args.explain:
        print("\nEffective knobs:")
        print(json.dumps({
            "preset": args.preset,
            "langs": langs,
            "yt": {
                "videos": yt_videos, "order": yt_order,
                "min_views": yt_min_views, "min_duration": yt_min_duration,
                "max_comments": yt_max_comments, "min_comment_likes": yt_min_comment_likes,
                "max_comment_share": yt_max_comment_share,
                "allow": yt_allow, "block": yt_block,
            },
            "reddit": {
                "limit": reddit_limit, "comments": reddit_comments,
                "min_score": reddit_min_score, "min_comment_score": reddit_min_comment_score,
                "max_comment_share": reddit_max_comment_share,
                "mode": args.reddit_mode, "subreddits": subs,
            },
            "dedupe": args.dedupe,
            "cache": args.cache, "refresh": args.refresh, "sample": args.sample,
        }, indent=2))
        print()

    log.info("Connector status:")
    for name, ok, reason in [
        _status_tuple("YouTube", yt),
        _status_tuple("Reddit (API)", rd),
        _status_tuple("Reddit (Scrape)", rds),
        _status_tuple("X/Twitter", xa),
        _status_tuple("YT-Transcript-IO", ytti),
    ]:
        if ok:
            log.info("  %-18s : AVAILABLE", name)
        else:
            log.info("  %-18s : disabled (%s)", name, (reason or ""))

    stat_yt: Dict[str, int] = {}
    stat_rd: Dict[str, int] = {}
    stat_rd_api: Dict[str, int] = {}

    items: List[Item] = []
    yt_progress = 0
    rd_progress = 0

    _emit_progress(log, 1, 0, 0)

    # ---- YouTube (run only if available and requested) ----
    y_items: List[Item] = []
    if yt_videos and yt_videos > 0 and _status_tuple("YouTube", yt)[1]:
        y_items = yt.collect(
            topic=args.topic, since_iso=args.since,
            max_videos=yt_videos,
            comments_per_video=yt_max_comments,
            order=yt_order,
            min_views=yt_min_views,
            min_duration_sec=yt_min_duration,
            min_comment_likes=yt_min_comment_likes,
            langs=langs,
            channel_allow=yt_allow,
            channel_block=yt_block,
            stats=stat_yt,
        )
    items.extend(y_items)
    yt_progress = 40 if y_items else 0
    _emit_progress(log, 30, yt_progress, rd_progress)

    # ---- Reddit routing (unchanged logic) ----
    r_items: List[Item] = []
    mode = args.reddit_mode
    use_api = _status_tuple("Reddit (API)", rd)[1]
    use_scrape = _status_tuple("Reddit (Scrape)", rds)[1]

    if mode == "api":
        if use_api:
            r_items = rd.collect(args.topic, args.since, limit_posts=reddit_limit, comments_per_post=reddit_comments,
                                 subreddits=subs, min_score=reddit_min_score, min_comment_score=reddit_min_comment_score, langs=langs, stats=stat_rd_api)
        else:
            logging.warning("Reddit API requested but unavailable.")
    elif mode == "scrape":
        if use_scrape:
            r_items = rds.collect(args.topic, args.since, limit_posts=reddit_limit, comments_per_post=reddit_comments,
                                  subreddits=subs, min_score=reddit_min_score, min_comment_score=reddit_min_comment_score, langs=langs, stats=stat_rd)
        else:
            logging.warning("Reddit scraping requested but disabled. Use --allow-scraping or ALLOW_SCRAPING=1.")
    elif mode == "off":
        r_items = []
    else:
        if use_api:
            r_items = rd.collect(args.topic, args.since, limit_posts=reddit_limit, comments_per_post=reddit_comments,
                                 subreddits=subs, min_score=reddit_min_score, min_comment_score=reddit_min_comment_score, langs=langs, stats=stat_rd_api)
        elif use_scrape:
            r_items = rds.collect(args.topic, args.since, limit_posts=reddit_limit, comments_per_post=reddit_comments,
                                  subreddits=subs, min_score=reddit_min_score, min_comment_score=reddit_min_comment_score, langs=langs, stats=stat_rd)

    items.extend(r_items)
    rd_progress = 40 if r_items else 0
    _emit_progress(log, 65, yt_progress, rd_progress)

    # ---- Transcripts (unchanged) ----
    if args.yt_transcripts == "ytti" and _status_tuple("YT-Transcript-IO", ytti)[1]:
        video_ids = sorted({it.id for it in y_items if getattr(it, "context", {}).get("channelId") is not None})
        transcripts = ytti.collect(video_ids, per_video_limit=(args.yt_transcripts_limit or None))
        items.extend(transcripts)
    elif args.yt_transcripts != "off":
        ok, reason = ytti.status()
        if not ok:
            log.info("Skipping transcripts: %s", reason)

    # ---- Serialize / Dedupe / Cache / Sample (unchanged) ----
    serial = [_as_dict(it) for it in items]
    serial = apply_variety_guard(serial, yt_share=yt_max_comment_share, rd_share=reddit_max_comment_share)

    if args.dedupe:
        before = len(serial)
        serial = dedupe_items(serial)
        log.info("Dedupe reduced items: %d -> %d", before, len(serial))

    dropped_by_cache = 0
    cache_path = args.cache.strip()
    if cache_path and not args.refresh:
        conn = open_db(cache_path)
        seen = load_seen(conn)
        keep = []
        for it in serial:
            key = (it["platform"], it["id"])
            if key in seen:
                dropped_by_cache += 1
                continue
            keep.append(it)
        serial = keep
        conn.close()

    sampled_n = 0
    if args.sample and args.sample > 0 and len(serial) > args.sample:
        rnd = random.Random(0xC0FFEE)
        serial = rnd.sample(serial, args.sample)
        sampled_n = len(serial)

    run_dir = Path(args.out) / _now_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(run_dir / "raw.jsonl", serial)

    lines = []
    for it in serial:
        ttl = f"{it['title']} — " if it.get("title") else ""
        snippet = (it.get("text") or "").strip().replace("\n", " ")
        if len(snippet) > 1200:
            snippet = snippet[:1200] + "…"
        lines.append(f"[{it['platform']}] {ttl}{snippet}\n{it['url']}")
    write_txt(run_dir / "paste-ready.txt", lines)
    _emit_progress(log, 90, yt_progress, rd_progress)

    counts = _counts_by_kind(serial)
    manifest = {
        "run_id": run_dir.name,
        "topic": args.topic,
        "since": args.since,
        "preset": args.preset,
        "effective": {
            "langs": langs,
            "yt": {
                "videos": yt_videos, "order": yt_order,
                "min_views": yt_min_views, "min_duration": yt_min_duration,
                "max_comments": yt_max_comments, "min_comment_likes": yt_min_comment_likes,
                "max_comment_share": yt_max_comment_share,
                "allow": yt_allow, "block": yt_block,
            },
            "reddit": {
                "limit": reddit_limit, "comments": reddit_comments,
                "min_score": reddit_min_score, "min_comment_score": reddit_min_comment_score,
                "max_comment_share": reddit_max_comment_share,
                "mode": args.reddit_mode, "subreddits": subs,
            },
            "dedupe": args.dedupe, "cache": cache_path, "refresh": args.refresh, "sample": args.sample,
        },
        "connectors": {
            "youtube": _status_tuple("YouTube", yt)[1],
            "reddit_api": _status_tuple("Reddit (API)", rd)[1],
            "reddit_scrape": _status_tuple("Reddit (Scrape)", rds)[1],
            "transcripts": _status_tuple("YT-Transcript-IO", ytti)[1],
        },
        "counts": {"total": len(serial), **counts},
        "dropped_by_cache": dropped_by_cache,
        "sampled": sampled_n or None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    stats_total = {
        "youtube": stat_yt,
        "reddit_scrape": stat_rd,
        "reddit_api": stat_rd_api,
    }
    (run_dir / "stats.json").write_text(json.dumps(stats_total, indent=2), encoding="utf-8")

    latest = Path(args.out) / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            try:
                latest.unlink()
            except Exception:
                pass
        latest.symlink_to(run_dir.name)
    except Exception:
        (Path(args.out) / "latest.txt").write_text(str(run_dir), encoding="utf-8")

    if cache_path:
        conn = open_db(cache_path)
        upsert_many(conn, ((it["platform"], it["id"]) for it in serial))
        conn.close()

    log.info("Wrote %d items to %s", len(serial), str(run_dir))
    if dropped_by_cache:
        log.info("Cache skipped %d previously seen items", dropped_by_cache)
    if sampled_n:
        log.info("Sampling applied: %d items kept", sampled_n)
    _emit_progress(log, 100, yt_progress, rd_progress)

    def _flat(d: Dict[str, int]) -> str:
        return ", ".join(f"{k}:{v}" for k, v in sorted(d.items())) if d else "-"

    log.info("Telemetry (YouTube): %s", _flat(stat_yt))
    log.info("Telemetry (Reddit scrape): %s", _flat(stat_rd))
    log.info("Telemetry (Reddit API): %s", _flat(stat_rd_api))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
