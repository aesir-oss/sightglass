"""Serve the API with uvicorn: ``python -m sightglass.api [--reload] [--port N]``.

uvicorn's own logging setup is turned off, so its records go through the same structured JSON output as the app's.
"""

import argparse
import sys
from collections.abc import Sequence

import uvicorn


def main(argv: Sequence[str] | None = None) -> int:
    """Run the server until interrupted."""
    parser = argparse.ArgumentParser(prog="sightglass.api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on code changes, for development")
    args = parser.parse_args(argv)
    uvicorn.run(
        "sightglass.api.app:serve",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
