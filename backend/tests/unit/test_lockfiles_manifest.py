"""Tests for reading a workspace's declared dependencies."""

from sightglass.lockfiles.manifest import parse_manifest

PIXI_TOML = b"""
[workspace]
name = "orbit-platform"

[dependencies]
Kestrel-Core = ">=1.2"

[pypi-dependencies]
Heron_SDK = { version = ">=3", extras = ["fast"] }

[target.win-64.dependencies]
tinted = "*"

[feature.test.dependencies]
probe = "*"

[feature.docs.pypi-dependencies]
quill = "*"

[environments]
test = ["test"]
docs = { features = ["docs"], no-default-feature = true }
"""


def test_pixi_toml_features_and_environments() -> None:
    """Top-level tables are the default feature, target tables count for it, and environments combine features."""
    manifest = parse_manifest("pixi.toml", PIXI_TOML)
    assert manifest is not None
    assert manifest.direct("default") == {("conda", "kestrel-core"), ("pypi", "heron-sdk"), ("conda", "tinted")}
    assert ("conda", "probe") in manifest.direct("test") and ("conda", "kestrel-core") in manifest.direct("test")
    assert manifest.direct("docs") == {("pypi", "quill")}
    assert manifest.features_of("unknown") == {"default"}


def test_pyproject_with_pixi_project_extras_and_groups() -> None:
    """[tool.pixi], PEP 621 dependencies and extras, and PEP 735 groups with include-group all declare."""
    content = b"""
[project]
name = "orbit-platform"
dependencies = ["Orbit_Client>=2.4", "!!bad"]

[project.optional-dependencies]
fast = ["quickhash"]

[dependency-groups]
lint = ["checker"]
dev = [{ include-group = "Lint" }, "probe", { include-group = "dev" }]

[tool.pixi.dependencies]
python = "3.14.*"

[tool.pixi.environments]
dev = ["dev", "fast"]
"""
    manifest = parse_manifest("pyproject.toml", content)
    assert manifest is not None
    assert manifest.direct("default") == {("pypi", "orbit-client"), ("conda", "python")}
    assert manifest.direct("dev") == {
        ("pypi", "orbit-client"),
        ("conda", "python"),
        ("pypi", "quickhash"),
        ("pypi", "checker"),
        ("pypi", "probe"),
    }


def test_plain_pyproject_and_unreadable_files() -> None:
    """A pyproject.toml without pixi still declares its dependencies; unreadable TOML gives None."""
    plain = parse_manifest("pyproject.toml", b'[project]\nname = "x"\ndependencies = ["kestrel"]\n')
    assert plain is not None and plain.direct("default") == {("pypi", "kestrel")}
    assert parse_manifest("pixi.toml", b"[workspace") is None
    assert parse_manifest("pixi.toml", b"\xff\xfe") is None
