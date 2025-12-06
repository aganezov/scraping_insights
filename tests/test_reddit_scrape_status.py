import importlib


def test_reddit_scrape_disabled(monkeypatch):
    monkeypatch.delenv("ALLOW_SCRAPING", raising=False)
    rds = importlib.import_module("insight_mine.connectors.reddit_scrape")
    ok, reason = rds.status()
    assert not ok and "scraping disabled" in reason


def test_reddit_scrape_enabled(monkeypatch):
    monkeypatch.setenv("ALLOW_SCRAPING", "1")
    rds = importlib.import_module("insight_mine.connectors.reddit_scrape")
    ok, _ = rds.status()
    assert ok
