"""Install-time hook rules: code that runs when a package is built, installed or Python starts.

- ``setup.py`` runs whenever an sdist is built or installed. A change that only edits literal values, such as the
  version, doesn't fire. A change is check, or high when the added lines make a network, subprocess, exec or decoding
  call.
- An in-tree build backend (``backend-path`` in ``pyproject.toml``) is code from the sdist that the installer runs.
  Switching to one is high; a change to its code is leveled like ``setup.py``.
- A ``.pth`` file at the top of a wheel is read at every interpreter start, and its ``import`` lines run.
"""

import ast
import tomllib
from typing import Any

from sightglass.log import get_logger
from sightglass.rules import patterns, pyast
from sightglass.rules.base import RULES, Evidence, Level, PairAnalysis, Signal
from sightglass.rules.pairing import FilePair

log = get_logger(__name__)

# Line ranges named in a message; the evidence lists every one.
NAMED = 5


def _ranges_text(ranges: list[tuple[int, int]]) -> str:
    single = len(ranges) == 1 and ranges[0][0] == ranges[0][1]
    named = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges[:NAMED])
    return ("line " if single else "lines ") + named + (", ..." if len(ranges) > NAMED else "")


def _evidence(path: str, ranges: list[tuple[int, int]]) -> tuple[Evidence, ...]:
    return tuple(Evidence(path, a, b, "new") for a, b in ranges) or (Evidence(path, side="new"),)


def _without_literals(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            node.value = None
    return ast.dump(tree)


def _only_literals_changed(analysis: PairAnalysis, pair: FilePair) -> bool:
    old, new = analysis.old_text.get(pair.path), analysis.new_text.get(pair.path)
    if pair.status != "changed" or old is None or new is None:
        return False
    old_tree, new_tree = pyast.parse(old, pair.path), pyast.parse(new, pair.path)
    return old_tree is not None and new_tree is not None and _without_literals(old_tree) == _without_literals(new_tree)


def _pair(analysis: PairAnalysis, path: str) -> FilePair | None:
    return next((p for p in analysis.files if p.path == path), None)


def _changed_code(analysis: PairAnalysis, pair: FilePair) -> list[tuple[int, int]] | None:
    """Added line ranges of a new or changed Python hook, or None when nothing but literal values changed."""
    if pair.status not in ("added", "changed") or _only_literals_changed(analysis, pair):
        return None
    return pyast.line_ranges(pyast.added_lines(analysis, pair) or ())


def _hook_level(analysis: PairAnalysis, pair: FilePair) -> Level:
    return "high" if pair.status == "added" or patterns.risky_added(analysis, pair) else "check"


@RULES.rule("hooks.setup_py", 3, "New or changed setup.py in the sdist")
def setup_py(analysis: PairAnalysis) -> list[Signal]:
    """Report a new ``setup.py``, or a changed one whose code (not just its literal values) changed."""
    pair = _pair(analysis, "setup.py")
    if pair is None or (ranges := _changed_code(analysis, pair)) is None:
        return []
    if pair.status == "added":
        message = f"{analysis.new.version} adds setup.py, which runs when the sdist is built or installed"
    elif ranges:
        message = f"setup.py, which runs when the sdist is built or installed, changed ({_ranges_text(ranges)})"
    else:
        message = "setup.py, which runs when the sdist is built or installed, changed"
    return [Signal("hooks.setup_py", _hook_level(analysis, pair), message, _evidence("setup.py", ranges))]


def _build_system(analysis: PairAnalysis, side: str) -> dict[str, Any] | None:
    texts = analysis.new_text if side == "new" else analysis.old_text
    text = texts.get("pyproject.toml")
    if text is None:
        return None
    try:
        build_system = tomllib.loads(text).get("build-system", {})
    except tomllib.TOMLDecodeError as exc:
        log.warning("pyproject_parse_failed", side=side, error=str(exc))
        return None
    return build_system if isinstance(build_system, dict) else None


def _backend_files(build_system: dict[str, Any]) -> list[str]:
    backend = build_system.get("build-backend")
    paths = build_system.get("backend-path")
    if not isinstance(backend, str) or not isinstance(paths, list):
        return []
    module = backend.split(":", 1)[0].replace(".", "/")
    out = []
    for base in paths:
        if isinstance(base, str):
            root = base.strip("/").removeprefix("./")
            prefix = f"{root}/" if root and root != "." else ""
            out += [f"{prefix}{module}.py", f"{prefix}{module}/__init__.py"]
    return out


@RULES.rule("hooks.build_backend", 3, "New or changed in-tree build backend")
def build_backend(analysis: PairAnalysis) -> list[Signal]:
    """Report an in-tree build backend that is new, moved, or whose code changed."""
    new = _build_system(analysis, "new")
    if new is None or not (files := _backend_files(new)):
        return []
    old = _build_system(analysis, "old")
    pyproject = _pair(analysis, "pyproject.toml")
    configured = (new.get("build-backend"), new.get("backend-path"))
    signals = []
    if (old is not None and (old.get("build-backend"), old.get("backend-path")) != configured) or (
        old is None and pyproject is not None and pyproject.status == "added"
    ):
        signals.append(
            Signal(
                "hooks.build_backend",
                "high",
                f"pyproject.toml now builds with the in-tree backend `{new.get('build-backend')}` from "
                f"{', '.join(map(str, new['backend-path']))}",
                (
                    Evidence(
                        "pyproject.toml",
                        side="new",
                        before=str(old.get("build-backend")) if old is not None else None,
                        after=str(new.get("build-backend")),
                    ),
                ),
            )
        )
    for path in files:
        pair = _pair(analysis, path)
        if pair is None or (ranges := _changed_code(analysis, pair)) is None:
            continue
        where = f" ({_ranges_text(ranges)})" if ranges else ""
        signals.append(
            Signal(
                "hooks.build_backend",
                _hook_level(analysis, pair),
                f"The in-tree build backend {path}, which runs when the sdist is built, changed{where}",
                _evidence(path, ranges),
            )
        )
    return signals


def _is_root_pth(path: str) -> bool:
    for prefix in ("*.data/purelib/", "*.data/platlib/"):
        path = path.removeprefix(prefix)
    return path.endswith(".pth") and "/" not in path


@RULES.rule("hooks.pth_import", 1, "New import lines in a .pth file, which run at interpreter startup")
def pth_import(analysis: PairAnalysis) -> list[Signal]:
    """Report ``.pth`` files at the top of a wheel whose added lines start with ``import``."""
    signals = []
    for pair in analysis.files:
        if pair.status not in ("added", "changed") or not _is_root_pth(pair.path):
            continue
        text = analysis.new_text.get(pair.path)
        added = pyast.added_lines(analysis, pair)
        if text is None or not added:
            continue
        lines = text.splitlines()
        runs = [n for n in sorted(added) if n <= len(lines) and lines[n - 1].startswith(("import ", "import\t"))]
        if not runs:
            continue
        ranges = pyast.line_ranges(runs)
        first = lines[runs[0] - 1].strip()
        signals.append(
            Signal(
                "hooks.pth_import",
                "high",
                f"{pair.path} runs code at every Python startup: {_ranges_text(ranges)} (`{first[:80]}`)",
                _evidence(pair.path, ranges),
            )
        )
    return signals
