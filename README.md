# insight-mine

A small personal-use CLI that gathers Reddit and YouTube content for a topic and writes:
- `out/<timestamp>/raw.jsonl` – normalized items (one JSON per line)
- `out/<timestamp>/paste-ready.txt` – short snippets + URLs for easy ChatGPT paste

## Fresh macOS install

First-time requirements on a new Mac:
- Xcode Command Line Tools: `xcode-select --install`
- `git` (usually installed with the command line tools)
- `uv` (simplest route: `brew install uv`)

Then:

```bash
git clone <your-github-url>
cd scraping_insights_cursor
make setup-gui
cp .env.example .env
# fill the keys you need in .env
make run-gui ENV_FILE=.env
```

Notes:
- You do not need to install Python manually; `uv` will install Python 3.11 for the project.
- The simplest day-to-day source-checkout flow is `make run-gui ENV_FILE=.env`.
- If you only want CLI usage, `uv sync` is enough; the GUI needs `uv sync --extra gui`.

## Updating a source checkout

Once the app is already installed from a git checkout:
- In the app: `More -> Update source checkout`
- In terminal: `make update-source-gui`

The in-app updater only runs on a clean git checkout. It does:
- `git pull --ff-only`
- `uv sync --extra gui`
- optional app restart

## Quickstart

```bash
uv python install 3.11
uv venv --python 3.11
source .venv/bin/activate
uv sync
# GUI work: uv sync --extra gui
# Packaging: uv sync --extra gui --extra packaging

# set env (or copy .env.example and export)
export YOUTUBE_API_KEY=...
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USER_AGENT="insight-mine/0.1 (by u/yourname)"
```

Run:

```bash
insight-mine collect --topic "your topic" --since 2025-10-01 --subreddits "r/AskReddit,r/SomeSub" --reddit-limit 30 --yt-videos 20
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

Run tests with `uv`:

```bash
uv run pytest
```

GUI smoke and free-only E2E:

```bash
cp .env.example .env
# fill YOUTUBE_API_KEY in .env for the real path

make gui-smoke
make gui-e2e-free ENV_FILE=.env
make run-gui ENV_FILE=.env
```

`make gui-smoke` is deterministic and local: it drives the live pywebview GUI against a fake collector and writes `tmp/gui-smoke-report.json`.

`make gui-e2e-free` drives the real GUI and real CLI with YouTube enabled, Reddit disabled, and paid transcript fallback forced off. It writes `tmp/gui-e2e-free-report.json` and uses `tmp/gui-e2e-free-out` for run artifacts.

## Notes

YouTube: only titles/descriptions and top-level comments (no transcripts).

Reddit: search posts in selected subreddits, plus a few top comments per post.

X/Twitter: placeholder only; add once you have API access.

## macOS app packaging

Prereqs on macOS (matching target arch): `uv sync --extra gui --extra packaging`.

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
