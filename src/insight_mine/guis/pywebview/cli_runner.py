"""Threaded CLI subprocess runner shared by the GUI bridge."""
from __future__ import annotations

import subprocess
import threading
from typing import Callable, Dict, List, Optional

from . import progress_parser as pp


class CliRunner:
    """
    Shared runner for CLI subprocess execution and stdout parsing.
    Encapsulates reader/finisher threads used by the GUI bridge.
    """

    def __init__(
        self,
        *,
        selected: Dict[str, bool],
        counts: Dict[str, int],
        clamp_overall: Optional[Callable[[int], int]] = None,
        parse_kept: Callable[[str, str], tuple[int, int]],
    ) -> None:
        self.selected = selected
        self.counts = counts
        self.clamp_overall = clamp_overall
        self.parse_kept = parse_kept

        self.proc: Optional[subprocess.Popen] = None
        self.reader_t: Optional[threading.Thread] = None
        self.finish_t: Optional[threading.Thread] = None

    def start(
        self,
        *,
        cmd: List[str],
        env: Dict[str, str],
        on_log: Callable[[str], None],
        emit_progress: Callable[..., None],
        emit_yt_counts: Callable[[int, int], None],
        emit_rd_counts: Callable[[int, int], None],
        emit_counts: Callable[[], None],
        on_finished: Callable[[int], None],
    ) -> None:
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        def reader():
            assert self.proc and self.proc.stdout
            for raw_line in self.proc.stdout:
                line = raw_line.rstrip("\n")
                on_log(line)

                telemetry = pp.parse_telemetry_line(line)
                if telemetry:
                    source, tail = telemetry
                    if tail.strip() == "-":
                        continue
                    par, com = self.parse_kept(tail, source)
                    if "youtube" in source.lower():
                        self.counts["yt_par"] = par
                        self.counts["yt_com"] = com
                        emit_progress(yt_par=par, yt_com=com)
                        emit_yt_counts(par, com)
                    else:
                        self.counts["rd_par"] = par
                        self.counts["rd_com"] = com
                        emit_progress(rd_par=par, rd_com=com)
                        emit_rd_counts(par, com)
                    emit_counts()
                    continue

                obj = pp.parse_json_event(line)
                if isinstance(obj, dict):
                    if obj.get("event") == "progress":
                        emit_progress(
                            overall=obj.get("overall"),
                            youtube=obj.get("youtube"),
                            reddit=obj.get("reddit"),
                            yt_par=obj.get("yt_par"),
                            yt_com=obj.get("yt_com"),
                            rd_par=obj.get("rd_par"),
                            rd_com=obj.get("rd_com"),
                        )
                        continue
                    if obj.get("event") == "item":
                        plat = (obj.get("item") or {}).get("platform")
                        if plat == "youtube":
                            self.counts["yt_par"] += 1
                        if plat == "reddit":
                            self.counts["rd_par"] += 1
                        emit_progress(
                            yt_par=self.counts.get("yt_par"),
                            yt_com=self.counts.get("yt_com"),
                            rd_par=self.counts.get("rd_par"),
                            rd_com=self.counts.get("rd_com"),
                        )
                        continue

                prog = pp.parse_progress_line(line)
                if prog:
                    if self.clamp_overall and prog.get("overall") is not None:
                        prog["overall"] = self.clamp_overall(prog["overall"])  # type: ignore[arg-type]
                    emit_progress(
                        overall=prog.get("overall"),
                        youtube=prog.get("youtube"),
                        reddit=prog.get("reddit"),
                    )
                    continue

                wrote = pp.parse_wrote_line(line)
                if wrote is not None:
                    if self.selected.get("youtube") and not self.selected.get("reddit"):
                        par = self.counts.get("yt_par", 0)
                        emit_progress(yt_par=par, yt_com=max(0, wrote - par))
                    elif self.selected.get("reddit") and not self.selected.get("youtube"):
                        par = self.counts.get("rd_par", 0)
                        emit_progress(rd_par=par, rd_com=max(0, wrote - par))
                    continue

        def finisher():
            assert self.proc
            code = self.proc.wait()
            # Wait for reader to finish processing all stdout (including telemetry)
            if self.reader_t:
                self.reader_t.join(timeout=5)
            on_finished(code)
            self.proc = None

        self.reader_t = threading.Thread(target=reader, daemon=True)
        self.reader_t.start()
        self.finish_t = threading.Thread(target=finisher, daemon=True)
        self.finish_t.start()
