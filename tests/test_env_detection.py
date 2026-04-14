
import importlib
import importlib.util
import sys
from types import ModuleType


def _stub_google_client():
    """Provide a stub googleapiclient so status import works without the real dependency."""
    try:
        spec = importlib.util.find_spec("googleapiclient.discovery")
    except ModuleNotFoundError:
        spec = None
    if spec is not None:
        return
    ga = ModuleType("googleapiclient")
    discovery = ModuleType("googleapiclient.discovery")

    def build(*args, **kwargs):
        raise RuntimeError("Stubbed googleapiclient; install google-api-python-client for real use.")

    discovery.build = build
    ga.discovery = discovery
    sys.modules.setdefault("googleapiclient", ga)
    sys.modules.setdefault("googleapiclient.discovery", discovery)


def _stub_praw():
    try:
        spec = importlib.util.find_spec("praw")
    except (ModuleNotFoundError, ValueError):
        spec = None
    if spec is not None:
        return
    praw_stub = ModuleType("praw")

    class FakeReddit:
        def __init__(self, *args, **kwargs):
            self.read_only = True

    praw_stub.Reddit = FakeReddit
    sys.modules.setdefault("praw", praw_stub)


def test_youtube_disabled(monkeypatch):
    _stub_google_client()
    monkeypatch.setenv("INSIGHT_MINE_DISABLE_DOTENV", "1")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    yt = importlib.reload(importlib.import_module("insight_mine.connectors.youtube"))
    ok, reason = yt.status()
    assert not ok and "YOUTUBE_API_KEY" in reason


def test_youtube_enabled(monkeypatch):
    _stub_google_client()
    monkeypatch.setenv("YOUTUBE_API_KEY", "dummy")
    yt = importlib.reload(importlib.import_module("insight_mine.connectors.youtube"))
    ok, reason = yt.status()
    assert ok and reason == "OK"


def test_reddit_disabled(monkeypatch):
    _stub_praw()
    monkeypatch.setenv("INSIGHT_MINE_DISABLE_DOTENV", "1")
    for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    rd = importlib.reload(importlib.import_module("insight_mine.connectors.reddit"))
    ok, reason = rd.status()
    assert not ok and "REDDIT_CLIENT" in reason


def test_reddit_enabled(monkeypatch):
    _stub_praw()
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    rd = importlib.reload(importlib.import_module("insight_mine.connectors.reddit"))
    ok, reason = rd.status()
    assert ok and reason == "OK"
