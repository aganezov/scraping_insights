from .args import build_parser, resolve_settings  # noqa: F401

__all__ = ["build_parser", "resolve_settings", "run_collect", "main"]


def run_collect(*args, **kwargs):
    from .orchestrator import run_collect as _run_collect
    return _run_collect(*args, **kwargs)


def main(argv=None):
    from .main import main as _main
    return _main(argv)
