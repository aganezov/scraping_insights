from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import webview

from insight_mine.guis.pywebview import envutil
from insight_mine.guis.pywebview.app import _assets_dir, _bridge_bootstrap_js, _bridge_js_path, _read
from insight_mine.guis.pywebview.bridge import Bridge


@dataclass(frozen=True)
class Scenario:
    name: str
    topic: str
    youtube: bool
    reddit: bool
    transcript_mode: str
    require_youtube_key: bool
    timeout_s: float
    out_dir_name: str


SCENARIOS = {
    "fake-happy": Scenario(
        name="fake-happy",
        topic="battery charging anxiety",
        youtube=True,
        reddit=True,
        transcript_mode="off",
        require_youtube_key=False,
        timeout_s=12.0,
        out_dir_name="gui-smoke-out",
    ),
    "real-youtube-free": Scenario(
        name="real-youtube-free",
        topic="battery charging anxiety",
        youtube=True,
        reddit=False,
        transcript_mode="free",
        require_youtube_key=True,
        timeout_s=45.0,
        out_dir_name="gui-e2e-free-out",
    ),
}

EXPECTED_RUN_FILES = ("raw.jsonl", "paste-ready.txt", "run.json", "run_manifest.json")


def _scenario(name: str) -> Scenario:
    try:
        return SCENARIOS[name]
    except KeyError as exc:  # pragma: no cover - argparse choices prevents this
        raise ValueError(f"unknown scenario: {name}") from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_out_dir(scenario: Scenario) -> Path:
    return _repo_root() / "tmp" / scenario.out_dir_name


def _default_report_path(scenario: Scenario) -> Path:
    return _repo_root() / "tmp" / f"{scenario.name}-report.json"


def _default_since() -> str:
    return (date.today() - timedelta(days=30)).isoformat()


def _project_script_path(name: str) -> Path:
    candidates = [
        Path(sys.executable).with_name(name),
        _repo_root() / ".venv" / "bin" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"{name} not found next to {sys.executable}")


def build_runtime_env_text(base_text: str, *, out_dir: Path, scenario: Scenario, fake_cli_bin: Path | None = None) -> str:
    text = base_text or ""
    text = envutil.upsert_env_key(text, "IM_OUT_DIR", str(out_dir.resolve()))
    text = envutil.upsert_env_key(text, "YTTI_SKIP_PAID", "1")
    text = envutil.upsert_env_key(text, "YTTI_FREE_TIMEOUT_SEC", "10")
    if scenario.name == "fake-happy":
        if fake_cli_bin is None:
            raise ValueError("fake_cli_bin is required for fake-happy scenario")
        text = envutil.upsert_env_key(text, "ALLOW_SCRAPING", "1")
        text = envutil.upsert_env_key(text, "IM_CLI_BIN", str(fake_cli_bin.resolve()))
    return text


