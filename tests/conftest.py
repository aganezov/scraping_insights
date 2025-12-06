import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from insight_mine.models import Item

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True, scope="session")
def disable_paid_transcripts_for_tests():
    """
    Ensure test runs never trigger paid transcript API calls.
    Can be overridden by explicitly setting YTTI_ALLOW_PAID_TESTS=1.
    """
    if os.getenv("YTTI_ALLOW_PAID_TESTS") == "1":
        return
    os.environ["YTTI_SKIP_PAID"] = "1"


def _load_items(path: Path) -> List[Item]:
    data = json.loads(path.read_text())
    return [Item(**d) for d in data]


@pytest.fixture
def youtube_items():
    return _load_items(FIXTURES_DIR / "youtube_items.json")


@pytest.fixture
def reddit_items():
    return _load_items(FIXTURES_DIR / "reddit_items.json")


@pytest.fixture
def mock_youtube(monkeypatch, youtube_items):
    from insight_mine import connectors as connectors_pkg
    monkeypatch.setattr(connectors_pkg.youtube, "collect", lambda *a, **k: youtube_items)
    monkeypatch.setattr(connectors_pkg.youtube, "status", lambda: (True, "OK"))
    return youtube_items


@pytest.fixture
def mock_reddit(monkeypatch, reddit_items):
    from insight_mine import connectors as connectors_pkg
    monkeypatch.setattr(connectors_pkg.reddit, "collect", lambda *a, **k: reddit_items)
    monkeypatch.setattr(connectors_pkg.reddit, "status", lambda: (True, "OK"))
    return reddit_items


@pytest.fixture
def dummy_args():
    return SimpleNamespace(
        topic="test-topic",
        since="2025-01-01",
        preset=None,
        reddit_mode="auto",
        subreddits=[],
        dedupe=True,
        cache="",
        refresh=False,
        sample=0,
    )
