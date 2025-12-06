
from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    import keyring  # optional
except Exception:  # pragma: no cover
    keyring = None

SERVICE = "insight-mine"
_DOTENV_LOADED = False


def _load_dotenv() -> None:
    """Populate os.environ from project .env if present."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    if os.environ.get("INSIGHT_MINE_DISABLE_DOTENV") == "1":
        _DOTENV_LOADED = True
        return
    _DOTENV_LOADED = True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if value and value[0] in {'"', "'"} and value[-1:] == value[0]:
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except Exception as exc:  # pragma: no cover - non-critical helper
        log.debug("Unable to load .env: %s", exc)


def _from_env(name: str) -> Optional[str]:
    _load_dotenv()
    val = os.environ.get(name)
    return val.strip() if val else None


def _from_keyring(name: str) -> Optional[str]:
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE, name)
    except Exception:
        log.debug("Keyring not available.")
        return None


def get_secret(name: str) -> Optional[str]:
    """Env has priority; falls back to macOS Keychain via keyring if present."""
    return _from_env(name) or _from_keyring(name)
