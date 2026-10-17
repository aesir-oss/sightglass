"""Pattern rules over added Python code: network, subprocess, dynamic execution and encoded payloads.

A match must be on a line this release added, and the file must now have more of that call (or that literal) than
before, so code that was only moved or reformatted doesn't fire. Calls are matched by the name they resolve to
through the module's imports, so ``from subprocess import run`` then ``run(...)`` is ``subprocess.run``.
"""

import ast
import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sightglass.rules import pyast, scope
from sightglass.rules.base import RULES, Evidence, Level, PairAnalysis, Signal
from sightglass.rules.pairing import FilePair

# Calls that open a connection or resolve a host. Constructors of options, constants and helpers (``ssl``
# contexts, ``aiohttp.ClientTimeout``, ``socket.fileno``) don't, so they aren't listed.
_NETWORK_NAMES = frozenset(
    {
        "socket.socket",
        "socket.create_connection",
        "socket.create_server",
        "socket.fromfd",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.gethostbyaddr",
        "ssl.wrap_socket",
        "urllib.request.urlopen",
        "urllib.request.urlretrieve",
        "urllib.request.build_opener",
        "http.client.HTTPConnection",
        "http.client.HTTPSConnection",
        *(f"requests.{m}" for m in ("get", "post", "put", "patch", "delete", "head", "options", "request")),
        "requests.Session",
        "requests.session",
        *(f"httpx.{m}" for m in ("get", "post", "put", "patch", "delete", "head", "options", "request", "stream")),
        "httpx.Client",
        "httpx.AsyncClient",
        "aiohttp.ClientSession",
        "aiohttp.request",
        "urllib3.PoolManager",
        "urllib3.ProxyManager",
        "urllib3.HTTPConnectionPool",
        "urllib3.HTTPSConnectionPool",
        "urllib3.connection_from_url",
        "urllib3.request",
        "ftplib.FTP",
        "ftplib.FTP_TLS",
        "smtplib.SMTP",
        "smtplib.SMTP_SSL",
        "smtplib.LMTP",
        "telnetlib.Telnet",
        "poplib.POP3",
        "poplib.POP3_SSL",
        "imaplib.IMAP4",
        "imaplib.IMAP4_SSL",
        "xmlrpc.client.ServerProxy",
        "websocket.create_connection",
        "websocket.WebSocketApp",
        "websockets.connect",
        "websockets.serve",
        "websockets.client.connect",
        "websockets.sync.client.connect",
        "paramiko.SSHClient",
        "paramiko.Transport",
        "pycurl.Curl",
    }
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
            # surrogatepass: a literal like "\\udce2" is valid Python but not encodable UTF-8.
            raw = node.value.encode("utf-8", "surrogatepass") if isinstance(node.value, str) else node.value
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


def _network_calls(tree: ast.Module) -> list[Match]:
    return _call_matches(tree, _NETWORK_NAMES.__contains__)


def _subprocess_calls(tree: ast.Module) -> list[Match]:
    return _call_matches(tree, lambda n: bool(_SUBPROCESS_RE.match(n)))


def _exec_calls(tree: ast.Module) -> list[Match]:
    return _call_matches(tree, _EXEC_NAMES.__contains__)


# Each pattern rule's finder, by rule id.
FINDERS: dict[str, Callable[[ast.Module], list[Match]]] = {
    "behavior.network": _network_calls,
    "behavior.subprocess": _subprocess_calls,
    "behavior.dynamic_exec": _exec_calls,
    "behavior.encoded_payload": _decode_calls,
}
# Words one of the finders could match; a file without any of them isn't parsed when looking for capabilities.
_PREFILTER = re.compile(
    rb"socket|ssl|urllib|http|requests|aiohttp|ftplib|smtplib|telnetlib|poplib|imaplib|xmlrpc|websocket|paramiko"
    rb"|pycurl|subprocess|os\.|spawn|exec|eval|compile|decode|decompress|marshal|fromhex|unhexlify|a2b_|[A-Za-z0-9+/]{256}"
)


def is_risky(name: str) -> bool:
    """Whether a call name is a network, subprocess, dynamic execution or decoding call."""
    return name in _NETWORK_NAMES or bool(_SUBPROCESS_RE.match(name)) or name in _EXEC_NAMES or name in _DECODE_NAMES


def risky_added(analysis: PairAnalysis, pair: FilePair) -> bool:
    """Whether the lines this release added to a Python file make a network, subprocess, exec or decoding call."""
    text = analysis.new_text.get(pair.path)
    added = pyast.added_lines(analysis, pair)
    if text is None or (tree := pyast.parse(text, pair.path)) is None:
        return True  # Unknown counts as risky: the hook still runs.
    if added is None:
        return True
    return any(not added.isdisjoint(m.lines) for finder in FINDERS.values() for m in finder(tree))


def capabilities(sources: Iterable[tuple[str, bytes]]) -> frozenset[str]:
    """The pattern rules whose calls (or blobs) appear anywhere in these Python files.

    Args:
        sources: ``(path, content)`` of each Python file of a release's package code.

    Returns:
        Rule ids from :data:`FINDERS`.
    """
    found: set[str] = set()
    for path, data in sources:
        if len(found) == len(FINDERS) or not _PREFILTER.search(data):
            continue
        text = data.decode("utf-8", "replace")
        if (tree := pyast.parse(text, path)) is None:
            continue
        found.update(rule_id for rule_id, finder in FINDERS.items() if rule_id not in found and finder(tree))
    return frozenset(found)


def _level(analysis: PairAnalysis, rule_id: str, path: str) -> Level:
    """High for a kind of call the package didn't make before; check when it did; note outside the package."""
    if scope.outside_package(analysis, path):
        return "note"
    if analysis.old_capabilities is not None and rule_id in analysis.old_capabilities:
        return "check"
    return "high"


def _rule(rule_id: str, what: str) -> Callable[[PairAnalysis], list[Signal]]:
    finder = FINDERS[rule_id]

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
            signals.append(Signal(rule_id, _level(analysis, rule_id, pair.path), message, evidence))
        return signals

    return check


SUMMARY = "{}; high when the previous release made no such call, check when it did, note outside the installed package"
network_calls = RULES.rule("behavior.network", 2, SUMMARY.format("New network calls in added lines"))(
    _rule("behavior.network", "network calls")
)
subprocess_calls = RULES.rule("behavior.subprocess", 2, SUMMARY.format("New subprocess or shell calls in added lines"))(
    _rule("behavior.subprocess", "process calls")
)
dynamic_exec = RULES.rule("behavior.dynamic_exec", 2, SUMMARY.format("New exec, eval or compile calls in added lines"))(
    _rule("behavior.dynamic_exec", "dynamic code execution")
)
encoded_payloads = RULES.rule(
    "behavior.encoded_payload", 2, SUMMARY.format("New decoding calls or encoded blobs in added lines")
)(_rule("behavior.encoded_payload", "decoding or encoded data"))
