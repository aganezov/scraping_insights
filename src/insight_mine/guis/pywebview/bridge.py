from __future__ import annotations
import json, os, re, threading, subprocess, shlex
from pathlib import Path
import webview

from . import cli_adapter, storage, envutil

PROG_RE   = re.compile(r"PROGRESS\s+overall=(\d+)(?:\s+yt=(\d+))?(?:\s+rd=(\d+))?", re.I)
TEL_RE    = re.compile(r"Telemetry\s+\((YouTube|Reddit(?: [^)]+)?)\):\s*(.*)$", re.I)
WROTE_RE  = re.compile(r"Wrote\s+(\d+)\s+items\b", re.I)
_KEPT_RE  = re.compile(r'\b(?P<k>(yt_video_kept|yt_comment_kept|rd_post_kept|rd_comment_kept))\s*:\s*(?P<v>\d+)')


SETTINGS_FILE = envutil.ensure_app_dir() / "gui_settings.json"


def _default_out_dir() -> str:
    return str(Path.cwd())


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                return {
                    "env_path": data.get("env_path"),
                    "out_dir": data.get("out_dir") or None,
                }
        except Exception:
            pass
    return {"env_path": None, "out_dir": None}


def _save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except Exception:
        pass


def _compose_env(env_path: Path) -> dict:
    return envutil.compose_env(env_path)


def _status_snapshot(env: dict) -> dict:
    return {
        "youtube": bool(env.get("YOUTUBE_API_KEY")),
        "reddit": bool(env.get("REDDIT_CLIENT_ID") and env.get("REDDIT_CLIENT_SECRET")),
        "transcripts_auto": False,
    }


def _preview_env(env: dict, out_dir: str) -> str:
    lines = [
        "# Loaded environment (preview)",
        f"IM_OUT_DIR={out_dir}",
        f"YOUTUBE_API_KEY={'SET' if env.get('YOUTUBE_API_KEY') else '(missing)'}",
        f"REDDIT_CLIENT_ID={'SET' if env.get('REDDIT_CLIENT_ID') else '(missing)'}",
        f"REDDIT_CLIENT_SECRET={'SET' if env.get('REDDIT_CLIENT_SECRET') else '(missing)'}",
        f"REDDIT_USER_AGENT={'SET' if env.get('REDDIT_USER_AGENT') else '(missing)'}",
        f"ALLOW_SCRAPING={env.get('ALLOW_SCRAPING','0')}",
    ]
    return "\n".join(lines)


