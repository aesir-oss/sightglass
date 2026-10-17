"""Fixtures shared by unit and integration tests."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Restore structlog's defaults so one test's logging config can't leak into another."""
    yield
    structlog.reset_defaults()


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes() -> Callable[[str], bytes]:
    """Read a file from tests/fixtures by relative path."""
    return lambda name: (FIXTURES / name).read_bytes()
