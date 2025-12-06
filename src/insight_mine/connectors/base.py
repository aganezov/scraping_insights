
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ConnectorStatus:
    name: str
    available: bool
    reason: str  # human-friendly description
