# insight-mine

A small personal-use CLI that gathers Reddit and YouTube content for a topic and writes:
- `out/<timestamp>/raw.jsonl` – normalized items (one JSON per line)
- `out/<timestamp>/paste-ready.txt` – short snippets + URLs for easy ChatGPT paste

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e .
# or: pip install -e ".[test]" if you add extras

# set env (or copy .env.example and export)
export YOUTUBE_API_KEY=...
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USER_AGENT="insight-mine/0.1 (by u/yourname)"
```

Run:

```bash
insight-mine collect --topic "your topic" --since 2025-10-01 --subreddits "r/AskReddit,r/SomeSub" --limit 30 --yt-videos 20
```

If some API keys are missing, the CLI will list disabled connectors and proceed with the ones enabled.

Optional: If you prefer Keychain, install keyring (already a dependency) and set secrets via:

```bash
python -m keyring set insight-mine YOUTUBE_API_KEY
python -m keyring set insight-mine REDDIT_CLIENT_ID
python -m keyring set insight-mine REDDIT_CLIENT_SECRET
```

The app checks env first, then Keychain.

## Development

Python 3.11+

pytest to run tests:

```bash
pytest
```

## Notes

YouTube: only titles/descriptions and top-level comments (no transcripts).

Reddit: search posts in selected subreddits, plus a few top comments per post.

X/Twitter: placeholder only; add once you have API access.

## macOS app packaging

Prereqs on macOS (matching target arch): `python -m pip install -U pip` then `pip install -e ".[gui,packaging]"`.

Workflow:
- Bump version: `echo 0.1.0 > packaging/VERSION`
- macOS icon source: `packaging/icon.png` (square, flat); regen .icns/iconset from it via `make icon` (only rebuilds placeholder art if the PNG is missing or `--force-placeholder` is used).
- UI app icon (1024x2014 PNG + SVG): `src/insight_mine/guis/pywebview/assets/app-icon-1024x2014.*`
- Build CLI and GUI app bundle: `make app` (outputs `dist/Insight Mine.app` and a versioned copy `dist/Insight Mine-<version>.app`)
- First run (shows logs): `./dist/Insight\\ Mine.app/Contents/MacOS/Insight\\ Mine`
- Normal run: `open "./dist/Insight Mine.app"`

Env handling:
- GUI uses `~/"Library/Application Support/InsightMine/settings.env"` (auto-created on first launch).
- To bundle initial values, edit `packaging/seed_settings.env` before `make app` (copied on first run if no settings exist).