def preflight_errors(scenario: Scenario, env: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if env.get("YTTI_SKIP_PAID") != "1":
        errors.append("YTTI_SKIP_PAID=1 is required for smoke runs that must avoid paid transcripts")
    if scenario.require_youtube_key and not (env.get("YOUTUBE_API_KEY") or "").strip():
        errors.append("YOUTUBE_API_KEY is required for the real YouTube free-transcript smoke run")
    return errors


def _find_latest_run_dir(out_root: Path) -> Path | None:
    latest = out_root / "latest"
    if latest.is_symlink():
        try:
            return latest.resolve()
        except OSError:
            pass
    runs = sorted(
        (path for path in out_root.iterdir() if path.is_dir() and path.name != "latest"),
        key=lambda path: path.name,
        reverse=True,
    ) if out_root.exists() else []
    return runs[0] if runs else None


def artifact_errors(run_dir: Path | None) -> list[str]:
    if run_dir is None:
        return ["no run directory found under output root"]
    return [f"missing artifact: {name}" for name in EXPECTED_RUN_FILES if not (run_dir / name).exists()]


def report_errors(report: dict[str, Any]) -> list[str]:
    if not report.get("ok"):
        return [str(report.get("error") or "probe failed")]
    steps = report.get("steps") or []
    if not steps:
        return ["probe did not record any steps"]
    final = steps[-1].get("snapshot") or {}
    errors: list[str] = []
    if not final.get("resultsTabActive"):
        errors.append("results tab did not open")
    if not final.get("currentRunId"):
        errors.append("no current run id present in the final GUI snapshot")
    if int(final.get("currentRunItems") or 0) <= 0:
        errors.append("no items surfaced in the final GUI snapshot")
    if "DONE" not in str(final.get("log") or "") and "CLI exited with code 0" not in str(final.get("log") or ""):
        errors.append("run log never reached a successful terminal marker")
    main_links_total = int(final.get("mainRowLinksTotal") or 0)
    main_links_unique = int(final.get("mainRowLinksUnique") or 0)
    if main_links_total > 0 and main_links_unique != main_links_total:
        errors.append(
            f"results table rendered duplicate parent rows ({main_links_unique} unique links for {main_links_total} rendered rows)"
        )
    for name, ok in (report.get("interaction_checks") or {}).items():
        if not ok:
            errors.append(f"interaction check failed: {name}")
    return errors


def _preflight_payload(scenario: Scenario, errors: list[str], *, out_root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "scenario": scenario.name,
        "error": "; ".join(errors),
        "preflight_errors": errors,
        "out_root": str(out_root),
    }


def _json_eval(win: Any, expr: str) -> Any:
    raw = win.evaluate_js(
        f"""
        (() => {{
          const value = ({expr});
          return JSON.stringify(value);
        }})()
        """
    )
    return json.loads(raw)


def _eval(win: Any, js: str) -> Any:
    return win.evaluate_js(js)


def _wait_for(win: Any, expr: str, *, timeout_s: float, interval_s: float = 0.1) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _json_eval(win, expr):
            return True
        time.sleep(interval_s)
    return False


def _set_checkbox(win: Any, element_id: str, checked: bool) -> None:
    _eval(
        win,
        f"""
        (() => {{
          const el = document.getElementById({json.dumps(element_id)});
          if (!el) return false;
          el.checked = {str(checked).lower()};
          el.dispatchEvent(new Event('change', {{bubbles:true}}));
          el.dispatchEvent(new Event('input', {{bubbles:true}}));
          return true;
        }})()
        """,
    )


def _set_value(win: Any, element_id: str, value: str) -> None:
    _eval(
        win,
        f"""
        (() => {{
          const el = document.getElementById({json.dumps(element_id)});
          if (!el) return false;
          el.value = {json.dumps(value)};
          el.dispatchEvent(new Event('input', {{bubbles:true}}));
          el.dispatchEvent(new Event('change', {{bubbles:true}}));
          return true;
        }})()
        """,
    )


def _click(win: Any, element_id: str) -> None:
    _eval(
        win,
        f"""
        (() => {{
          const el = document.getElementById({json.dumps(element_id)});
          if (!el) return false;
          el.click();
          return true;
        }})()
        """,
    )


def _click_selector(win: Any, selector: str) -> None:
    _eval(
        win,
        f"""
        (() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) return false;
          el.click();
          return true;
        }})()
        """,
    )


def _scroll_to_actions(win: Any) -> None:
    _eval(
        win,
        """
        (() => {
          const target = document.getElementById('runBtn');
          if (!target) return false;
          target.scrollIntoView({behavior:'instant', block:'center'});
          return true;
        })()
        """,
    )


def _snapshot(win: Any) -> dict[str, Any]:
    return _json_eval(
        win,
        """
        (() => ({
          redditSelector: document.getElementById('redditSelector')?.value || '',
          topic: document.getElementById('topic')?.value || '',
          since: document.getElementById('since')?.value || '',
          youtubeEnabled: !!document.getElementById('enableYoutube')?.checked,
          redditEnabled: !!document.getElementById('enableReddit')?.checked,
          transcriptMode: document.getElementById('transcriptMode')?.value || '',
          cmd: document.getElementById('cmd')?.value || document.getElementById('cmd')?.textContent || '',
          ytStatus: document.getElementById('ytStatus')?.textContent || '',
          rdStatus: document.getElementById('rdStatus')?.textContent || '',
          trStatus: document.getElementById('trStatus')?.textContent || '',
          ytCount: document.getElementById('ytCount')?.textContent || '',
          rdCount: document.getElementById('rdCount')?.textContent || '',
          progressOverall: document.getElementById('progOverall')?.style.width || '',
          progressYT: document.getElementById('progYT')?.style.width || '',
          progressRD: document.getElementById('progRD')?.style.width || '',
          log: document.getElementById('log')?.textContent || '',
          runLabel: document.getElementById('runBtnLabel')?.textContent || '',
          resultsTabActive: document.querySelector('.tab[data-tab="results"]')?.classList.contains('active') || false,
          runItems: Array.isArray(window.runs) ? window.runs.length : -1,
          currentRunId: window.currentRun?.id || '',
          currentRunItems: window.currentRun?.manifest?.items?.length || 0,
          exportMeta: document.getElementById('exportMeta')?.textContent || '',
          rowCount: document.getElementById('rowCount')?.textContent || '',
          mainRowLinksTotal: Array.from(document.querySelectorAll('#resultsBody tr:not(.details-row) td:last-child a')).length,
          mainRowLinksUnique: new Set(Array.from(document.querySelectorAll('#resultsBody tr:not(.details-row) td:last-child a')).map(el => el.getAttribute('href') || '')).size,
        }))()
        """,
    )


def _exercise_interactions(win: Any, scenario: Scenario) -> dict[str, bool]:
    checks: dict[str, bool] = {}

    _click(win, "hideCollectHero")
    time.sleep(0.1)
    checks["collect_intro_hides"] = bool(
        _json_eval(
            win,
            "document.getElementById('collectHero')?.classList.contains('hidden') && !document.getElementById('collectHeroReveal')?.classList.contains('hidden')",
        )
    )
    _click(win, "showCollectHero")
    time.sleep(0.1)
    checks["collect_intro_restores"] = bool(
        _json_eval(
            win,
            "!document.getElementById('collectHero')?.classList.contains('hidden') && document.getElementById('collectHeroReveal')?.classList.contains('hidden')",
        )
    )

    _click_selector(win, '.topic-idea[data-topic="JetBrains"]')
    time.sleep(0.1)
    checks["topic_chip_sets_topic"] = _snapshot(win).get("topic") == "JetBrains"

    _click_selector(win, '.quick-since[data-days="7"]')
    time.sleep(0.1)
    checks["quick_since_sets_date"] = bool(_snapshot(win).get("since"))

    _set_checkbox(win, "enableReddit", False)
    time.sleep(0.1)
    disabled_snap = _snapshot(win)
    checks["reddit_toggle_updates_status"] = (
        disabled_snap.get("redditEnabled") is False
        and "disabled" in str(disabled_snap.get("rdStatus", "")).lower()
    )
    _set_checkbox(win, "enableReddit", scenario.reddit)

    _click(win, "openSubredditPicker")
    time.sleep(0.1)
    checks["subreddit_modal_opens"] = bool(
        _json_eval(win, "document.getElementById('modalSubreddits')?.style.display === 'block'")
    )
    _click(win, "closeSubredditsBtn")

    _click(win, "explain")
    time.sleep(0.1)
    checks["explain_modal_opens"] = bool(
        _json_eval(win, "document.getElementById('modalExplain')?.style.display === 'block'")
    )
    _eval(win, "window.closeExplain && window.closeExplain()")

    return checks


def _run_sequence(win: Any, scenario: Scenario) -> dict[str, Any]:
    report: dict[str, Any] = {"scenario": scenario.name, "steps": []}

    def record(label: str) -> None:
        report["steps"].append({"label": label, "snapshot": _snapshot(win)})

    _wait_for(win, "document.readyState === 'interactive' || document.readyState === 'complete'", timeout_s=10.0)
    time.sleep(1.0)
    report["ready_diag_pre"] = _json_eval(
        win,
        """
        (() => ({
          readyState: document.readyState,
          hasRunBtn: !!document.getElementById('runBtn'),
          hasCmd: !!document.getElementById('cmd'),
          hasTopic: !!document.getElementById('topic'),
          updateCmdType: typeof window.updateCmd,
          collectKnobsType: typeof window.collectKnobs,
          imBridgeType: typeof window.IMBridge,
          pywebview: !!window.pywebview,
        }))()
        """,
    )
    if report["ready_diag_pre"].get("updateCmdType") != "function":
        raise RuntimeError(f"GUI scripts did not finish loading: {report['ready_diag_pre']}")

    _eval(win, _bridge_bootstrap_js(_read(_bridge_js_path())))
    if not _wait_for(win, "typeof window.collectKnobs === 'function' && typeof window.IMBridge === 'object'", timeout_s=10.0):
        raise RuntimeError("Bridge injection did not finish loading")

    report["interaction_checks"] = _exercise_interactions(win, scenario)
    record("initial")

    _set_value(win, "topic", scenario.topic)
    _set_value(win, "since", _default_since())
    _set_checkbox(win, "enableYoutube", scenario.youtube)
    _set_checkbox(win, "enableReddit", scenario.reddit)
    _set_value(win, "transcriptMode", scenario.transcript_mode)
    _scroll_to_actions(win)
    record("configured")
    configured = _snapshot(win)
    if scenario.reddit:
        report["interaction_checks"]["reddit_defaults_to_search_preview"] = (
            configured.get("redditSelector") == "search"
            and "--reddit-source search" in str(configured.get("cmd", ""))
        )

    _click(win, "runBtn")
    time.sleep(0.5)
    record("after-run-click")

    deadline = time.time() + scenario.timeout_s
    terminal_markers = ("DONE", "CLI exited with code", "Cancelled", "failed to assemble run", "Failed to launch CLI")
    while time.time() < deadline:
        snap = _snapshot(win)
        log = str(snap.get("log", ""))
        if any(marker in log for marker in terminal_markers) or snap.get("currentRunItems", 0):
            report["steps"].append({"label": "settled", "snapshot": snap})
            break
        time.sleep(0.5)
    else:
        report["steps"].append({"label": "timeout", "snapshot": _snapshot(win)})

    _click_selector(win, '.tab[data-tab="results"]')
    time.sleep(0.8)
    record("results-opened")

    _click(win, "runBtnOpen")
    time.sleep(0.2)
    report["interaction_checks"]["run_menu_opens"] = bool(
        _json_eval(win, "document.getElementById('runMenu')?.style.display === 'block'")
    )
    report["interaction_checks"]["results_rowcount_updates"] = "Filtered " in str(_snapshot(win).get("rowCount", ""))

    _click_selector(win, '.tab[data-tab="collect"]')
    time.sleep(0.2)
    report["interaction_checks"]["collect_tab_restores"] = not bool(
        _snapshot(win).get("resultsTabActive")
    )

    _click_selector(win, '.tab[data-tab="results"]')
    time.sleep(0.4)
    record("results-reopened")
    return report


def run_smoke(env_path: Path, scenario_name: str) -> dict[str, Any]:
    scenario = _scenario(scenario_name)
    bridge = Bridge(env_path=str(env_path))
    ui_html = (_assets_dir() / "ui.html").read_text(encoding="utf-8")
    win = webview.create_window(
        title=f"Insight Mine Smoke ({scenario.name})",
        html=ui_html,
        width=1280,
        height=900,
        resizable=True,
        easy_drag=False,
        js_api=bridge,
    )
    if win is None:
        raise RuntimeError("failed to create smoke window")

    outcome: dict[str, Any] = {}

    def on_start() -> None:
        nonlocal outcome
        try:
            outcome = {"ok": True, **_run_sequence(win, scenario)}
        except Exception as exc:  # pragma: no cover - live smoke path
            outcome = {"ok": False, "scenario": scenario.name, "error": str(exc), "steps": []}
        finally:
            win.destroy()

    webview.start(on_start, debug=False)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="fake-happy")
    parser.add_argument("--env", default=None, help="Base env file to layer for real scenarios")
    parser.add_argument("--out", default=None, help="Output root override")
    parser.add_argument("--report", default=None, help="Path to write the smoke report JSON")
    args = parser.parse_args(argv)

    scenario = _scenario(args.scenario)
    out_root = Path(args.out).expanduser() if args.out else _default_out_dir(scenario)
    out_root.mkdir(parents=True, exist_ok=True)

    base_text = ""
    if args.env:
        base_path = Path(args.env).expanduser()
        base_text = base_path.read_text(encoding="utf-8") if base_path.exists() else ""

    fake_cli_bin = _project_script_path("insight-mine-fake-cli") if scenario.name == "fake-happy" else None
    runtime_env_text = build_runtime_env_text(base_text, out_dir=out_root, scenario=scenario, fake_cli_bin=fake_cli_bin)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".env", delete=False) as handle:
        handle.write(runtime_env_text)
        runtime_env_path = Path(handle.name)

    report_path = Path(args.report).expanduser() if args.report else _default_report_path(scenario)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    env = envutil.compose_env(runtime_env_path)
    errors = preflight_errors(scenario, env)
    if errors:
        payload = _preflight_payload(scenario, errors, out_root=out_root)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            runtime_env_path.unlink()
        except OSError:
            pass
        return 1

    try:
        report = run_smoke(runtime_env_path, scenario.name)
    finally:
        try:
            runtime_env_path.unlink()
        except OSError:
            pass

    run_dir = _find_latest_run_dir(out_root)
    validation_errors = report_errors(report) + artifact_errors(run_dir)
    report.update(
        {
            "out_root": str(out_root),
            "run_dir": str(run_dir) if run_dir else "",
            "validation_errors": validation_errors,
        }
    )
    report["ok"] = report.get("ok", False) and not validation_errors
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
