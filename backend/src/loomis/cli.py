"""Command-line entry point: ``loomis <command>``.

Stdlib argparse keeps the base dependency-free. Today only ``serve`` (run the
API) and ``version`` exist; ``backup`` and friends arrive with M1.
"""

from __future__ import annotations

import argparse

from . import __version__
from .config import get_settings


def _serve(_: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    # import string so uvicorn can manage the app lifecycle / reload
    uvicorn.run(
        "loomis.app:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
    )
    return 0


def _version(_: argparse.Namespace) -> int:
    print(f"loomis {__version__}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loomis", description="Loomis backend CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the daemon + FastAPI API")
    p_serve.set_defaults(func=_serve)

    p_version = sub.add_parser("version", help="print version")
    p_version.set_defaults(func=_version)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
