"""Package name normalization."""

import re

_PEP503_SEPARATORS = re.compile(r"[-_.]+")


def normalize_name(ecosystem: str, name: str) -> str:
    """Return the canonical form of a package name for storage and lookup.

    PyPI names follow PEP 503: runs of ``-``, ``_`` and ``.`` collapse to one ``-``, and letters are lowercased.
    Other ecosystems are only lowercased.

    Args:
        ecosystem: The package index, such as ``pypi``.
        name: The name as written by a user or an index.

    Returns:
        The normalized name.

    Raises:
        ValueError: If the name is empty or only whitespace.
    """
    stripped = name.strip()
    if not stripped:
        raise ValueError("package name is empty")
    if ecosystem == "pypi":
        return _PEP503_SEPARATORS.sub("-", stripped).lower()
    return stripped.lower()
