"""CLI entrypoint wiring argument parsing to collectors."""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict

from ..utils.logging import setup_logging
from ..utils.text import mask_secret
from .args import build_parser, resolve_settings
from .orchestrator import run_collect


def _log_env(log: logging.Logger) -> None:
    for k in ["YOUTUBE_API_KEY", "YTTI_API_TOKEN", "YTTI_WS_USER", "YTTI_WS_PASS", "IM_OUT_DIR"]:
        v = os.environ.get(k, "")
        log.info("ENV %s=%s", k, mask_secret(v))


def _maybe_explain(args, effective: Dict[str, Any]) -> None:
    if not args.explain:
        return
    print("\nEffective knobs:")
    print(json.dumps({
        "preset": args.preset,
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
        "dedupe": args.dedupe,
        "cache": args.cache, "refresh": args.refresh, "sample": args.sample,
    }, indent=2))
    print()


def main(argv=None):
    setup_logging()
    log = logging.getLogger("insight-mine")

    parser = build_parser()
    args = parser.parse_args(argv)

    _log_env(log)

    if args.cmd == "gui":
        from ..guis.pywebview.app import main as gui_main
        sys.argv = [sys.argv[0]] + (["--env", args.env] if args.env else [])
        return gui_main()

    if args.allow_scraping:
        os.environ["ALLOW_SCRAPING"] = "1"

    if getattr(args, "reddit_limit", None) is None and getattr(args, "reddit_limit_legacy", None) is not None:
        args.reddit_limit = args.reddit_limit_legacy

    effective = resolve_settings(args)
    _maybe_explain(args, effective)

    return run_collect(args, effective, log)
