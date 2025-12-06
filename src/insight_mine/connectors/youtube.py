# src/insight_mine/connectors/youtube.py
from __future__ import annotations

import os
import time
import logging
from typing import Dict, Any, List, Tuple, Iterable
from itertools import islice

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httplib2

from ..config import get_secret
from ..models import Item
from ..utils.text import keep_by_lang

log = logging.getLogger("insight_mine.connectors.youtube")

# ---------------- Tunables (override by env if needed) ----------------
HTTP_TIMEOUT_SEC         = int(os.getenv("YT_HTTP_TIMEOUT", "20"))      # per HTTP call
SEARCH_PAGE_LIMIT        = int(os.getenv("YT_SEARCH_PAGE_LIMIT", "6"))  # cap search pages
THREADS_PAGE_LIMIT       = int(os.getenv("YT_THREADS_PAGE_LIMIT", "10"))# cap comments pages
COMMENTS_DEADLINE_SEC    = int(os.getenv("YT_COMMENT_DEADLINE_SEC", "45"))  # wall-clock per video

# ---------------- Public API expected by cli.py -----------------------

def status() -> Tuple[bool, str]:
    """
    Returns (ok, reason). cli.py normalizes via _status_tuple().
    Uses get_secret() which checks os.environ and .env fallback.
    """
    key = get_secret("YOUTUBE_API_KEY")
    if not key:
        return (False, "YOUTUBE_API_KEY not set.")
    return (True, "AVAILABLE")


