"""Static analysis helpers for the behavior rules: parsing, import aliases, calls, and added lines.

Code is only parsed with :func:`ast.parse`, never compiled, imported or run.
"""

import ast
import functools
from collections.abc import Iterable, Iterator

from sightglass.log import get_logger
from sightglass.rules.base import PairAnalysis
from sightglass.rules.pairing import FilePair

log = get_logger(__name__)

# Bodies that don't run when their enclosing statement does.
_DEFERRED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def parse(text: str, path: str) -> ast.Module | None:
    """Parse Python source, or return None (and log why) when it can't be parsed.

    A leading UTF-8 byte-order mark, which Python accepts in source files but not in a string given to the parser, is
    dropped first.
    """
    try:
        return ast.parse(text.removeprefix("\ufeff"), filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        log.warning("python_parse_failed", path=path, error=type(exc).__name__)
        return None


@functools.lru_cache(maxsize=256)
def parsed(text: str, path: str) -> ast.Module | None:
    """:func:`parse`, cached: several rules read the same changed file. The tree is shared, so don't change it."""
    return parse(text, path)


@functools.lru_cache(maxsize=1024)
def aliases(tree: ast.Module) -> dict[str, str]:
    """Map each name the module's imports bind to the qualified name it refers to.

    ``import urllib.request as r`` maps ``r`` to ``urllib.request``; ``from subprocess import run`` maps ``run`` to
    ``subprocess.run``. Relative imports keep their dots. Cached per tree; don't change the result.
    """
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    names[a.asname] = a.name
                else:
                    top = a.name.split(".", 1)[0]
                    names[top] = top
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (f"{node.module}." if node.module else "")
            for a in node.names:
                names[a.asname or a.name] = prefix + a.name
    return names


def qualified_name(node: ast.expr, names: dict[str, str]) -> str | None:
    """The dotted name a call target refers to, resolved through the module's imports, or None if it isn't a name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(names.get(node.id, node.id))
    return ".".join(reversed(parts))


def calls(node: ast.AST) -> Iterator[ast.Call]:
    """Every call that runs when ``node`` runs: function and lambda bodies are skipped, class bodies are not."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Call):
            yield current
        for child in ast.iter_child_nodes(current):
            if isinstance(child, _DEFERRED):
                # Decorators and default values still run at definition time.
                if not isinstance(child, ast.Lambda):
                    stack.extend(child.decorator_list)
                stack.extend(d for d in (*child.args.defaults, *child.args.kw_defaults) if d is not None)
                continue
            stack.append(child)


def added_lines(analysis: PairAnalysis, pair: FilePair) -> set[int] | None:
    """Line numbers in the new file that this release added, or None when that isn't known.

    Every line of a new file is added. For a changed file the line diff is needed; without one (too large to diff)
    the answer is unknown.
    """
    diff = analysis.diffs.get(pair.path)
    if diff is not None and not diff.too_large:
        return {line for line, _ in diff.added_lines()}
    if pair.status == "added":
        text = analysis.new_text.get(pair.path)
        return None if text is None else set(range(1, text.count("\n") + 2))
    return None


def statement_lines(node: ast.stmt) -> range:
    """The lines a statement spans, decorators included."""
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
    return range(start, (node.end_lineno or node.lineno) + 1)


def line_ranges(lines: Iterable[int]) -> list[tuple[int, int]]:
    """Group line numbers into sorted, inclusive ``(start, end)`` runs of consecutive lines."""
    ranges: list[tuple[int, int]] = []
    for line in sorted(set(lines)):
        if ranges and ranges[-1][1] == line - 1:
            ranges[-1] = (ranges[-1][0], line)
        else:
            ranges.append((line, line))
    return ranges
