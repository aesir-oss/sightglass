"""Behavior rules over added Python code, by static analysis only."""

import ast

from sightglass.rules import patterns, pyast, scope
from sightglass.rules.base import RULES, Evidence, Level, PairAnalysis, Signal

# Calls common at module level that only set up names; they don't fire the import-time rule.
IMPORT_TIME_ALLOWED = frozenset(
    {
        "logging.getLogger",
        "typing.TypeVar",
        "typing.ParamSpec",
        "typing.TypeVarTuple",
        "typing.NewType",
        "typing.NamedTuple",
        "typing.TypedDict",
        "typing_extensions.TypeVar",
        "typing_extensions.ParamSpec",
        "typing_extensions.TypeVarTuple",
        "typing_extensions.NewType",
        "collections.namedtuple",
        "pkgutil.extend_path",
        "importlib.metadata.version",
        "importlib_metadata.version",
    }
)
# Statements that define names or document the module; the issue's "defs, classes, imports or docstrings".
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)


def _import_time_calls(stmt: ast.stmt, names: dict[str, str]) -> list[str]:
    found = []
    for call in pyast.calls(stmt):
        name = pyast.qualified_name(call.func, names)
        if name not in IMPORT_TIME_ALLOWED:
            found.append(name or "an expression")
    return found


def _span(r: range) -> str:
    return str(r.start) if len(r) == 1 else f"{r.start}-{r[-1]}"


@RULES.rule("behavior.import_time_code", 3, "New code that runs at import time in __init__.py")
def import_time_code(analysis: PairAnalysis) -> list[Signal]:
    """Report added module-level statements in ``__init__.py`` files that call something when the package is imported.

    Function and class definitions, imports, docstrings and assignments of plain values don't fire, and neither do
    the setup calls in :data:`IMPORT_TIME_ALLOWED`. The signal is high when one of the calls is a network, subprocess,
    dynamic execution or decoding call, and a note otherwise, or outside the installed package.
    """
    signals = []
    for pair in analysis.files:
        if pair.status not in ("added", "changed") or not pair.path.endswith("__init__.py"):
            continue
        text = analysis.new_text.get(pair.path)
        added = pyast.added_lines(analysis, pair)
        if text is None or not added or (tree := pyast.parse(text, pair.path)) is None:
            continue
        names = pyast.aliases(tree)
        found: list[tuple[range, list[str]]] = []
        for stmt in tree.body:
            if isinstance(stmt, _DEFINITIONS):
                continue
            lines = pyast.statement_lines(stmt)
            if added.isdisjoint(lines):
                continue
            if called := _import_time_calls(stmt, names):
                found.append((lines, called))
        if not found:
            continue
        if len(found) == 1:
            lines, called = found[0]
            which = f"line {_span(lines)}" if len(lines) == 1 else f"lines {_span(lines)}"
            message = f"New module-level code in {pair.path} runs at import: {which} calls `{called[0]}`"
        else:
            where = ", ".join(_span(r) for r, _ in found)
            message = f"{len(found)} new module-level statements in {pair.path} run at import (lines {where})"
        evidence = tuple(Evidence(pair.path, r.start, r[-1], "new") for r, _ in found)
        risky = any(patterns.is_risky(name) for _, called in found for name in called)
        level: Level = "high" if risky and not scope.outside_package(analysis, pair.path) else "note"
        signals.append(Signal("behavior.import_time_code", level, message, evidence))
    return signals
