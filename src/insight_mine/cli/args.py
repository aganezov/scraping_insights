"""Argument parsing and effective setting resolution for the CLI."""
from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from typing import Any, Dict

PRESETS: Dict[str, Dict[str, Any]] = {
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

REDDIT_SOURCE_CHOICES = ["search", "hot", "new", "top"]
REDDIT_SEARCH_SORT_CHOICES = ["relevance", "hot", "new", "top", "comments"]
REDDIT_TIME_CHOICES = ["all", "hour", "day", "week", "month", "year"]


def build_parser() -> argparse.ArgumentParser:
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

    c.add_argument(
        "--langs", "--lang",
        dest="langs",
        default=os.environ.get("LANGS", ""),
        help="Comma-separated language codes (e.g., en,es). Empty = no filter.",
    )
    dedupe_group = c.add_mutually_exclusive_group()
    dedupe_group.add_argument("--dedupe", dest="dedupe", action="store_true", help="Enable text-based deduplication.")
    dedupe_group.add_argument("--no-dedupe", dest="dedupe", action="store_false", help="Disable text-based deduplication.")
    c.set_defaults(dedupe=False)

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
    c.add_argument("--reddit-limit", dest="reddit_limit", type=int, default=None,
                   help="Target number of KEPT reddit posts (after filtering).")
    c.add_argument("--limit", dest="reddit_limit_legacy", type=int,
                   help="Alias for --reddit-limit.")
    c.add_argument("--reddit-comments", type=int, default=None)
    c.add_argument("--reddit-min-score", type=int, default=None)
    c.add_argument("--reddit-min-comment-score", type=int, default=None)
    c.add_argument("--reddit-max-comment-share", type=float, default=None)
    c.add_argument("--reddit-source", choices=REDDIT_SOURCE_CHOICES, default=None,
                   help="Scrape source: search uses topic/query; hot/new/top use listing endpoints.")
    c.add_argument("--reddit-query", default=None,
                   help="Explicit Reddit query when using --reddit-source search. Defaults to --topic.")
    c.add_argument("--reddit-sort", choices=REDDIT_SEARCH_SORT_CHOICES, default=None,
                   help="Sort for --reddit-source search.")
    c.add_argument("--reddit-t", dest="reddit_t", choices=REDDIT_TIME_CHOICES, default=None,
                   help="Time window for --reddit-source search.")
    c.add_argument("--reddit-top-t", dest="reddit_top_t", choices=REDDIT_TIME_CHOICES, default=None,
                   help="Time window for --reddit-source top.")

    c.add_argument("--yt-transcripts", choices=["off", "ytti"], default="off")
    c.add_argument("--yt-transcripts-limit", type=int, default=0)

    g = sub.add_parser("gui", help="Launch the Insight Mine desktop GUI.")
    g.add_argument("--env", default=None, help="Path to .env for the GUI")

    c.add_argument("--cache", default="", help="Path to SQLite cache file to skip previously seen items.")
    c.add_argument("--refresh", action="store_true", help="Ignore cache and process all items.")

    return ap


def _resolve_setting(name: str, current, fallback, preset: Dict[str, Any]) -> Any:
    return current if current is not None else (preset.get(name) if name in preset else fallback)


def resolve_settings(args: argparse.Namespace) -> Dict[str, Any]:
    preset = PRESETS.get(args.preset or "", {})
    deprecated_limit = getattr(args, "reddit_limit_legacy", None)

    # Prefer explicit --langs; otherwise preset; otherwise LANGS env
    lang_raw = (args.langs or "").strip()
    if not lang_raw:
        lang_raw = (preset.get("langs") or "") or os.environ.get("LANGS", "")
    langs = [s.strip() for s in (lang_raw or "").split(",") if s.strip()]

    yt_videos = _resolve_setting("yt_videos", args.yt_videos, 30, preset)
    yt_order = _resolve_setting("yt_order", args.yt_order, "viewCount", preset)
    yt_min_views = _resolve_setting("yt_min_views", args.yt_min_views, 10000, preset)
    yt_min_duration = _resolve_setting("yt_min_duration", args.yt_min_duration, 120, preset)
    yt_max_comments = _resolve_setting("yt_max_comments", args.yt_max_comments, 20, preset)
    yt_min_comment_likes = _resolve_setting("yt_min_comment_likes", args.yt_min_comment_likes, 0, preset)
    yt_max_comment_share = _resolve_setting("yt_max_comment_share", args.yt_max_comment_share, None, preset)

    reddit_limit = _resolve_setting("reddit_limit", args.reddit_limit, deprecated_limit if deprecated_limit is not None else 40, preset)
    reddit_comments = _resolve_setting("reddit_comments", args.reddit_comments, 8, preset)
    reddit_min_score = _resolve_setting("reddit_min_score", args.reddit_min_score, 0, preset)
    reddit_min_comment_score = _resolve_setting("reddit_min_comment_score", args.reddit_min_comment_score, 0, preset)
    reddit_max_comment_share = _resolve_setting("reddit_max_comment_share", args.reddit_max_comment_share, None, preset)
    reddit_source = _resolve_setting("reddit_source", getattr(args, "reddit_source", None), "search", preset)
    reddit_query = (getattr(args, "reddit_query", None) or "").strip()
    reddit_sort = _resolve_setting("reddit_sort", getattr(args, "reddit_sort", None), "new", preset)
    reddit_t = _resolve_setting("reddit_t", getattr(args, "reddit_t", None), "all", preset)
    reddit_top_t = _resolve_setting("reddit_top_t", getattr(args, "reddit_top_t", None), "week", preset)

    yt_allow = [s.strip() for s in (args.yt_channel_allow.split(",") if args.yt_channel_allow else []) if s.strip()]
    yt_block = [s.strip() for s in (args.yt_channel_block.split(",") if args.yt_channel_block else []) if s.strip()]
    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    return {
        "preset": preset,
        "langs": langs,
        "yt_videos": yt_videos,
        "yt_order": yt_order,
        "yt_min_views": yt_min_views,
        "yt_min_duration": yt_min_duration,
        "yt_max_comments": yt_max_comments,
        "yt_min_comment_likes": yt_min_comment_likes,
        "yt_max_comment_share": yt_max_comment_share,
        "reddit_limit": reddit_limit,
        "reddit_comments": reddit_comments,
        "reddit_min_score": reddit_min_score,
        "reddit_min_comment_score": reddit_min_comment_score,
        "reddit_max_comment_share": reddit_max_comment_share,
        "reddit_source": reddit_source,
        "reddit_query": reddit_query,
        "reddit_sort": reddit_sort,
        "reddit_t": reddit_t,
        "reddit_top_t": reddit_top_t,
        "yt_allow": yt_allow,
        "yt_block": yt_block,
        "subs": subs,
        "deprecated_limit": deprecated_limit,
    }
