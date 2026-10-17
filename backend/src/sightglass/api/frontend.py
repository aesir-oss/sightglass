"""Serving the built frontend from the API process, so production is one service.

Files under ``assets/`` are served as they are; any other non-API path gets ``index.html``, and the React router
takes it from there. Unknown ``/api`` paths stay JSON 404s.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sightglass.log import get_logger

log = get_logger(__name__)

FRONTEND_DIR_ENV = "SIGHTGLASS_FRONTEND_DIR"
# backend/src/sightglass/api/frontend.py -> repository root -> frontend/dist
DEFAULT_DIR = Path(__file__).resolve().parents[4] / "frontend" / "dist"


def frontend_dir() -> Path:
    """``SIGHTGLASS_FRONTEND_DIR``, or ``frontend/dist`` in the repository."""
    return Path(os.environ.get(FRONTEND_DIR_ENV) or DEFAULT_DIR)


def mount_frontend(app: FastAPI, root: Path | None = None) -> bool:
    """Serve the built frontend in ``root`` from ``app``; returns False (API only) when it hasn't been built."""
    root = root or frontend_dir()
    index = root / "index.html"
    if not index.is_file():
        log.info("frontend_not_built", path=str(root))
        return False
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{page:path}", include_in_schema=False)
    def page(page: str) -> FileResponse:
        if page == "api" or page.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (root / page).resolve()
        if page and candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