def collect(
    topic: str,
    since_iso: str,
    max_videos: int,
    comments_per_video: int,
    order: str,
    min_views: int,
    min_duration_sec: int,
    min_comment_likes: int,
    langs: List[str],
    channel_allow: List[str],
    channel_block: List[str],
    stats: Dict[str, int],
) -> List[Item]:
    """
    Fetch-until-keep: max_videos is the KEPT target after filtering.
    Uses a soft budget of max(8, max_videos*8) candidates, bounded by
    page caps and HTTP timeouts so we never loop forever.

    Args:
        topic: Search query (omit q param if blank)
        since_iso: ISO date string for publishedAfter
        max_videos: Target number of KEPT videos
        comments_per_video: Max comments to fetch per video
        order: YouTube search order (viewCount, date, relevance)
        min_views: Drop videos below this view count
        min_duration_sec: Drop videos shorter than this
        min_comment_likes: Drop comments below this like count
        langs: Language filter (light heuristic via keep_by_lang)
        channel_allow: If non-empty, only keep videos from these channels
        channel_block: Block videos from these channels
        stats: Dict to mutate in-place with telemetry counters

    Returns:
        List[Item] - videos (with title) and comments (no title)
    """
    api_key = get_secret("YOUTUBE_API_KEY")
    items: List[Item] = []

    # Initialize stats counters
    stats.setdefault("yt_video_kept", 0)
    stats.setdefault("yt_comment_kept", 0)

    # Short-circuit if no videos requested
    if max_videos <= 0:
        log.info("YT fetch-until-keep: target=%s budget=%s (short-circuit)", max_videos, 0)
        return items

    # Short-circuit if no API key
    if not api_key:
        log.warning("YOUTUBE_API_KEY missing; returning 0 kept.")
        return items

    # Normalize channel lists to lowercase for case-insensitive matching
    allow_set = {c.lower().strip() for c in channel_allow if c.strip()}
    block_set = {c.lower().strip() for c in channel_block if c.strip()}

    # Build client with explicit timeouts
    yt = _build_client(api_key)

    target = int(max_videos)
    budget = max(8, target * 8)  # upper bound on *candidates*, not kept
    rel_lang = langs[0] if langs else "en"

    log.info(
        "YT fetch-until-keep: target=%s budget=%s buckets=[None] rel_lang=%s order=%s",
        target, budget, rel_lang, (order or "viewCount")
    )

    # ---------- 1) Collect candidate IDs (bounded pages) ----------
    ids: List[str] = []
    search_params: Dict[str, Any] = {
        "part": "id",
        "type": "video",
        "publishedAfter": (since_iso if "T" in since_iso else since_iso + "T00:00:00Z"),
        "order": (order or "viewCount"),
        "safeSearch": "none",
        "maxResults": 50,
    }
    # Only add q param if topic is non-empty (allows browsing without search)
    if topic and topic.strip():
        search_params["q"] = topic.strip()
    # Only add relevanceLanguage if we have a language preference
    if rel_lang:
        search_params["relevanceLanguage"] = rel_lang

    try:
        req = yt.search().list(**search_params)
    except Exception as e:
        log.warning("Failed to create search request: %s", e)
        return items

    page_count = 0
    while req is not None and len(ids) < max(budget, target) and page_count < SEARCH_PAGE_LIMIT:
        try:
            resp = req.execute(num_retries=2)
        except HttpError as e:
            log.warning("search.list failed: %s", e, exc_info=False)
            break
        except Exception as e:
            log.warning("search.list error: %s", e, exc_info=False)
            break

        for it in resp.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            if vid:
                ids.append(vid)

        try:
            req = yt.search().list_next(req, resp)
        except Exception:
            req = None
        page_count += 1

    if not ids:
        log.info("No video candidates found for topic=%r", topic)
        return items

    # ---------- 2) Hydrate candidates (statistics + snippet + contentDetails) ----------
    kept_video = 0
    kept_comments = 0
    dropped_count = 0

    for chunk in _chunk(ids, 50):
        if kept_video >= target or (kept_video + dropped_count) >= budget:
            break

        try:
            vresp = yt.videos().list(
                part="id,contentDetails,snippet,statistics",
                id=",".join(chunk),
            ).execute(num_retries=2)
        except HttpError as e:
            log.warning("videos.list failed: %s", e, exc_info=False)
            continue
        except Exception as e:
            log.warning("videos.list error: %s", e, exc_info=False)
            continue

        for v in vresp.get("items", []):
            if kept_video >= target:
                break
            if (kept_video + dropped_count) >= budget:
                break

            snippet = v.get("snippet") or {}
            statistics = v.get("statistics") or {}
            content_details = v.get("contentDetails") or {}

            # Filter: min_views
            views = int(statistics.get("viewCount") or 0)
            if min_views and views < int(min_views):
                stats["yt_video_drop_min_views"] = stats.get("yt_video_drop_min_views", 0) + 1
                dropped_count += 1
                continue

            # Filter: min_duration
            dur_iso = content_details.get("duration", "PT0S")
            dur_sec = _iso8601_seconds(dur_iso)
            if min_duration_sec and dur_sec < int(min_duration_sec):
                stats["yt_video_drop_min_duration"] = stats.get("yt_video_drop_min_duration", 0) + 1
                dropped_count += 1
                continue

            # Filter: channel_allow (if set, only keep videos from allowed channels)
            channel_title = (snippet.get("channelTitle") or "").strip()
            channel_id = (snippet.get("channelId") or "").strip()
            if allow_set:
                if channel_title.lower() not in allow_set and channel_id.lower() not in allow_set:
                    stats["yt_video_drop_channel_not_allowed"] = stats.get("yt_video_drop_channel_not_allowed", 0) + 1
                    dropped_count += 1
                    continue

            # Filter: channel_block
            if block_set:
                if channel_title.lower() in block_set or channel_id.lower() in block_set:
                    stats["yt_video_drop_channel_blocked"] = stats.get("yt_video_drop_channel_blocked", 0) + 1
                    dropped_count += 1
                    continue

            # Filter: language (light heuristic on title + description)
            title = snippet.get("title") or ""
            description = snippet.get("description") or ""
            if langs and not keep_by_lang((title + " " + description).strip(), langs):
                stats["yt_video_drop_lang"] = stats.get("yt_video_drop_lang", 0) + 1
                dropped_count += 1
                continue

            # Build video Item
            video_id = v.get("id")
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            channel_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""

            video_item = Item(
                platform="youtube",
                id=video_id,
                url=video_url,
                author=channel_title,
                created_at=snippet.get("publishedAt") or "",
                title=title,
                text=description,
                metrics={
                    "views": views,
                    "likes": int(statistics.get("likeCount") or 0),
                    "replies": 0,  # will be updated with comment count
                },
                context={
                    "channel": channel_title,
                    "channelId": channel_id,
                    "channelUrl": channel_url,
                    "duration_sec": dur_sec,
                },
            )

            # Fetch comments for this video
            video_comments: List[Item] = []
            if comments_per_video > 0:
                try:
                    deadline = time.monotonic() + COMMENTS_DEADLINE_SEC
                    video_comments = _fetch_comments_as_items(
                        yt, video_id, video_url, comments_per_video,
                        min_comment_likes, langs, deadline, stats
                    )
                except Exception as e:
                    log.warning("comments failed for %s: %s", video_id, e, exc_info=False)

            # Update video metrics with actual comment count
            video_item.metrics["replies"] = len(video_comments)

            # Add video and its comments to output
            items.append(video_item)
            items.extend(video_comments)

            kept_video += 1
            kept_comments += len(video_comments)
            stats["yt_video_kept"] = kept_video
            stats["yt_comment_kept"] = kept_comments

    log.info("YT collect complete: kept %d videos, %d comments", kept_video, kept_comments)
    return items


