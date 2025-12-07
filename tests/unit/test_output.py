import json
from types import SimpleNamespace

from insight_mine.cli.output import as_dict, counts_by_kind, write_outputs, SNIPPET_MAX_LEN
from insight_mine.models import Item


def test_as_dict_serializes_item():
    item = Item(
        platform="youtube",
        id="v1",
        url="u",
        author="a",
        created_at="now",
        title="t",
        text="body",
        metrics={"views": 1},
        context={"channelId": "c"},
    )
    d = as_dict(item)
    assert d["platform"] == "youtube"
    assert d["metrics"]["views"] == 1
    assert d["context"]["channelId"] == "c"


def test_counts_by_kind_categorizes_items():
    items = [
        {"platform": "youtube", "id": "v1", "title": "Video"},
        {"platform": "youtube", "id": "c1", "title": None},
        {"platform": "reddit", "id": "t3_post", "title": "Post"},
        {"platform": "reddit", "id": "t1_comment", "title": None},
    ]
    counts = counts_by_kind(items)
    assert counts["youtube_video"] == 1
    assert counts["youtube_comment"] == 1
    assert counts["reddit_post"] == 1
    assert counts["reddit_comment"] == 1


def test_write_outputs_creates_files_and_truncates_paste_ready(tmp_path):
    item = {
        "platform": "youtube",
        "id": "v1",
        "url": "http://example.com",
        "title": "Video",
        "text": "x" * (SNIPPET_MAX_LEN + 20),
        "metrics": {},
        "context": {},
        "author": "author",
        "created_at": "now",
    }
    args = SimpleNamespace(
        topic="t",
        since="2025-01-01",
        preset=None,
        reddit_mode="auto",
        subreddits=[],
        dedupe=True,
        cache="",
        refresh=False,
        sample=0,
    )
    effective = {
        "langs": ["en"],
        "yt_videos": 1,
        "yt_order": "viewCount",
        "yt_min_views": 0,
        "yt_min_duration": 0,
        "yt_max_comments": 0,
        "yt_min_comment_likes": 0,
        "yt_max_comment_share": None,
        "yt_allow": [],
        "yt_block": [],
        "reddit_limit": 0,
        "reddit_comments": 0,
        "reddit_min_score": 0,
        "reddit_min_comment_score": 0,
        "reddit_max_comment_share": None,
        "subs": [],
    }
    connectors = {"youtube": True, "reddit_api": False, "reddit_scrape": False, "transcripts": False}

    write_outputs(
        run_dir=tmp_path,
        serial=[item],
        args=args,
        effective=effective,
        counts={"youtube_video": 1},
        stats_total={"youtube": {}, "reddit_api": {}, "reddit_scrape": {}},
        connectors=connectors,
        dropped_by_cache=0,
        sampled_n=0,
    )

    raw_path = tmp_path / "raw.jsonl"
    paste_path = tmp_path / "paste-ready.txt"
    manifest_path = tmp_path / "run_manifest.json"
    stats_path = tmp_path / "stats.json"

    assert raw_path.exists()
    assert paste_path.exists()
    assert manifest_path.exists()
    assert stats_path.exists()

    paste_line = paste_path.read_text().splitlines()[0]
    assert paste_line.endswith("…")
    assert len(paste_line) < SNIPPET_MAX_LEN + 20

    manifest = json.loads(manifest_path.read_text())
    assert manifest["topic"] == "t"
    assert manifest["connectors"] == connectors


