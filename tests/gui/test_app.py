from __future__ import annotations

from pathlib import Path

from insight_mine.guis.pywebview import app


def test_bridge_bootstrap_waits_for_base_ui_contract():
    bootstrap = app._bridge_bootstrap_js("window.__bridgeLoaded = true;")

    assert 'document.readyState === "complete"' in bootstrap
    assert "window.__imUiReady === true" in bootstrap
    assert "window.__imBridgeLoaded = true;" in bootstrap
    assert "window.__bridgeLoaded = true;" in bootstrap


def test_main_creates_window_and_injects_bridge(monkeypatch, tmp_path):
    ui_dir = tmp_path / "assets"
    ui_dir.mkdir()
    (ui_dir / "ui.html").write_text("<html></html>", encoding="utf-8")

    calls: dict[str, object] = {}

    class FakeWindow:
        def evaluate_js(self, js: str) -> None:
            calls["bridge_js"] = js

    class FakeWebview:
        @staticmethod
        def create_window(**kwargs):
            calls["window_kwargs"] = kwargs
            return FakeWindow()

        @staticmethod
        def start(func, debug=False):
            calls["debug"] = debug
            func()

    monkeypatch.setattr(app, "_assets_dir", lambda: ui_dir)
    monkeypatch.setattr(app, "_bridge_js_path", lambda: Path("/unused/bridge_inject.js"))
    monkeypatch.setattr(app, "_read", lambda _p: "window.__bridgeLoaded = true;")
    monkeypatch.setattr(app, "webview", FakeWebview)
    monkeypatch.setattr(app, "Bridge", lambda env_path=None: {"env_path": env_path})
    monkeypatch.setattr("sys.argv", ["insight-mine-gui", "--env", str(tmp_path / "settings.env")])

    app.main()

    kwargs = calls["window_kwargs"]
    assert kwargs["title"] == "Insight Mine"
    assert kwargs["js_api"] == {"env_path": str(tmp_path / "settings.env")}
    assert kwargs["html"] == "<html></html>"
    assert "url" not in kwargs
    assert "window.__bridgeLoaded = true;" in calls["bridge_js"]
    assert "window.__imBridgeLoaded = true;" in calls["bridge_js"]
    assert calls["debug"] is False


def test_main_raises_when_window_creation_fails(monkeypatch, tmp_path):
    ui_dir = tmp_path / "assets"
    ui_dir.mkdir()
    (ui_dir / "ui.html").write_text("<html></html>", encoding="utf-8")

    class FakeWebview:
        @staticmethod
        def create_window(**kwargs):
            return None

        @staticmethod
        def start(func, debug=False):
            raise AssertionError("webview.start should not run when window creation fails")

    monkeypatch.setattr(app, "_assets_dir", lambda: ui_dir)
    monkeypatch.setattr(app, "_bridge_js_path", lambda: Path("/unused/bridge_inject.js"))
    monkeypatch.setattr(app, "_read", lambda _p: "window.__bridgeLoaded = true;")
    monkeypatch.setattr(app, "webview", FakeWebview)
    monkeypatch.setattr(app, "Bridge", lambda env_path=None: {"env_path": env_path})
    monkeypatch.setattr("sys.argv", ["insight-mine-gui"])

    try:
        app.main()
    except RuntimeError as exc:
        assert "Failed to create Insight Mine window" in str(exc)
    else:
        raise AssertionError("app.main() should raise when webview.create_window returns None")
