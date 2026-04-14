
from insight_mine.guis.pywebview.bridge import Bridge


def test_normalize_knobs_flattens_v15_structure(monkeypatch, tmp_path):
    monkeypatch.setenv("IM_OUT_DIR", str(tmp_path))
    b = Bridge(env_path=None)
    knobs = {
        "advanced": {
            "yt": {"max_videos": 5, "comments_per_video": 10, "min_views": 1000},
            "rd": {"max_posts": 4, "comments_per_post": 3, "min_score": 2},
            "language": "es",
        },
        "connectors": {"youtube": True, "reddit": True},
    }
    out = b._normalize_knobs(knobs)
    assert out["yt_videos"] == 5
    assert out["reddit_limit"] == 4
    assert out["lang"] == "es"
    assert out["reddit_comments"] == 3
    assert out["reddit_source"] == "search"


def test_build_command_returns_valid_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("IM_OUT_DIR", str(tmp_path))
    b = Bridge(env_path=None)
    knobs = {"topic": "k1", "since": "2025-01-01", "yt_videos": 1, "connectors": {"youtube": True, "reddit": False}}
    result = b.build_command(knobs)
    assert result["ok"] is True
    cmd = result["cmd"]
    assert "collect" in cmd
    assert "k1" in result["cmd_string"]

