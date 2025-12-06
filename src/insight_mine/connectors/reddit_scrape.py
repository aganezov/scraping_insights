from __future__ import annotations
import os, time, logging, requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Iterable, Optional
from dataclasses import dataclass
import itertools, math
from ..models import Item
from ..config import get_secret
from ..utils.text import keep_by_lang

log = logging.getLogger(__name__)
NAME = "reddit-scrape"
BASE = "https://www.reddit.com"
SLEEP_S = 0.8
TIMEOUT_S = 20
MAX_PER_PAGE = 100


@dataclass
class _RdFUParams:
    target_keep: int
    budget: int
    comments_per_post: int
    min_score: int
    selector: str
    subreddits: list[str]
    search_query: str = ""
    search_sort: str = "relevance"
    search_time: str = "all"
    top_time: str = "week"
    since_ts: Optional[int] = None


def _rd_post_passes_filters(p: Dict[str, Any], params: _RdFUParams, drop: Dict[str, int]) -> bool:
    if params.since_ts and int(p.get("created_utc") or 0) < params.since_ts:
        drop["rd_post_drop_since"] = drop.get("rd_post_drop_since", 0) + 1
        return False
    if int(p.get("score") or 0) < int(params.min_score):
        drop["rd_post_drop_min_score"] = drop.get("rd_post_drop_min_score", 0) + 1
        return False
    return True


def _rd_iter_candidates(session: requests.Session, topic: str, params: _RdFUParams, seen: set[str]) -> Iterable[Dict[str, Any]]:
    subs = params.subreddits or ["all"]
    num_subs = len(subs)
    consecutive_empty = 0  # Track consecutive subreddits with no new posts
    
    for sub in itertools.cycle(subs):
        remaining = max(1, min(params.budget, MAX_PER_PAGE))
        found_any = False
        for pdata in _search_listing(session, topic, sub if sub != "all" else None, remaining):
            pid = pdata.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            found_any = True
            consecutive_empty = 0  # Reset counter when we find something
            yield pdata
        
        if not found_any:
            consecutive_empty += 1
            # If we've gone through all subreddits without finding anything new, stop
            if consecutive_empty >= num_subs:
                break


def _rd_fetch_until_keep(session: requests.Session, topic: str, params: _RdFUParams,
                         telemetry: Dict[str, int], keep_fn, fetch_comments_fn, writer, progress_cb=None):
    kept_posts = 0
    kept_comments = 0
    seen: set[str] = set()
    pulled = 0

    def rd_pct():
        if params.target_keep <= 0:
            return 100
        return min(98, int(100 * kept_posts / max(1, params.target_keep)))

    for post in _rd_iter_candidates(session, topic, params, seen):
        pulled += 1
        if pulled > params.budget:
            telemetry["rd_budget_exhausted"] = telemetry.get("rd_budget_exhausted", 0) + 1
            break

        if not keep_fn(post):
            if progress_cb: progress_cb({"reddit": rd_pct()})
            continue

        cmts = fetch_comments_fn(post, params.comments_per_post) if params.comments_per_post > 0 else []
        kept_comments += len(cmts)

        writer(post, cmts)

        kept_posts += 1
        telemetry["rd_post_kept"] = telemetry.get("rd_post_kept", 0) + 1
        telemetry["rd_comment_kept"] = telemetry.get("rd_comment_kept", 0) + len(cmts)

        if progress_cb: progress_cb({"reddit": rd_pct()})
        if kept_posts >= params.target_keep:
            break

    if progress_cb:
        progress_cb({"reddit": 100})


def _truthy(v: Optional[str]) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"} if v is not None else False


def status() -> Tuple[bool, str]:
    allow = os.environ.get("ALLOW_SCRAPING") or get_secret("ALLOW_SCRAPING")
    if not _truthy(allow):
        return False, "scraping disabled (pass --allow-scraping or set ALLOW_SCRAPING=1)."
    return True, "OK"


def _headers() -> Dict[str, str]:
    ua = os.environ.get("SCRAPE_USER_AGENT") or get_secret("SCRAPE_USER_AGENT") or get_secret("REDDIT_USER_AGENT") or "insight-mine/0.3 (personal use; contact: you@example.com)"
    return {"User-Agent": ua, "Accept": "application/json"}


