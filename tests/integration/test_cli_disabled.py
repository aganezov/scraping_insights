from types import SimpleNamespace
import json

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


def _args(out_dir):
    return SimpleNamespace(
        topic="t",
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


def test_all_connectors_disabled_produces_empty_output(tmp_path, monkeypatch):
    from insight_mine import connectors as connectors_pkg
    monkeypatch.setattr(connectors_pkg.youtube, "status", lambda: (False, "missing key"))
    monkeypatch.setattr(connectors_pkg.youtube, "collect", lambda *a, **k: [])
    monkeypatch.setattr(connectors_pkg.reddit, "status", lambda: (False, "disabled"))
    monkeypatch.setattr(connectors_pkg.reddit, "collect", lambda *a, **k: [])
    monkeypatch.setattr(connectors_pkg.reddit_scrape, "status", lambda: (False, "disabled"))
    monkeypatch.setattr(connectors_pkg.reddit_scrape, "collect", lambda *a, **k: [])

    args = _args(tmp_path)
    eff = _effective()
    code = run_collect(args, eff, log=__import__("logging").getLogger(__name__))
    assert code == 0
    run_dirs = sorted(tmp_path.iterdir())
    latest = run_dirs[-1]
    manifest = json.loads((latest / "run_manifest.json").read_text())
    assert manifest["counts"]["total"] == 0


