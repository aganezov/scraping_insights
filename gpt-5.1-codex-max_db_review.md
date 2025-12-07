# Database / Cache Usage (gpt-5.1-codex-max)

## High-level picture
- Only database is a **SQLite cache** to remember seen `(platform,id)` pairs and skip them on later runs.
- All content/results live in files under the chosen `--out` directory (JSON/JSONL/TXT). No ORM, no other DB engines.
- GUI reuses those files and produces `run.json` for UI, plus a small settings JSON in the user home dir.

## SQLite cache (dedupe across runs)
- **Location:** user-supplied `--cache /path/to/cache.sqlite`; empty string disables; no default path.
- **Module:** `src/insight_mine/utils/cache.py`
- **Open/init:** `open_db(path)` creates parent dirs, applies schema and pragmas (`WAL`, `synchronous=NORMAL`).
- **Schema:** single table `seen(platform TEXT NOT NULL, id TEXT NOT NULL, first_seen_ts INTEGER NOT NULL, PRIMARY KEY(platform,id))`.
- **Stored keys (examples):**
  - YouTube video: `("youtube", "<video_id>")`
  - YouTube comment: `("youtube", "<comment_id>")` with `context["videoId"]` linking back
  - Reddit post: `("reddit", "t3_<post_id>")`
  - Reddit comment: `("reddit", "t1_<comment_id>")` with `context["post_id"]` linking back

### Cache read path (skipping already-seen)
- **Entry:** `run_collect()` in `src/insight_mine/cli/orchestrator.py`.
- **Gate:** requires `--cache` AND `not --refresh`.
- **Timing in pipeline:** after fetch → serialize → variety guard → optional text dedupe; **before** optional sampling and **before** writing any outputs.
- **Operation:** loads entire `seen` set into memory, filters out items whose `(platform,id)` is present, increments `dropped_by_cache`.
- **Effect on outputs:** dropped items never reach `raw.jsonl`, manifests, or stats.

### Cache write path (recording this run)
- **Entry:** same `run_collect()` near the end.
- **Gate:** any truthy `--cache` (even if `--refresh` skipped the read, writes still happen).
- **Timing:** after outputs and `latest` symlink are created.
- **Operation:** `upsert_many()` bulk `INSERT OR IGNORE` with `first_seen_ts = time.time()`; one commit per run.
- **Durability/perf:** WAL + synchronous=NORMAL; safe for single-writer CLI usage; no retry logic.

### CLI switches impacting cache
- `--cache PATH`: turns cache on; creates DB if missing.
- `--refresh`: bypasses the read, but still writes new items (good for force-processing while growing the cache).
- `--dedupe`: separate text/content dedupe step that runs **before** cache check.
- `--sample N`: random sampling occurs **after** cache filtering, so cache only receives kept items.

## File-based persistence (non-DB)
- **Run directory layout:** `<out>/<timestamp>/`
  - `raw.jsonl` — all kept items (flat list of dicts).
  - `paste-ready.txt` — human/LLM-friendly snippets.
  - `run_manifest.json` — metadata: topic, since, preset, effective knobs (including cache path/refresh), connector availability, counts, dropped_by_cache, sampled.
  - `stats.json` — per-connector telemetry counters.
  - `latest` symlink at `<out>/latest` points to most recent run dir.
- **Writers:** `write_outputs()` in `src/insight_mine/cli/output.py`.
- **GUI post-processing:** `src/insight_mine/guis/pywebview/storage.py`
  - Builds `run.json` (UI format) and `run.log` in the run dir via `build_ui_run()`.
  - Maps flat JSONL into parent-with-comments structure; attaches transcripts when available.
  - Keeps GUI settings at `~/.insight-mine/gui_settings.json` (out_dir/env path).

## Invocation flow (where cache hooks in)
1) Connectors fetch (YouTube API, Reddit API/Scrape, optional transcripts).
2) Items → dict (`as_dict`) → variety guard → optional text dedupe.
3) **Cache read (if enabled, unless refresh):** drop already-seen.
4) Optional sampling.
5) Write outputs (`raw.jsonl`, `paste-ready.txt`, `run_manifest.json`, `stats.json`, symlink).
6) **Cache write (if enabled):** upsert kept `(platform,id)` pairs.

## Observability / what to inspect
- Cache DB: inspect `seen` table with `sqlite3 <path> 'select * from seen limit 20;'`.
- Run results: inspect `<out>/latest` or specific `<out>/<run_id>/raw.jsonl`.
- Cache impact: `run_manifest.json` field `dropped_by_cache` shows how many items were skipped.

## Not present
- No migrations, no multi-table schemas, no background DB jobs, no ORM.
- No per-user or auth data stored; only content items and manifest metadata.

