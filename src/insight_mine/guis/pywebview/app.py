from __future__ import annotations
from pathlib import Path
import argparse
import importlib.resources as importlib_resources
import pkgutil
import sys
import time
import webview

from insight_mine.guis.pywebview.bridge import Bridge


def _bundle_base() -> Path:
    """
    Resolve the base path for bundled resources when frozen with PyInstaller.
    Falls back to the source layout when running from the repo.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _assets_dir() -> Path:
    # When frozen, assets are collected under insight_mine/guis/pywebview/assets
    bundled = _bundle_base() / "insight_mine" / "guis" / "pywebview" / "assets"
    if bundled.exists():
        return bundled
    return Path(__file__).resolve().parent / "assets"


def _bridge_js_path() -> Path:
    bundled = _bundle_base() / "insight_mine" / "guis" / "pywebview" / "bridge_inject.js"
    if bundled.is_file():
        return bundled
    if bundled.is_dir():
        inner = bundled / "bridge_inject.js"
        if inner.is_file():
            return inner
        # pick the first .js inside, if any
        for cand in bundled.glob("*.js"):
            return cand
    return Path(__file__).resolve().parent / "bridge_inject.js"


def _read(p: Path) -> str:
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8")
        if p.is_dir():
            nested = p / "bridge_inject.js"
            if nested.is_file():
                return nested.read_text(encoding="utf-8")
            # last resort: any .js inside that directory
            for cand in p.glob("*.js"):
                return cand.read_text(encoding="utf-8")
    except IsADirectoryError:
        pass
    # Fallback to package data (covers cases where PyInstaller treated the path oddly)
    try:
        data = pkgutil.get_data("insight_mine.guis.pywebview", "bridge_inject.js")
        if data is not None:
            return data.decode("utf-8")
    except IsADirectoryError:
        pass
    try:
        res = importlib_resources.files("insight_mine.guis.pywebview").joinpath("bridge_inject.js")
        if res.is_file():
            return res.read_text(encoding="utf-8")
    except Exception:
        pass
    raise FileNotFoundError(f"bridge_inject.js not found at {p}")

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env", default=None)
    # tolerate extra args (we only care about --env here)
    args, _ = parser.parse_known_args()

    assets_dir = _assets_dir()
    ui_path = assets_dir / "ui.html"
    bridge_js = _read(_bridge_js_path())

    # IMPORTANT: provide an instance so we can pass env_path
    js_api = Bridge(env_path=args.env)

    # Cache-bust: append timestamp to force WebKit to reload
    cache_bust = int(time.time())
    win = webview.create_window(
        title="Insight Mine",
        url=f"{ui_path.as_uri()}?v={cache_bust}",
        width=1280,
        height=900,
        resizable=True,
        easy_drag=False,
        js_api=js_api,
    )

    webview.start(lambda: win.evaluate_js(bridge_js), debug=False)

if __name__ == "__main__":
    main()
