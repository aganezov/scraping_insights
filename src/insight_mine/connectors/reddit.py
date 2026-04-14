from __future__ import annotations
import time
import logging
import praw
from datetime import datetime, timezone
from typing import List, Tuple, Iterable, Dict
from ..models import Item
from ..config import get_secret
from ..utils.text import keep_by_lang

log = logging.getLogger(__name__)
NAME = "reddit"

# Budget multiplier for fetch-until-keep
BUDGET_MULTIPLIER = 12


def status() -> Tuple[bool, str]:
    cid = get_secret("REDDIT_CLIENT_ID")
    csec = get_secret("REDDIT_CLIENT_SECRET")
    if not cid or not csec:
        return False, "REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set."
    return True, "OK"


def _client():
    cid = get_secret("REDDIT_CLIENT_ID")
    csec = get_secret("REDDIT_CLIENT_SECRET")
    ua = get_secret("REDDIT_USER_AGENT") or "insight-mine/0.1 (personal use)"
    if not cid or not csec:
        raise RuntimeError("Missing Reddit credentials.")
    r = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua)
    r.read_only = True
    return r


def collect(
    topic: str,
    since_iso: str,
    limit_posts: int = 40,
    comments_per_post: int = 8,
    subreddits: List[str] | None = None,
    min_score: int = 0,
    min_comment_score: int = 0,
    langs: Iterable[str] = (),
    stats: Dict[str, int] | None = None,
) -> List[Item]:
    """
    Fetch-until-keep: limit_posts is the KEPT target after filtering.
    Uses a budget of limit_posts * 12 to prevent infinite loops.
    """
    ok, why = status()
    if not ok:
        log.info("Reddit API disabled: %s", why)
        return []

    if stats is None:
        stats = {}

    # Initialize counters
    stats.setdefault("rd_post_kept", 0)
    stats.setdefault("rd_comment_kept", 0)

    if limit_posts <= 0:
        log.info("Reddit API: limit_posts=0, skipping")
        return []

    r = _client()
    since_dt = datetime.fromisoformat(since_iso).replace(tzinfo=timezone.utc)
    sr = "+".join([s.replace("r/", "") for s in (subreddits or []) if s.strip()]) if subreddits else "all"
    langs_list = list(langs) if langs else []

    out: List[Item] = []
    target = limit_posts
    budget = target * BUDGET_MULTIPLIER
    candidates_seen = 0
    kept_posts = 0

    log.info("Reddit API fetch-until-keep: target=%d budget=%d subreddit=%s", target, budget, sr)

    # Fetch more candidates than target to allow for filtering
    # PRAW's search returns a generator, we iterate until we hit target or budget
    try:
        search_results = r.subreddit(sr).search(topic, sort="new", time_filter="all", limit=budget)
    except Exception as e:
        log.warning("Reddit API search failed: %s", e)
        return out

    for post in search_results:
        candidates_seen += 1

        # Check budget
        if candidates_seen > budget:
            stats["rd_budget_exhausted"] = 1
            log.info("Reddit API: budget exhausted after %d candidates, kept %d posts", candidates_seen, kept_posts)
            break

        # Check if we've hit target
        if kept_posts >= target:
            break

        # Filter: time
        try:
            created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
        except Exception:
            stats["rd_post_drop_time"] = stats.get("rd_post_drop_time", 0) + 1
            continue

        if created < since_dt:
            stats["rd_post_drop_time"] = stats.get("rd_post_drop_time", 0) + 1
            continue

        # Filter: min_score
        post_score = int(post.score or 0)
        if min_score and post_score < min_score:
            stats["rd_post_drop_min_score"] = stats.get("rd_post_drop_min_score", 0) + 1
            continue

        # Filter: language
        title = post.title or ""
        body = (post.selftext or "").strip()
        if langs_list and not keep_by_lang((title + " " + body).strip(), langs_list):
            stats["rd_post_drop_lang"] = stats.get("rd_post_drop_lang", 0) + 1
            continue

        # Post passes all filters - add it
        out.append(Item(
            platform=NAME,
            id=f"t3_{post.id}",
            url=f"https://www.reddit.com{post.permalink}",
            author=str(post.author) if post.author else None,
            created_at=created.isoformat(),
            title=title,
            text=body,
            metrics={
                "score": post_score,
                "replies": int(post.num_comments or 0),
                "likes": None,
                "views": None,
            },
            context={"subreddit": f"r/{post.subreddit.display_name}"},
        ))
        kept_posts += 1
        stats["rd_post_kept"] = kept_posts

        # Fetch comments for this post
        if comments_per_post > 0:
            try:
                post.comments.replace_more(limit=0)
            except Exception as e:
                log.debug("replace_more failed for %s: %s", post.id, e)

            pulled = 0
            for c in post.comments:
                if pulled >= comments_per_post:
                    break

                score = int(getattr(c, "score", 0) or 0)
                text = getattr(c, "body", "").strip()

                if not text:
                    continue

                # Filter: min_comment_score
                if min_comment_score and score < min_comment_score:
                    stats["rd_comment_drop_min_score"] = stats.get("rd_comment_drop_min_score", 0) + 1
                    continue

                # Filter: language
                if langs_list and not keep_by_lang(text, langs_list):
                    stats["rd_comment_drop_lang"] = stats.get("rd_comment_drop_lang", 0) + 1
                    continue

                out.append(Item(
                    platform=NAME,
                    id=f"t1_{c.id}",
                    url=f"https://www.reddit.com{post.permalink}{c.id}",
                    author=str(c.author) if c.author else None,
                    created_at=datetime.fromtimestamp(
                        getattr(c, "created_utc", 0) or 0, tz=timezone.utc
                    ).isoformat(),
                    title=None,
                    text=text,
                    metrics={
                        "score": score,
                        "replies": len(getattr(c, "replies", []) or []),
                        "likes": None,
                        "views": None,
                    },
                    context={
                        "subreddit": f"r/{post.subreddit.display_name}",
                        "post_id": f"t3_{post.id}",
                    },
                ))
                pulled += 1
                stats["rd_comment_kept"] = stats.get("rd_comment_kept", 0) + 1

        # Rate limiting
        time.sleep(0.25)

    log.info("Reddit API collect complete: kept %d posts, %d comments", kept_posts, stats.get("rd_comment_kept", 0))
    return out
