"""Tests for the build backend, binaries and timing rules."""

from datetime import UTC, datetime, timedelta

import pytest

from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.build import backend_changed, compiled_without_source, generator
from sightglass.rules.pairing import FilePair, IndexedFile
from sightglass.rules.ruleset import RULES
from sightglass.rules.timing import long_gap, recent

WHEEL = "*.dist-info/WHEEL"
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def wheel_file(gen: str) -> str:
    """A WHEEL metadata file."""
    return f"Wheel-Version: 1.0\nGenerator: {gen}\nRoot-Is-Purelib: true\nTag: py3-none-any\n"


def facts(version: str, days_ago: float | None = None) -> ReleaseFacts:
    """A release published ``days_ago`` before NOW."""
    return ReleaseFacts(version, None if days_ago is None else NOW - timedelta(days=days_ago))


def base(**kwargs: object) -> PairAnalysis:
    """An orbit-client pair with the given fields."""
    fields: dict[str, object] = {"old": ReleaseFacts("2.4.1"), "new": ReleaseFacts("2.5.0")} | kwargs
    return PairAnalysis("pypi", "orbit-client", **fields)  # type: ignore[arg-type]


def test_registered() -> None:
    """The rules are in the full rule set."""
    ids = {r.id for r in RULES}
    assert {"build.backend_changed", "binaries.no_source", "timing.recent", "timing.long_gap"} <= ids


def test_backend_changed() -> None:
    """A different generator tool is check; a version bump of the same tool isn't."""
    [signal] = backend_changed(
        base(old_text={WHEEL: wheel_file("hatchling 1.25.0")}, new_text={WHEEL: wheel_file("setuptools (80.9.0)")})
    )
    assert (signal.level, signal.message) == ("check", "2.5.0 was built by setuptools; 2.4.1 was built by hatchling")
    assert signal.evidence[0].to_json() == {"file": WHEEL, "side": "new", "before": "hatchling", "after": "setuptools"}
    same = base(old_text={WHEEL: wheel_file("hatchling 1.25.0")}, new_text={WHEEL: wheel_file("Hatchling 1.27.0")})
    assert backend_changed(same) == []


@pytest.mark.parametrize("new", [None, "Wheel-Version: 1.0\n", "Wheel-Version: 1.0\nGenerator: \n"])
def test_backend_unknown(new: str | None) -> None:
    """No WHEEL file, or no Generator in it, is unknown and doesn't fire."""
    texts = {} if new is None else {WHEEL: new}
    assert backend_changed(base(old_text={WHEEL: wheel_file("hatchling 1.25.0")}, new_text=texts)) == []
    assert generator(texts) is None


def compiled(path: str, status: str = "added") -> FilePair:
    """A compiled file pair."""
    new = IndexedFile(path, "c" * 64, False, compiled=True)
    return FilePair(path, status, None if status == "added" else new, new)  # type: ignore[arg-type]


SO = "orbit/_speedups.cpython-314-x86_64-linux-gnu.so"


def test_new_compiled_file_without_source() -> None:
    """A new extension module with nothing that builds it in the sdist is check."""
    [signal] = compiled_without_source(base(files=(compiled(SO),), sdist_files=frozenset({"orbit/__init__.py"})))
    assert (signal.level, signal.message) == (
        "check",
        f"{SO} is a new compiled file with no matching source in the sdist",
    )
    many = tuple(compiled(f"orbit/m{i}.so") for i in range(6))
    [grouped] = compiled_without_source(base(files=many, sdist_files=frozenset()))
    assert grouped.message.startswith("6 new compiled files have no matching source in the sdist: orbit/m0.so")
    assert grouped.message.endswith("and 1 more") and len(grouped.evidence) == 6


@pytest.mark.parametrize(
    "sdist",
    [
        {"src/orbit/_speedups.c"},
        {"orbit/_speedups.pyx"},
        {"Cargo.toml", "src/lib.rs"},
        {"CMakeLists.txt"},
    ],
)
def test_compiled_file_with_source_does_not_fire(sdist: set[str]) -> None:
    """A same-stem native source or a native build manifest accounts for the compiled file."""
    assert compiled_without_source(base(files=(compiled(SO),), sdist_files=frozenset(sdist))) == []


def test_compiled_skips() -> None:
    """Changed compiled files, non-compiled binaries and an unknown sdist don't fire."""
    image = FilePair("orbit/logo.png", "added", None, IndexedFile("orbit/logo.png", "d" * 64, False))
    assert compiled_without_source(base(files=(compiled(SO, "changed"), image), sdist_files=frozenset())) == []
    assert compiled_without_source(base(files=(compiled(SO),))) == []


def test_recent_release() -> None:
    """A release from 2 days ago is check, with dates; under a day says so."""
    [signal] = recent(base(new=facts("2.5.0", 2), analyzed_at=NOW))
    assert signal.message == "2.5.0 was published on 2026-10-15, 2 days before this analysis (2026-10-17)"
    assert (
        recent(base(new=facts("2.5.0", 0.5), analyzed_at=NOW))[0].message.split(", ")[1].startswith("less than a day")
    )
    assert "1 day before" in recent(base(new=facts("2.5.0", 1.2), analyzed_at=NOW))[0].message


@pytest.mark.parametrize(("days_ago", "now"), [(8, NOW), (-1, NOW), (None, NOW), (2, None)])
def test_recent_does_not_fire(days_ago: float | None, now: datetime | None) -> None:
    """Older, future-dated and unknown times don't fire."""
    assert recent(base(new=facts("2.5.0", days_ago), analyzed_at=now)) == []


def test_long_gap() -> None:
    """A release over a year after the previous one is a note."""
    [signal] = long_gap(base(old=facts("2.4.1", 500), new=facts("2.5.0", 0)))
    assert signal.level == "note"
    assert signal.message == "2.5.0 came 500 days after 2.4.1 (2025-06-04 to 2026-10-17)"


def test_long_gap_respects_cadence() -> None:
    """A project that releases yearly doesn't fire at a year; one that releases monthly does."""
    yearly = tuple(facts(f"2.{i}.0", 400 * (5 - i)) for i in range(1, 4))
    assert long_gap(base(old=facts("2.4.1", 400), new=facts("2.5.0", 0), history=yearly)) == []
    monthly = tuple(facts(f"2.{i}.0", 400 + 30 * (4 - i)) for i in range(1, 4))
    assert len(long_gap(base(old=facts("2.4.1", 400), new=facts("2.5.0", 0), history=monthly))) == 1


@pytest.mark.parametrize(("old", "new"), [(100, 0), (None, 0), (500, None)])
def test_long_gap_does_not_fire(old: float | None, new: float | None) -> None:
    """Short gaps and unknown dates don't fire."""
    assert long_gap(base(old=facts("2.4.1", old), new=facts("2.5.0", new))) == []
