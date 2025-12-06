
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class Item:
    platform: str
    id: str
    url: str
    author: Optional[str]
    created_at: str  # ISO8601
    title: Optional[str]
    text: str
    metrics: Dict[str, Any]
    context: Dict[str, Any]
