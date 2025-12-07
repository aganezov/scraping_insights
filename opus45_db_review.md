# Database and Storage Usage Review

## Overview

The Insight Mine project uses **two distinct storage mechanisms**:

1. **SQLite Cache** (`src/insight_mine/utils/cache.py`) - For deduplication across CLI runs
2. **File-based JSON Storage** (`src/insight_mine/guis/pywebview/storage.py`) - For persisting run results

---

## 1. SQLite Cache Database

### Location
- User-specified via `--cache` CLI argument
- No default location (cache is disabled by default)

### Schema

```sql
CREATE TABLE IF NOT EXISTS seen (
    platform TEXT NOT NULL,
    id TEXT NOT NULL,
    first_seen_ts INTEGER NOT NULL,
    PRIMARY KEY (platform, id)
);
```

### Database Pragmas

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

### Functions

| Function | Purpose |
|----------|---------|
| `open_db(path)` | Opens/creates SQLite database, applies schema |
| `load_seen(conn)` | Returns `Set[Tuple[platform, id]]` of all seen items |
| `upsert_many(conn, keys)` | Bulk insert items with `INSERT OR IGNORE` |

### What Gets Cached

Each collected item is stored as a `(platform, id)` tuple:
- **YouTube videos**: `("youtube", "<video_id>")`
- **YouTube comments**: `("youtube", "<comment_id>")`
- **Reddit posts**: `("reddit", "t3_<post_id>")`
- **Reddit comments**: `("reddit", "t1_<comment_id>")`

### When Cache is Checked (Read)

**CLI Invocation:** During `collect` command, AFTER:
1. Items are fetched from connectors (YouTube API, Reddit API/Scrape)
2. Items are serialized to dict format
3. Variety guard is applied
4. Deduplication (if `--dedupe` enabled)

**Code Location:** `src/insight_mine/cli.py:398-411` and `src/insight_mine/cli/orchestrator.py:179-192`

```python
dropped_by_cache = 0
cache_path = args.cache.strip()
if cache_path and not args.refresh:
    conn = open_db(cache_path)
    seen = load_seen(conn)
    keep = []
    for it in serial:
        key = (it["platform"], it["id"])
        if key in seen:
            dropped_by_cache += 1
            continue
        keep.append(it)
    serial = keep
    conn.close()
```

### When Cache is Updated (Write)

**CLI Invocation:** At the END of `collect` command, AFTER:
1. All filtering/sampling complete
2. Output files written (`raw.jsonl`, `paste-ready.txt`, etc.)
3. Latest symlink created

**Code Location:** `src/insight_mine/cli.py:488-491` and `src/insight_mine/cli/orchestrator.py:229-232`

```python
if cache_path:
    conn = open_db(cache_path)
    upsert_many(conn, ((it["platform"], it["id"]) for it in serial))
    conn.close()
```

### Cache Bypass

The `--refresh` flag ignores the cache read (but still writes to it):

```python
if cache_path and not args.refresh:  # Skip read if refresh=True
    # ... check cache ...
```

---

## 2. File-based Run Storage

### Directory Structure

```
<out_dir>/
├── <run_id>/                    # Timestamped directory (YYYYMMDD_HHMMSS)
│   ├── raw.jsonl                # All collected items (JSONL)
│   ├── paste-ready.txt          # Human-readable summaries
│   ├── run_manifest.json        # CLI metadata and counts
│   ├── run.json                 # GUI-format run data (created by GUI)
│   ├── run.log                  # Empty log file (GUI)
│   └── stats.json               # Connector telemetry
│   └── cli_out/                 # (optional) Legacy CLI output subdirectory
│       └── latest -> <subdir>   # Symlink to latest CLI run
└── latest -> <run_id>           # Symlink to most recent run
```

### Output Files

#### `raw.jsonl` - Machine-readable normalized data

Written during CLI `collect`:
```python
write_jsonl(run_dir / "raw.jsonl", serial)
```

Each line is a JSON object:
```json
{
  "platform": "youtube|reddit",
  "id": "unique_id",
  "url": "https://...",
  "author": "username",
  "created_at": "ISO8601",
  "title": "optional title (videos/posts only)",
  "text": "content text",
  "metrics": {"views": 1000, "likes": 50, ...},
  "context": {"videoId": "...", "channelId": "...", ...}
}
```

#### `paste-ready.txt` - Human/LLM-readable summaries

