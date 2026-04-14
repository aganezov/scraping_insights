# Copies a packaged seed env into Application Support on first run
import shutil
import sys
from pathlib import Path


def app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "InsightMine"


def seed_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "resources" / "seed_settings.env"


def _has_meaningful_content(p: Path) -> bool:
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception:
        return False
    for line in txt.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return True
    return False


def main():
    try:
        dest = app_support_dir() / "settings.env"
        src = seed_path()
        if not src.exists():
            return
        should_copy = False
        if not dest.exists():
            should_copy = True
        else:
            # Replace if dest is empty/comment-only (e.g., stub from prior run)
            if not _has_meaningful_content(dest):
                should_copy = True
        if should_copy:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
    except Exception:
        # Do not break the app if the copy fails
        pass


main()

