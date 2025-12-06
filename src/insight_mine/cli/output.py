"""Output helpers for serializing runs and applying variety guards."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from collections import defaultdict

from ..utils.io import write_jsonl, write_txt
from ..models import Item

SNIPPET_MAX_LEN = 1200


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def as_dict(item: Item) -> dict:
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
            groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
            for idx, it in yt_comments:
                groups[it["context"]["videoId"]].append((idx, it))
            for vid in groups:
                groups[vid].sort(key=lambda t: _sort_key_for_comment(t[1]), reverse=True)
            to_remove = set()
            for arr in groups.values():
                per_group_max = max(1, int(len(arr) * yt_share))
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
            groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
            for idx, it in rd_comments:
                pid = it.get("context", {}).get("post_id") or ""
                groups[pid].append((idx, it))
            for pid in groups:
                groups[pid].sort(key=lambda t: _sort_key_for_comment(t[1]), reverse=True)
            to_remove = set()
            for arr in groups.values():
                per_group_max = max(1, int(len(arr) * rd_share))
                for j, (idx, _) in enumerate(arr):
                    if j >= per_group_max:
                        to_remove.add(idx)
            out = [it for i, it in enumerate(out) if i not in to_remove]
    return out


def counts_by_kind(serial: List[Dict[str, Any]]) -> Dict[str, int]:
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


def write_outputs(
    run_dir: Path,
    serial: List[Dict[str, Any]],
    args,
    effective: Dict[str, Any],
    counts: Dict[str, int],
    stats_total: Dict[str, Any],
    connectors: Dict[str, bool],
    dropped_by_cache: int,
    sampled_n: int,
) -> None:
    write_jsonl(run_dir / "raw.jsonl", serial)

    lines = []
    for it in serial:
        ttl = f"{it['title']} — " if it.get("title") else ""
        snippet = (it.get("text") or "").strip().replace("\n", " ")
        if len(snippet) > SNIPPET_MAX_LEN:
            snippet = snippet[:SNIPPET_MAX_LEN] + "…"
        lines.append(f"[{it['platform']}] {ttl}{snippet}\n{it['url']}")
    write_txt(run_dir / "paste-ready.txt", lines)

    manifest = {
        "run_id": run_dir.name,
        "topic": args.topic,
        "since": args.since,
        "preset": args.preset,
        "effective": {
            "langs": effective["langs"],
            "yt": {
                "videos": effective["yt_videos"], "order": effective["yt_order"],
                "min_views": effective["yt_min_views"], "min_duration": effective["yt_min_duration"],
                "max_comments": effective["yt_max_comments"], "min_comment_likes": effective["yt_min_comment_likes"],
                "max_comment_share": effective["yt_max_comment_share"],
                "allow": effective["yt_allow"], "block": effective["yt_block"],
            },
            "reddit": {
                "limit": effective["reddit_limit"], "comments": effective["reddit_comments"],
                "min_score": effective["reddit_min_score"], "min_comment_score": effective["reddit_min_comment_score"],
                "max_comment_share": effective["reddit_max_comment_share"],
                "mode": args.reddit_mode, "subreddits": effective["subs"],
            },
            "dedupe": args.dedupe, "cache": args.cache.strip(), "refresh": args.refresh, "sample": args.sample,
        },
        "connectors": connectors,
        "counts": {"total": len(serial), **counts},
        "dropped_by_cache": dropped_by_cache or 0,
        "sampled": sampled_n or None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (run_dir / "stats.json").write_text(json.dumps(stats_total, indent=2), encoding="utf-8")
