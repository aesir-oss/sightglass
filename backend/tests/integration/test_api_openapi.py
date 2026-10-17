"""Integration tests for writing the OpenAPI schema to disk."""

from pathlib import Path

import pytest

from sightglass.api.openapi import main, openapi_json


@pytest.mark.integration
def test_main_writes_schema_creating_parent_dirs(tmp_path: Path) -> None:
    """The schema is written to the given path, creating missing directories."""
    out = tmp_path / "nested" / "openapi.json"

    assert main([str(out)]) == 0
    assert out.read_text() == openapi_json()
