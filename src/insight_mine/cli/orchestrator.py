"""Collection orchestrator wiring connectors, filtering, and output writing."""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .output import apply_variety_guard, as_dict, counts_by_kind, now_stamp, write_outputs
from ..utils.text import dedupe_items
from ..utils.cache import cache_db, load_seen, upsert_many
from ..models import Item

# Connectors
from ..connectors import youtube as yt
from ..connectors import reddit as rd
from ..connectors import reddit_scrape as rds

try:
    from ..connectors import ytti as ytti
except Exception:
    class _YTTIStub:
        def status(self): return (False, "transcripts provider not configured")
        def collect(self, *a, **k): return []
    ytti = _YTTIStub()  # type: ignore

try:
    from ..connectors import x_api as xa
except Exception:
    class _XAStub:
        @staticmethod
        def status(): return (False, "not configured")
        @staticmethod
        def collect(): return []
    xa = _XAStub()  # type: ignore


def emit_progress(log: logging.Logger, overall: float, yt_pct: float | None = None, rd_pct: float | None = None) -> None:
    parts = [f"PROGRESS overall={int(overall)}"]
    if yt_pct is not None:
        parts.append(f"yt={int(yt_pct)}")
    if rd_pct is not None:
        parts.append(f"rd={int(rd_pct)}")
    log.info(" ".join(parts))


def _status_tuple(name, mod):
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


def run_collect(args, effective: Dict[str, Any], log: logging.Logger) -> int:
    connector_statuses = {
        "youtube": _status_tuple("YouTube", yt),
        "reddit_api": _status_tuple("Reddit (API)", rd),
        "reddit_scrape": _status_tuple("Reddit (Scrape)", rds),
        "x_api": _status_tuple("X/Twitter", xa),
        "transcripts": _status_tuple("YT-Transcript-IO", ytti),
    }

    log.info("Connector status:")
    for label, (_name, ok_val, reason) in [
        ("YouTube", connector_statuses["youtube"]),
        ("Reddit (API)", connector_statuses["reddit_api"]),
        ("Reddit (Scrape)", connector_statuses["reddit_scrape"]),
        ("X/Twitter", connector_statuses["x_api"]),
        ("YT-Transcript-IO", connector_statuses["transcripts"]),
    ]:
        if ok_val:
            log.info("  %-18s : AVAILABLE", label)
        else:
            log.info("  %-18s : disabled (%s)", label, (reason or ""))

    stat_yt: Dict[str, int] = {}
    stat_rd: Dict[str, int] = {}
    stat_rd_api: Dict[str, int] = {}

    items: List[Item] = []
    yt_progress = 0
    rd_progress = 0

    emit_progress(log, 1, 0, 0)

    langs = effective["langs"]
    yt_videos = effective["yt_videos"]
    yt_order = effective["yt_order"]
    yt_min_views = effective["yt_min_views"]
    yt_min_duration = effective["yt_min_duration"]
    yt_max_comments = effective["yt_max_comments"]
    yt_min_comment_likes = effective["yt_min_comment_likes"]
    yt_max_comment_share = effective["yt_max_comment_share"]

    reddit_limit = effective["reddit_limit"]
    reddit_comments = effective["reddit_comments"]
    reddit_min_score = effective["reddit_min_score"]
    reddit_min_comment_score = effective["reddit_min_comment_score"]
    reddit_max_comment_share = effective["reddit_max_comment_share"]
    yt_allow = effective["yt_allow"]
    yt_block = effective["yt_block"]
    subs = effective["subs"]

    # ---- YouTube (run only if available and requested) ----
    y_items: List[Item] = []
    yt_available = connector_statuses["youtube"][1]
    rd_api_available = connector_statuses["reddit_api"][1]
    rd_scrape_available = connector_statuses["reddit_scrape"][1]
    transcripts_available = connector_statuses["transcripts"][1]

    if yt_videos and yt_videos > 0 and yt_available:
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
    emit_progress(log, 30, yt_progress, rd_progress)

    # ---- Reddit routing (unchanged logic) ----
    r_items: List[Item] = []
    mode = args.reddit_mode
    use_api = rd_api_available
    use_scrape = rd_scrape_available

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
    emit_progress(log, 65, yt_progress, rd_progress)

    # ---- Transcripts ----
    if args.yt_transcripts == "ytti" and transcripts_available:
        video_ids = sorted({it.id for it in y_items if getattr(it, "context", {}).get("channelId") is not None})
        transcripts = ytti.collect(video_ids, per_video_limit=(args.yt_transcripts_limit or None))
        items.extend(transcripts)
    elif args.yt_transcripts != "off":
        ok, reason = ytti.status()
        if not ok:
            log.info("Skipping transcripts: %s", reason)

    # ---- Serialize / Dedupe / Cache / Sample ----
    serial = [as_dict(it) for it in items]
    serial = apply_variety_guard(serial, yt_share=yt_max_comment_share, rd_share=reddit_max_comment_share)

    if args.dedupe:
        before = len(serial)
        serial = dedupe_items(serial)
        log.info("Dedupe reduced items: %d -> %d", before, len(serial))

    dropped_by_cache = 0
    cache_path = args.cache.strip()
    if cache_path and not args.refresh:
        with cache_db(cache_path) as conn:
            seen = load_seen(conn)
            keep = []
            for it in serial:
                key = (it["platform"], it["id"])
                if key in seen:
                    dropped_by_cache += 1
                    continue
                keep.append(it)
            serial = keep

    sampled_n = 0
    if args.sample and args.sample > 0 and len(serial) > args.sample:
        rnd = random.Random(0xC0FFEE)
        serial = rnd.sample(serial, args.sample)
        sampled_n = len(serial)

    run_dir = Path(args.out) / now_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)

    write_outputs(
        run_dir=run_dir,
        serial=serial,
        args=args,
        effective=effective,
        counts=counts_by_kind(serial),
        stats_total={
            "youtube": stat_yt,
            "reddit_scrape": stat_rd,
            "reddit_api": stat_rd_api,
        },
        connectors={
            "youtube": yt_available,
            "reddit_api": rd_api_available,
            "reddit_scrape": rd_scrape_available,
            "transcripts": transcripts_available,
        },
        dropped_by_cache=dropped_by_cache,
        sampled_n=sampled_n,
    )

    emit_progress(log, 90, yt_progress, rd_progress)

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
        with cache_db(cache_path) as conn:
            upsert_many(conn, ((it["platform"], it["id"]) for it in serial))

    log.info("Wrote %d items to %s", len(serial), str(run_dir))
    if dropped_by_cache:
        log.info("Cache skipped %d previously seen items", dropped_by_cache)
    if sampled_n:
        log.info("Sampling applied: %d items kept", sampled_n)
    emit_progress(log, 100, yt_progress, rd_progress)

    def _flat(d: Dict[str, int]) -> str:
        return ", ".join(f"{k}:{v}" for k, v in sorted(d.items())) if d else "-"

    log.info("Telemetry (YouTube): %s", _flat(stat_yt))
    log.info("Telemetry (Reddit scrape): %s", _flat(stat_rd))
    log.info("Telemetry (Reddit API): %s", _flat(stat_rd_api))

    return 0
