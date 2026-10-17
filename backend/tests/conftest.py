"""Fixtures shared by unit and integration tests."""

import base64
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Restore structlog's defaults so one test's logging config can't leak into another."""
    yield
    structlog.reset_defaults()


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes() -> Callable[[str], bytes]:
    """Read a file from tests/fixtures by relative path."""
    return lambda name: (FIXTURES / name).read_bytes()


def _der_utf8(text: str) -> bytes:
    data = text.encode()
    if len(data) < 128:
        return b"\x0c" + bytes([len(data)]) + data
    return b"\x0c\x82" + len(data).to_bytes(2, "big") + data


def make_certificate(claims: dict[str, str]) -> str:
    """A self-signed certificate carrying Fulcio extensions for ``claims`` (OID suffix to value), base64 DER."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sightglass-test")])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(minutes=5))
    )
    for suffix, value in claims.items():
        oid = x509.ObjectIdentifier(f"1.3.6.1.4.1.57264.1.{suffix}")
        builder = builder.add_extension(x509.UnrecognizedExtension(oid, _der_utf8(value)), critical=False)
    cert = builder.sign(key, hashes.SHA256())
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


GITHUB_CLAIMS = {
    "9": "https://github.com/kestrel-weather/orbit-client/.github/workflows/release.yml@refs/tags/v2.5.0",
    "11": "github-hosted",
    "12": "https://github.com/kestrel-weather/orbit-client",
    "13": "0123456789abcdef0123456789abcdef01234567",
    "14": "refs/tags/v2.5.0",
    "20": "release",
    "21": "https://github.com/kestrel-weather/orbit-client/actions/runs/42/attempts/1",
}


@pytest.fixture
def provenance_payload() -> Callable[..., bytes]:
    """Build an Integrity API response for one file, attested by a GitHub trusted publisher by default."""

    def build(
        sha256: str = "2" * 64,
        publisher: dict[str, Any] | None = None,
        claims: dict[str, str] | None = None,
    ) -> bytes:
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": "orbit_client-2.5.0-py3-none-any.whl", "digest": {"sha256": sha256}}],
            "predicateType": "https://docs.pypi.org/attestations/publish/v1",
            "predicate": None,
        }
        attestation = {
            "version": 1,
            "envelope": {"statement": base64.b64encode(json.dumps(statement).encode()).decode(), "signature": "c2ln"},
            "verification_material": {
                "certificate": make_certificate(GITHUB_CLAIMS if claims is None else claims),
                "transparency_entries": [],
            },
        }
        default_publisher = {
            "kind": "GitHub",
            "repository": "kestrel-weather/orbit-client",
            "workflow": "release.yml",
            "environment": "pypi",
            "claims": None,
        }
        bundle = {"publisher": publisher or default_publisher, "attestations": [attestation]}
        return json.dumps({"version": 1, "attestation_bundles": [bundle]}).encode()

    return build


@pytest.fixture
def certificate() -> Callable[[dict[str, str]], str]:
    """Build a base64 DER certificate with the given Fulcio extensions (OID suffix to value)."""
    return make_certificate


@pytest.fixture
def github_claims() -> dict[str, str]:
    """The Fulcio claims the default provenance payload carries."""
    return dict(GITHUB_CLAIMS)
