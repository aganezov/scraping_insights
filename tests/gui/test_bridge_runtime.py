from __future__ import annotations

from insight_mine.guis.pywebview import bridge


class _FakeRunner:
    instances: list["_FakeRunner"] = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.start_kwargs = None
        self.proc = object()
        self.reader_t = None
        self.finish_t = None
        self.__class__.instances.append(self)

    def start(self, **kwargs):
        self.start_kwargs = kwargs


class _FailingRunner(_FakeRunner):
    def start(self, **kwargs):
        raise FileNotFoundError("insight-mine")


def test_start_collect_cmd_normalizes_legacy_preview_and_appends_out(monkeypatch, tmp_path):
    out_dir = tmp_path / "gui-out"
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)
    monkeypatch.setattr(bridge, "CliRunner", _FakeRunner)
    monkeypatch.setattr(bridge.envutil, "compose_env", lambda _p: {"IM_CLI_BIN": "custom-cli"})
    monkeypatch.setattr(bridge.envutil, "get_output_dir_from_env", lambda _p: str(out_dir))

    b = bridge.Bridge(env_path=str(env_path))
    b._send = lambda *_args, **_kwargs: None

    result = b.start_collect_cmd(
        'insight-mine collect --topic "k1" --since 2025-01-01 --lang en --yt-comments-per-video 7 --limit 3',
        selected={"youtube": True, "reddit": False},
        transcript_mode="free",
        transcript_lang="",
    )

    assert result == {"ok": True}
    assert b._transcript_mode == "free"
    assert b._transcript_lang == "en"

    runner = _FakeRunner.instances[-1]
    cmd = runner.start_kwargs["cmd"]

    assert cmd[0] == "custom-cli"
    assert "--lang" not in cmd
    assert "--yt-comments-per-video" not in cmd
    assert "--limit" not in cmd
    assert "--langs" in cmd
    assert "--yt-max-comments" in cmd
    assert "--reddit-mode" in cmd
    assert "off" in cmd
    assert "--out" in cmd
    assert str(out_dir) in cmd
    assert out_dir.exists()


