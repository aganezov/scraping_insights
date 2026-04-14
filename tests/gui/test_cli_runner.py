import sys

from insight_mine.guis.pywebview.cli_runner import CliRunner


def test_cli_runner_parses_progress_and_finishes(tmp_path):
    counts = {"yt_par": 0, "yt_com": 0, "rd_par": 0, "rd_com": 0}
    finished = {"code": None}

    runner = CliRunner(
        selected={"youtube": True, "reddit": False},
        counts=counts,
        clamp_overall=None,
        parse_kept=lambda tail, src: (1, 2),
    )

    script = (
        "import sys, time\n"
        "print('Telemetry (YouTube): yt_video_kept:1, yt_comment_kept:2')\n"
        "print('PROGRESS overall=10 yt=5')\n"
    )

    def on_finished(code):
        finished["code"] = code

    runner.start(
        cmd=[sys.executable, "-c", script],
        env={},
        on_log=lambda line: None,
        emit_progress=lambda **kwargs: None,
        emit_yt_counts=lambda *args, **kwargs: None,
        emit_rd_counts=lambda *args, **kwargs: None,
        emit_counts=lambda: None,
        on_finished=on_finished,
    )

    runner.finish_t.join(timeout=5)
    runner.reader_t.join(timeout=5)

    assert finished["code"] == 0
    assert counts["yt_par"] == 1
    assert counts["yt_com"] == 2


