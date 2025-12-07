import json
from pathlib import Path

from insight_mine.guis.pywebview import storage


def test_build_ui_run_infers_topic_from_manifest(tmp_path):
    run_dir = tmp_path / "20250101_000000"
    run_dir.mkdir(parents=True, exist_ok=True)
    # seed run_manifest with topic so build_ui_run can infer
    (run_dir / "run_manifest.json").write_text(json.dumps({"topic": "from_manifest"}), encoding="utf-8")
    run = storage.build_ui_run("20250101_000000", run_dir, knobs={})
    assert run["manifest"]["knobs"]["topic"] == "from_manifest"
    assert (run_dir / "run.json").exists()


def test_list_runs_returns_created_runs(tmp_path):
    out_root = tmp_path
    rd1 = out_root / "20250101_000000"
    rd1.mkdir()
    rd1_manifest = {
        "id": "20250101_000000",
        "manifest": {"knobs": {"topic": "t1"}, "items": []},
        "stats": {"dropped": {}},
    }
    (rd1 / "run.json").write_text(json.dumps(rd1_manifest), encoding="utf-8")

    rd2 = out_root / "20250102_000000"
    rd2.mkdir()
    rd2_manifest = {
        "id": "20250102_000000",
        "manifest": {"knobs": {"topic": "t2"}, "items": []},
        "stats": {"dropped": {}},
    }
    (rd2 / "run.json").write_text(json.dumps(rd2_manifest), encoding="utf-8")

    runs = storage.list_runs(out_root)
    topics = {r["topic"] for r in runs}
    assert "t1" in topics and "t2" in topics


