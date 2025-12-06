# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

block_cipher = None

spec_path = Path(sys.argv[0]).resolve()
proj_root = spec_path.parents[1]
src_root = proj_root / "src"

# Use a stable entrypoint that imports the package, to keep relative imports valid.
entry = proj_root / "packaging" / "cli_entry.py"

a = Analysis(
    [str(entry)],
    pathex=[str(src_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name="insight-mine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

