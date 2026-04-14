from __future__ import annotations

import os
import shlex
import subprocess
import logging
import concurrent.futures
from typing import Optional

import requests


log = logging.getLogger(__name__)


class TranscriptError(RuntimeError):
    """Raised when transcript retrieval fails."""


# Free transcript timeout (seconds); prevents hanging on bad proxies/creds
YTTI_FREE_TIMEOUT_SEC = int(os.getenv("YTTI_FREE_TIMEOUT_SEC", "15"))


def fetch_transcript(video_id: str, lang: str, *, allow_paid: bool = True) -> tuple[str, str]:
    """
    Fetch a transcript via youtube-transcript-api first, then an optional external
    command template, then HTTP.
    Returns (transcript_text, source) where source is one of:
    - "free" (youtube-transcript-api)
    - "cli" (external command template)
    - "paid" (youtube-transcript.io API)
    """
    global _yt_api_last_error
    errors = []
    log.debug(
        "fetch_transcript start video_id=%s lang=%s allow_paid=%s ws_user=%s ws_pass_set=%s",
        video_id, lang, allow_paid, os.getenv("YTTI_WS_USER"), bool(os.getenv("YTTI_WS_PASS")),
    )
    
    # Try youtube-transcript-api (free, no API key needed)
    try:
        text = _fetch_via_yt_transcript_api(video_id, lang)
        if text:
            return text.strip(), "free"
        errors.append(f"yt-api: {_yt_api_last_error or 'no transcript'}")
        if _yt_api_last_error:
            log.debug("yt-transcript-api free path failed for %s: %s", video_id, _yt_api_last_error)
    except Exception as e:
        errors.append(f"yt-api: {e}")
    
    # Fallback to CLI
    try:
        text = _fetch_via_cli(video_id, lang)
        if text:
            return text.strip(), "cli"
        errors.append("cli: not available")
    except Exception as e:
        errors.append(f"cli: {e}")
    
    # Fallback to HTTP API (paid); allow toggle via flag or env
    if (not allow_paid) or (os.getenv("YTTI_SKIP_PAID") == "1"):
        errors.append("http: skipped (paid disabled)")
    else:
        try:
            text = _fetch_via_http(video_id, lang)
            if text:
                return text.strip(), "paid"
            errors.append("http: no token or failed")
        except Exception as e:
            errors.append(f"http: {e}")
    
    msg = f"No transcript for {video_id}: {'; '.join(errors)}"
    log.warning(msg)
    raise TranscriptError(msg)


_yt_api_last_error = ""

def _fetch_via_yt_transcript_api(video_id: str, lang: str) -> Optional[str]:
    """Fetch transcript using youtube-transcript-api package (free, no API key)."""
    global _yt_api_last_error
    _yt_api_last_error = ""
    try:
        return _run_with_timeout(lambda: _yt_api_fetch_core(video_id, lang), timeout=YTTI_FREE_TIMEOUT_SEC)
    except concurrent.futures.TimeoutError:
        _yt_api_last_error = "timeout"
        log.warning("yt-transcript-api timeout for %s after %ss", video_id, YTTI_FREE_TIMEOUT_SEC)
        return None
    except ImportError:
        _yt_api_last_error = "package not installed"
        return None
    except Exception as e:
        _yt_api_last_error = type(e).__name__
        return None


