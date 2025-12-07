from insight_mine.guis.pywebview.cli_adapter import slug, build_collect_cmd
from pathlib import Path


def test_slug_sanitizes_and_truncates():
    assert slug("Hello World!") == "hello_world"
    assert len(slug("x" * 100)) <= 40


def test_build_collect_cmd_includes_youtube_flags(tmp_path):
    k = {
        "topic": "t",
        "since": "2025-01-01",
        "lang": "en",
        "connectors": {"youtube": True, "reddit": True},
        "yt_videos": 5,
        "yt_max_comments": 10,
        "yt_min_views": 5000,
        "yt_min_duration": 120,
        "yt_min_comment_likes": 2,
        "yt_order": "viewCount",
        "reddit_limit": 0,
    }
    cmd, run_id, run_dir = build_collect_cmd(k, {}, tmp_path, create_dirs=False)
    assert "--yt-videos" in cmd
    assert "--yt-min-views" in cmd
    assert str(run_dir).startswith(str(tmp_path))
    assert run_id


def test_build_collect_cmd_excludes_disabled_reddit(tmp_path):
    k = {
        "topic": "t",
        "since": "2025-01-01",
        "lang": "en",
        "connectors": {"youtube": True, "reddit": False},
        "yt_videos": 1,
        "reddit_limit": 10,
    }
    cmd, _, _ = build_collect_cmd(k, {}, tmp_path, create_dirs=False)
    assert "--reddit-limit" not in cmd


