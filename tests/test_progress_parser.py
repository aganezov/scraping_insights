from insight_mine.guis.pywebview import progress_parser as pp


def test_parse_progress_line_extracts_values():
    line = "PROGRESS overall=42 yt=10 rd=5"

    result = pp.parse_progress_line(line)

    assert result == {"overall": 42, "youtube": 10, "reddit": 5}


def test_parse_telemetry_and_kept_counts():
    line = "Telemetry (YouTube): yt_video_kept:3, yt_comment_kept:7"

    src, tail = pp.parse_telemetry_line(line)
    par, com = pp.parse_kept_from_tail(tail)

    assert "YouTube" in src
    assert par == 3
    assert com == 7


def test_parse_json_event_handles_non_json():
    assert pp.parse_json_event("not json") is None
