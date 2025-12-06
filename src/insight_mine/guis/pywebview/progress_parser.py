"""Shared parsing utilities for CLI stdout progress and telemetry."""
from __future__ import annotations

import json
import re
from typing import Dict, Optional, Tuple

# Shared regex patterns for CLI output parsing
PROG_RE = re.compile(r"PROGRESS\s+overall=(\d+)(?:\s+yt=(\d+))?(?:\s+rd=(\d+))?", re.I)
TEL_RE = re.compile(r"Telemetry\s+\((YouTube|Reddit(?: [^)]+)?)\):\s*(.*)$", re.I)
WROTE_RE = re.compile(r"Wrote\s+(\d+)\s+items\b", re.I)
KEPT_RE = re.compile(r"\b(?P<k>(yt_video_kept|yt_comment_kept|rd_post_kept|rd_comment_kept))\s*:\s*(?P<v>\d+)")


def parse_json_event(line: str) -> Optional[Dict]:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def parse_progress_line(line: str) -> Optional[Dict[str, Optional[int]]]:
    m = PROG_RE.search(line)
    if not m:
        return None
    overall = int(m.group(1) or 0)
    youtube = int(m.group(2)) if m.group(2) else None
    reddit = int(m.group(3)) if m.group(3) else None
    return {"overall": overall, "youtube": youtube, "reddit": reddit}


def parse_telemetry_line(line: str) -> Optional[Tuple[str, str]]:
    t = TEL_RE.search(line)
    if not t:
        return None
    src = t.group(1) or ""
    tail = t.group(2) or ""
    return src, tail


def parse_wrote_line(line: str) -> Optional[int]:
    w = WROTE_RE.search(line)
    if not w:
        return None
    return int(w.group(1))


def parse_kept_from_tail(tail: str) -> tuple[int, int]:
    """Return (parents_kept, comments_kept) from a telemetry tail string."""
    parents = comments = 0
    for m in KEPT_RE.finditer(tail or ""):
        k, v = m.group("k"), int(m.group("v"))
        if k.endswith("video_kept") or k.endswith("post_kept"):
            parents += v
        elif k.endswith("comment_kept"):
            comments += v
    return parents, comments


def parse_kept_pairs(tail: str, source: str) -> tuple[int, int]:
    """
    Returns (parents, comments) from telemetry '... foo_kept:NN ...' tail.
    YouTube keys: yt_video_kept, yt_comment_kept
    Reddit  keys: rd_post_kept, rd_comment_kept (if present)
    Unknowns are ignored.
    """
    p = c = 0
    for tok in (tail or "").split(","):
        tok = tok.strip()
        if ":" not in tok:
            continue
        k, v = tok.split(":", 1)
        try:
            n = int((v or "0").strip())
        except Exception:
            n = 0
        ks = k.strip().lower()
        if source.lower().startswith("youtube"):
            if "video_kept" in ks:
                p += n
            elif "comment_kept" in ks:
                c += n
        else:
            if "post_kept" in ks:
                p += n
            elif "comment_kept" in ks:
                c += n
    return p, c
