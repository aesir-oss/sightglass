"""Tests for sightglass.api.openapi."""

import json

import pytest

from sightglass.api.openapi import main, openapi_json


def test_schema_lists_health_route_with_operation_id() -> None:
    """The exported schema includes each route under its stable operation id."""
    schema = json.loads(openapi_json())

    assert schema["paths"]["/api/health"]["get"]["operationId"] == "getHealth"
    assert "Health" in schema["components"]["schemas"]


def test_schema_text_is_stable() -> None:
    """Two exports are byte-identical, so the committed file only changes when the API does."""
    assert openapi_json() == openapi_json()
    assert openapi_json().endswith("}\n")


@pytest.mark.parametrize("argv", [[], ["a.json", "b.json"]])
def test_main_rejects_wrong_argument_count(argv: list[str]) -> None:
    """Anything other than exactly one output path is a usage error."""
    assert main(argv) == 2
