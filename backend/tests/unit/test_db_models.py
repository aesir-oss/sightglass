"""Tests for sightglass.db.models that need no database."""

from sqlalchemy.dialects.postgresql import JSONB

from sightglass.db.models import Base


def test_phase_one_tables_exist() -> None:
    """The schema has the design's phase 1 tables and nothing else yet."""
    assert set(Base.metadata.tables) == {
        "package",
        "release",
        "artifact",
        "attestation",
        "blob",
        "file",
        "source_snapshot",
        "analysis",
        "signal",
        "ownership_snapshot",
    }


def test_evidence_and_bundles_are_jsonb() -> None:
    """Structured evidence is stored as JSONB so it can be queried."""
    tables = Base.metadata.tables
    assert isinstance(tables["signal"].c.evidence.type, JSONB)
    assert isinstance(tables["attestation"].c.bundle.type, JSONB)
    assert isinstance(tables["ownership_snapshot"].c.roles.type, JSONB)


def test_timestamps_are_timezone_aware() -> None:
    """Every timestamp column stores a time zone."""
    for table in Base.metadata.tables.values():
        for column in table.c:
            if column.type.python_type.__name__ == "datetime":
                assert column.type.timezone, f"{table.name}.{column.name}"  # type: ignore[attr-defined]
