
from __future__ import annotations
from ..models import Item

NAME = "x"


def status():
    return False, "X/Twitter connector disabled: no API access configured."


def collect(*args, **kwargs):
    # Placeholder; return empty list to keep the pipeline simple.
    return []
