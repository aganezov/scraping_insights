from __future__ import annotations
import os, re, sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path.home() / "Library" / "Application Support" / "InsightMine"

def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR

def default_env_path() -> Path:
    """
    Priority:
      - If running frozen (PyInstaller), avoid bundle cwd (read-only) and use
        Application Support settings.env.
      - Otherwise, use ./.env if present; fallback to Application Support.
    """
    frozen = getattr(sys, "frozen", False)
    if not frozen:
        cwd_env = Path(".env")
        if cwd_env.exists():
            return cwd_env
    p = ensure_app_dir() / "settings.env"
    if not p.exists():
        # create an empty starter
        p.write_text("# Insight Mine settings\n# Put your keys here, e.g.:\n# YOUTUBE_API_KEY=...\n", encoding="utf-8")
    return p

def resolve_env_path(cli_env: str | None) -> Path:
    frozen = getattr(sys, "frozen", False)
    if not cli_env:
        return default_env_path()

    p = Path(cli_env).expanduser()

    if frozen:
        # In a frozen app, avoid writing to the bundle cwd (read-only). Only honor
        # absolute paths under the user's domain; otherwise fall back to App Support.
        if not p.is_absolute():
            return default_env_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text("# Insight Mine settings (.env)\n", encoding="utf-8")
            return p
        except OSError:
            return default_env_path()

    # Non-frozen: keep legacy behavior
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# Insight Mine settings (.env)\n", encoding="utf-8")
    return p

def read_env_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"# ERROR reading {path}: {e}\n"

def write_env_file(path: Path, text: str) -> Tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")
        return True, ""
    except Exception as e:
        return False, str(e)

# ---------- Output dir helpers ----------
def read_env_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def write_env_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")

def parse_env_lines(text: str) -> dict:
    env = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        # Only strip quotes if they form a matching pair (same logic as config.py)
        if v and v[0] in {'"', "'"} and len(v) > 1 and v[-1] == v[0]:
            quote_char = v[0]
            v = v[1:-1]
            # Unescape escaped quotes inside the value
            if quote_char == '"':
                v = v.replace('\\"', '"')
            else:
                v = v.replace("\\'", "'")
        env[k] = v
    return env

def upsert_env_key(text: str, key: str, value: str) -> str:
    lines = (text or "").splitlines()
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    
    # Quote value if it contains spaces or special characters that need protection
    needs_quoting = any(c in value for c in ' \t()[]{}$#!')
    if needs_quoting and not (value.startswith('"') and value.endswith('"')):
        # Escape any existing double quotes inside the value
        value = '"' + value.replace('"', '\\"') + '"'
    
    replaced = False
    for i, ln in enumerate(lines):
        if key_re.match(ln):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"{key}={value}")
    out = "\n".join(lines)
    if out and not out.endswith("\n"):
        out += "\n"
    return out

def get_output_dir_from_env(env_path: Path) -> str:
    txt = read_env_text(env_path)
    kv = parse_env_lines(txt)
    v = (kv.get("IM_OUT_DIR") or "").strip()
    return str(Path(v).expanduser()) if v else os.getcwd()

def set_output_dir_in_env(env_path: Path, new_dir: str) -> str:
    new_dir = str(Path(new_dir).expanduser())
    txt = read_env_text(env_path)
    txt_new = upsert_env_key(txt, "IM_OUT_DIR", new_dir)
    write_env_text(env_path, txt_new)
    return new_dir

# ---------- Compose env ----------
def compose_env(env_path: Path | None) -> dict:
    env = dict(os.environ)
    try:
        if env_path:
            kv = parse_env_lines(read_env_text(env_path))
            env.update(kv)
    except Exception:
        pass
    env["IM_OUT_DIR"] = get_output_dir_from_env(env_path) if env_path else os.getcwd()
    return env
