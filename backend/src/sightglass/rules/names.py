"""Name rules: a package name close to a popular one.

Names are normalized (PEP 503) first. A name is a lookalike when it matches a popular name with the separators
removed (``python-dateutil`` and ``pythondateutil``), or is within a small edit distance of one: 1 edit for popular
names of 5 or more characters, 2 for 10 or more, counting a swap of two adjacent characters as one edit. Popular
packages themselves, and pairs listed in :data:`KNOWN_FORKS`, are never lookalikes.
"""

from packaging.utils import canonicalize_name

from sightglass.rules import top_packages
from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal

# Related projects with similar names that aren't impersonating each other.
KNOWN_FORKS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"pil", "pillow"}),
        frozenset({"pycrypto", "pycryptodome"}),
        frozenset({"pycryptodome", "pycryptodomex"}),
        frozenset({"python-jose", "python-jose-cryptodome"}),
    }
)
_TOP = top_packages.load()


def _squash(name: str) -> str:
    return name.replace("-", "")


def edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal string alignment distance between ``a`` and ``b``, or ``limit + 1`` once it exceeds ``limit``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _limit(popular: str) -> int:
    return 2 if len(popular) >= 10 else 1 if len(popular) >= 5 else 0


def lookalike(name: str, popular: tuple[str, ...]) -> tuple[str, int] | None:
    """The popular name ``name`` is closest to and the distance (0 for separators only), or None."""
    name = canonicalize_name(name)
    if name in popular:
        return None
    squashed = _squash(name)
    best: tuple[int, int, str] | None = None
    for rank, candidate in enumerate(popular):
        if frozenset({name, candidate}) in KNOWN_FORKS:
            continue
        if _squash(candidate) == squashed:
            distance = 0
        elif (limit := _limit(candidate)) and (distance := edit_distance(name, candidate, limit)) <= limit:
            pass
        else:
            continue
        if best is None or (distance, rank) < best[:2]:
            best = (distance, rank, candidate)
    return None if best is None else (best[2], best[0])


@RULES.rule("name.lookalike", 1, "Package name close to a popular package", data_version=f"top-{_TOP.queried_at}")
def lookalike_name(analysis: PairAnalysis) -> list[Signal]:
    """Report a package whose name is one or two edits, or only separators, away from a popular package."""
    if analysis.ecosystem != "pypi":
        return []
    match = lookalike(analysis.package, _TOP.names)
    if match is None:
        return []
    popular, distance = match
    how = "differs only in separators from" if distance == 0 else f"is {distance} edit{'s' * (distance > 1)} from"
    rank = _TOP.rank[popular]
    return [
        Signal(
            "name.lookalike",
            "check",
            f"`{canonicalize_name(analysis.package)}` {how} `{popular}`, number {rank:,} by PyPI downloads "
            f"(list from {_TOP.queried_at})",
            (Evidence(before=popular, after=canonicalize_name(analysis.package)),),
        )
    ]
