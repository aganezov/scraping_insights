import os
import sys
from pathlib import Path

# Prefer the bundled CLI binary extracted by PyInstaller (onefile uses _MEIPASS).
def _resolve_cli_bin() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "insight-mine"
        if candidate.exists():
            return candidate
    # Fallback: sibling of the GUI executable (onedir) or same name replacement.
    return Path(sys.executable).with_name("insight-mine")


cli = _resolve_cli_bin()
os.environ.setdefault("IM_CLI_BIN", str(cli))



