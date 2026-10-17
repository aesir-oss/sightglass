"""Tests for sightglass.log."""

import io
import json

import pytest

from sightglass.log import configure_logging, get_logger


def test_json_output_has_event_level_logger_and_timestamp() -> None:
    """JSON mode writes one parseable object per line with the standard fields."""
    stream = io.StringIO()
    configure_logging(stream=stream)

    get_logger("sightglass.test").info("fetched", package="orbit-client")

    record = json.loads(stream.getvalue())
    assert record["event"] == "fetched"
    assert record["level"] == "info"
    assert record["logger"] == "sightglass.test"
    assert record["package"] == "orbit-client"
    assert record["timestamp"].endswith("Z")


def test_key_value_output() -> None:
    """Key=value mode renders fields without JSON quoting of the line."""
    stream = io.StringIO()
    configure_logging(json=False, stream=stream)

    get_logger("sightglass.test").warning("slow", seconds=3)

    line = stream.getvalue()
    assert "event='slow'" in line
    assert "seconds=3" in line
    assert "level='warning'" in line


def test_level_filters_lower_levels() -> None:
    """Messages below the configured level are dropped."""
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)

    log = get_logger("sightglass.test")
    log.info("hidden")
    log.error("shown")

    lines = stream.getvalue().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["shown"]


def test_unknown_level_raises() -> None:
    """An unknown level name is rejected with the valid names in the message."""
    with pytest.raises(ValueError, match="expected one of debug"):
        configure_logging("verbose")
