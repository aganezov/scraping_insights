import importlib


def test_ytti_disabled(monkeypatch):
    monkeypatch.delenv("YTTI_API_TOKEN", raising=False)
    ytti = importlib.import_module("insight_mine.connectors.ytti")
    ok, reason = ytti.status()
    assert not ok and "YTTI_API_TOKEN" in reason
