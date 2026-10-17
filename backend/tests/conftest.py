"""Fixtures shared by unit and integration tests."""

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Restore structlog's defaults so one test's logging config can't leak into another."""
    yield
    structlog.reset_defaults()
