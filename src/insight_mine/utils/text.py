from __future__ import annotations
import hashlib
import re
from typing import Iterable, List, Optional

try:
    from langdetect import detect as _ld_detect
    from langdetect.lang_detect_exception import LangDetectException
except Exception:
    _ld_detect = None
    LangDetectException = Exception  # type: ignore

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)


def clean_for_hash(text: str) -> str:
    t = text or ""
    t = t.lower()
    t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()


def detect_lang(text: str) -> Optional[str]:
    if not text:
        return None
    if _ld_detect is None:
        return None
    try:
        return _ld_detect(text)
    except LangDetectException:
        return None


def keep_by_lang(text: str, allowed: Iterable[str]) -> bool:
    """Return True if no filter or detected language ∈ allowed set."""
    allowed_set = {x.strip().lower() for x in (allowed or []) if x.strip()}
    if not allowed_set:
        return True  # no filter
    lang = detect_lang(text)
    return lang in allowed_set if lang else False


def dedupe_items(items: List[dict]) -> List[dict]:
    """
    Remove near-duplicates using a hash of normalized title+text.
    Items are dicts shaped by CLI serialization.
    """
    seen: set[str] = set()
    out: List[dict] = []
    for it in items:
        basis = (it.get("title") or "") + "\n" + (it.get("text") or "")
        sig = sha1(clean_for_hash(basis)) if basis.strip() else sha1(f"{it.get('platform')}::{it.get('id')}")
        if sig in seen:
            continue
        seen.add(sig)
        out.append(it)
    return out
