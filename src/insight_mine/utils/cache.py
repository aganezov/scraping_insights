"""SQLite-backed cache utilities for deduping seen items."""
from __future__ import annotations
import sqlite3, time
from pathlib import Path
from typing import Iterable, Tuple, Set
from contextlib import contextmanager

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    platform TEXT NOT NULL,
    id TEXT NOT NULL,
    first_seen_ts INTEGER NOT NULL,
    PRIMARY KEY (platform, id)
);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


@contextmanager
def cache_db(path: str | Path):
    """Context manager wrapper for cache connections."""
    conn = open_db(path)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_seen(conn: sqlite3.Connection) -> Set[Tuple[str, str]]:
    rows = conn.execute("SELECT platform, id FROM seen").fetchall()
    return {(r[0], r[1]) for r in rows}


def upsert_many(conn: sqlite3.Connection, keys: Iterable[Tuple[str, str]]) -> None:
    ts = int(time.time())
    conn.executemany(
        "INSERT OR IGNORE INTO seen (platform, id, first_seen_ts) VALUES (?, ?, ?)",
        [(plat, _id, ts) for plat, _id in keys],
    )
    conn.commit()
