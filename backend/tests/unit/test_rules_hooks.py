"""Tests for the install-time hook rules."""

import textwrap

from sightglass import _core
from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.hooks import build_backend, pth_import, setup_py
from sightglass.rules.pairing import FilePair, IndexedFile
from sightglass.rules.ruleset import RULES

SETUP = textwrap.dedent(
    """\
    from setuptools import setup

    setup(
        name="orbit-client",
        version="2.4.1",
    )
    """
)
IN_TREE = textwrap.dedent(
    """\
    [build-system]
    requires = []
    build-backend = "orbit_build:backend"
    backend-path = ["_build"]
    """
)
HATCH = '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'


def analysis(files: dict[str, tuple[str | None, str | None]]) -> PairAnalysis:
    """A pair with the given files as path -> (old text, new text); None means the file isn't on that side."""
    pairs, diffs, old_text, new_text = [], {}, {}, {}
    for path, (old, new) in files.items():
        status = "added" if old is None else "removed" if new is None else "same" if old == new else "changed"
        pairs.append(
            FilePair(
                path,
                status,
                None if old is None else IndexedFile(path, str(hash(old)), True),
                None if new is None else IndexedFile(path, str(hash(new)), True),
            )
        )
        diffs[path] = _core.diff_lines((old or "").encode(), (new or "").encode())
        if old is not None:
            old_text[path] = old
        if new is not None:
            new_text[path] = new
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        files=tuple(pairs),
        diffs=diffs,
        new_text=new_text,
        old_text=old_text,
    )


def test_registered() -> None:
    """The hook rules are in the full rule set."""
    assert {"hooks.setup_py", "hooks.build_backend", "hooks.pth_import"} <= {r.id for r in RULES}


def test_setup_py_code_change_fires_with_added_lines() -> None:
    """New code in setup.py is check, with the added lines as evidence."""
    new = SETUP.replace("from setuptools import setup\n", "from setuptools import setup\nimport os\n").replace(
        "version", "cmdclass=os.environ,\n    version"
    )
    [signal] = setup_py(analysis({"setup.py": (SETUP, new)}))
    assert signal.level == "check"
    assert signal.message == "setup.py, which runs when the sdist is built or installed, changed (lines 2, 6)"
    assert [(e.line_start, e.line_end) for e in signal.evidence] == [(2, 2), (6, 6)]


def test_setup_py_risky_call_is_high() -> None:
    """A change that adds a network, subprocess, exec or decoding call to setup.py is high."""
    new = SETUP.replace("from setuptools import setup\n", "from setuptools import setup\nimport subprocess\n")
    new += 'subprocess.run(["sh", "-c", "true"])\n'
    [signal] = setup_py(analysis({"setup.py": (SETUP, new)}))
    assert signal.level == "high"


def test_setup_py_version_bump_does_not_fire() -> None:
    """A change to literal values only, like the version, isn't a new hook."""
    assert setup_py(analysis({"setup.py": (SETUP, SETUP.replace("2.4.1", "2.5.0"))})) == []


def test_new_setup_py_fires() -> None:
    """An sdist that starts shipping setup.py is reported."""
    [signal] = setup_py(analysis({"setup.py": (None, SETUP)}))
    assert signal.message == "2.5.0 adds setup.py, which runs when the sdist is built or installed"
    assert signal.evidence[0].line_start == 1


def test_setup_py_without_diff_or_unchanged() -> None:
    """A changed setup.py with no diff points at the file; unchanged and removed setup.py don't fire."""
    changed = analysis({"setup.py": (SETUP, SETUP + "print('x')\n")})
    changed.diffs.clear()
    [signal] = setup_py(changed)
    assert signal.message.endswith("changed") and signal.evidence[0].line_start is None
    assert setup_py(analysis({"setup.py": (SETUP, SETUP)})) == []
    assert setup_py(analysis({"setup.py": (SETUP, None)})) == []
    assert setup_py(analysis({})) == []


def test_switch_to_in_tree_backend_and_backend_changes() -> None:
    """Moving to an in-tree backend is reported, and so is new code in the backend module."""
    backend = "def build_wheel(*a):\n    return 'x.whl'\n"
    result = build_backend(
        analysis(
            {
                "pyproject.toml": (HATCH, IN_TREE),
                "_build/orbit_build.py": (backend, backend + "import socket\n"),
            }
        )
    )
    assert [s.message for s in result] == [
        "pyproject.toml now builds with the in-tree backend `orbit_build:backend` from _build",
        "The in-tree build backend _build/orbit_build.py, which runs when the sdist is built, changed (line 3)",
    ]
    assert result[0].evidence[0].to_json() == {
        "file": "pyproject.toml",
        "side": "new",
        "before": "hatchling.build",
        "after": "orbit_build:backend",
    }


def test_in_tree_backend_in_a_new_pyproject_and_package_backend() -> None:
    """A new pyproject with an in-tree backend fires; a package backend's __init__.py is found."""
    config = IN_TREE.replace('"orbit_build:backend"', '"tools.backend"').replace('["_build"]', '["."]')
    configured, module = build_backend(
        analysis({"pyproject.toml": (None, config), "tools/backend/__init__.py": (None, "x = 1\n")})
    )
    assert configured.message == "pyproject.toml now builds with the in-tree backend `tools.backend` from ."
    assert configured.evidence[0].before is None
    assert module.message.startswith("The in-tree build backend tools/backend/__init__.py")


def test_build_backend_does_not_fire() -> None:
    """Standard backends, unchanged in-tree backends, literal-only edits and unparseable config don't fire."""
    backend = "VERSION = '1'\n"
    assert build_backend(analysis({"pyproject.toml": (HATCH, HATCH)})) == []
    assert (
        build_backend(analysis({"pyproject.toml": (IN_TREE, IN_TREE), "_build/orbit_build.py": (backend, backend)}))
        == []
    )
    literal_only = analysis(
        {"pyproject.toml": (IN_TREE, IN_TREE), "_build/orbit_build.py": (backend, "VERSION = '2'\n")}
    )
    assert build_backend(literal_only) == []
    assert build_backend(analysis({"pyproject.toml": (IN_TREE, "[build-system\n")})) == []
    unknown_old = analysis({"pyproject.toml": (IN_TREE, IN_TREE)})
    unknown_old.old_text.clear()
    assert build_backend(unknown_old) == []
    odd = '[build-system]\nbuild-backend = "b"\nbackend-path = "not-a-list"\n'
    assert build_backend(analysis({"pyproject.toml": (None, odd)})) == []
    assert build_backend(analysis({"pyproject.toml": (None, "build-system = 3\n")})) == []
    assert build_backend(analysis({})) == []


def test_pth_import_lines() -> None:
    """New import lines in a top-level .pth file are high; path lines and nested .pth files aren't."""
    old = "/opt/orbit/lib\n"
    new = old + "import orbit_hook; orbit_hook.install()\n"
    [signal] = pth_import(analysis({"orbit_client.pth": (old, new)}))
    assert signal.message == (
        "orbit_client.pth runs code at every Python startup: line 2 (`import orbit_hook; orbit_hook.install()`)"
    )
    assert pth_import(analysis({"orbit_client.pth": (None, "/opt/orbit/lib\n")})) == []
    assert pth_import(analysis({"orbit/data/x.pth": (None, "import os\n")})) == []
    [data] = pth_import(analysis({"*.data/purelib/hook.pth": (None, "import\tos\n")}))
    assert data.evidence[0].file == "*.data/purelib/hook.pth"
    unknown = analysis({"orbit_client.pth": (None, "import os\n")})
    unknown.new_text.clear()
    assert pth_import(unknown) == []
