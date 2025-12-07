import json
from types import SimpleNamespace

from insight_mine.cli.orchestrator import run_collect


def _effective():
    return {
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


def _args(out_dir, cache_path, refresh=False):
    return SimpleNamespace(
        topic="cache-topic",
        since="2025-01-01",
        out=str(out_dir),
        preset=None,
        reddit_mode="auto",
        subreddits=[],
        dedupe=False,
        cache=str(cache_path),
        refresh=refresh,
        sample=0,
        yt_transcripts="off",
        yt_transcripts_limit=0,
    )


def test_cache_skips_seen_items(tmp_path, mock_youtube):
    cache_path = tmp_path / "seen.db"

    # First run: populates cache
    args1 = _args(tmp_path, cache_path, refresh=False)
    eff = _effective()
    code1 = run_collect(args1, eff, log=__import__("logging").getLogger(__name__))
    assert code1 == 0
    run1 = sorted([p for p in tmp_path.iterdir() if p.is_dir()])[-1]
    manifest1 = json.loads((run1 / "run_manifest.json").read_text())
    assert manifest1["dropped_by_cache"] == 0

    # Second run: should drop already seen items
    args2 = _args(tmp_path, cache_path, refresh=False)
    code2 = run_collect(args2, eff, log=__import__("logging").getLogger(__name__))
    assert code2 == 0
    run2 = sorted([p for p in tmp_path.iterdir() if p.is_dir()])[-1]
    manifest2 = json.loads((run2 / "run_manifest.json").read_text())
    assert manifest2["dropped_by_cache"] >= 1

    # Third run with refresh should ignore cache
    args3 = _args(tmp_path, cache_path, refresh=True)
    code3 = run_collect(args3, eff, log=__import__("logging").getLogger(__name__))
    assert code3 == 0
    run3 = sorted([p for p in tmp_path.iterdir() if p.is_dir()])[-1]
    manifest3 = json.loads((run3 / "run_manifest.json").read_text())
    assert manifest3["dropped_by_cache"] == 0


