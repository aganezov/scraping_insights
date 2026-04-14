from insight_mine.guis.pywebview import ytti_client
import pytest


def test_fetch_via_cli_requires_explicit_template(monkeypatch):
    monkeypatch.delenv("IM_CLI_TRANSCRIPT_CMD", raising=False)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called without IM_CLI_TRANSCRIPT_CMD")

    monkeypatch.setattr(ytti_client.subprocess, "run", fail_run)

    assert ytti_client._fetch_via_cli("abc123", "en") is None


def test_fetch_via_cli_uses_configured_template(monkeypatch):
    monkeypatch.setenv("IM_CLI_TRANSCRIPT_CMD", "echo transcript-for-{video_id}-{lang}")

    class Result:
        returncode = 0
        stdout = "transcript body\n"

    monkeypatch.setattr(ytti_client.subprocess, "run", lambda *args, **kwargs: Result())

    assert ytti_client._fetch_via_cli("abc123", "en") == "transcript body"


def test_fetch_transcript_skips_paid_when_disabled_by_env(monkeypatch):
    monkeypatch.setenv("YTTI_SKIP_PAID", "1")
    monkeypatch.setattr(ytti_client, "_fetch_via_yt_transcript_api", lambda video_id, lang: None)
    monkeypatch.setattr(ytti_client, "_fetch_via_cli", lambda video_id, lang: None)
    monkeypatch.setattr(
        ytti_client,
        "_fetch_via_http",
        lambda video_id, lang: (_ for _ in ()).throw(AssertionError("paid fallback should not run")),
    )

    with pytest.raises(ytti_client.TranscriptError) as exc:
        ytti_client.fetch_transcript("abc123", "en", allow_paid=True)

    assert "paid disabled" in str(exc.value)


def test_fetch_transcript_skips_paid_when_allow_paid_is_false(monkeypatch):
    monkeypatch.delenv("YTTI_SKIP_PAID", raising=False)
    monkeypatch.setattr(ytti_client, "_fetch_via_yt_transcript_api", lambda video_id, lang: None)
    monkeypatch.setattr(ytti_client, "_fetch_via_cli", lambda video_id, lang: None)
    monkeypatch.setattr(
        ytti_client,
        "_fetch_via_http",
        lambda video_id, lang: (_ for _ in ()).throw(AssertionError("paid fallback should not run")),
    )

    with pytest.raises(ytti_client.TranscriptError) as exc:
        ytti_client.fetch_transcript("abc123", "en", allow_paid=False)

    assert "paid disabled" in str(exc.value)
