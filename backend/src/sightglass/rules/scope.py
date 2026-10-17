"""Where a file sits in a pair: installed or not, new or kept from the previous release, code or inert.

Rules use these to choose a level: a fact about new installed code is high, the same fact about a file the previous
release already had unchanged, or one the sdist carries but never installs or runs, is a note.
"""

import ast
import tomllib
from collections.abc import Callable, Collection
from typing import Any

from sightglass.rules import pyast
from sightglass.rules.base import PairAnalysis
from sightglass.rules.pairing import PairStatus

# Top-level sdist directories that hold files which aren't installed and don't run when the sdist is built.
NOT_SHIPPED = frozenset(
    {
        "bench",
        "benchmark",
        "benchmarks",
        "ci",
        "demo",
        "demos",
        "doc",
        "docs",
        "example",
        "examples",
        "scripts",
        "test",
        "testing",
        "tests",
        "tools",
    }
)
# Modules an inert file may import: they only provide names for annotations.
_INERT_IMPORTS = frozenset({"__future__", "typing", "typing_extensions"})


def outside_package(analysis: PairAnalysis, path: str) -> bool:
    """Whether ``path`` is an sdist file that isn't installed and doesn't run or compile when the sdist is built.

    With the release's wheel known, a file is inside the package when the wheel installs it, when it's build code
    (:func:`sdist_shipped`), or when it's a compiled or build source, which ends up in the wheel's binaries. Without
    a wheel, files in the top-level directories of :data:`NOT_SHIPPED` and dot directories are outside.
    """
    if analysis.kind != "sdist":
        return False
    if analysis.installed is not None:
        return path not in analysis.installed and not build_source(path)
    if "/" not in path:
        return False
    top = path.split("/", 1)[0]
    return top.lower() in NOT_SHIPPED or top.startswith(".")


# Sources a build compiles or runs: they end up in the wheel's binaries or drive the build, whether or not the wheel
# carries them by name.
_BUILD_SOURCE_EXTENSIONS = frozenset(
    {"c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx", "rs", "pyx", "pxd", "pxi", "f", "f90", "f95", "for", "s", "asm",
     "m", "mm", "go", "cmake"}
)  # fmt: skip
_BUILD_SOURCE_NAMES = frozenset(
    {"setup.py", "CMakeLists.txt", "meson.build", "meson.options", "meson_options.txt", "Makefile", "configure", "build.rs"}
)  # fmt: skip


def build_source(path: str) -> bool:
    """Whether a file is compiled or run by a build: C, C++, Rust, Cython, Fortran, assembly, and build scripts."""
    name = path.rsplit("/", 1)[-1]
    stem, dot, ext = name.rpartition(".")
    return name in _BUILD_SOURCE_NAMES or (bool(dot and stem) and ext.lower() in _BUILD_SOURCE_EXTENSIONS)


def _imported_modules(text: str, path: str) -> set[str]:
    tree = pyast.parse(text, path)
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".", 1)[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".", 1)[0])
    return names


def _hook_paths(pyproject: dict[str, Any]) -> set[str]:
    """Build hook and in-tree backend files a ``pyproject.toml`` names."""
    found: set[str] = set()
    build_system = pyproject.get("build-system", {})
    for base in build_system.get("backend-path", []) if isinstance(build_system, dict) else []:
        if isinstance(base, str):
            found.add(base.strip("/").removeprefix("./") + "/")
    hatch = pyproject.get("tool", {}).get("hatch", {}).get("build", {})
    hooks = [hatch.get("hooks", {})] + [
        t.get("hooks", {}) for t in hatch.get("targets", {}).values() if isinstance(t, dict)
    ]
    for h in hooks:
        custom = h.get("custom") if isinstance(h, dict) else None
        if isinstance(custom, dict):
            found.add(str(custom.get("path", "hatch_build.py")))
    return found


