from insight_mine.cli.args import build_parser, resolve_settings


def test_preset_override_respects_explicit_flags():
    parser = build_parser()
    args = parser.parse_args(["collect", "--topic", "t", "--preset", "strict", "--yt-videos", "50"])

    effective = resolve_settings(args)

    assert effective["yt_videos"] == 50  # explicit flag overrides preset
    # order should still come from preset since not explicitly set
    assert effective["yt_order"] == "viewCount"


def test_legacy_reddit_limit_used_when_current_missing():
    parser = build_parser()
    args = parser.parse_args(["collect", "--topic", "t"])
    args.reddit_limit = None
    args.reddit_limit_legacy = 5

    effective = resolve_settings(args)

    assert effective["reddit_limit"] == 5


def test_channel_allow_block_lists_trim_whitespace():
    parser = build_parser()
    args = parser.parse_args([
        "collect", "--topic", "t",
        "--yt-channel-allow", "foo , bar ",
        "--yt-channel-block", "baz,qux ",
    ])

    effective = resolve_settings(args)

    assert effective["yt_allow"] == ["foo", "bar"]
    assert effective["yt_block"] == ["baz", "qux"]


def test_langs_resolves_with_env_fallback(monkeypatch):
    parser = build_parser()
    args = parser.parse_args(["collect", "--topic", "t"])
    args.langs = ""
    monkeypatch.setenv("LANGS", "en,es")

    effective = resolve_settings(args)

    assert effective["langs"] == ["en", "es"]
