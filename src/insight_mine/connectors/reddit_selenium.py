from __future__ import annotations
import os, time, logging, urllib.parse
from typing import List, Tuple, Optional
import requests
from datetime import datetime, timezone

from ..models import Item
from ..utils.text import keep_by_lang
from ..config import get_secret

log = logging.getLogger(__name__)
NAME = "reddit-selenium"
BASE = "https://www.reddit.com"
SLEEP_S = 1.0


def _truthy(v: Optional[str]) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"} if v is not None else False


def status() -> Tuple[bool, str]:
    allow_env = os.environ.get("ALLOW_SELENIUM") or get_secret("ALLOW_SELENIUM")
    if not _truthy(allow_env):
        return False, "selenium disabled (pass --allow-selenium or set ALLOW_SELENIUM=1)."
    # Lazy import so module import never fails
    try:
        import importlib
        importlib.import_module("selenium")
    except Exception:
        return False, "selenium not installed"
    return True, "OK"


def _headers() -> dict:
    ua = (
        os.environ.get("SCRAPE_USER_AGENT")
        or get_secret("SCRAPE_USER_AGENT")
        or get_secret("REDDIT_USER_AGENT")
        or "insight-mine/0.2 (personal use; contact: you@example.com)"
    )
    return {"User-Agent": ua, "Accept": "application/json"}


def _driver():
    # Import here (lazy)
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    headless = _truthy(os.environ.get("SELENIUM_HEADLESS") or "1")
    opts = Options()
    if headless:
        try:
            opts.add_argument("--headless=new")
        except Exception:
            opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    # Use system Chrome/Chromium; assume chromedriver is in PATH or Selenium Manager can provision
    drv = webdriver.Chrome(options=opts)
    return drv, By, WebDriverWait, EC


def _collect_post_json(permalink: str, min_comment_score: int, lang: str | None, lang_thr: float) -> List[Item]:
    items: List[Item] = []
    url = f"{BASE}{permalink}.json"
    try:
        resp = requests.get(url, headers=_headers(), timeout=25)
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return items
    if resp.status_code >= 400:
        return items
    try:
        data = resp.json()
    except Exception:
        return items
    if not isinstance(data, list) or len(data) < 2:
        return items

    post = ((data[0] or {}).get("data") or {}).get("children", [])
    if post and post[0].get("kind") == "t3":
        p = post[0]["data"]
        title = p.get("title") or ""
        selftext = (p.get("selftext") or "").strip()
        if lang and not keep_by_lang(f"{title}\n{selftext}", [lang]):
            return items
        created = datetime.fromtimestamp(p.get("created_utc", 0) or 0, tz=timezone.utc).isoformat()
        items.append(Item(
            platform="reddit",
            id=f"t3_{p.get('id')}",
            url=f"{BASE}{permalink}",
            author=str(p.get("author")) if p.get("author") else None,
            created_at=created,
            title=title,
            text=selftext,
            metrics={"score": int(p.get("score", 0) or 0), "replies": int(p.get("num_comments", 0) or 0),
                     "likes": None, "views": None},
            context={"subreddit": p.get("subreddit")},
        ))

    comments_listing = ((data[1] or {}).get("data") or {}).get("children") or []
    pulled = 0
    for child in comments_listing:
        if child.get("kind") != "t1":
            continue
        c = child.get("data") or {}
        body = (c.get("body") or "").strip()
        like_score = int(c.get("score", 0) or 0)
        if like_score < (min_comment_score or 0):
            continue
        if lang and not keep_by_lang(body, [lang]):
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
            metrics={"score": like_score, "replies": int(c.get("replies", {}).get("data", {}).get("children", []) and 1 or 0),
                     "likes": None, "views": None},
            context={"subreddit": c.get("subreddit"), "post_id": f"t3_{c.get('link_id','').replace('t3_','')}"}
        ))

    return items


def collect(
    topic: str,
    since_iso: str,
    limit_posts: int = 20,
    comments_per_post: int = 8,
    subreddits: List[str] | None = None,
    min_comment_score: int = 0,
    block_subs: List[str] | None = None,
    lang: str | None = None,
    lang_threshold: float = 0.8,
):
    ok, why = status()
    if not ok:
        log.info("Reddit Selenium disabled: %s", why)
        return []

    drv, By, WebDriverWait, EC = _driver()
    out: List[Item] = []

    try:
        targets = [None] if not subreddits else [sr.replace("r/", "").strip() for sr in subreddits if sr.strip()]
        blocks = {b.replace("r/", "").lower() for b in (block_subs or []) if b}
        pulled = 0
        for sr in targets:
            if pulled >= limit_posts:
                break
            if sr and sr.lower() in blocks:
                continue
            query = urllib.parse.quote_plus(topic)
            if sr:
                url = f"{BASE}/r/{sr}/search/?q={query}&sort=new&t=all&type=link"
            else:
                url = f"{BASE}/search/?q={query}&sort=new&t=all&type=link"
            drv.get(url)
            WebDriverWait(drv, 12).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[data-click-id='body']")))
            links = drv.find_elements(By.CSS_SELECTOR, "a[data-click-id='body']")
            hrefs = []
            for a in links:
                try:
                    href = a.get_attribute("href") or ""
                    if href.startswith("https://www.reddit.com/r/") and "/comments/" in href:
                        hrefs.append(href)
                except Exception:
                    continue
            # Deduplicate and cap
            hrefs = list(dict.fromkeys(hrefs))
            for href in hrefs:
                if pulled >= limit_posts:
                    break
                # permalink path:
                try:
                    p = urllib.parse.urlparse(href)
                    permalink = p.path if p.path.endswith("/") else p.path + "/"
                except Exception:
                    continue
                items = _collect_post_json(permalink, min_comment_score, lang, lang_threshold)
                if not items:
                    continue
                # limit comments per post
                # keep the 1st item (post), then first N comments
                post = [it for it in items if it.id.startswith("t3_")]
                comments = [it for it in items if it.id.startswith("t1_")][:comments_per_post]
                out.extend(post + comments)
                pulled += 1
                time.sleep(SLEEP_S)
            time.sleep(SLEEP_S)
    finally:
        try:
            drv.quit()
        except Exception:
            pass

    return out
