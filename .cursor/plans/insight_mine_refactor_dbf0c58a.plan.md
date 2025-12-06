---
name: Insight Mine Refactor
overview: Comprehensive refactoring addressing security vulnerabilities (credential exposure), architectural issues (monolithic bridge.py/cli.py), missing test coverage, and code quality improvements identified by Gemini, Codex, and Opus reviews.
todos:
  - id: security-secrets
    content: Remove real credentials from seed_settings.env, replace with placeholders
    status: pending
  - id: security-mask-cli
    content: Add mask_secret() helper and apply to cli.py:209-211 logging
    status: pending
  - id: security-mask-gui
    content: Mask credentials in bridge.py:671-675 GUI logging
    status: pending
  - id: arch-extract-cli-runner
    content: Extract duplicate reader/finisher threads from bridge.py into cli_runner.py
    status: pending
  - id: arch-extract-progress
    content: Extract regex patterns and telemetry parsing into progress_parser.py
    status: pending
  - id: arch-split-cli
    content: Split cli.py into args.py, orchestrator.py, output.py modules
    status: pending
  - id: arch-db-context
    content: Add context manager for SQLite connections in cache.py
    status: pending
  - id: robust-reddit-backoff
    content: Add exponential backoff for 5xx errors in reddit_scrape.py
    status: pending
  - id: robust-thread-cleanup
    content: Add thread join in cancel_collect() method
    status: pending
  - id: test-cli-args
    content: Add tests for CLI argument parsing and preset resolution
    status: pending
  - id: test-variety-guard
    content: Add tests for variety guard algorithm
    status: pending
  - id: test-progress-regex
    content: Add tests for progress/telemetry parsing regex
    status: pending
  - id: polish-naming
    content: Rename _eff() and extract magic numbers to constants
    status: pending
  - id: polish-docstrings
    content: Add module-level docstrings to key files
    status: pending
---

# Insight Mine Comprehensive Refactoring Plan

Based on code reviews from Gemini 3 Pro, GPT-5.1 Codex Max, and Claude Opus 4.5.

## Phase 1: Critical Security Fixes

### 1.1 Remove Exposed Credentials

`packaging/seed_settings.env` contains real API keys that ship with builds.

**Actions:**

- Replace real values with placeholders in `seed_settings.env`
- Add `.env` pattern to `.gitignore` if missing
- **Rotate/revoke all exposed credentials immediately** (manual step)

### 1.2 Mask Secrets in Logs

Credentials logged in plaintext at:

- `cli.py:209-211` - logs full env values
- `bridge.py:671-675` - sends credentials to UI log panel

**Actions:**

- Create `_mask_secret()` helper in `utils/text.py`:
```python
def mask_secret(val: str) -> str:
    if not val: return "(not set)"
    if len(val) <= 8: return "****"
    return f"{val[:3]}...{val[-3:]}"
```

- Apply masking in CLI and GUI logging

---

## Phase 2: Architecture Refactoring

### 2.1 Split `bridge.py` (1311 lines)

Current responsibilities: subprocess management, log parsing, file I/O, transcript fetching, settings persistence, run history.

**Target structure:**

```
guis/pywebview/
├── bridge.py           # Slim JS API exposure (~200 lines)
├── cli_runner.py       # Subprocess + thread management
├── progress_parser.py  # Regex patterns, telemetry extraction
├── transcript_ops.py   # Transcript fetching logic
└── (existing files)
```

**Key extraction:**

- Extract duplicate `reader()` and `finisher()` functions from `start_collect()` (line 695) and `start_collect_cmd()` (line 951) into `cli_runner.py`

### 2.2 Split `cli.py` (511 lines)

**Target structure:**

```
cli/
├── __init__.py        # Re-exports main()
├── args.py            # Argument parsing, preset resolution
├── orchestrator.py    # Connector coordination
└── output.py          # File writing, formatting, variety guard
```

### 2.3 Database Context Managers

`cli.py:401-411` - connections not managed safely.

**Action:** Wrap with context manager:

```python
@contextlib.contextmanager
def cache_db(path: str):
    conn = open_db(path)
    try:
        yield conn
    finally:
        conn.close()
```

---

## Phase 3: Robustness Improvements

### 3.1 Reddit Scraping Resilience

`reddit_scrape.py` only handles 429; no exponential backoff for 5xx.

**Action:** Add jittered exponential backoff:

```python
for attempt in range(max_retries):
    # ... request ...
    if resp.status_code >= 500:
        delay = min(30, (2 ** attempt) + random.uniform(0, 1))
        time.sleep(delay)
        continue
```

### 3.2 Thread Cleanup on Cancel

`bridge.py:1113-1125` - `cancel_collect()` doesn't join threads.

**Action:** Add explicit thread cleanup:

```python
def cancel_collect(self):
    # ... existing terminate/kill ...
    if self.reader_t:
        self.reader_t.join(timeout=2)
    if self.finish_t:
        self.finish_t.join(timeout=2)
```

### 3.3 Narrow Exception Handling

Replace `except Exception:` with specific exceptions where safe.

---

## Phase 4: Testing Expansion

### 4.1 Priority Test Cases

Current tests only cover connector status toggles and language utils.

**Add tests for:**

1. **CLI argument parsing** - preset resolution, flag overrides
2. **Variety guard algorithm** - `apply_variety_guard()`
3. **Progress parsing regex** - `PROG_RE`, `TEL_RE`, `_KEPT_RE`
4. **Output serialization** - JSONL/text formatting
5. **Integration tests** - mock API responses for YouTube/Reddit collect flows

### 4.2 Test Infrastructure

- Add `conftest.py` with fixtures for sample data
- Add mock factories for API responses

---

## Phase 5: Code Quality Polish

### 5.1 Naming and Constants

- Rename `_eff()` to `_resolve_setting()` in `cli.py`
- Extract magic numbers to named constants:
  - `SNIPPET_MAX_LEN = 1200` (cli.py:428)
  - `BUDGET_MULTIPLIER = 8` (youtube.py:100)

### 5.2 Documentation

- Add module-level docstrings to all files
- Document Item schema fields in `models.py`

### 5.3 Type Safety

- Convert `metrics: Dict[str, Any] `to `TypedDict` in `models.py`
- Move `pytest` to dev dependencies in `pyproject.toml`

### 5.4 Cleanup

- Remove or implement `x_api.py` placeholder connector