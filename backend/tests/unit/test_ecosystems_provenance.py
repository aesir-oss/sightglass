"""Tests for parsing PEP 740 provenance, with generated certificates and no network."""

import base64
import json
from collections.abc import Callable

import pytest

from sightglass.ecosystems.provenance import (
    CertificateClaims,
    Publisher,
    parse_certificate,
    parse_provenance,
)
from sightglass.ecosystems.pypi import IndexDataError

SHA = "2" * 64


def test_certificate_claims_are_read(
    certificate: Callable[[dict[str, str]], str], github_claims: dict[str, str]
) -> None:
    """Every Fulcio build claim Sightglass uses is decoded from its DER UTF8String."""
    assert parse_certificate(certificate(github_claims)) == CertificateClaims(
        build_signer_uri=github_claims["9"],
        runner_environment="github-hosted",
        source_repository="https://github.com/kestrel-weather/orbit-client",
        source_commit="0123456789abcdef0123456789abcdef01234567",
        source_ref="refs/tags/v2.5.0",
        build_trigger="release",
        run_url=github_claims["21"],
    )


def test_long_claim_values_use_long_form_lengths(certificate: Callable[[dict[str, str]], str]) -> None:
    """Values of 128 bytes or more use DER's long-form length and still decode."""
    long_ref = "refs/heads/" + "x" * 200
    assert parse_certificate(certificate({"14": long_ref})).source_ref == long_ref


def test_missing_claims_are_none(certificate: Callable[[dict[str, str]], str]) -> None:
    """A certificate without the extensions gives unknown claims, not an error."""
    assert parse_certificate(certificate({})) == CertificateClaims()


@pytest.mark.parametrize("bad", ["not base64!", base64.b64encode(b"not a certificate").decode()])
def test_unreadable_certificate_gives_empty_claims(bad: str) -> None:
    """A broken certificate is logged and treated as saying nothing."""
    assert parse_certificate(bad) == CertificateClaims()


def test_provenance_from_github_publisher(provenance_payload: Callable[..., bytes]) -> None:
    """The publisher, claims and statement subject come through; nothing is marked verified."""
    provenance = parse_provenance(provenance_payload())
    assert provenance.status == "present"
    (att,) = provenance.attestations
    assert att.publisher == Publisher("GitHub", "kestrel-weather/orbit-client", "release.yml", "pypi", None)
    assert att.claims.source_commit == "0123456789abcdef0123456789abcdef01234567"
    assert att.predicate_type == "https://docs.pypi.org/attestations/publish/v1"
    assert att.covers(SHA) and not att.covers("3" * 64)
    assert att.verified is False
    assert provenance.raw["version"] == 1


def test_google_publisher_has_email_and_no_repository(provenance_payload: Callable[..., bytes]) -> None:
    """Publisher kinds without a repository leave it unknown, and empty environments become None."""
    payload = provenance_payload(
        publisher={"kind": "Google", "email": "release@orbit.iam.example.net", "environment": ""}, claims={}
    )
    (att,) = parse_provenance(payload).attestations
    assert att.publisher == Publisher("Google", None, None, None, "release@orbit.iam.example.net")
    assert att.claims == CertificateClaims()


def test_unreadable_statement_has_no_subjects(provenance_payload: Callable[..., bytes]) -> None:
    """A statement that isn't base64 JSON leaves the attestation without subjects instead of failing."""
    raw = json.loads(provenance_payload())
    raw["attestation_bundles"][0]["attestations"][0]["envelope"]["statement"] = "!!!"
    (att,) = parse_provenance(json.dumps(raw).encode()).attestations
    assert (att.predicate_type, att.subject_sha256s) == (None, ())


@pytest.mark.parametrize("bad", [b"not json", b"{}", b'{"version": 1, "attestation_bundles": [{"publisher": {}}]}'])
def test_malformed_provenance_raises(bad: bytes) -> None:
    """Responses that aren't the Integrity API's shape are IndexDataError."""
    with pytest.raises(IndexDataError):
        parse_provenance(bad)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\x0c\x03abc", "abc"),
        (b"refs/heads/main", "refs/heads/main"),
        (b"\x0c\x05ab", None),
        (b"\x0c\x02\xff\xfe", None),
        (b"\xff\xfe", None),
    ],
)
def test_der_utf8_decoding(raw: bytes, expected: str | None) -> None:
    """DER UTF8Strings and legacy raw values decode; truncated or non-UTF-8 values become unknown."""
    from sightglass.ecosystems.provenance import _der_utf8

    assert _der_utf8(raw) == expected
