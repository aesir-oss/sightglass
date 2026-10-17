"""FastAPI application factory."""

import os
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from sightglass import __version__
from sightglass.api import files, pairs, releases
from sightglass.api.frontend import mount_frontend
from sightglass.log import configure_logging

LOG_LEVEL_ENV = "SIGHTGLASS_LOG_LEVEL"


class Health(BaseModel):
    """Liveness response."""

    status: Literal["ok"]
    version: str


def create_app(*, serve_frontend: bool = True) -> FastAPI:
    """Build the Sightglass API application.

    Args:
        serve_frontend: Also serve the built frontend, when ``frontend/dist`` (or ``SIGHTGLASS_FRONTEND_DIR``) exists.

    Returns:
        The FastAPI app with every route registered.
    """
    app = FastAPI(title="Sightglass", version=__version__)

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(status="ok", version=__version__)

    # Releases first: its fixed path segment would otherwise match the pair route's version.
    app.include_router(releases.router)
    app.include_router(pairs.router)
    app.include_router(files.router)
    # Last: its catch-all route must not shadow the API.
    if serve_frontend:
        mount_frontend(app)
    return app


def serve() -> FastAPI:
    """The app as served by uvicorn: logging configured first, so every line is structured JSON."""
    configure_logging(os.environ.get(LOG_LEVEL_ENV, "info"))
    return create_app()
