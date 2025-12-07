import sqlite3

import pytest

from insight_mine.utils.cache import open_db, cache_db, load_seen, upsert_many


def test_open_db_creates_schema(tmp_path):
    db_path = tmp_path / "cache.db"
    conn = open_db(db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(seen)").fetchall()]
    finally:
        conn.close()
    assert {"platform", "id", "first_seen_ts"}.issubset(set(cols))


def test_cache_db_context_closes_connection(tmp_path):
    db_path = tmp_path / "cache.db"
    with cache_db(db_path) as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_load_seen_returns_stored_keys(tmp_path):
    db_path = tmp_path / "cache.db"
    with cache_db(db_path) as conn:
        conn.execute("INSERT INTO seen (platform, id, first_seen_ts) VALUES (?, ?, ?)", ("youtube", "v1", 1))
        conn.commit()
        seen = load_seen(conn)
    assert ("youtube", "v1") in seen


def test_upsert_many_dedupes_on_conflict(tmp_path):
    db_path = tmp_path / "cache.db"
    keys = [("youtube", "a"), ("youtube", "a"), ("reddit", "b")]
    with cache_db(db_path) as conn:
        upsert_many(conn, keys)
        rows = conn.execute("SELECT platform, id FROM seen").fetchall()
    assert set(rows) == {("youtube", "a"), ("reddit", "b")}