Written during CLI `collect`:
```python
lines = []
for it in serial:
    ttl = f"{it['title']} — " if it.get("title") else ""
    snippet = (it.get("text") or "").strip().replace("\n", " ")
    if len(snippet) > 1200:
        snippet = snippet[:1200] + "…"
    lines.append(f"[{it['platform']}] {ttl}{snippet}\n{it['url']}")
write_txt(run_dir / "paste-ready.txt", lines)
```

#### `run_manifest.json` - CLI metadata

Written during CLI `collect`:
```json
{
  "run_id": "20251205_143022",
  "topic": "search topic",
  "since": "2025-11-05",
  "preset": "balanced",
  "effective": {
    "langs": ["en"],
    "yt": {...},
    "reddit": {...},
    "dedupe": true,
    "cache": "path/to/cache.db",
    "refresh": false,
    "sample": 0
  },
  "connectors": {
    "youtube": true,
    "reddit_api": false,
    "reddit_scrape": true,
    "transcripts": false
  },
  "counts": {
    "total": 150,
    "youtube_video": 10,
    "youtube_comment": 80,
    "reddit_post": 20,
    "reddit_comment": 40
  },
  "dropped_by_cache": 5,
  "sampled": null,
  "created_at": "2025-12-05T14:30:22"
}
```

#### `run.json` - GUI-format run data

Created by GUI's `build_ui_run()` when viewing/completing a run:
```json
{
  "id": "20251205_143022",
  "manifest": {
    "started_at": "2025-12-05T14:30:22Z",
    "knobs": {...},
    "items": [
      {
        "platform": "youtube",
        "kind": "video",
        "id": "...",
        "url": "...",
        "title": "...",
        "text": "...",
        "comments": [{...}, {...}],
        "transcript": "..."
      }
    ]
  },
  "stats": {
    "dropped": {"low_views": 0, "low_score": 0, "lang_mismatch": 0}
  }
}
```

#### `stats.json` - Connector telemetry

Written during CLI `collect`:
```json
{
  "youtube": {"yt_video_kept": 10, "yt_comment_kept": 80, ...},
  "reddit_scrape": {"rd_post_kept": 20, "rd_comment_kept": 40, ...},
  "reddit_api": {}
}
```

---

## 3. Storage Function Reference

### `storage.py` Functions

| Function | Purpose | When Called |
|----------|---------|-------------|
| `list_runs(out_root)` | Scan directory for runs, return summaries | GUI history panel load |
| `load_run(run_id, out_root)` | Load full run data by ID | GUI run detail view |
| `build_ui_run(run_id, run_dir, knobs)` | Create/update run.json with UI format | After CLI collect completes |
| `get_paste_ready(run_id, out_root)` | Load paste-ready.txt content | GUI "Copy All" button |
| `update_item_transcript(run_id, item_id, text, out_root)` | Update transcript in run.json | After transcript fetch |
| `map_items(raw_items)` | Convert flat JSONL to nested parent/comments | Loading old runs |

### `list_runs()` - How runs are discovered

```python
def list_runs(out_root: Path) -> list[dict]:
    # Scan both <out_root>/ and <out_root>/out/ for run directories
    candidates = []
    for p in out_root.iterdir():
        if p.is_dir() and not p.is_symlink():
            candidates.append(p)
    
    for d in sorted(candidates, ...):
        # Try run.json first (GUI format)
        run_json = d / "run.json"
        if run_json.exists():
            # Extract counts from manifest.items
            ...
        
        # Fallback to run_manifest.json (CLI format)
        manifest_json = d / "run_manifest.json"
        if manifest_json.exists():
            # Extract counts from counts dict
            ...
        
        # Last resort: scan raw.jsonl
        raw_jsonl = d / "raw.jsonl"
        if raw_jsonl.exists():
            # Parse and count items
            ...
```

---

## 4. GUI Settings Storage

### Location
```
~/.insight-mine/gui_settings.json
```

### Contents
```json
{
  "env_path": "/path/to/.env",
  "out_dir": "/path/to/output"
}
```

### Functions
| Function | Purpose |
|----------|---------|
| `_load_settings()` | Load from `gui_settings.json` |
| `_save_settings(s)` | Persist to `gui_settings.json` |

---

## 5. Invocation Flow Summary

### CLI `collect` Command

```
1. Parse args
2. Check connector status
3. Fetch YouTube items
4. Fetch Reddit items
5. Fetch transcripts (if enabled)
6. Serialize items to dicts
7. Apply variety guard
8. Dedupe (if --dedupe)
9. ★ CHECK CACHE ★ (if --cache, skip if --refresh)
10. Sample (if --sample)
11. Write raw.jsonl
12. Write paste-ready.txt
13. Write run_manifest.json
14. Write stats.json
15. Create "latest" symlink
16. ★ UPDATE CACHE ★ (if --cache)
17. Log summary
```