def sdist_shipped(
    paths: Collection[str], wheel_paths: Collection[str], read: Callable[[str], str | None]
) -> frozenset[str]:
    """The sdist paths a wheel installs or a build runs, as :attr:`PairAnalysis.installed` holds them.

    Args:
        paths: Every path in the sdist, without its top-level directory.
        wheel_paths: The sdist paths the source check found the wheel's files at.
        read: Reads an sdist file's text, or None.

    Returns:
        The wheel's files, Python files at the sdist's top level (``setup.py``, build hooks), the in-tree backend and
        hooks named in ``pyproject.toml``, and the local modules and packages those import.
    """
    shipped = set(wheel_paths) & set(paths)
    build = {p for p in paths if "/" not in p and p.endswith(".py")}
    pyproject_text = read("pyproject.toml")
    if pyproject_text is not None:
        try:
            pyproject = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            pyproject = {}
        for hook in _hook_paths(pyproject):
            build |= {p for p in paths if p == hook or (hook.endswith("/") and p.startswith(hook))}
    tops = {p.split("/", 1)[0] for p in paths if "/" in p}
    for script in list(build):
        text = read(script) if script.endswith(".py") else None
        for module in _imported_modules(text, script) if text else ():
            for prefix in ("", *(f"{t}/" for t in tops)):
                if f"{prefix}{module}.py" in paths:
                    build.add(f"{prefix}{module}.py")
                package = f"{prefix}{module}/"
                if f"{package}__init__.py" in paths:
                    build |= {p for p in paths if p.startswith(package)}
    return frozenset(shipped | build)


def statuses(analysis: PairAnalysis) -> dict[str, PairStatus]:
    """Each file's status against the previous release, by normalized path."""
    return {p.path: p.status for p in analysis.files}


def inert(text: str, path: str) -> bool:
    """Whether Python source only binds values: no calls, functions, classes, or imports beyond typing.

    Version files written by setuptools-scm and hatch-vcs look like this. Importing one can't do anything but assign.
    """
    tree = pyast.parse(text, path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            return False
        if isinstance(node, ast.Import) and any(a.name not in _INERT_IMPORTS for a in node.names):
            return False
        if isinstance(node, ast.ImportFrom) and (node.level or node.module not in _INERT_IMPORTS):
            return False
    return True


# Extensions of files that run, are compiled, or drive a build. Everything else (documentation, licenses, lock files,
# declarative config, data, type stubs) can't run by itself.
_CODE_EXTENSIONS = frozenset(
    {
        "py", "pyw", "pth", "pyx", "pxd", "pxi",
        "c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx", "m", "mm", "rs", "go", "f", "f90", "f95", "for", "s", "asm",
        "js", "mjs", "cjs", "ts", "sh", "bash", "zsh", "ps1", "bat", "cmd", "cmake",
    }
)  # fmt: skip
_CODE_NAMES = frozenset(
    {"Makefile", "CMakeLists.txt", "meson.build", "meson.options", "meson_options.txt", "configure"}
)


def code_file(path: str) -> bool:
    """Whether a file runs, is compiled, or drives a build; installed scripts always count."""
    name = path.rsplit("/", 1)[-1]
    if path.startswith("*.data/scripts/") or name in _CODE_NAMES:
        return True
    stem, dot, ext = name.rpartition(".")
    return bool(dot and stem) and ext.lower() in _CODE_EXTENSIONS


# Names whose literal value a build or archive may set differently from the tag, such as a version left unbumped.
VERSION_NAMES = frozenset(
    {"__version__", "version", "VERSION", "__version_info__", "version_info", "VERSION_INFO", "__version_tuple__",
     "version_tuple", "__release__", "release",
     # versioneer's git-archive keywords, which GitHub fills in when it makes the archive
     "git_refnames", "git_full", "git_date"}
)  # fmt: skip


def _without_version_values(tree: ast.Module) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None and all(isinstance(t, ast.Name) and t.id in VERSION_NAMES for t in targets):
                if all(isinstance(n, ast.Constant | ast.Tuple | ast.List | ast.UnaryOp) for n in ast.walk(node.value)
                       if not isinstance(n, ast.expr_context | ast.unaryop)):  # fmt: skip
                    node.value = ast.Constant(None)
    return ast.dump(tree)


def same_code(package_text: str, source_text: str, path: str) -> bool:
    """Whether two Python files run the same code, apart from comments, formatting and version values.

    Any other difference, a changed URL or number included, is a difference in what runs.
    """
    package, source = pyast.parse(package_text, path), pyast.parse(source_text, path)
    return (
        package is not None
        and source is not None
        and _without_version_values(package) == _without_version_values(source)
    )


_VERSIONEER_HEADER = "# This file was generated by 'versioneer.py'"


def versioneer(text: str, path: str) -> bool:
    """Whether a file is exactly versioneer's generated ``_version.py``: a JSON string and a function that returns it.

    The template is matched by structure, so anything added to it doesn't count.
    """
    if not text.lstrip().startswith(_VERSIONEER_HEADER) or (tree := pyast.parse(text, path)) is None:
        return False
    expected = ast.parse("import json\nversion_json = ''\ndef get_versions():\n    return json.loads(version_json)\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.dump(tree) == ast.dump(expected)
