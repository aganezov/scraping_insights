import importlib


def test_reddit_selenium_disabled(monkeypatch):
    monkeypatch.delenv("ALLOW_SELENIUM", raising=False)
    rsel = importlib.import_module("insight_mine.connectors.reddit_selenium")
    ok, reason = rsel.status()
    assert not ok and "selenium" in reason.lower()
