"""Build rules: the tool that built the wheel, and compiled files with no source in the sdist."""

from email.parser import HeaderParser
from pathlib import PurePosixPath

from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal

WHEEL_FILE = "*.dist-info/WHEEL"
# Generators that are one backend under another name: bdist_wheel was the wheel package's command run by setuptools.
GENERATOR_ALIASES = {"bdist_wheel": "setuptools"}
# Source extensions that compile to extension modules, matched by file stem.
NATIVE_SOURCES = frozenset({".c", ".cc", ".cpp", ".cxx", ".pyx", ".rs", ".go", ".f", ".f90", ".m", ".mm", ".zig"})
# Build manifests whose presence accounts for compiled files whose names don't follow their sources.
NATIVE_MANIFESTS = frozenset({"Cargo.toml", "CMakeLists.txt", "meson.build", "go.mod", "build.zig"})
# Files named in a message; the evidence lists every one.
NAMED = 5


def generator(texts: dict[str, str]) -> str | None:
    """The backend named in a wheel's ``WHEEL`` ``Generator`` header, without its version, with aliases resolved."""
    text = texts.get(WHEEL_FILE)
    value = HeaderParser().parsestr(text).get("Generator") if text is not None else None
    if not value or not value.split():
        return None
    name = value.split()[0].lower()
    return GENERATOR_ALIASES.get(name, name)


@RULES.rule("build.backend_changed", 2, "Build backend changed, from the WHEEL Generator")
def backend_changed(analysis: PairAnalysis) -> list[Signal]:
    """Report a wheel built by a different tool than the previous release's, ignoring version changes."""
    before, after = generator(analysis.old_text), generator(analysis.new_text)
    if before is None or after is None or before == after:
        return []
    return [
        Signal(
            "build.backend_changed",
            "check",
            f"{analysis.new.version} was built by {after}; {analysis.old.version} was built by {before}",
            (Evidence(WHEEL_FILE, side="new", before=before, after=after),),
        )
    ]


def _module_stem(path: str) -> str:
    return PurePosixPath(path).name.split(".", 1)[0]


def _has_source(compiled: str, sdist_files: frozenset[str]) -> bool:
    stem = _module_stem(compiled)
    for path in sdist_files:
        p = PurePosixPath(path)
        if p.name in NATIVE_MANIFESTS:
            return True
        if p.suffix in NATIVE_SOURCES and p.stem == stem:
            return True
    return False


@RULES.rule("binaries.no_source", 1, "New compiled files with no corresponding source in the sdist")
def compiled_without_source(analysis: PairAnalysis) -> list[Signal]:
    """Report compiled files new in this release when the sdist has no source or build manifest for them.

    A source is a native file (``.c``, ``.pyx``, ``.rs`` and so on) with the same stem as the compiled module, or a
    build manifest such as ``Cargo.toml`` or ``CMakeLists.txt``, whose outputs needn't share a source's name.
    """
    if analysis.sdist_files is None:
        return []
    new = [
        p.path
        for p in analysis.files
        if p.status == "added"
        and p.new is not None
        and p.new.compiled
        and not _has_source(p.path, analysis.sdist_files)
    ]
    if not new:
        return []
    named = ", ".join(new[:NAMED]) + (f", and {len(new) - NAMED} more" if len(new) > NAMED else "")
    message = (
        f"{new[0]} is a new compiled file with no matching source in the sdist"
        if len(new) == 1
        else f"{len(new)} new compiled files have no matching source in the sdist: {named}"
    )
    return [Signal("binaries.no_source", "check", message, tuple(Evidence(path, side="new") for path in new))]
