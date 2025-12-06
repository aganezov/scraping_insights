from insight_mine.utils.text import clean_for_hash, sha1, dedupe_items, mask_secret


def test_clean_for_hash_normalizes_whitespace_and_punct():
    assert clean_for_hash(" Hello,\tWorld!! ") == "hello world"


def test_sha1_consistent_output():
    h1 = sha1("abc")
    h2 = sha1("abc")
    assert h1 == h2
    assert len(h1) == 40


def test_dedupe_items_removes_duplicates_by_content():
    items = [
        {"platform": "youtube", "id": "1", "title": "T", "text": "Same text"},
        {"platform": "youtube", "id": "2", "title": "T", "text": "Same text"},
        {"platform": "youtube", "id": "3", "title": "Other", "text": "Different"},
    ]
    out = dedupe_items(items)
    ids = {it["id"] for it in out}
    assert ids == {"1", "3"}


def test_mask_secret_behaviors():
    assert mask_secret("") == "(not set)"
    assert mask_secret("short") == "****"
    assert mask_secret("longsecret") == "lon...ret"

