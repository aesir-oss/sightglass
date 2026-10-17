"""FastAPI application factory."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from sightglass import __version__


class Health(BaseModel):
    """Liveness response."""

    status: Literal["ok"]
    version: str


def create_app() -> FastAPI:
    """Build the Sightglass API application.

    Returns:
        The FastAPI app with every route registered.
    """
    app = FastAPI(title="Sightglass", version=__version__)

    @app.get("/api/health", operation_id="getHealth")
    def health() -> Health:
        return Health(status="ok", version=__version__)

    return app
