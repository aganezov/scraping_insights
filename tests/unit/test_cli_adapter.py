from insight_mine.guis.pywebview.cli_adapter import slug, build_collect_cmd, normalize_collect_argv


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


def test_build_collect_cmd_uses_supported_cli_flags(tmp_path):
    k = {
        "topic": "t",
        "since": "2025-01-01",
        "lang": "en",
        "dedupe": True,
        "connectors": {"youtube": True, "reddit": True},
        "yt_videos": 1,
        "yt_comments_per_video": 2,
        "reddit_limit": 3,
        "reddit_comments": 4,
        "reddit_mode": "scrape",
        "reddit_source": "search",
        "reddit_query": "battery OR charging",
        "reddit_sort": "relevance",
        "reddit_t": "month",
    }
    cmd, _, _ = build_collect_cmd(k, {}, tmp_path, create_dirs=False)
    assert "--langs" in cmd
    assert "--dedupe" in cmd
    assert "--reddit-source" in cmd
    assert "--allow-scraping" in cmd
    assert "--lang" not in cmd
    assert "--limit" not in cmd


def test_normalize_collect_argv_enforces_source_toggles():
    argv = [
        "insight-mine", "collect",
        "--lang", "en",
        "--yt-videos", "5",
        "--yt-comments-per-video", "10",
        "--reddit-limit", "3",
        "--reddit-comments", "2",
        "--reddit-mode", "scrape",
    ]

    normalized = normalize_collect_argv(argv, selected={"youtube": False, "reddit": True})

    assert "--langs" in normalized
    assert "--lang" not in normalized
    assert normalized.count("--yt-videos") == 1
    yt_idx = normalized.index("--yt-videos")
    assert normalized[yt_idx + 1] == "0"
    assert "--yt-comments-per-video" not in normalized
    assert "--allow-scraping" in normalized

