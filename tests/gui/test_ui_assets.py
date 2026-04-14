from __future__ import annotations

from pathlib import Path
import re


def _assets_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "insight_mine"
        / "guis"
        / "pywebview"
        / "assets"
    )


def _ui_html() -> str:
    path = _assets_dir() / "ui.html"
    return path.read_text(encoding="utf-8")


def _bridge_js() -> str:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "insight_mine"
        / "guis"
        / "pywebview"
        / "bridge_inject.js"
    )
    return path.read_text(encoding="utf-8")


def test_active_ui_is_not_mock_branded():
    html = _ui_html()

    assert "<title>Insight Mine</title>" in html
    assert "Interactive Mock v15" not in html


def test_active_ui_preview_uses_supported_cli_flags():
    html = _ui_html()

    assert "--yt-max-comments" in html
    assert "--reddit-mode scrape" in html
    assert "--reddit-limit" in html
    assert "--allow-scraping" in html
    assert "--yt-comments-per-video" not in html


def test_active_ui_declares_ready_marker_and_safe_storage_helpers():
    html = _ui_html()

    assert "function safeStorageGet" in html
    assert "function safeStorageSet" in html
    assert "window.__imUiReady = true;" in html


def test_active_ui_collect_hero_is_dismissible_with_updated_topic_chips():
    html = _ui_html()

    assert 'id="collectHero"' in html
    assert 'id="collectHeroReveal"' in html
    assert 'id="hideCollectHero"' in html
    assert 'id="showCollectHero"' in html
    assert 'COLLECT_HERO_PREF_KEY' in html
    assert 'data-topic="JetBrains"' in html
    assert 'data-topic="Coding"' in html
    assert 'data-topic="Software Development"' in html
    assert 'data-topic="EV charging anxiety"' not in html
    assert 'id="openSourceUpdate"' in html


def test_pywebview_assets_only_ship_live_ui_entrypoint():
    html_files = sorted(path.name for path in _assets_dir().glob("*.html"))

    assert html_files == ["ui.html"]


def test_bridge_static_dom_ids_match_live_ui():
    html = _ui_html()
    js = _bridge_js()

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r'getElementById\(["\']([^"\']+)["\']\)', js))
    js_ids |= set(re.findall(r'querySelector\(["\']#([A-Za-z0-9_-]+)', js))

    allowed_missing = {
        "clearLogBtn",
        "envMock",
        "outDirChip",
        "outDirLabel",
        "saveSettingsBtn",
    }

    missing = {id_ for id_ in js_ids if id_ not in html_ids}

    assert missing <= allowed_missing
    assert "stats" not in js_ids
    assert {"keptT", "dropT"} <= js_ids


def test_bridge_export_path_uses_bridge_filtered_subset():
    js = _bridge_js()

    assert "window.getFilteredSortedItems(true)" in js
    assert "window.getParentsSubset ? window.getParentsSubset()" not in js
