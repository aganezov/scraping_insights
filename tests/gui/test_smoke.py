from __future__ import annotations

from insight_mine.guis.pywebview import smoke


def test_build_runtime_env_text_for_fake_scenario_sets_fake_cli_and_free_only(tmp_path):
    scenario = smoke.SCENARIOS["fake-happy"]
    fake_cli = tmp_path / "bin" / "insight-mine-fake-cli"
    fake_cli.parent.mkdir(parents=True, exist_ok=True)
    fake_cli.write_text("", encoding="utf-8")

    text = smoke.build_runtime_env_text(
        "YOUTUBE_API_KEY=test-key\n",
        out_dir=tmp_path / "out",
        scenario=scenario,
        fake_cli_bin=fake_cli,
    )

    env = smoke.envutil.parse_env_lines(text)

    assert env["YTTI_SKIP_PAID"] == "1"
    assert env["IM_CLI_BIN"] == str(fake_cli.resolve())
    assert env["ALLOW_SCRAPING"] == "1"
    assert env["IM_OUT_DIR"] == str((tmp_path / "out").resolve())


def test_preflight_errors_for_real_free_run_require_youtube_key():
    scenario = smoke.SCENARIOS["real-youtube-free"]

    errors = smoke.preflight_errors(scenario, {"YTTI_SKIP_PAID": "1"})

    assert errors == ["YOUTUBE_API_KEY is required for the real YouTube free-transcript smoke run"]


def test_find_latest_run_dir_prefers_latest_symlink(tmp_path):
    older = tmp_path / "20260410_010101"
    newer = tmp_path / "20260410_020202"
    older.mkdir()
    newer.mkdir()
    (tmp_path / "latest").symlink_to(newer.name)

    assert smoke._find_latest_run_dir(tmp_path) == newer.resolve()


def test_artifact_errors_report_missing_files(tmp_path):
    run_dir = tmp_path / "20260410_020202"
    run_dir.mkdir()
    (run_dir / "raw.jsonl").write_text("", encoding="utf-8")

    errors = smoke.artifact_errors(run_dir)

    assert "missing artifact: paste-ready.txt" in errors
    assert "missing artifact: run.json" in errors


def test_report_errors_detect_missing_terminal_state():
    report = {
        "ok": True,
        "steps": [
            {
                "label": "results-opened",
                "snapshot": {
                    "resultsTabActive": True,
                    "currentRunId": "20260410_123456",
                    "currentRunItems": 2,
                    "log": "still running",
                },
            }
        ],
    }

    errors = smoke.report_errors(report)

    assert errors == ["run log never reached a successful terminal marker"]


def test_report_errors_surface_failed_interaction_checks():
    report = {
        "ok": True,
        "interaction_checks": {"collect_tab_restores": False},
        "steps": [
            {
                "label": "results-opened",
                "snapshot": {
                    "resultsTabActive": True,
                    "currentRunId": "20260410_123456",
                    "currentRunItems": 2,
                    "log": "DONE",
                },
            }
        ],
    }

    errors = smoke.report_errors(report)

    assert errors == ["interaction check failed: collect_tab_restores"]


def test_report_errors_surface_duplicate_parent_rows():
    report = {
        "ok": True,
        "steps": [
            {
                "label": "results-opened",
                "snapshot": {
                    "resultsTabActive": True,
                    "currentRunId": "20260410_123456",
                    "currentRunItems": 3,
                    "log": "DONE",
                    "mainRowLinksTotal": 6,
                    "mainRowLinksUnique": 3,
                },
            }
        ],
    }

    errors = smoke.report_errors(report)

    assert errors == ["results table rendered duplicate parent rows (3 unique links for 6 rendered rows)"]
