"""Export the API's OpenAPI schema without starting a server.

Run as ``python -m sightglass.api.openapi <output path>``; the frontend generates its TypeScript types from the file.
"""

import json
import sys
from pathlib import Path

from sightglass.api.app import create_app
from sightglass.log import get_logger

log = get_logger(__name__)


def openapi_json() -> str:
    """Render the OpenAPI schema as stable, diff-friendly JSON.

    Returns:
        The schema with sorted keys, two-space indents and a trailing newline.
    """
    return json.dumps(create_app(serve_frontend=False).openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the OpenAPI schema to the path given as the only argument.

    Args:
        argv: Command-line arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code: 0 on success, 2 on a usage error.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        log.error("usage", expected="python -m sightglass.api.openapi <output path>", got=args)
        return 2
    out = Path(args[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(openapi_json())
    log.info("openapi_written", path=str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
