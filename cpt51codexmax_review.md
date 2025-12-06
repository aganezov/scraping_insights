## Code Review — scraping_insights_cursor (gpt-5.1-codex-max)

### High-Severity
- **Secrets committed and bundled**: `packaging/seed_settings.env` contains real-looking API keys/tokens and is packaged via PyInstaller datas, so any build ships these secrets. They also appear in the repo history. Rotate/revoke immediately and remove from VCS + build inputs.
- **Secrets logged in cleartext**: CLI and GUI print sensitive env vars (`YOUTUBE_API_KEY`, `YTTI_API_TOKEN`, `YTTI_WS_USER`, `YTTI_WS_PASS`) to stdout/UI logs. This leaks credentials to console/log files. Mask presence instead of values.

### Medium
- **Transcript fetching robustness**: `ytti.collect` uses single retry handling (429 only) with 30s timeout; other failures just warn and continue. GUI batch fetch swallows per-video errors and can leave progress clamped at 90% if transcripts stall. Surface errors to UI and bound retries/backoff.
- **Reddit scraping resilience**: Basic 429 handling and generic UA; no exponential backoff for 5xx, so can hammer endpoints or fail under rate limits. Consider jittered backoff and clearer retry budgets.
- **Progress completion ambiguity**: GUI clamps progress when transcripts pending; if they fail silently, bars can remain below 100% without user-facing error.

### Low / Code Quality
- **Testing gaps**: Tests only cover connector status toggles and a lang helper. No coverage for main CLI `collect`, cache/dedupe, transcript flows, or GUI bridge env/output-dir handling. Add integration tests around CLI happy-path and disabled connectors, plus unit tests for env resolution and cache.
- **Logging of paths**: GUI logs full env path; acceptable, but ensure no sensitive content in paths.

### Suggested Remediations
- Remove `packaging/seed_settings.env` from repo/bundles; replace with placeholders; rotate exposed credentials.
- Mask secrets in CLI/GUI logs (log presence/length only).
- Add retry/backoff and explicit error surfacing for transcript and scraping calls; ensure progress completes or reports failure.
- Expand automated tests for CLI argument resolution, dedupe/cache behavior, and transcript error paths.

