---
name: Insight Mine Refactor
overview: Comprehensive refactoring addressing security vulnerabilities (credential exposure), architectural issues (monolithic bridge.py/cli.py), missing test coverage, and code quality improvements identified by Gemini, Codex, and Opus reviews.
todos:
  - id: security-secrets
    content: Remove real credentials from seed_settings.env, replace with placeholders
    status: completed
  - id: security-mask-cli
    content: Add mask_secret() helper and apply to cli.py:209-211 logging
    status: completed
  - id: security-mask-gui
    content: Mask credentials in bridge.py:671-675 GUI logging
    status: completed
  - id: arch-extract-cli-runner
    content: Extract duplicate reader/finisher threads from bridge.py into cli_runner.py
    status: completed
  - id: arch-extract-progress
    content: Extract regex patterns and telemetry parsing into progress_parser.py
    status: completed
  - id: arch-split-cli
    content: Split cli.py into args.py, orchestrator.py, output.py modules
    status: completed
  - id: arch-db-context
    content: Add context manager for SQLite connections in cache.py
    status: completed
  - id: robust-reddit-backoff
    content: Add exponential backoff for 5xx errors in reddit_scrape.py
    status: completed
  - id: robust-thread-cleanup
    content: Add thread join in cancel_collect() method
    status: completed
  - id: test-cli-args
    content: Add tests for CLI argument parsing and preset resolution
    status: completed
  - id: test-variety-guard
    content: Add tests for variety guard algorithm
    status: completed
  - id: test-progress-regex
    content: Add tests for progress/telemetry parsing regex
    status: completed
  - id: polish-naming
    content: Rename _eff() and extract magic numbers to constants
    status: completed
  - id: polish-docstrings
    content: Add module-level docstrings to key files
    status: completed
---

# Test Suite Expansion Plan

## Goals

- Broaden coverage across CLI flows, connectors, and GUI bridge behavior.
- Enforce zero paid API usage in tests; allow recorded fixtures/mocks only.

## Scope & Strategy

- **Unit tests (pure/mocked):**
- `src/insight_mine/cli/args.py`: flag/preset/env resolution (langs, limits, toggles), ensure `YTTI_SKIP_PAID` respected.
- `src/insight_mine/connectors/youtube.py`: budget calc, status handling (no real API; mock `get_secret` and client build), filtering helpers.
- `src/insight_mine/connectors/reddit_scrape.py`: backoff logic (timing via monkeypatch), filter predicates, JSON handling with mocked `requests.Session`.
- `src/insight_mine/guis/pywebview/progress_parser.py`: progress/telemetry regex parsing.
- `src/insight_mine/utils/cache.py`: context manager behavior, schema init.

- **Integration tests (mocked/recorded I/O, no paid):**
- CLI collect end-to-end with faked connectors: patch yt/rd collectors to return fixtures; assert outputs (`raw.jsonl`, `paste-ready.txt`, `run_manifest.json`) and progress logs.
- Variety guard + dedupe + cache interaction: seed cache, run collect, verify drops and manifest counts.
- Transcript flow (free-only): set `YTTI_SKIP_PAID=1`, mock `ytti_client` free path to return text, ensure paid path never called.
- Optional recorded fixtures: allow VCRpy for deterministic HTTP snapshots for reddit search JSON (non-paid) with `record_mode=none` in CI.

- **GUI/bridge behavior tests (headless/logic-level):**
- Bridge command construction and env masking: patch `_send`, assert masked keys and built CLI args.
- Progress parsing via `CliRunner` + `progress_parser`: feed synthetic stdout lines, assert emitted progress/counts.
- Cancel behavior: ensure threads joined and proc killed (use dummy proc mock).

- **User-behavior style tests (lightweight):**
- CLI UX: golden output for `--explain` (snapshot text) with stable fixtures.
- GUI command preview: unit-level test for `build_command` output given knobs/env (no UI automation needed).

## Safety Controls (paid usage guard)

- Keep `tests/conftest.py` auto-setting `YTTI_SKIP_PAID=1`; only allow paid via explicit `YTTI_ALLOW_PAID_TESTS=1` opt-in.
- For recorded fixtures, store cassettes under `tests/fixtures/cassettes/` and set record mode to “none” by default.

## Tooling & Structure

- Add fixtures under `tests/fixtures/` (sample items, manifests, reddit/youtube sample JSON).
- Use `pytest` with markers: `unit`, `integration`, `gui`, `slow`. Default run excludes `slow`.
- Add `pytest.ini` to register markers and set env defaults (e.g., `YTTI_SKIP_PAID=1`).

## Deliverables

- New/updated tests across areas above with mocks/fixtures.
- Updated test config (`pytest.ini`) and fixtures directory.
- Documentation note in `README` or `CONTRIBUTING` about paid API guard and how to opt-in for paid tests (optional).