def _get_json(s: requests.Session, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for attempt in range(3):
        resp = s.get(url, params=params, headers=_headers(), timeout=TIMEOUT_S)
        if resp.status_code == 429:
            retry = float(resp.headers.get("Retry-After", "2.0"))
            time.sleep(max(2.0, min(30.0, retry)))
            continue
        if resp.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            log.warning("Reddit error %s on %s", resp.status_code, url)
            return None
        try:
            return resp.json()
        except Exception as e:
            log.warning("JSON parse error for %s: %s", url, e)
            return None
    return None


def _search_listing(s: requests.Session, topic: str, subreddit: Optional[str], remaining: int):
    url = f"{BASE}/search.json" if not subreddit else f"{BASE}/r/{subreddit}/search.json"
    params: Dict[str, Any] = {
        "q": topic, "sort": "new", "t": "all", "limit": min(MAX_PER_PAGE, max(1, remaining)),
        "restrict_sr": 1 if subreddit else 0, "raw_json": 1, "include_over_18": "on",
    }
    pulled = 0
    after = None
    while pulled < remaining:
        if after:
            params["after"] = after
        data = _get_json(s, url, params)
        if not data:
            break
        children = (data.get("data") or {}).get("children") or []
        if not children:
            break
        for it in children:
            if it.get("kind") != "t3":
                continue
            yield it["data"]
            pulled += 1
            if pulled >= remaining:
                break
        after = (data.get("data") or {}).get("after")
        if not after:
            break
        time.sleep(SLEEP_S)


def _reply_children_count_from_obj(replies) -> int:
    if not replies or isinstance(replies, str):
        return 0
    try:
        ch = (replies.get("data") or {}).get("children") or []
        return sum(1 for c in ch if isinstance(c, dict) and c.get("kind") == "t1")
    except Exception:
        return 0


def _fetch_top_comments(s: requests.Session, permalink: str, max_comments: int, min_comment_score: int, langs: Iterable[str], stats: Dict[str, int] | None) -> List[Item]:
    items: List[Item] = []
    url = f"{BASE}{permalink}.json"
    params = {"sort": "top", "limit": max(1, min(100, max_comments)), "raw_json": 1}
    data = _get_json(s, url, params)
    if not data or not isinstance(data, list) or len(data) < 2:
        return items
    comments_listing = ((data[1] or {}).get("data") or {}).get("children") or []
    pulled = 0
    for child in comments_listing:
        if child.get("kind") != "t1":
            continue
        c = child.get("data") or {}
        body = (c.get("body") or "").strip()
        if not body:
            continue
        score = int(c.get("score", 0) or 0)
        if min_comment_score and score < min_comment_score:
            if stats is not None:
                stats["rd_comment_drop_min_score"] = stats.get("rd_comment_drop_min_score", 0) + 1
            continue
        if not keep_by_lang(body, langs):
            if stats is not None:
                stats["rd_comment_drop_lang"] = stats.get("rd_comment_drop_lang", 0) + 1
            continue
        created = datetime.fromtimestamp(c.get("created_utc", 0) or 0, tz=timezone.utc).isoformat()
        items.append(Item(
            platform="reddit",
            id=f"t1_{c.get('id')}",
            url=f"{BASE}{permalink}{c.get('id')}",
            author=str(c.get("author")) if c.get("author") else None,
            created_at=created,
            title=None,
            text=body,
            metrics={"score": score, "replies": _reply_children_count_from_obj(c.get("replies")), "likes": None, "views": None},
            context={"subreddit": c.get("subreddit"), "post_id": f"t3_{c.get('link_id','').replace('t3_','')}"}
        ))
        pulled += 1
        if stats is not None:
            stats["rd_comment_kept"] = stats.get("rd_comment_kept", 0) + 1
        if pulled >= max_comments:
            break
    time.sleep(SLEEP_S)
    return items


def collect(topic: str, since_iso: str, limit_posts: int = 40, comments_per_post: int = 8, subreddits: List[str] | None = None, min_score: int = 0, min_comment_score: int = 0, langs: Iterable[str] = (), stats: Dict[str, int] | None = None) -> List[Item]:
    ok, why = status()
    if not ok:
        log.info("Reddit scraping disabled: %s", why)
        return []
    stats = stats if stats is not None else {}
    # Initialize counters so they always appear in telemetry
    stats.setdefault("rd_post_kept", 0)
    stats.setdefault("rd_comment_kept", 0)
    since_dt = datetime.fromisoformat(since_iso).replace(tzinfo=timezone.utc)
    since_ts = int(since_dt.timestamp())
    s = requests.Session()
    s.headers.update(_headers())
    out: List[Item] = []

    params = _RdFUParams(
        target_keep=max(0, limit_posts),
        budget=max(1, max(0, limit_posts) * 12),
        comments_per_post=comments_per_post,
        min_score=min_score,
        selector="hot",
        subreddits=[sr.replace("r/", "").strip() for sr in (subreddits or []) if sr.strip()],
        search_query=topic,
        since_ts=since_ts,
    )

    def _writer(post: Dict[str, Any], comments: List[Item]) -> None:
        pid = post.get("id")
        if not pid:
            return
        created = datetime.fromtimestamp(post.get("created_utc", 0) or 0, tz=timezone.utc)
        permalink = post.get("permalink") or ""
        body = (post.get("selftext") or "").strip()
        title = post.get("title") or ""
        # language filter (match old behavior)
        if not keep_by_lang((title + " " + body).strip(), langs):
            stats["rd_post_drop_lang"] = stats.get("rd_post_drop_lang", 0) + 1
            return
        out.append(Item(
            platform="reddit",
            id=f"t3_{pid}",
            url=f"{BASE}{permalink}",
            author=str(post.get("author")) if post.get("author") else None,
            created_at=created.isoformat(),
            title=title,
            text=body,
            metrics={"score": int(post.get("score", 0) or 0), "replies": int(post.get("num_comments", 0) or 0), "likes": None, "views": None},
            context={"subreddit": post.get("subreddit")},
        ))
        out.extend(comments)

    def _keep_fn(p: Dict[str, Any]) -> bool:
        return _rd_post_passes_filters(p, params, stats)

    def _fetch_comments_fn(post: Dict[str, Any], max_count: int) -> List[Item]:
        permalink = post.get("permalink") or ""
        if max_count <= 0 or not permalink:
            return []
        return _fetch_top_comments(s, permalink, max_count, min_comment_score, langs, stats)

    _rd_fetch_until_keep(
        session=s,
        topic=topic,
        params=params,
        telemetry=stats,
        keep_fn=_keep_fn,
        fetch_comments_fn=_fetch_comments_fn,
        writer=_writer,
        progress_cb=None,
    )

    log.info("Reddit scrape collect complete: kept %d posts, %d comments",
             stats.get("rd_post_kept", 0), stats.get("rd_comment_kept", 0))
    return out
