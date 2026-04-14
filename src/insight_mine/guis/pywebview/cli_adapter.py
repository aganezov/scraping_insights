from __future__ import annotations
import time
import uuid
from pathlib import Path
from typing import Dict


def slug(s: str) -> str:
    s = (s or "").strip().lower().replace(" ", "_")
    return "".join(c for c in s if c.isalnum() or c in ("_", "-"))[:40]


_LEGACY_ARG_ALIASES = {
    "--lang": "--langs",
    "--yt-comments-per-video": "--yt-max-comments",
    "--limit": "--reddit-limit",
    "--rd-comments-per-post": "--reddit-comments",
    "--rd-min-score": "--reddit-min-score",
    "--rd-min-comment-score": "--reddit-min-comment-score",
}

_YOUTUBE_VALUE_FLAGS = {
    "--yt-videos",
    "--yt-max-comments",
    "--yt-min-views",
    "--yt-min-duration",
    "--yt-min-comment-likes",
    "--yt-order",
    "--yt-channel-allow",
    "--yt-channel-block",
    "--yt-max-comment-share",
    "--yt-transcripts",
    "--yt-transcripts-limit",
}
_REDDIT_VALUE_FLAGS = {
    "--subreddits",
    "--reddit-mode",
    "--rd-fetch-budget",
    "--reddit-limit",
    "--reddit-comments",
    "--reddit-min-score",
    "--reddit-min-comment-score",
    "--reddit-max-comment-share",
    "--reddit-source",
    "--reddit-query",
    "--reddit-sort",
    "--reddit-t",
    "--reddit-top-t",
}
_REDDIT_BOOL_FLAGS = {"--allow-scraping"}


def _strip_options(argv: list[str], *, value_flags: set[str], bool_flags: set[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in bool_flags:
            i += 1
            continue
        if arg in value_flags:
            i += 2 if i + 1 < len(argv) else 1
            continue
        out.append(arg)
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out.append(argv[i + 1])
            i += 2
        else:
            i += 1
    return out


def _value_of(argv: list[str], flag: str) -> str | None:
    for i, arg in enumerate(argv[:-1]):
        if arg == flag and not argv[i + 1].startswith("--"):
            return argv[i + 1]
    return None


def normalize_collect_argv(argv: list[str], *, selected: Dict[str, bool] | None = None) -> list[str]:
    normalized: list[str] = []
    i = 0
    while i < len(argv):
        arg = _LEGACY_ARG_ALIASES.get(argv[i], argv[i])
        normalized.append(arg)
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            normalized.append(argv[i + 1])
            i += 2
        else:
            i += 1

    sel = {"youtube": True, "reddit": True}
    if selected:
        sel.update(selected)

    if not sel.get("youtube", True):
        normalized = _strip_options(normalized, value_flags=_YOUTUBE_VALUE_FLAGS, bool_flags=set())
        normalized += ["--yt-videos", "0", "--yt-max-comments", "0"]

    if not sel.get("reddit", True):
        normalized = _strip_options(normalized, value_flags=_REDDIT_VALUE_FLAGS, bool_flags=_REDDIT_BOOL_FLAGS)
        normalized += ["--reddit-mode", "off", "--reddit-limit", "0", "--reddit-comments", "0"]
    else:
        mode = _value_of(normalized, "--reddit-mode")
        if mode in (None, "scrape") and "--allow-scraping" not in normalized:
            normalized.append("--allow-scraping")

    return normalized


def build_collect_cmd(k: dict, env: dict, out_root: Path, *, run_id: str | None = None, create_dirs: bool = True):
    """
    Returns (cmd:list[str], run_id:str, run_dir:Path).
    Builds flags that mirror the v15 "Command preview" (UI contract).
    Only includes Reddit flags when reddit is enabled; same for YT.
    """
    if create_dirs:
        out_root.mkdir(parents=True, exist_ok=True)
    run_id = run_id or f"{time.strftime('%Y%m%d_%H%M%S')}_{slug(k.get('topic') or 'run')}_{uuid.uuid4().hex[:4]}"
    run_dir = out_root / run_id
    if create_dirs:
        (run_dir / "cli_out").mkdir(parents=True, exist_ok=True)

    cmd = [env.get("IM_CLI_BIN", "insight-mine"), "collect",
           "--topic", k.get("topic", ""),
           "--since", k.get("since", "") or "1970-01-01"]

    subs = (k.get("subreddits") or "").strip()
    if subs and k.get("connectors", {}).get("reddit", True):
        cmd += ["--subreddits", subs]

    # language / transcripts / dedupe
    cmd += ["--langs", k.get("lang", "en")]
    if k.get("transcripts") == "auto":
        cmd += ["--yt-transcripts", "ytti"]
    if k.get("dedupe", True):
        cmd += ["--dedupe"]

    # YouTube block
    if k.get("connectors", {}).get("youtube", True) and k.get("yt_videos", 0) > 0:
        cmd += ["--yt-videos", str(k["yt_videos"]),
                "--yt-max-comments", str(k.get("yt_comments_per_video", k.get("yt_max_comments", 60))),
                "--yt-min-views", str(k.get("yt_min_views", 20000)),
                "--yt-min-duration", str(k.get("yt_min_duration", 120)),
                "--yt-min-comment-likes", str(k.get("yt_min_comment_likes", 0)),
                "--yt-order", k.get("yt_order", "viewCount")]

    # Reddit block
    if k.get("connectors", {}).get("reddit", True) and k.get("reddit_limit", 0) > 0:
        reddit_source = k.get("reddit_source", "search")
        cmd += ["--reddit-limit", str(k.get("reddit_limit", 40)),
                "--reddit-comments", str(k.get("reddit_comments", 8)),
                "--reddit-min-score", str(k.get("reddit_min_score", 0)),
                "--reddit-min-comment-score", str(k.get("reddit_min_comment_score", 0)),
                "--reddit-mode", k.get("reddit_mode", "scrape"),
                "--reddit-source", reddit_source]
        if reddit_source == "search":
            query = (k.get("reddit_query") or k.get("topic") or "").strip()
            if query:
                cmd += ["--reddit-query", query]
            cmd += ["--reddit-sort", k.get("reddit_sort", "relevance"),
                    "--reddit-t", k.get("reddit_t", "all")]
        elif reddit_source == "top":
            cmd += ["--reddit-top-t", k.get("reddit_top_t", "week")]
        if k.get("reddit_mode", "scrape") == "scrape":
            cmd += ["--allow-scraping"]

    # Output folder (one run = one subdir)
    cmd += ["--out", str(run_dir / "cli_out")]
    return cmd, run_id, run_dir