def _yt_api_fetch_core(video_id: str, lang: str) -> Optional[str]:
    from youtube_transcript_api import YouTubeTranscriptApi
    proxy_cfg = None
    try:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        ws_user = os.getenv("YTTI_WS_USER")
        ws_pass = os.getenv("YTTI_WS_PASS")
        if ws_user and ws_pass:
            log.debug("yt-transcript-api: using proxy user=%s", ws_user)
            proxy_cfg = WebshareProxyConfig(
                proxy_username=ws_user,
                proxy_password=ws_pass,
            )
        else:
            log.debug("yt-transcript-api: proxy disabled (missing YTTI_WS_USER/PASS)")
    except Exception as e:
        log.debug("yt-transcript-api: proxy setup failed: %s", e)

    api = YouTubeTranscriptApi(proxy_config=proxy_cfg) if proxy_cfg else YouTubeTranscriptApi()
    langs = [lang] if lang else []
    if "en" not in langs:
        langs.append("en")

    transcript_list = None
    # First attempt: fetch with preferred languages (manual or generated)
    try:
        transcript_list = api.fetch(video_id, languages=langs)
    except Exception as e:
        _yt_api_last_error = type(e).__name__

    # Second attempt: list and fetch any available transcript
    if not transcript_list:
        try:
            tlist = api.list(video_id)
            t = tlist.find_transcript(langs) if hasattr(tlist, "find_transcript") else next(iter(tlist), None)
            if t:
                transcript_list = t.fetch()
        except Exception as e:
            _yt_api_last_error = type(e).__name__
    # Combine all text segments (snippets have .text attribute)
    if transcript_list:
        texts = []
        for item in transcript_list:
            # Handle both object attributes and dict keys
            if hasattr(item, 'text'):
                texts.append(item.text)
            elif isinstance(item, dict) and 'text' in item:
                texts.append(item['text'])
        if texts:
            return _format_transcript(" ".join(texts))
        return None
    return None


def _run_with_timeout(fn, timeout: int):
    if timeout and timeout > 0:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(fn)
            return fut.result(timeout=timeout)
    return fn()


def _format_transcript(text: str, target_para_len: int = 500) -> str:
    """
    Format raw transcript text into readable paragraphs.
    Adds paragraph breaks after sentence-ending punctuation when ~target_para_len chars accumulated.
    """
    import re
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    result = []
    current_para = []
    current_len = 0
    
    # Split into words
    words = text.split()
    
    for word in words:
        current_para.append(word)
        current_len += len(word) + 1  # +1 for space
        
        # Check if we should break after this word
        if current_len >= target_para_len and word and word[-1] in '.!?':
            result.append(' '.join(current_para))
            current_para = []
            current_len = 0
    
    # Don't forget remaining words
    if current_para:
        result.append(' '.join(current_para))
    
    return '\n\n'.join(result)


def _fetch_via_cli(video_id: str, lang: str) -> Optional[str]:
    template = os.getenv("IM_CLI_TRANSCRIPT_CMD")
    if not template:
        return None
    try:
        cmd = shlex.split(template.format(video_id=video_id, lang=lang))
    except Exception:
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _fetch_via_http(video_id: str, lang: str) -> Optional[str]:
    """Fallback to youtube-transcript.io API (uses credits, requires YTTI_API_TOKEN)."""
    from insight_mine.config import get_secret
    
    # Try to get token from env or keychain (same as CLI's ytti connector)
    token = os.getenv("YTTI_TOKEN") or os.getenv("YTTI_API_TOKEN")
    if not token:
        try:
            token = get_secret("YTTI_API_TOKEN")
        except Exception:
            pass
    if not token:
        return None
    
    # Use same endpoint as CLI connector
    endpoint = os.getenv("YTTI_ENDPOINT") or "https://www.youtube-transcript.io/api/transcripts"
    # Use Basic auth like CLI connector
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    
    try:
        resp = requests.post(endpoint, json={"ids": [video_id]}, headers=headers, timeout=30)
    except Exception:
        return None
    if resp.status_code >= 400:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    
    # Handle response format (list of video results)
    results = data if isinstance(data, list) else data.get("transcripts") or data.get("data") or []
    for v in results:
        vid = v.get("id") or v.get("video_id") or v.get("videoId")
        if vid == video_id or not vid:
            # Extract text from segments
            text_parts = []
            for key in ("segments", "transcript", "items", "results", "data"):
                if isinstance(v.get(key), list):
                    for seg in v[key]:
                        if isinstance(seg, dict) and "text" in seg:
                            text_parts.append(str(seg.get("text") or ""))
            if not text_parts:
                for key in ("full_text", "full_transcript", "text"):
                    if isinstance(v.get(key), str):
                        text_parts.append(v[key])
                        break
            if text_parts:
                raw = " ".join(t.strip() for t in text_parts if t).strip()
                return _format_transcript(raw)
    return None
