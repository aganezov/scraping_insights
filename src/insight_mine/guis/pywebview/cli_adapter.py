from __future__ import annotations
import time, uuid
from pathlib import Path


def slug(s: str) -> str:
    s = (s or "").strip().lower().replace(" ", "_")
    return "".join(c for c in s if c.isalnum() or c in ("_", "-"))[:40]


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
        cmd += ["--reddit-limit", str(k.get("reddit_limit", 40)),
                "--reddit-comments", str(k.get("reddit_comments", 8)),
                "--reddit-min-score", str(k.get("reddit_min_score", 0)),
                "--reddit-min-comment-score", str(k.get("reddit_min_comment_score", 0)),
                "--reddit-mode", k.get("reddit_mode", "scrape")]

    # Output folder (one run = one subdir)
    cmd += ["--out", str(run_dir / "cli_out")]
    return cmd, run_id, run_dir
