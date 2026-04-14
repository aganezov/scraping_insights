from types import SimpleNamespace
from pathlib import Path
import json

from insight_mine.cli.orchestrator import run_collect


def _effective_defaults():
    return {
        "langs": ["en"],
        "yt_videos": 2,
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


def _args(out_dir: Path):
    return SimpleNamespace(
        topic="integration-topic",
        since="2025-01-01",
        out=str(out_dir),
        preset=None,
        reddit_mode="auto",
        subreddits=[],
        dedupe=False,
        cache="",
        refresh=False,
        sample=0,
        yt_transcripts="off",
        yt_transcripts_limit=0,
    )


def test_youtube_collect_creates_outputs(tmp_path, mock_youtube):
    args = _args(tmp_path)
    effective = _effective_defaults()
    effective["yt_videos"] = 1
    code = run_collect(args, effective, log=__import__("logging").getLogger(__name__))
    assert code == 0
    # newest directory in out
    run_dirs = sorted(tmp_path.iterdir())
    assert run_dirs
    latest = run_dirs[-1]
    assert (latest / "raw.jsonl").exists()
    assert (latest / "paste-ready.txt").exists()
    manifest = json.loads((latest / "run_manifest.json").read_text())
    assert manifest["topic"] == "integration-topic"
    assert manifest["counts"]["youtube_video"] >= 1


def test_reddit_collect_creates_outputs(tmp_path, mock_reddit):
    args = _args(tmp_path)
    effective = _effective_defaults()
    effective.update({
        "reddit_limit": 1,
        "reddit_comments": 1,
    })
    # enable reddit, disable youtube
    from insight_mine import connectors as connectors_pkg
    connectors_pkg.youtube.status = lambda: (False, "disabled")
    connectors_pkg.youtube.collect = lambda *a, **k: []

    code = run_collect(args, effective, log=__import__("logging").getLogger(__name__))
    assert code == 0
    run_dirs = sorted(tmp_path.iterdir())
    latest = run_dirs[-1]
    manifest = json.loads((latest / "run_manifest.json").read_text())
    assert manifest["counts"]["reddit_post"] >= 1 or manifest["counts"]["reddit_comment"] >= 1


