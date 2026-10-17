"""Pattern rules over added Python code: network, subprocess, dynamic execution and encoded payloads.

A match must be on a line this release added, and the file must now have more of that call (or that literal) than
before, so code that was only moved or reformatted doesn't fire. Calls are matched by the name they resolve to
through the module's imports, so ``from subprocess import run`` then ``run(...)`` is ``subprocess.run``.
"""

import ast
import hashlib
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sightglass.rules import pyast
from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal
from sightglass.rules.pairing import FilePair

_NETWORK_RE = re.compile(
    r"^(socket|ssl|urllib\.request|http\.client|requests|httpx|aiohttp|urllib3|ftplib|smtplib|telnetlib|poplib"
    r"|imaplib|xmlrpc\.client|websocket|websockets|paramiko|pycurl)\.[A-Za-z_][\w.]*$"
)
_SUBPROCESS_RE = re.compile(
    r"^(subprocess\.[A-Za-z_]\w*|os\.(system|popen|startfile|exec[lv]p?e?|spawn[lv]p?e?|posix_spawnp?)"
    r"|asyncio\.create_subprocess_(exec|shell)|pty\.spawn)$"
)
_EXEC_NAMES = frozenset(
    {"exec", "eval", "compile", "builtins.exec", "builtins.eval", "builtins.compile", "__builtins__.exec"}
)
_DECODE_NAMES = frozenset(
    {
        "base64.b64decode",
        "base64.b32decode",
        "base64.b16decode",
        "base64.b85decode",
        "base64.a85decode",
        "base64.urlsafe_b64decode",
        "base64.decodebytes",
        "binascii.a2b_base64",
        "binascii.a2b_hex",
        "binascii.unhexlify",
        "codecs.decode",
        "zlib.decompress",
        "gzip.decompress",
        "bz2.decompress",
        "lzma.decompress",
        "marshal.loads",
        "bytes.fromhex",
    }
)
# A string literal this long made only of base64 or hex characters is reported as an encoded blob.
ENCODED_MIN_LENGTH = 256
_ENCODED_RE = re.compile(r"^(?:[A-Za-z0-9+/_-]+={0,2}|[0-9a-fA-F]+)$")
# Lines named in a message; the evidence lists every one.
NAMED = 5


@dataclass(frozen=True)
class Match:
    """One matched call or literal: what it is, a key for counting, and its lines."""

    label: str
    key: str
    lines: range


def _call_matches(tree: ast.Module, wanted: Callable[[str], bool]) -> list[Match]:
    names = pyast.aliases(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = pyast.qualified_name(node.func, names)
            if name is not None and wanted(name):
                found.append(Match(f"`{name}`", name, range(node.lineno, (node.end_lineno or node.lineno) + 1)))
    return found


def _encoded(tree: ast.Module) -> list[Match]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
            raw = node.value.encode() if isinstance(node.value, str) else node.value
            compact = re.sub(rb"\s+", b"", raw)
            if len(compact) >= ENCODED_MIN_LENGTH and _ENCODED_RE.match(compact.decode("ascii", "replace")):
                key = hashlib.sha256(compact).hexdigest()
                lines = range(node.lineno, (node.end_lineno or node.lineno) + 1)
                found.append(Match(f"a {len(compact)}-character encoded string", key, lines))
    return found


def _decode_calls(tree: ast.Module) -> list[Match]:
    return _call_matches(tree, _DECODE_NAMES.__contains__) + _encoded(tree)


def _new_matches(analysis: PairAnalysis, pair: FilePair, finder: Callable[[ast.Module], list[Match]]) -> list[Match]:
    """Matches on added lines whose key occurs more often than in the old file."""
    text = analysis.new_text.get(pair.path)
    added = pyast.added_lines(analysis, pair)
    if text is None or not added or (tree := pyast.parse(text, pair.path)) is None:
        return []
    candidates = [m for m in finder(tree) if not added.isdisjoint(m.lines)]
    if not candidates:
        return []
    before: Counter[str] = Counter()
    old_text = analysis.old_text.get(pair.path) if pair.status == "changed" else None
    if old_text is not None and (old_tree := pyast.parse(old_text, pair.path)) is not None:
        before.update(m.key for m in finder(old_tree))
    after = Counter(m.key for m in finder(tree))
    return [m for m in candidates if after[m.key] > before[m.key]]


def _span(r: range) -> str:
    return str(r.start) if len(r) == 1 else f"{r.start}-{r[-1]}"


def _rule(
    rule_id: str, what: str, finder: Callable[[ast.Module], list[Match]]
) -> Callable[[PairAnalysis], list[Signal]]:
    def check(analysis: PairAnalysis) -> list[Signal]:
        signals = []
        for pair in analysis.files:
            if pair.status not in ("added", "changed") or not pair.path.endswith((".py", ".pyw")):
                continue
            matches = sorted(_new_matches(analysis, pair, finder), key=lambda m: m.lines.start)
            if not matches:
                continue
            labels = ", ".join(dict.fromkeys(m.label for m in matches))
            lines = ", ".join(_span(m.lines) for m in matches[:NAMED]) + (", ..." if len(matches) > NAMED else "")
            plural = "line" if len(matches) == 1 and len(matches[0].lines) == 1 else "lines"
            message = f"Added {what} in {pair.path}: {labels} ({plural} {lines})"
            evidence = tuple(Evidence(pair.path, m.lines.start, m.lines[-1], "new") for m in matches)
            signals.append(Signal(rule_id, "high", message, evidence))
        return signals

    return check


network_calls = RULES.rule("behavior.network", 1, "New network calls in added lines")(
    _rule("behavior.network", "network calls", lambda t: _call_matches(t, lambda n: bool(_NETWORK_RE.match(n))))
)
subprocess_calls = RULES.rule("behavior.subprocess", 1, "New subprocess or shell calls in added lines")(
    _rule("behavior.subprocess", "process calls", lambda t: _call_matches(t, lambda n: bool(_SUBPROCESS_RE.match(n))))
)
dynamic_exec = RULES.rule("behavior.dynamic_exec", 1, "New exec, eval or compile calls in added lines")(
    _rule("behavior.dynamic_exec", "dynamic code execution", lambda t: _call_matches(t, _EXEC_NAMES.__contains__))
)
encoded_payloads = RULES.rule("behavior.encoded_payload", 1, "New decoding calls or encoded blobs in added lines")(
    _rule("behavior.encoded_payload", "decoding or encoded data", _decode_calls)
)