# ------------------------- internals --------------------------

def _build_client(api_key: str):
    http = httplib2.Http(timeout=HTTP_TIMEOUT_SEC)
    return build("youtube", "v3", developerKey=api_key, http=http, cache_discovery=False)


def _chunk(seq, n):
    it = iter(seq)
    while True:
        part = list(islice(it, n))
        if not part:
            return
        yield part


def _fetch_comments_as_items(
    yt,
    video_id: str,
    video_url: str,
    want: int,
    min_likes: int,
    langs: Iterable[str],
    deadline_monotonic: float,
    stats: Dict[str, int],
) -> List[Item]:
    """Fetch comments and return as Item instances, respecting min_likes filter."""
    out: List[Item] = []
    langs_list = list(langs) if langs else []

    try:
        req = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            textFormat="plainText",
            order="relevance",
            maxResults=100,
        )
    except HttpError as e:
        # Comments might be disabled for this video
        if "commentsDisabled" in str(e) or "disabled comments" in str(e).lower():
            log.debug("Comments disabled for video %s", video_id)
        else:
            log.warning("commentThreads.list failed for %s: %s", video_id, e)
        return out
    except Exception as e:
        log.warning("commentThreads.list error for %s: %s", video_id, e)
        return out

    pages = 0
    while req is not None and len(out) < want and pages < THREADS_PAGE_LIMIT:
        if time.monotonic() > deadline_monotonic:
            log.warning("YouTube comments deadline reached for %s; kept %d", video_id, len(out))
            break

        try:
            resp = req.execute(num_retries=1)
        except HttpError as e:
            if "commentsDisabled" in str(e):
                break
            log.warning("commentThreads execute failed for %s: %s", video_id, e)
            break
        except Exception as e:
            log.warning("commentThreads execute error for %s: %s", video_id, e)
            break

        for it in resp.get("items", []):
            if len(out) >= want:
                break

            top_comment = (it.get("snippet") or {}).get("topLevelComment") or {}
            snippet = top_comment.get("snippet") or {}

            comment_text = snippet.get("textDisplay") or snippet.get("textOriginal") or ""
            likes = int(snippet.get("likeCount") or 0)

            # Filter: min_comment_likes
            if min_likes and likes < min_likes:
                stats["yt_comment_drop_min_likes"] = stats.get("yt_comment_drop_min_likes", 0) + 1
                continue

            # Filter: language
            if langs_list and not keep_by_lang(comment_text, langs_list):
                stats["yt_comment_drop_lang"] = stats.get("yt_comment_drop_lang", 0) + 1
                continue

            comment_id = it.get("id") or ""
            comment_url = f"{video_url}&lc={comment_id}" if comment_id else video_url

            out.append(Item(
                platform="youtube",
                id=comment_id,
                url=comment_url,
                author=snippet.get("authorDisplayName") or "",
                created_at=snippet.get("publishedAt") or snippet.get("updatedAt") or "",
                title=None,  # comments have no title - this is how CLI distinguishes them
                text=comment_text,
                metrics={
                    "likes": likes,
                    "score": likes,  # alias for compatibility
                    "replies": int((it.get("snippet") or {}).get("totalReplyCount") or 0),
                    "views": None,
                },
                context={
                    "videoId": video_id,
                    "authorChannelUrl": snippet.get("authorChannelUrl") or "",
                },
            ))

        try:
            req = yt.commentThreads().list_next(req, resp)
        except Exception:
            req = None
        pages += 1

    return out


def _iso8601_seconds(iso: str) -> int:
    """Parse ISO 8601 duration (e.g., PT1H2M3S) to seconds."""
    h = m = s = 0
    num = ""
    for ch in iso:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            h = int(num or 0)
            num = ""
        elif ch == "M":
            m = int(num or 0)
            num = ""
        elif ch == "S":
            s = int(num or 0)
            num = ""
    return h * 3600 + m * 60 + s
