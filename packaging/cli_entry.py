"""PyInstaller entrypoint that calls the packaged CLI."""

from insight_mine.cli.main import main


if __name__ == "__main__":
    raise SystemExit(main())