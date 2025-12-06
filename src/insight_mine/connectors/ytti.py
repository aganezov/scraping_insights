from __future__ import annotations
from typing import List, Dict, Any
import time
import logging
import requests

from ..models import Item
from ..config import get_secret

log = logging.getLogger(__name__)
NAME = "yt-transcript-io"

# Provider limits
_MAX_IDS_PER_REQUEST = 50      # POST accepts up to 50 IDs
_MAX_REQ_PER_WINDOW = 5        # 5 requests / 10 seconds
_WINDOW_SECONDS = 10
_DEFAULT_SLEEP = (_WINDOW_SECONDS / _MAX_REQ_PER_WINDOW) + 0.1  # ~2.1s


def status() -> tuple[bool, str]:
    token = get_secret("YTTI_API_TOKEN")
    if not token:
        return False, "YTTI_API_TOKEN not set (env or Keychain)."
    return True, "OK"


def _endpoint() -> str:
    return get_secret("YTTI_ENDPOINT") or "https://www.youtube-transcript.io/api/transcripts"


def _auth_header() -> dict[str, str]:
    token = get_secret("YTTI_API_TOKEN")
    if not token:
        raise RuntimeError("Missing YTTI_API_TOKEN.")
    # Provider expects 'Authorization: Basic <token>' (token string, not username:password)
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _chunked(seq: List[str], size: int) -> List[List[str]]:
    return [seq[i:i+size] for i in range(0, len(seq), size)]


def _extract_text_maybe(video_payload: Dict[str, Any]) -> str:
    """
    Join any segment 'text' fields into a single string.
    Tolerates minor schema differences.
    """
    candidates: list[str] = []
    for key in ("segments", "transcript", "items", "results", "data"):
        if isinstance(video_payload.get(key), list):
            for seg in video_payload[key]:
                if isinstance(seg, dict) and "text" in seg:
                    candidates.append(str(seg.get("text") or ""))
    if not candidates:
        for key in ("full_text", "full_transcript", "text"):
            if isinstance(video_payload.get(key), str):
                candidates.append(video_payload[key])
                break
    return " ".join(t.strip() for t in candidates if t).strip()


def collect(video_ids: List[str], per_video_limit: int | None = None) -> List[Item]:
    """
    Fetch transcripts for the given video IDs from youtube-transcript.io.
    Returns Items with context.kind='transcript'. Gracefully handles 429.
    """
    ok, why = status()
    if not ok:
        log.info("YT Transcript connector disabled: %s", why)
        return []

    if not video_ids:
        return []

    endpoint = _endpoint()
    headers = _auth_header()

    out: List[Item] = []
    requests_made = 0
    start_window = time.monotonic()

    # Deduplicate while preserving order
    uniq_ids: List[str] = list(dict.fromkeys(video_ids))

    for batch in _chunked(uniq_ids, _MAX_IDS_PER_REQUEST):
        # basic token bucket rate control
        now = time.monotonic()
        if now - start_window >= _WINDOW_SECONDS:
            start_window = now
            requests_made = 0
        if requests_made >= _MAX_REQ_PER_WINDOW:
            sleep_for = max(0.0, _WINDOW_SECONDS - (now - start_window)) + 0.1
            time.sleep(sleep_for)
            start_window = time.monotonic()
            requests_made = 0

        resp = requests.post(endpoint, headers=headers, json={"ids": batch}, timeout=30)
        requests_made += 1

        if resp.status_code == 429:
            retry = float(resp.headers.get("Retry-After", "2.2"))
            log.warning("Rate limited; sleeping %.2fs", retry)
            time.sleep(retry)
            resp = requests.post(endpoint, headers=headers, json={"ids": batch}, timeout=30)

        if resp.status_code >= 400:
            log.warning("Provider error %s: %s", resp.status_code, resp.text[:200])
            time.sleep(_DEFAULT_SLEEP)
            continue

        try:
            payload = resp.json()
        except Exception:
            log.warning("Provider returned non-JSON; skipping batch.")
            time.sleep(_DEFAULT_SLEEP)
            continue

        # Expected: list of per-video dicts; accept a few shapes
        results = payload if isinstance(payload, list) else payload.get("transcripts") or payload.get("data") or []
        for v in results:
            vid = v.get("id") or v.get("video_id") or v.get("videoId")
            if not vid:
                continue
            text = _extract_text_maybe(v)
            if per_video_limit and text:
                words = text.split()
                if len(words) > per_video_limit:
                    text = " ".join(words[:per_video_limit]) + " …"
            out.append(Item(
                platform="youtube",
                id=f"{vid}:transcript",
                url=f"https://www.youtube.com/watch?v={vid}",
                author=None,
                created_at="",
                title="Transcript",
                text=text or "",
                metrics={"score": None, "replies": None, "likes": None, "views": None},
                context={"videoId": vid, "kind": "transcript", "provider": "youtube-transcript.io"},
            ))
        time.sleep(_DEFAULT_SLEEP)

    return out
