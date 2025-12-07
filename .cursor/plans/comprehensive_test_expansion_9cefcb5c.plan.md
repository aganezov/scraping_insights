---
name: Comprehensive Test Expansion
overview: Unified test suite expansion combining recommendations from Opus 4.5 and Codex reviews. Covers unit tests, integration tests with fixtures extracted from existing runs, GUI bridge tests, and property-based testing - all without paid API usage.
todos:
  - id: fixtures-extract
    content: Extract fixture data from existing runs in Downloads/test_out/, sanitize usernames
    status: completed
  - id: conftest-enhance
    content: Enhance conftest.py with fixture loaders and mock factories
    status: completed
  - id: unit-cache
    content: Add unit tests for cache.py (open_db, cache_db, load_seen, upsert_many)
    status: completed
  - id: unit-text
    content: Add unit tests for text.py (clean_for_hash, sha1, dedupe_items, mask_secret)
    status: completed
  - id: unit-output
    content: Add unit tests for output.py serialization
    status: completed
  - id: unit-cli-adapter
    content: Add unit tests for cli_adapter.py (slug, build_collect_cmd)
    status: completed
  - id: integration-collect
    content: Add integration tests for CLI collect flow with mocked connectors
    status: completed
  - id: integration-disabled
    content: Add integration tests for disabled connector handling
    status: completed
  - id: integration-cache
    content: Add integration tests for cache skip/refresh behavior
    status: completed
  - id: gui-knobs
    content: Add GUI tests for knob normalization and command building
    status: completed
  - id: gui-storage
    content: Add GUI tests for storage run listing and topic inference
    status: completed
  - id: gui-runner
    content: Add GUI tests for CLI runner thread handling
    status: completed
  - id: property-filters
    content: Add property-based tests for variety guard and dedupe using hypothesis
    status: completed
---

# Comprehensive Test Suite Expansion

Combining testing recommendations from Claude Opus 4.5 and GPT-5.1 Codex Max reviews.

## Test Directory Structure

```
tests/
├── conftest.py                 # Shared fixtures, API guards, mock factories
├── fixtures/                   # Extracted from existing runs
│   ├── youtube_items.json
│   └── reddit_items.json
├── unit/
│   ├── test_cache.py
│   ├── test_text_utils.py
│   ├── test_cli_adapter.py
│   ├── test_output.py
│   └── test_env_resolution.py
├── integration/
│   ├── test_cli_collect.py
│   ├── test_cli_disabled.py
│   ├── test_cache_behavior.py
│   └── test_error_scenarios.py
├── gui/
│   ├── test_bridge_knobs.py
│   ├── test_storage.py
│   ├── test_cli_runner.py
│   └── test_envutil.py
└── property/
    └── test_filters_hypothesis.py
```

---

## Phase 1: Fixtures from Existing Runs

### Source Data
Extract sanitized samples from `/Users/saganezov/Downloads/test_out/`:
- YouTube run: `20251206_120950/raw.jsonl` (3 videos, 94 comments)
- Reddit run: `20251202_214156/raw.jsonl` (posts + comments)

### Extraction
- Extract 2-3 videos + 5-10 comments (YouTube)
- Extract 2-3 posts + 3-5 comments (Reddit)
- Replace real usernames with placeholders
- Write to `tests/fixtures/youtube_items.json` and `reddit_items.json`

---

## Phase 2: Unit Tests

### 2.1 Cache Utils (`tests/unit/test_cache.py`)
```python
def test_open_db_creates_schema(tmp_path)
def test_cache_db_context_closes_connection(tmp_path)
def test_load_seen_returns_stored_keys(tmp_path)
def test_upsert_many_dedupes_on_conflict(tmp_path)
```

### 2.2 Text Utils (`tests/unit/test_text_utils.py`)
```python
def test_clean_for_hash_normalizes_whitespace()
def test_sha1_consistent_output()
def test_dedupe_items_removes_duplicates()
def test_mask_secret_short_and_long_values()
```

### 2.3 Output Serialization (`tests/unit/test_output.py`)
```python
def test_as_dict_serializes_item_correctly()
def test_counts_by_kind_categorizes_items()
def test_paste_ready_truncates_long_snippets()
```

### 2.4 CLI Adapter (`tests/unit/test_cli_adapter.py`)
```python
def test_slug_sanitizes_special_chars()
def test_build_collect_cmd_includes_youtube_flags()
def test_build_collect_cmd_excludes_disabled_connectors()
```

---

## Phase 3: Integration Tests

### 3.1 CLI Collect Flow (`tests/integration/test_cli_collect.py`)
```python
def test_youtube_only_collect(mock_youtube, tmp_path)
def test_reddit_only_collect(mock_reddit, tmp_path)
def test_filters_applied_correctly(mock_youtube, tmp_path)
```

### 3.2 Disabled Connectors (`tests/integration/test_cli_disabled.py`)
```python
def test_youtube_disabled_skips_gracefully(monkeypatch)
def test_all_connectors_disabled_produces_empty_output(monkeypatch)
```

### 3.3 Cache Behavior (`tests/integration/test_cache_behavior.py`)
```python
def test_first_run_stores_all_items(tmp_path)
def test_second_run_skips_cached_items(tmp_path)
def test_refresh_flag_ignores_cache(tmp_path)
```

---

## Phase 4: GUI Bridge Tests

### 4.1 Knob Normalization (`tests/gui/test_bridge_knobs.py`)
```python
def test_normalize_knobs_flattens_v15_structure()
def test_build_command_returns_valid_cli()
```

### 4.2 Storage (`tests/gui/test_storage.py`)
```python
def test_build_ui_run_assembles_manifest(tmp_path)
def test_list_runs_finds_directories(tmp_path)
def test_infer_topic_from_manifest()
```

### 4.3 CLI Runner (`tests/gui/test_cli_runner.py`)
```python
def test_reader_parses_progress_lines()
def test_cancel_terminates_and_joins_threads()
```

---

## Phase 5: Property-Based Tests

### 5.1 Filter Properties (`tests/property/test_filters_hypothesis.py`)
```python
@given(st.lists(...))
def test_variety_guard_never_increases_count(items)

@given(st.lists(...))
def test_dedupe_is_idempotent(items)
```

---

## Safety Guarantees

1. `conftest.py` sets `YTTI_SKIP_PAID=1` session-wide
2. All connector tests use monkeypatched mocks
3. Use `tmp_path` fixture for file operations
4. Fixtures use sanitized placeholder usernames