def test_compose_env_prefers_local_cli_binary_when_path_lookup_fails(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")

    local_bin = tmp_path / "bin" / "insight-mine"
    local_bin.parent.mkdir(parents=True, exist_ok=True)
    local_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(bridge.envutil, "compose_env", lambda _p: {"VIRTUAL_ENV": str(tmp_path)})
    monkeypatch.setattr(bridge.shutil, "which", lambda _name: None)
    monkeypatch.setattr(bridge.sys, "executable", str(tmp_path / "python"))

    composed = bridge._compose_env(env_path)

    assert composed["IM_CLI_BIN"] == str(local_bin.resolve())


def test_start_collect_cmd_reports_launch_error(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)
    monkeypatch.setattr(bridge, "CliRunner", _FailingRunner)
    monkeypatch.setattr(bridge.envutil, "compose_env", lambda _p: {"IM_CLI_BIN": "missing-cli"})
    monkeypatch.setattr(bridge.envutil, "get_output_dir_from_env", lambda _p: str(tmp_path))

    events: list[tuple[str, dict]] = []

    b = bridge.Bridge(env_path=str(env_path))
    b._send = lambda typ, payload: events.append((typ, payload))

    result = b.start_collect_cmd(
        'insight-mine collect --topic "k1" --since 2025-01-01 --lang en',
        selected={"youtube": False, "reddit": True},
    )

    assert "Failed to launch CLI" in result["error"]
    assert any(typ == "run_error" and "Failed to launch CLI" in payload["message"] for typ, payload in events)


def test_fetch_transcript_defaults_empty_lang_to_en_without_paid_fallback(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)

    b = bridge.Bridge(env_path=str(env_path))
    b._send = lambda *_args, **_kwargs: None

    seen: dict[str, str] = {}

    def fake_free(video_id: str, lang: str):
        seen["video_id"] = video_id
        seen["lang"] = lang
        return "free transcript body"

    def fail_paid(*_args, **_kwargs):
        raise AssertionError("paid transcript path should not be used in free mode")

    monkeypatch.setattr("insight_mine.guis.pywebview.ytti_client._fetch_via_yt_transcript_api", fake_free)
    monkeypatch.setattr("insight_mine.guis.pywebview.ytti_client.fetch_transcript", fail_paid)

    result = b.fetch_transcript("dQw4w9WgXcQ", run_id="", lang="", mode="free")

    assert result == {"ok": True, "text": "free transcript body", "source": "free"}
    assert seen == {"video_id": "dQw4w9WgXcQ", "lang": "en"}


def test_update_source_checkout_pulls_and_syncs_clean_repo(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)
    monkeypatch.setattr(bridge, "_repo_checkout_root", lambda start=None: repo_root)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls: list[list[str]] = []

    class _Completed:
        def __init__(self, args: list[str], stdout: str = "", stderr: str = "", returncode: int = 0):
            self.args = args
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    head_calls = 0

    def fake_run(args, cwd=None, text=None, capture_output=None):
        nonlocal head_calls
        calls.append(list(args))
        match args:
            case [_, "rev-parse", "--abbrev-ref", "HEAD"]:
                return _Completed(list(args), stdout="main\n")
            case [_, "status", "--porcelain", "--untracked-files=no"]:
                return _Completed(list(args), stdout="")
            case [_, "rev-parse", "HEAD"]:
                head_calls += 1
                head = "abc1234\n" if head_calls == 1 else "def5678\n"
                return _Completed(list(args), stdout=head)
            case [_, "pull", "--ff-only"]:
                return _Completed(list(args), stdout="Updating abc1234..def5678\n")
            case [_, "sync", "--extra", "gui"]:
                return _Completed(list(args), stdout="Resolved 1 package in 0.1s\n")
            case _:
                raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    b = bridge.Bridge(env_path=str(env_path))

    result = b.update_source_checkout()

    assert result["ok"] is True
    assert result["updated"] is True
    assert result["branch"] == "main"
    assert result["before"] == "abc1234"
    assert result["after"] == "def5678"
    assert any(cmd[:3] == ["/usr/bin/git", "pull", "--ff-only"] for cmd in calls)
    assert any(cmd[:4] == ["/usr/bin/uv", "sync", "--extra", "gui"] for cmd in calls)


def test_update_source_checkout_refuses_dirty_repo(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)
    monkeypatch.setattr(bridge, "_repo_checkout_root", lambda start=None: repo_root)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: f"/usr/bin/{name}")

    class _Completed:
        def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(args, cwd=None, text=None, capture_output=None):
        match args:
            case [_, "rev-parse", "--abbrev-ref", "HEAD"]:
                return _Completed(stdout="main\n")
            case [_, "status", "--porcelain", "--untracked-files=no"]:
                return _Completed(stdout=" M README.md\n")
            case _:
                raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    b = bridge.Bridge(env_path=str(env_path))

    result = b.update_source_checkout()

    assert result["ok"] is False
    assert "dirty checkout" in result["error"]


def test_restart_app_relaunches_current_entrypoint(monkeypatch, tmp_path):
    env_path = tmp_path / "settings.env"
    env_path.write_text("", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    launcher = tmp_path / "bin" / "insight-mine-gui"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(bridge, "_save_settings", lambda _s: None)
    monkeypatch.setattr(bridge, "_repo_checkout_root", lambda start=None: repo_root)
    monkeypatch.setattr(bridge.sys, "argv", [str(launcher), "--env", str(env_path)])

    launched: dict[str, object] = {}

    def fake_popen(cmd, cwd=None, env=None, start_new_session=None):
        launched["cmd"] = cmd
        launched["cwd"] = cwd
        launched["env"] = env
        launched["start_new_session"] = start_new_session
        class _Proc:
            pass
        return _Proc()

    class _Window:
        def destroy(self):
            launched["destroyed"] = True

    monkeypatch.setattr(bridge.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bridge, "_main_window", lambda: _Window())

    b = bridge.Bridge(env_path=str(env_path))
    b.env = {"IM_OUT_DIR": str(tmp_path / "out")}

    result = b.restart_app()

    assert result == {"ok": True}
    assert launched["cmd"] == [str(launcher.resolve()), "--env", str(env_path)]
    assert launched["cwd"] == str(repo_root)
    assert launched["start_new_session"] is True
    assert launched["destroyed"] is True