### GUI `start_collect()`

```
1. Load/compose environment
2. Build CLI command from knobs
3. Reset progress tracking
4. Spawn CLI subprocess
5. Stream logs to UI
6. On CLI exit:
   a. Call build_ui_run() → writes run.json
   b. Fetch transcripts (if mode != "off")
   c. Update run.json with transcripts
   d. Send run_complete event to UI
```

### GUI `list_runs()`

```
1. Get out_dir from env
2. Call storage.list_runs(out_root)
   - Scan directories
   - Try run.json → run_manifest.json → raw.jsonl
   - Extract: id, started_at, topic, items count, comments count
3. Return list to UI
```

### GUI `get_run(run_id)`

```
1. Get out_dir from env
2. Call storage.load_run(run_id, out_root)
   - Try run.json first
   - Fallback: build from run_manifest.json + raw.jsonl
   - map_items() converts flat items to nested structure
3. Return full run data to UI
```

---

## 6. Data Flow Diagram

```
                                    CLI Collect
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Connector Fetch                              │
│   YouTube API ─────┐                                                │
│   Reddit API  ─────┼──────▶  List[Item]                             │
│   Reddit Scrape ───┘                                                │
└─────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Post-processing Pipeline                       │
│                                                                      │
│   serialize ──▶ variety_guard ──▶ dedupe ──▶ CACHE CHECK ──▶ sample │
│                                                    │                 │
│                                          ┌────────┴────────┐        │
│                                          │  SQLite Cache   │        │
│                                          │  (seen table)   │        │
│                                          └─────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Output Writing                               │
│                                                                      │
│   raw.jsonl ◀───────────────┐                                       │
│   paste-ready.txt ◀─────────┼─── serial items                       │
│   run_manifest.json ◀───────┤                                       │
│   stats.json ◀──────────────┘                                       │
└─────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Cache Update                                  │
│                                                                      │
│   SQLite: INSERT OR IGNORE (platform, id, timestamp)                │
└─────────────────────────────────────────────────────────────────────┘


                                   GUI Flow
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      On Run Complete                                 │
│                                                                      │
│   build_ui_run() ─────▶ run.json (nested items with comments)       │
│                                                                      │
│   fetch_transcripts_batch() ─────▶ update run.json with transcripts │
└─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      History Loading                                 │
│                                                                      │
│   list_runs() ────▶ Scan directories for run.json/run_manifest.json │
│                                                                      │
│   load_run() ─────▶ Read run.json or reconstruct from raw.jsonl     │
│                                                                      │
│   map_items() ────▶ Convert flat items to parent/comments structure │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Potential Issues / Recommendations

### Current Issues

1. **Connection not closed properly**: The cache DB connection is opened and closed manually without context managers. A crash between open and close could leave connections dangling.

2. **No cache pruning**: The seen table grows indefinitely. Consider adding TTL or manual cleanup.

3. **Duplicate code**: Cache logic is duplicated between `cli.py` and `cli/orchestrator.py`.

4. **File format mismatch**: CLI writes `run_manifest.json`, GUI expects `run.json`. The `load_run()` function handles both but adds complexity.

### Recommendations

1. **Use context managers for SQLite**:
```python
from contextlib import closing

with closing(open_db(cache_path)) as conn:
    seen = load_seen(conn)
```

2. **Add cache stats command**:
```bash
insight-mine cache --stats  # Show item count, oldest/newest
insight-mine cache --prune --before 2025-01-01  # Remove old entries
```

3. **Consolidate run formats**: Either always write both `run.json` and `run_manifest.json`, or migrate to a single format.

4. **Add database migrations**: If schema changes are needed, add a version table and migration support.

---

## 8. Summary Table

| Storage Type | Location | Format | Written By | Read By |
|-------------|----------|--------|------------|---------|
| SQLite Cache | User-specified `--cache` | SQLite | CLI (end of collect) | CLI (start of collect) |
| raw.jsonl | `<out>/<run_id>/` | JSONL | CLI | GUI (fallback) |
| paste-ready.txt | `<out>/<run_id>/` | Plain text | CLI | GUI (Copy All) |
| run_manifest.json | `<out>/<run_id>/` | JSON | CLI | GUI (fallback) |
| run.json | `<out>/<run_id>/` | JSON | GUI | GUI (primary) |
| stats.json | `<out>/<run_id>/` | JSON | CLI | - |
| gui_settings.json | `~/.insight-mine/` | JSON | GUI | GUI |