class Bridge:
    """
    JS-exposed API. Methods are called from bridge_inject.js via window.pywebview.api.
    """

    # Accept env_path from app.py (may be None)
    def __init__(self, env_path: str | None = None):
        self.proc: subprocess.Popen[str] | None = None
        self.reader_t: threading.Thread | None = None
        self.finish_t: threading.Thread | None = None
        self.yt_count = 0
        self.rd_count = 0
        self._pmax = {"overall": 0, "youtube": 0, "reddit": 0}
        self._counts = {"yt_par": 0, "yt_com": 0, "rd_par": 0, "rd_com": 0}
        self._selected = {"youtube": True, "reddit": True}
        self._transcript_progress = {"enabled": False, "total": 0, "done": 0, "complete": True}
        self.proc = None
        self.settings = _load_settings()   # {env_path, out_dir}
        # CLI --env argument takes absolute precedence over saved settings
        if env_path is not None:
            self._env_path = envutil.resolve_env_path(env_path)
        else:
            self._env_path = envutil.resolve_env_path(self.settings.get("env_path"))
        self.settings["env_path"] = str(self._env_path)
        self.settings["out_dir"] = envutil.get_output_dir_from_env(self._env_path)
        self.env = _compose_env(self._env_path)  # merged process env
        _save_settings(self.settings)

    # ---------- Utility ----------
    def _send(self, typ: str, payload: dict) -> None:
        try:
            js = f'window.IMBridge.receive({json.dumps(typ)}, {json.dumps(payload)});'
            webview.windows[0].evaluate_js(js)
        except Exception as e:
            print("[IM] send error:", e)

    def _candidate_roots_for_run(self, run_id: str) -> list[Path]:
        """
        Return candidate output roots that may contain the run directory.
        Prefers existing roots. Falls back to the configured out_dir and its /out sibling.
        """
        base_out = Path(envutil.get_output_dir_from_env(self._env_path)).expanduser()
        roots = [base_out, base_out / "out"]
        existing = [r for r in roots if (r / run_id).exists()]
        return existing or roots

    def _latest_run_dir(self, out_root: Path) -> Path | None:
        """
        Best-effort guess of the most recent run directory under out_root or out_root/out.
        Prefers directories containing run_manifest.json or run.json.
        """
        candidates: list[Path] = []
        for root in (out_root, out_root / "out"):
            if not root.exists() or not root.is_dir():
                continue
            for p in root.iterdir():
                if p.is_dir() and not p.is_symlink():
                    candidates.append(p)
        if not candidates:
            return None
        # Sort by mtime descending
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        # Prefer ones with run_manifest or run.json
        for p in candidates:
            if (p / "run_manifest.json").exists() or (p / "run.json").exists():
                return p
        return candidates[0]

    def _clamp_cli_progress_for_transcripts(self, overall: int | None, youtube: int | None) -> tuple[int | None, int | None]:
        """
        When transcripts are enabled, keep CLI-reported progress bars from jumping
        to 100% until transcript fetching completes.
        """
        if self._transcripts_pending():
            if overall is not None and overall >= 100:
                overall = 90
            if youtube is not None and youtube >= 100:
                youtube = 40  # hold YT bar at collection-done level until transcripts finish
        return overall, youtube

    def _emit_progress(self, *, overall=None, youtube=None, reddit=None,
                       yt_par=None, yt_com=None, rd_par=None, rd_com=None):
        overall, youtube = self._clamp_cli_progress_for_transcripts(overall, youtube)
        if overall is not None:
            self._pmax["overall"] = max(self._pmax["overall"], int(overall))
        if youtube is not None:
            self._pmax["youtube"] = max(self._pmax["youtube"], int(youtube))
        if reddit is not None:
            self._pmax["reddit"] = max(self._pmax["reddit"], int(reddit))
        if yt_par is not None:
            self._counts["yt_par"] = int(yt_par)
        if yt_com is not None:
            self._counts["yt_com"] = int(yt_com)
        if rd_par is not None:
            self._counts["rd_par"] = int(rd_par)
        if rd_com is not None:
            self._counts["rd_com"] = int(rd_com)
        payload = {
            "overall": self._pmax["overall"],
            "youtube": self._pmax["youtube"],
            "reddit":  self._pmax["reddit"],
            "yt_par":  self._counts["yt_par"], "yt_com": self._counts["yt_com"],
            "rd_par":  self._counts["rd_par"], "rd_com": self._counts["rd_com"],
            "yt_count": self._counts["yt_par"] + self._counts["yt_com"],
            "rd_count": self._counts["rd_par"] + self._counts["rd_com"],
        }
        self._send("progress", payload)

    def _set_transcript_tracking(self, enabled: bool) -> None:
        """
        Initialize transcript progress tracking. When enabled, CLI-reported
        progress will be capped until post-collection transcript fetching
        finishes. When disabled, progress flows through unchanged.
        """
        self._transcript_progress = {
            "enabled": bool(enabled),
            "total": 0,
            "done": 0,
            "complete": not bool(enabled),
        }

    def _transcripts_pending(self) -> bool:
        tp = getattr(self, "_transcript_progress", {})
        return bool(tp.get("enabled")) and not bool(tp.get("complete"))

    def _clamp_cli_overall_for_transcripts(self, overall: int | None) -> int | None:
        """
        When transcripts are enabled, keep CLI-reported progress from jumping
        to 100% until transcript fetching completes.
        """
        if overall is None:
            return None
        if self._transcripts_pending() and overall >= 100:
            return 90
        return overall

    def _emit_transcript_progress(self, done: int, total: int) -> None:
        """
        Emit progress updates that include transcript fetching as the final
        slice of the YouTube/overall bars.
        """
        tp = self._transcript_progress
        if not tp.get("enabled"):
            return
        tp["total"] = total
        tp["done"] = done
        tp["complete"] = (total <= 0) or (done >= total)
        if total <= 0:
            return

        overall = min(100, 90 + int(10 * done / total))
        youtube = min(100, 40 + int(60 * done / total))
        self._emit_progress(overall=overall, youtube=youtube)

    def _emit_yt_counts(self, parents: int, comments: int):
        """Send YT counts via a dedicated event and also update DOM directly as a fallback."""
        try:
            self._send("yt_counts", {"parents": int(parents), "comments": int(comments)})
        except Exception:
            pass
        try:
            if getattr(self, "window", None):
                self.window.evaluate_js(
                    f"(function(){{var el=document.getElementById('ytCount');"
                    f"if(el) el.textContent='{int(parents)}/{int(comments)}';}})();"
                )
        except Exception:
            pass

    def _emit_rd_counts(self, parents: int, comments: int):
        """Send Reddit counts via a dedicated event and also update DOM directly as a fallback."""
        try:
            self._send("rd_counts", {"parents": int(parents), "comments": int(comments)})
        except Exception:
            pass
        # Also try direct DOM update using the same mechanism as _send
        try:
            js = f"(function(){{var el=document.getElementById('rdCount');if(el)el.textContent='{int(parents)}/{int(comments)}';}})();"
            webview.windows[0].evaluate_js(js)
        except Exception:
            pass

    def _kv_ints(self, tail: str) -> dict:
        out: dict = {}
        for tok in (tail or "").split(","):
            if ":" not in tok:
                continue
            k, v = tok.split(":", 1)
            k = k.strip()
            v = v.strip()
            try:
                out[k] = int(v)
            except ValueError:
                continue
        return out

    def _emit_counts(self):
        payload = {}
        if hasattr(self, "_yt_par"): payload["yt_par"] = int(self._yt_par)
        if hasattr(self, "_yt_com"): payload["yt_com"] = int(self._yt_com)
        if hasattr(self, "_rd_par"): payload["rd_par"] = int(self._rd_par)
        if hasattr(self, "_rd_com"): payload["rd_com"] = int(self._rd_com)
        if payload:
            self._send("counts", payload)

    def _reset_progress(self, selected=None):
        sel = selected or {}
        self._selected = {
            "youtube": bool(sel.get("youtube", True)),
            "reddit":  bool(sel.get("reddit",  True)),
        }
        self._pmax = {"overall": 0, "youtube": 0, "reddit": 0}
        self._counts = {"yt_par": 0, "yt_com": 0, "rd_par": 0, "rd_com": 0}
        self._yt_par = 0; self._yt_com = 0
        self._rd_par = 0; self._rd_com = 0
        self._set_transcript_tracking(False)
        self._send("progress_reset", {"selected": self._selected})
        self._emit_yt_counts(0, 0)
        self._emit_counts()

    @staticmethod
    def _parse_kept_pairs(tail: str, source: str) -> tuple[int,int]:
        """
        Returns (parents, comments) from telemetry '... foo_kept:NN ...' tail.
        YouTube keys: yt_video_kept, yt_comment_kept
        Reddit  keys: rd_post_kept, rd_comment_kept (if present)
        Unknowns are ignored.
        """
        p = c = 0
        for tok in (tail or "").split(","):
            tok = tok.strip()
            if ":" not in tok:
                continue
            k, v = tok.split(":", 1)
            try:
                n = int((v or "0").strip())
            except Exception:
                n = 0
            ks = k.strip().lower()
            if source.lower().startswith("youtube"):
                if "video_kept" in ks:
                    p += n
                elif "comment_kept" in ks:
                    c += n
            else:
                if "post_kept" in ks:
                    p += n
                elif "comment_kept" in ks:
                    c += n
        return p, c

    def _telemetry_kept_sum(self, tail: str) -> int:
        par, com = self._parse_kept_pairs(tail, "YouTube")
        return par + com

    def _kept_from_tail(self, tail: str) -> tuple[int, int]:
        """Return (parents_kept, comments_kept) from a telemetry tail string."""
        parents = comments = 0
        for m in _KEPT_RE.finditer(tail or ""):
            k, v = m.group('k'), int(m.group('v'))
            if k.endswith('video_kept') or k.endswith('post_kept'):
                parents += v
            elif k.endswith('comment_kept'):
                comments += v
        return parents, comments

    def _parse_reddit_kept_tail(self, tail: str) -> tuple[int, int]:
        """
        Extract kept counters from a Reddit telemetry tail.
        Accepts keys like rd_post_kept, rd_comment_kept (and tolerant fallbacks).
        """
        def pick(keys):
            for k in keys:
                m = re.search(rf"{re.escape(k)}\\s*:\\s*(\\d+)", tail)
                if m:
                    return int(m.group(1))
            return 0
        posts = pick(["rd_post_kept", "post_kept"])
        comments = pick(["rd_comment_kept", "comment_kept"])
        return posts, comments

    @staticmethod
    def _normalize_knobs(k: dict) -> dict:
        """Accept v15 nested knobs (advanced.yt/rd) and return a flattened CLI shape."""
        k = k or {}
        if ("yt_videos" in k) or ("reddit_limit" in k):  # already flat
            return k

        adv = (k.get("advanced") or {})
        yt  = adv.get("yt") or {}
        rd  = adv.get("rd") or {}
        lang = adv.get("language") or k.get("lang") or "en"
        dedupe_on = (adv.get("dedupe") or "on") != "off"

        out = dict(k)
        # transcript_mode: "off", "free", "any" - handled post-collection in GUI
        transcript_mode = k.get("transcript_mode", "off")
        out.update({
            "lang": lang, "langs": lang, "dedupe": dedupe_on,
            "transcripts": "off",  # CLI doesn't fetch transcripts; GUI does post-collection
            "transcript_mode": transcript_mode,  # Preserve for post-collection processing
            "transcript_mode": transcript_mode,
            "connectors": k.get("connectors", {"youtube": True, "reddit": True}),
            # YT
            "yt_videos": yt.get("max_videos", 25),
            "yt_comments_per_video": yt.get("comments_per_video", 60),
            "yt_min_views": yt.get("min_views", 5000),
            "yt_min_duration": yt.get("min_duration", 120),
            "yt_min_comment_likes": yt.get("min_comment_likes", 2),
            "yt_order": yt.get("order", "viewCount"),
            # RD
            "reddit_limit": rd.get("max_posts", 40),
            "reddit_comments": rd.get("comments_per_post", 8),
            "reddit_min_score": rd.get("min_score", 5),
            "reddit_min_comment_score": rd.get("min_comment_score", 0),
            "reddit_mode": rd.get("mode") or "scrape",
            "reddit_source": rd.get("selector", "hot"),
            "reddit_query": rd.get("query", ""),
            "reddit_sort": rd.get("search_sort", "relevance"),
            "reddit_t": rd.get("search_time", "all"),
            "reddit_top_t": rd.get("top_time", "week"),
        })
        subs = out.get("subreddits", [])
        if isinstance(subs, list):
            out["subreddits"] = ",".join([s for s in subs if s])
        return out

    # ---------- Public API for JS ----------
    def get_env(self) -> dict:
        """Return the current env file path and its raw text."""
        p = self._env_path
        return {"env_path": str(p), "text": envutil.read_env_file(p)}

    def save_env(self, text: str) -> dict:
        """Persist raw text back to the same env file."""
        ok, err = envutil.write_env_file(self._env_path, text or "")
        if ok:
            # refresh cached env/settings so the next run uses the latest keys
            self.env = envutil.compose_env(self._env_path)
            self.settings["out_dir"] = envutil.get_output_dir_from_env(self._env_path)
            _save_settings(self.settings)
            self._send("out_dir_changed", {"out_dir": self.settings["out_dir"]})
        return {"ok": ok, "error": err}

    def choose_env_file(self) -> dict:
        """Open file dialog to select a different .env file."""
        try:
            sel = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("Environment Files (*.env)", "All Files (*.*)"),
            )
            if not sel:
                return {"ok": False, "cancelled": True}
            chosen = sel if isinstance(sel, str) else sel[0]
            chosen_path = Path(chosen)
            if not chosen_path.exists():
                return {"ok": False, "error": "File does not exist"}
            # Update internal state to use the new env file
            self._env_path = chosen_path
            self.settings["env_path"] = str(chosen_path)
            self.env = envutil.compose_env(self._env_path)
            self.settings["out_dir"] = envutil.get_output_dir_from_env(self._env_path)
            _save_settings(self.settings)
            self._send("out_dir_changed", {"out_dir": self.settings["out_dir"]})
            return {
                "ok": True,
                "env_path": str(chosen_path),
                "text": envutil.read_env_file(chosen_path),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_env_as(self, text: str) -> dict:
        """Open save dialog to write env content to a new file."""
        try:
            dest = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=".env",
                file_types=("Environment Files (*.env)", "All Files (*.*)"),
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            path = dest if isinstance(dest, str) else dest[0]
            dest_path = Path(path)
            dest_path.write_text(text or "", encoding="utf-8")
            # Switch to using this new file
            self._env_path = dest_path
            self.settings["env_path"] = str(dest_path)
            self.env = envutil.compose_env(self._env_path)
            self.settings["out_dir"] = envutil.get_output_dir_from_env(self._env_path)
            _save_settings(self.settings)
            self._send("out_dir_changed", {"out_dir": self.settings["out_dir"]})
            return {"ok": True, "env_path": str(dest_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_log(self, text: str) -> dict:
        """Prompt for a file path and save the provided log text."""
        try:
            dest = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE, save_filename="collect-log.txt"
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            path = dest if isinstance(dest, str) else dest[0]
            Path(path).write_text(text or "", encoding="utf-8")
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_settings(self) -> dict:
        """Return settings + a human preview to display in the mock Settings modal."""
        # reload env preview each time
        self.env = _compose_env(self._env_path)
        self.settings["out_dir"] = envutil.get_output_dir_from_env(self._env_path)
        preview = _preview_env(self.env, self.settings["out_dir"])
        _save_settings(self.settings)
        return {"env_path": str(self._env_path), "out_dir": self.settings["out_dir"], "env_preview": preview}

    # ---- Output folder API ----
    def get_output_dir(self) -> dict:
        path = envutil.get_output_dir_from_env(self._env_path)
        self.settings["out_dir"] = path
        _save_settings(self.settings)
        return {"out_dir": path}

    def set_output_dir(self, path: str) -> dict:
        try:
            newp = envutil.set_output_dir_in_env(self._env_path, path)
            self.settings["out_dir"] = newp
            _save_settings(self.settings)
            self._send("out_dir_changed", {"out_dir": newp})
            return {"ok": True, "out_dir": newp}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def choose_out_dir(self) -> dict:
        """Open system dialog to set the output folder; persist to settings."""
        try:
            sel = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not sel:
                return {"ok": False, "cancelled": True}
            chosen = sel if isinstance(sel, str) else sel[0]
            newp = envutil.set_output_dir_in_env(self._env_path, chosen)
            self.settings["out_dir"] = newp
            _save_settings(self.settings)
            self._send("out_dir_changed", {"out_dir": newp})
            return {"ok": True, "out_dir": newp}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_runs(self) -> list[dict]:
        """Return summaries of runs found under out_dir."""
        out_dir = envutil.get_output_dir_from_env(self._env_path)
        out_root = Path(out_dir).expanduser()
        
        # If no runs found and there's an "out" subdirectory, try there
        runs = storage.list_runs(out_root)
        if not runs:
            out_subdir = out_root / "out"
            if out_subdir.is_dir():
                runs = storage.list_runs(out_subdir)
                if runs:
                    out_dir = str(out_subdir)
                    out_root = out_subdir
        
        self.settings["out_dir"] = out_dir
        _save_settings(self.settings)
        return runs

    def get_run(self, run_id: str) -> dict:
        """
        Load full run data by ID.
        Returns the v15 UI run object:
          { id, manifest:{ started_at, knobs, items:[...] }, stats:{ dropped:{...} } }
        """
        out_dir = envutil.get_output_dir_from_env(self._env_path)
        out_root = Path(out_dir).expanduser()
        
        # Try main dir first, then "out" subdirectory
        run = storage.load_run(run_id, out_root)
        if run is None:
            out_subdir = out_root / "out"
            if out_subdir.is_dir():
                run = storage.load_run(run_id, out_subdir)
        
        if run is None:
            return {"ok": False, "error": f"Run '{run_id}' not found"}
        return {"ok": True, "run": run}

    def get_paste_ready(self, run_id: str) -> dict:
        """
        Load paste-ready.txt contents for a run.
        Returns { ok: true, text: "..." } or { ok: false, error: "..." }
        """
        out_dir = envutil.get_output_dir_from_env(self._env_path)
        out_root = Path(out_dir).expanduser()
        
        # Try main dir first, then "out" subdirectory
        text = storage.get_paste_ready(run_id, out_root)
        if text is None:
            out_subdir = out_root / "out"
            if out_subdir.is_dir():
                text = storage.get_paste_ready(run_id, out_subdir)
        
        if text is None:
            return {"ok": False, "error": f"paste-ready.txt not found for run '{run_id}'"}
        return {"ok": True, "text": text}

    def export_json(self, data: list | dict, filename: str = "export.json") -> dict:
        """
        Export data as JSON via save file dialog.
        data: The data to export (will be JSON serialized)
        filename: Default filename suggestion
        """
        try:
            dest = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=filename,
                file_types=("JSON Files (*.json)", "All Files (*.*)")
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            path = dest if isinstance(dest, str) else dest[0]
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_csv(self, rows: list, columns: list, filename: str = "export.csv") -> dict:
        """
        Export data as CSV via save file dialog.
        rows: List of dicts with data
        columns: List of column keys to include
        filename: Default filename suggestion
        """
        try:
            dest = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=filename,
                file_types=("CSV Files (*.csv)", "All Files (*.*)")
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            path = dest if isinstance(dest, str) else dest[0]
            
            # Build CSV content
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            
            Path(path).write_text(output.getvalue(), encoding="utf-8")
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_text(self, text: str, filename: str = "export.txt") -> dict:
        """
        Export text via save file dialog.
        """
        try:
            dest = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=filename,
                file_types=("Text Files (*.txt)", "All Files (*.*)")
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            path = dest if isinstance(dest, str) else dest[0]
            Path(path).write_text(text or "", encoding="utf-8")
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def build_command(self, knobs: dict) -> dict:
        """Return the exact command that would be executed for given knobs."""
        try:
            k = self._normalize_knobs(knobs)
            run_id = k.pop("__run_id", None)
            env = _compose_env(self._env_path)
            out_dir = envutil.get_output_dir_from_env(self._env_path)
            cmd, run_id, run_dir = cli_adapter.build_collect_cmd(k, env, Path(out_dir).expanduser(),
                                                                 run_id=run_id, create_dirs=False)
            cmd_str = " ".join(cmd)
            return {"ok": True, "cmd": cmd, "cmd_string": cmd_str, "run_id": run_id, "run_dir": str(run_dir)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def start_collect(self, knobs: dict) -> dict:
        """Start the real CLI. Progress/events are streamed to the page."""
        if self.proc:
            return {"error": "already running"}

        # env + knobs
        self.env = _compose_env(self._env_path)
        out_dir = envutil.get_output_dir_from_env(self._env_path)
        self.settings["out_dir"] = out_dir
        _save_settings(self.settings)

        # Emit env diagnostics at the very start so they appear first in the log
        self._send("log", {"line": f"[DEBUG] env_path={self._env_path}"})
        self._send("log", {"line": f"[DEBUG] env IM_OUT_DIR={out_dir}"})
        self._send("log", {"line": f"[DEBUG] env YTTI_WS_USER={self.env.get('YTTI_WS_USER')}, YTTI_WS_PASS={self.env.get('YTTI_WS_PASS')}"})
        self._send("log", {"line": f"[DEBUG] env YTTI_API_TOKEN={self.env.get('YTTI_API_TOKEN')}"})
        self._send("log", {"line": f"[DEBUG] env YOUTUBE_API_KEY={self.env.get('YOUTUBE_API_KEY')}"})

        self._reset_progress(knobs.get("connectors") if isinstance(knobs, dict) else None)
        k = self._normalize_knobs(knobs)
        run_id_hint = k.pop("__run_id", None)
        # Store transcript mode for post-collection processing
        self._transcript_mode = k.get("transcript_mode", "off")
        self._transcript_lang = k.get("lang", "en")
        self._send("log", {"line": f"[DEBUG] transcript_mode={self._transcript_mode}, lang={self._transcript_lang}"})
        self._set_transcript_tracking(self._transcript_mode in ("free", "any") and self._selected.get("youtube", True))

        # respect connector toggles when building flags
        cmd, run_id, run_dir = cli_adapter.build_collect_cmd(k, self.env, Path(out_dir).expanduser(),
                                                             run_id=run_id_hint, create_dirs=True)
        self._send("log", {"line": f"Executing CLI: {' '.join(cmd)}"})

        self.yt_count = 0; self.rd_count = 0
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, env=self.env)

        def reader():
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                self._send("log", {"line": line})
                m_yt = re.search(r"Telemetry \(YouTube\):\s*(.*)$", line)
                if m_yt:
                    tail = m_yt.group(1) or ""
                    if "-" not in tail:
                        kv = dict()
                        for tok in tail.split(","):
                            if ":" in tok:
                                k, v = tok.split(":", 1)
                                k, v = k.strip(), v.strip()
                                try:
                                    kv[k] = int(v)
                                except ValueError:
                                    pass
                        v_kept = int(kv.get("yt_video_kept", 0))
                        c_kept = int(kv.get("yt_comment_kept", 0))
                        self._counts["yt_par"] = v_kept
                        self._counts["yt_com"] = c_kept
                        self._emit_yt_counts(v_kept, c_kept)
                # Reddit telemetry (same pattern as YouTube)
                m_rd = re.search(r"Telemetry \(Reddit[^)]*\):\s*(.*)$", line)
                if m_rd:
                    tail = m_rd.group(1) or ""
                    if "-" not in tail:
                        kv = dict()
                        for tok in tail.split(","):
                            if ":" in tok:
                                k, v = tok.split(":", 1)
                                k, v = k.strip(), v.strip()
                                try:
                                    kv[k] = int(v)
                                except ValueError:
                                    pass
                        p_kept = int(kv.get("rd_post_kept", 0))
                        c_kept = int(kv.get("rd_comment_kept", 0))
                        # Store in self._counts so finisher can read them
                        self._counts["rd_par"] = p_kept
                        self._counts["rd_com"] = c_kept
                        self._emit_rd_counts(p_kept, c_kept)
                try:
                    obj = json.loads(line)
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("event") == "progress":
                    self._emit_progress(
                        overall=obj.get("overall"),
                        youtube=obj.get("youtube"),
                        reddit=obj.get("reddit"),
                        yt_par=obj.get("yt_par"), yt_com=obj.get("yt_com"),
                        rd_par=obj.get("rd_par"), rd_com=obj.get("rd_com"),
                    )
                    continue
                if isinstance(obj, dict) and obj.get("event") == "item":
                    plat = (obj.get("item") or {}).get("platform")
                    if plat == "youtube":
                        self._counts["yt_par"] += 1
                    if plat == "reddit":
                        self._counts["rd_par"] += 1
                    self._emit_progress(
                        yt_par=self._counts["yt_par"], yt_com=self._counts["yt_com"],
                        rd_par=self._counts["rd_par"], rd_com=self._counts["rd_com"],
                    )
                    continue
                m = PROG_RE.search(line)
                if m:
                    overall = int(m.group(1) or 0)
                    youtube = int(m.group(2)) if m.group(2) else None
                    reddit  = int(m.group(3)) if m.group(3) else None
                    overall = self._clamp_cli_overall_for_transcripts(overall)
                    self._emit_progress(
                        overall=overall,
                        youtube=youtube,
                        reddit=reddit,
                    )
                    continue
                t = TEL_RE.search(line)
                if t:
                    src = t.group(1) or ""
                    tail = t.group(2) or ""
                    # Skip placeholder "-" telemetry (no data), don't overwrite real counts
                    if tail.strip() == "-":
                        continue
                    par, com = self._kept_from_tail(tail)
                    if "youtube" in src.lower():
                        self._yt_par = par
                        self._yt_com = com
                        self._emit_progress(yt_par=par, yt_com=com)
                        self._emit_yt_counts(par, com)
                    else:
                        self._rd_par = par
                        self._rd_com = com
                        self._emit_progress(rd_par=par, rd_com=com)
                        self._emit_rd_counts(par, com)
                    self._emit_counts()
                    continue
                w = WROTE_RE.search(line)
                if w:
                    n = int(w.group(1))
                    if self._selected.get("youtube") and not self._selected.get("reddit"):
                        par = self._counts["yt_par"]
                        self._emit_progress(yt_par=par, yt_com=max(0, n - par))
                    elif self._selected.get("reddit") and not self._selected.get("youtube"):
                        par = self._counts["rd_par"]
                        self._emit_progress(rd_par=par, rd_com=max(0, n - par))
                    continue

        def finisher():
            code = self.proc.wait()
            # Wait for reader to finish processing all stdout (including telemetry)
            if self.reader_t:
                self.reader_t.join(timeout=5)
            run = None
            try:
                run = storage.build_ui_run(run_id, run_dir, k)
            except Exception as e:
                self._send("run_error", {"message": f"failed to assemble run: {e}"})
            if code == 0 and run:
                try:
                    # Use telemetry-parsed values from self._counts (set by reader)
                    # Don't recalculate - the telemetry is the source of truth
                    yt_par = self._counts.get("yt_par", 0)
                    yt_com = self._counts.get("yt_com", 0)
                    rd_par = self._counts.get("rd_par", 0)
                    rd_com = self._counts.get("rd_com", 0)
                    # If transcripts are pending, keep overall/youtube at the
                    # pre-transcript stage; the transcript fetcher will finish
                    # the bars.
                    pending_transcripts = self._transcripts_pending()
                    base_overall = 90 if pending_transcripts else 100
                    base_youtube = self._pmax["youtube"]
                    if not pending_transcripts and self._selected.get("youtube"):
                        base_youtube = 100
                    reddit_pct = 100 if self._selected.get("reddit") else 0

                    self._emit_progress(
                        overall=base_overall,
                        youtube=base_youtube if self._selected.get("youtube") else None,
                        reddit=reddit_pct,
                        yt_par=yt_par, yt_com=yt_com,
                        rd_par=rd_par, rd_com=rd_com,
                    )
                    # Explicitly emit counts to update chips (use telemetry values)
                    self._emit_yt_counts(yt_par, yt_com)
                    self._emit_rd_counts(rd_par, rd_com)
                except Exception:
                    pass
                
                # Post-collection transcript fetching
                transcript_mode = getattr(self, '_transcript_mode', 'off')
                transcript_lang = getattr(self, '_transcript_lang', 'en')
                self._send("log", {"line": f"[DEBUG] Finisher: transcript_mode={transcript_mode}"})
                if transcript_mode in ("free", "any"):
                    self._send("log", {"line": f"[DEBUG] Starting transcript fetch..."})
                    try:
                        self._fetch_transcripts_batch(run, run_dir, transcript_mode, transcript_lang)
                    except Exception as e:
                        self._send("log", {"line": f"Transcript fetch error: {e}"})
                
                # Emit a final DONE marker after all post-processing (including transcripts)
                self._send("log", {"line": "DONE"})
                self._send("run_complete", {"run": run})
            else:
                self._send("run_error", {"message": f"CLI exited with code {code}"})
            self.proc = None

        self.reader_t = threading.Thread(target=reader, daemon=True)
        self.reader_t.start()
        self.finish_t = threading.Thread(target=finisher, daemon=True)
        self.finish_t.start()
        return {"run_id": run_id}

    def start_collect_cmd(self, cli_text: str, selected: dict | None = None, transcript_mode: str = "off", transcript_lang: str = "en") -> dict:
        """Run exactly the provided CLI text (from the preview)."""
        if self.proc:
            return {"error": "already running"}
        cli_text = (cli_text or "").strip()
        if not cli_text:
            return {"error": "empty command"}

        self._reset_progress(selected)
        # Store transcript mode for post-collection processing
        self._transcript_mode = transcript_mode or "off"
        self._transcript_lang = transcript_lang or "en"
        self._send("log", {"line": f"[DEBUG] transcript_mode={self._transcript_mode}"})
        self._set_transcript_tracking(self._transcript_mode in ("free", "any") and self._selected.get("youtube", True))

        # Enforce source toggles at the boundary
        if not self._selected.get("youtube", False) and "--yt-videos" not in cli_text:
            cli_text += " --yt-videos 0 --yt-comments-per-video 0"
        if not self._selected.get("reddit", False) and ("--reddit-limit" not in cli_text and " --limit " not in cli_text):
            cli_text += " --reddit-limit 0 --rd-comments-per-post 0"
        if self._selected.get("reddit", False) and "--allow-scraping" not in cli_text:
            cli_text += " --allow-scraping"

        argv = shlex.split(cli_text)
        if not argv:
            return {"error": "bad command"}

        # Env from .env
        self.env = envutil.compose_env(self._env_path)
        bin_override = self.env.get("IM_CLI_BIN") or os.environ.get("IM_CLI_BIN")
        if argv[0] == "insight-mine" and bin_override:
            argv[0] = bin_override

        # Normalize legacy flags from the mock to real CLI flags
        def _normalize_args(av: list[str]) -> list[str]:
            out: list[str] = []
            mapping = {
                "--yt-comments-per-video": "--yt-max-comments",
                "--limit": "--reddit-limit",
                "--rd-comments-per-post": "--reddit-comments",
                "--rd-min-score": "--reddit-min-score",
                "--rd-min-comment-score": "--reddit-min-comment-score",
            }
            drop = {"--reddit-source", "--reddit-query", "--reddit-sort", "--reddit-t", "--reddit-top-t"}
            i = 0
            n = len(av)
            while i < n:
                a = av[i]
                if a in drop:
                    if i + 1 < n and not av[i + 1].startswith("--"):
                        i += 2
                    else:
                        i += 1
                    continue
                repl = mapping.get(a, a)
                out.append(repl)
                if i + 1 < n and not av[i + 1].startswith("--"):
                    # carry value
                    out.append(av[i + 1])
                    i += 2
                else:
                    i += 1
            return out

        argv = _normalize_args(argv)

        # Ensure --out exists
        out_dir = None
        for i, a in enumerate(argv):
            if a == "--out" and i + 1 < len(argv):
                out_dir = argv[i + 1]
                break
        if not out_dir:
            out_dir = envutil.get_output_dir_from_env(self._env_path)
            argv += ["--out", out_dir]
        out_path = Path(out_dir).expanduser()
        out_path.mkdir(parents=True, exist_ok=True)

        self._send("log", {"line": f"[exec] {' '.join(argv)}"})
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, env=self.env)

        def reader():
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                self._send("log", {"line": line})
                m_yt = re.search(r"Telemetry \(YouTube\):\s*(.*)$", line)
                if m_yt:
                    tail = m_yt.group(1) or ""
                    if "-" not in tail:
                        kv = dict()
                        for tok in tail.split(","):
                            if ":" in tok:
                                k, v = tok.split(":", 1)
                                k, v = k.strip(), v.strip()
                                try:
                                    kv[k] = int(v)
                                except ValueError:
                                    pass
                        v_kept = int(kv.get("yt_video_kept", 0))
                        c_kept = int(kv.get("yt_comment_kept", 0))
                        self._counts["yt_par"] = v_kept
                        self._counts["yt_com"] = c_kept
                        self._emit_yt_counts(v_kept, c_kept)
                # Reddit telemetry (same pattern as YouTube)
                m_rd = re.search(r"Telemetry \(Reddit[^)]*\):\s*(.*)$", line)
                if m_rd:
                    tail = m_rd.group(1) or ""
                    if "-" not in tail:
                        kv = dict()
                        for tok in tail.split(","):
                            if ":" in tok:
                                k, v = tok.split(":", 1)
                                k, v = k.strip(), v.strip()
                                try:
                                    kv[k] = int(v)
                                except ValueError:
                                    pass
                        p_kept = int(kv.get("rd_post_kept", 0))
                        c_kept = int(kv.get("rd_comment_kept", 0))
                        # Store in self._counts so finisher can read them
                        self._counts["rd_par"] = p_kept
                        self._counts["rd_com"] = c_kept
                        self._emit_rd_counts(p_kept, c_kept)
                try:
                    obj = json.loads(line)
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("event") == "progress":
                    self._emit_progress(
                        overall=obj.get("overall"),
                        youtube=obj.get("youtube"),
                        reddit=obj.get("reddit"),
                        yt_par=obj.get("yt_par"), yt_com=obj.get("yt_com"),
                        rd_par=obj.get("rd_par"), rd_com=obj.get("rd_com"),
                    )
                    continue
                if isinstance(obj, dict) and obj.get("event") == "item":
                    plat = (obj.get("item") or {}).get("platform")
                    if plat == "youtube":
                        self._counts["yt_par"] += 1
                    if plat == "reddit":
                        self._counts["rd_par"] += 1
                    self._emit_progress(yt_par=self._counts["yt_par"], yt_com=self._counts["yt_com"],
                                        rd_par=self._counts["rd_par"], rd_com=self._counts["rd_com"])
                    continue
                m = PROG_RE.search(line)
                if m:
                    self._emit_progress(
                        overall=int(m.group(1) or 0),
                        youtube=(int(m.group(2)) if m.group(2) else None),
                        reddit=(int(m.group(3)) if m.group(3) else None),
                    )
                    continue
                t = TEL_RE.search(line)
                if t:
                    src = t.group(1) or ""
                    tail = t.group(2) or ""
                    # Skip placeholder "-" telemetry (no data), don't overwrite real counts
                    if tail.strip() == "-":
                        continue
                    par, com = self._parse_kept_pairs(tail, src)
                    if "youtube" in src.lower():
                        self._emit_progress(yt_par=par, yt_com=com)
                        self._emit_yt_counts(par, com)
                    else:
                        self._emit_progress(rd_par=par, rd_com=com)
                        self._emit_rd_counts(par, com)
                    self._emit_counts()
                    continue
                w = WROTE_RE.search(line)
                if w:
                    n = int(w.group(1))
                    if self._selected.get("youtube") and not self._selected.get("reddit"):
                        par = self._counts["yt_par"]
                        self._emit_progress(yt_par=par, yt_com=max(0, n - par))
                    elif self._selected.get("reddit") and not self._selected.get("youtube"):
                        par = self._counts["rd_par"]
                        self._emit_progress(rd_par=par, rd_com=max(0, n - par))
                    continue

        def finisher():
            code = self.proc.wait()
            # Wait for reader to finish processing all stdout (including telemetry)
            if self.reader_t:
                self.reader_t.join(timeout=5)
            run = None
            run_dir = self._latest_run_dir(out_path) or out_path
            run_id = run_dir.name
            try:
                run = storage.build_ui_run(run_id, run_dir, {"cli": " ".join(argv)})
            except Exception as e:
                self._send("run_error", {"message": f"failed to assemble run: {e}"})
            if code == 0 and run:
                try:
                    # Use telemetry-parsed values from self._counts (set by reader)
                    # Don't recalculate - the telemetry is the source of truth
                    yt_par = self._counts.get("yt_par", 0)
                    yt_com = self._counts.get("yt_com", 0)
                    rd_par = self._counts.get("rd_par", 0)
                    rd_com = self._counts.get("rd_com", 0)
                    self._emit_progress(
                        overall=100,
                        youtube=100 if self._selected.get("youtube") else 0,
                        reddit=100 if self._selected.get("reddit") else 0,
                        yt_par=yt_par, yt_com=yt_com,
                        rd_par=rd_par, rd_com=rd_com,
                    )
                    # Explicitly emit counts to update chips (use telemetry values)
                    self._emit_yt_counts(yt_par, yt_com)
                    self._emit_rd_counts(rd_par, rd_com)
                except Exception:
                    pass

                # Persist run.json immediately so post-run fetches/refetches have a file to update
                try:
                    rj = run_dir / "run.json"
                    if not rj.exists():
                        rj.write_text(json.dumps(run, indent=2), encoding="utf-8")
                except Exception:
                    pass
                
                # Post-collection transcript fetching
                transcript_mode = getattr(self, '_transcript_mode', 'off')
                transcript_lang = getattr(self, '_transcript_lang', 'en')
                self._send("log", {"line": f"[DEBUG] Finisher: transcript_mode={transcript_mode}"})
                if transcript_mode in ("free", "any"):
                    self._send("log", {"line": f"[DEBUG] Starting transcript fetch..."})
                    try:
                        self._fetch_transcripts_batch(run, run_dir, transcript_mode, transcript_lang)
                    except Exception as e:
                        self._send("log", {"line": f"Transcript fetch error: {e}"})
                
                self._send("run_complete", {"run": run})
            else:
                self._send("run_error", {"message": f"CLI exited with code {code}"})
            self.proc = None

        self.reader_t = threading.Thread(target=reader, daemon=True)
        self.reader_t.start()
        self.finish_t = threading.Thread(target=finisher, daemon=True)
        self.finish_t.start()
        return {"ok": True}

    def cancel_collect(self) -> dict:
        if not self.proc:
            return {"ok": True}
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self._send("run_error", {"message": "Cancelled"})
        finally:
            self.proc = None
        return {"ok": True}

    def fetch_transcript(self, item_id: str, run_id: str = "", lang: str = "en", mode: str = "free") -> dict:
        """Fetch transcript for a YouTube video via ytti_client."""
        from . import ytti_client, storage
        import logging
        log = logging.getLogger(__name__)
        
        log.info(f"[fetch_transcript] item_id={item_id!r}, run_id={run_id!r}, lang={lang!r}, mode={mode!r}")
        
        # Extract video ID from item_id (could be the video URL or a custom ID)
        video_id = item_id
        # If it's a YouTube URL, extract the video ID
        if "youtube.com" in item_id or "youtu.be" in item_id:
            m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', item_id)
            if m:
                video_id = m.group(1)
        # If item_id contains a colon (like our internal IDs), try to extract video ID
        elif ":" in item_id:
            # Format might be "yt:VIDEO_ID" or similar
            parts = item_id.split(":")
            for p in parts:
                if len(p) == 11 and re.match(r'^[a-zA-Z0-9_-]+$', p):
                    video_id = p
                    break
        
        log.info(f"[fetch_transcript] extracted video_id={video_id!r}")
        
        try:
            mode = (mode or "free").lower().strip()
            log.info(f"[fetch_transcript] calling ytti_client.fetch_transcript... mode={mode}")
            use_lang = lang or it.get("context", {}).get("lang") or "en"
            if (mode or "any") == "free":
                # Strict free path: do not allow paid fallback
                text = ytti_client._fetch_via_yt_transcript_api(video_id, use_lang)
                source = "free" if text else None
                if not text:
                    raise ytti_client.TranscriptError("No free transcript available")
            else:
                text, source = ytti_client.fetch_transcript(video_id, use_lang, allow_paid=True)
            log.info(f"[fetch_transcript] got text, length={len(text) if text else 0}, source={source}")
            
            # Save transcript to storage if run_id provided
            if run_id:
                roots = self._candidate_roots_for_run(run_id)
                tried = []
                saved = False
                for root in roots:
                    tried.append(str(root))
                    try:
                        if storage.update_item_transcript(run_id, item_id, text, root):
                            log.info(f"[fetch_transcript] saved to {root}")
                            saved = True
                            break
                    except Exception as e:
                        log.debug(f"[fetch_transcript] save attempt failed at {root}: {e}")
                        continue
                if not saved:
                    log.warning(f"[fetch_transcript] failed to save transcript. tried={tried}")
            
            # Push transcript to UI
            self._send("transcript_ready", {"video_id": item_id, "text": text, "source": source})
            log.info(f"[fetch_transcript] SUCCESS")
            return {"ok": True, "text": text, "source": source}
        except ytti_client.TranscriptError as e:
            log.error(f"[fetch_transcript] TranscriptError: {e}")
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.error(f"[fetch_transcript] Exception: {e}")
            return {"ok": False, "error": f"Failed to fetch transcript: {e}"}

    def _fetch_transcripts_batch(self, run: dict, run_dir: Path, mode: str, lang: str) -> dict:
        """
        Fetch transcripts for all YouTube items in a run.
        mode: "free" (only free API) or "any" (free first, then paid)
        Returns counts: {free: N, paid: N, failed: N}
        """
        from . import ytti_client, storage
        import logging
        log = logging.getLogger(__name__)
        import os

        # Ensure transcript helpers see the same env the CLI had
        try:
            os.environ.update(self.env or {})
        except Exception:
            pass
        
        counts = {"free": 0, "paid": 0, "failed": 0, "skipped": 0}
        items = run.get("manifest", {}).get("items", [])
        self._send("log", {"line": f"[DEBUG] run keys: {list(run.keys())}"})
        self._send("log", {"line": f"[DEBUG] total items: {len(items)}"})
        yt_items = [it for it in items if it.get("platform") == "youtube" and not it.get("transcript")]
        self._send("log", {"line": f"[DEBUG] YouTube items without transcript: {len(yt_items)}"})
        
        if not yt_items:
            self._send("log", {"line": "Transcripts: No YouTube videos to process"})
            # Nothing to do: mark transcripts complete so progress can finish
            self._transcript_progress["complete"] = True
            self._emit_progress(overall=100, youtube=self._pmax.get("youtube"))
            return counts
        
        total = len(yt_items)
        self._send("log", {"line": f"Transcripts: Fetching for {total} YouTube videos (mode={mode})..."})
        self._emit_transcript_progress(0, total)
        
        for i, item in enumerate(yt_items, 1):
            item_id = item.get("id", "")
            item_url = item.get("url", "")
            
            # Extract video ID from URL first (most reliable), then from item_id
            video_id = None
            if item_url and ("youtube.com" in item_url or "youtu.be" in item_url):
                m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', item_url)
                if m:
                    video_id = m.group(1)
            if not video_id and ":" in item_id:
                parts = item_id.split(":")
                for p in parts:
                    if len(p) == 11 and re.match(r'^[a-zA-Z0-9_-]+$', p):
                        video_id = p
                        break
            if not video_id:
                # Try item_id directly if it looks like a video ID
                if len(item_id) == 11 and re.match(r'^[a-zA-Z0-9_-]+$', item_id):
                    video_id = item_id
            
            if not video_id:
                log.warning(f"Could not extract video ID from item {item_id}")
                counts["failed"] += 1
                continue
            
            # Emit env + fetch diagnostics just before each transcript pull
            self._send("log", {"line": f"[DEBUG] transcript_fetch video_id={video_id} lang={lang or item.get('context', {}).get('lang') or 'en'} mode={mode} ws_user={os.environ.get('YTTI_WS_USER')} ws_pass_set={bool(os.environ.get('YTTI_WS_PASS'))} token_set={bool(os.environ.get('YTTI_API_TOKEN'))}"})

            try:
                if mode == "free":
                    # Only try free API
                    text = ytti_client._fetch_via_yt_transcript_api(video_id, lang)
                    if text:
                        source = "free"
                    else:
                        counts["failed"] += 1
                        continue
                else:  # mode == "any"
                    # Use full fetch_transcript; allow paid in this mode
                    use_lang = lang or item.get("context", {}).get("lang") or "en"
                    text, source = ytti_client.fetch_transcript(video_id, use_lang, allow_paid=True)
                
                if text:
                    # Update item in run
                    item["transcript"] = text
                    counts[source] += 1
                    # Save to storage
                    # Persist transcript; try run_dir parent and its /out sibling
                    run_id = run.get("id", "")
                    roots = [run_dir] + self._candidate_roots_for_run(run_id)
                    for root in roots:
                        try:
                            if storage.update_item_transcript(run_id, item_id, text, root):
                                break
                        except Exception:
                            continue
                    # Notify UI
                    self._send("transcript_ready", {"video_id": item_id, "text": text, "source": source})
                else:
                    counts["failed"] += 1
                    
            except Exception as e:
                log.warning(f"Transcript fetch failed for {video_id}: {e}")
                counts["failed"] += 1
            
            # Progress update every item (and log every 5 for readability)
            self._emit_transcript_progress(i, total)
            if i % 5 == 0 or i == total:
                self._send("log", {"line": f"Transcripts: {i}/{total} done (free:{counts['free']}, paid:{counts['paid']}, failed:{counts['failed']})"})
        
        # Final summary
        summary = f"Transcripts complete: {counts['free']} free, {counts['paid']} paid, {counts['failed']} failed"
        self._send("log", {"line": summary})
        # Ensure progress bars reach completion
        self._emit_transcript_progress(total, total)
        return counts

    # legacy helpers for status chips if needed later
    def get_status(self) -> dict:
        return _status_snapshot(self.env)
