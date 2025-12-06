
from __future__ import annotations
from pathlib import Path
import orjson
from typing import Iterable, Any


def write_jsonl(path: Path, items: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for it in items:
            f.write(orjson.dumps(it) + b"\n")


def write_txt(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n\n---\n\n".join(lines)
    path.write_text(text, encoding="utf-8")
