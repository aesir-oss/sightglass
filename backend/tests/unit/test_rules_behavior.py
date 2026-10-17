"""Tests for the import-time code rule and its static-analysis helpers."""

import ast
import textwrap

import pytest

from sightglass import _core
from sightglass.rules import pyast
from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.behavior import import_time_code
from sightglass.rules.pairing import FilePair, IndexedFile
from sightglass.rules.ruleset import RULES

INIT = "orbit/__init__.py"
OLD = '''"""Orbit client."""

import logging

from orbit.client import Client

__version__ = "2.4.1"
log = logging.getLogger(__name__)
'''


def changed(old: str, new: str, path: str = INIT) -> PairAnalysis:
    """A pair where ``path`` changed from ``old`` to ``new``, with its real line diff."""
    pair = FilePair(path, "changed", IndexedFile(path, "a" * 64, True), IndexedFile(path, "b" * 64, True))
    diff = _core.diff_lines(old.encode(), new.encode())
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        files=(pair,),
        diffs={path: diff},
        new_text={path: new},
    )


def test_registered() -> None:
    """The rule is in the full rule set."""
    assert "behavior.import_time_code" in {r.id for r in RULES}


def test_added_call_at_module_level_fires() -> None:
    """A new module-level call is high, naming the resolved function and its line."""
    new = OLD.replace("import logging\n", "import logging\nimport urllib.request as req\n") + (
        "req.urlopen('https://telemetry.example.net/ping')\n"
    )
    [signal] = import_time_code(changed(OLD, new))
    assert signal.level == "high"
    assert signal.message == (
        "New module-level code in orbit/__init__.py runs at import: line 10 calls `urllib.request.urlopen`"
    )
    assert [e.to_json() for e in signal.evidence] == [{"file": INIT, "line_start": 10, "line_end": 10, "side": "new"}]


def test_several_statements_and_multiline_ranges() -> None:
    """Calls inside control flow and class-free blocks count; multi-line statements give a range."""
    new = OLD + textwrap.dedent(
        """\
        try:
            from subprocess import run
            run(["sh", "-c", "id"])
        except ImportError:
            pass
        _token = __import__("os").environ.get(
            "ORBIT_TOKEN"
        )
        """
    )
    [signal] = import_time_code(changed(OLD, new))
    assert signal.message == "2 new module-level statements in orbit/__init__.py run at import (lines 9-13, 14-16)"
    assert [(e.line_start, e.line_end) for e in signal.evidence] == [(9, 13), (14, 16)]


@pytest.mark.parametrize(
    "added",
    [
        "def helper():\n    return open('/etc/hosts').read()\n",
        "class Config:\n    pass\n",
        "import os\nfrom orbit import util\n",
        "__all__ = ['Client']\nTIMEOUT = 30\n",
        "T = TypeVar('T')\n",
        "from importlib.metadata import version\n__version__ = version('orbit-client')\n",
        "callback = lambda: os.system('id')\n",
        "if TYPE_CHECKING:\n    from orbit.types import Token\n",
    ],
)
def test_definitions_and_plain_values_do_not_fire(added: str) -> None:
    """Defs, classes, imports, plain values, allowed setup calls and lambdas don't fire."""
    prefix = "from typing import TYPE_CHECKING, TypeVar\nimport os\n"
    assert import_time_code(changed(OLD, OLD + prefix + added)) == []


def test_decorators_and_defaults_run_at_definition_time() -> None:
    """Top-level defs are excluded, decorators too; nested in other statements, decorators and defaults are calls."""
    assert import_time_code(changed(OLD, OLD + "@register(sink())\ndef hook(): ...\n")) == []
    calls = list(pyast.calls(ast.parse("if True:\n    @register(sink())\n    def hook(x=probe()): beacon()\n")))
    assert sorted(ast.unparse(c) for c in calls) == ["probe()", "register(sink())", "sink()"]


def test_unchanged_calls_do_not_fire() -> None:
    """A call that was already there doesn't fire when other lines change."""
    old = OLD + "start_background_sync()\n"
    new = old.replace('__version__ = "2.4.1"', '__version__ = "2.5.0"')
    assert import_time_code(changed(old, new)) == []


def test_new_init_file_fires_without_a_diff() -> None:
    """In a new file every line is added, even when no diff was computed."""
    path = "orbit/plugins/__init__.py"
    pair = FilePair(path, "added", None, IndexedFile(path, "c" * 64, True))
    analysis = PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        files=(pair,),
        new_text={path: "load_plugins()\n"},
    )
    [signal] = import_time_code(analysis)
    assert signal.message.endswith("line 1 calls `load_plugins`")


def test_unknown_or_unparseable_inputs_do_not_fire() -> None:
    """No text, a changed file too large to diff, other modules and syntax errors are skipped."""
    no_text = changed(OLD, OLD + "beacon()\n")
    no_text.new_text.clear()
    too_large = changed(OLD, OLD + "beacon()\n")
    too_large.diffs[INIT] = _core.diff_lines(b"x" * 20, b"y", _core.DiffLimits(max_size=10))
    assert too_large.diffs[INIT].too_large
    no_diff = changed(OLD, OLD + "beacon()\n")
    no_diff.diffs.clear()
    other_module = changed(OLD, OLD + "beacon()\n", path="orbit/client.py")
    broken = changed(OLD, OLD + "beacon(\n")
    for analysis in (no_text, too_large, no_diff, other_module, broken):
        assert import_time_code(analysis) == []


def test_aliases_and_qualified_names() -> None:
    """Imports resolve to qualified names; relative imports keep their dots; non-names have none."""
    tree = ast.parse(
        "import os.path\nimport urllib.request as r\nfrom subprocess import run as go\nfrom . import util\n"
        "from ..base import thing\n"
    )
    names = pyast.aliases(tree)
    assert names == {
        "os": "os",
        "r": "urllib.request",
        "go": "subprocess.run",
        "util": ".util",
        "thing": "..base.thing",
    }

    def target(src: str) -> str | None:
        expr = ast.parse(src, mode="eval").body
        assert isinstance(expr, ast.Call)
        return pyast.qualified_name(expr.func, names)

    assert target("r.urlopen(u)") == "urllib.request.urlopen"
    assert target("go(['id'])") == "subprocess.run"
    assert target("os.path.join(a)") == "os.path.join"
    assert target("getattr(m, 'x')()") is None


def test_deeply_nested_code_is_skipped() -> None:
    """Code too deep to parse is logged and skipped rather than crashing the analysis."""
    assert pyast.parse("x = " + "(" * 100_000 + ")" * 100_000, "deep.py") is None
