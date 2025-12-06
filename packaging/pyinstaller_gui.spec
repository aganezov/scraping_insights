# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

block_cipher = None

spec_path = Path(sys.argv[0]).resolve()
proj_root = spec_path.parents[1]
src_root = proj_root / "src"

version = (proj_root / "packaging" / "VERSION").read_text(encoding="utf-8").strip()

gui_script = src_root / "insight_mine" / "guis" / "pywebview" / "app.py"

datas = [
    (str(src_root / "insight_mine" / "guis" / "pywebview" / "assets"), "insight_mine/guis/pywebview/assets"),
    (str(src_root / "insight_mine" / "guis" / "pywebview" / "bridge_inject.js"), "insight_mine/guis/pywebview/bridge_inject.js"),
]

seed_env = proj_root / "packaging" / "seed_settings.env"
if seed_env.exists():
    datas.append((str(seed_env), "resources/seed_settings.env"))

binaries = []
# Bundle the onefile CLI binary if present (dist/insight-mine)
cli_bin = proj_root / "dist" / "insight-mine"
if cli_bin.exists():
    binaries.append((str(cli_bin), "."))

runtime_hooks = [
    str(proj_root / "packaging" / "hooks" / "bootstrap_env.py"),
    str(proj_root / "packaging" / "hooks" / "set_cli_bin.py"),
]


a = Analysis(
    [str(gui_script)],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Insight Mine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(proj_root / "packaging" / "app.icns"),
)

app = BUNDLE(
    exe,
    name="Insight Mine.app",
    icon=str(proj_root / "packaging" / "app.icns"),
    bundle_identifier="com.insightmine.app",
    info_plist={
        "CFBundleName": "Insight Mine",
        "CFBundleDisplayName": "Insight Mine",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
    },
)

