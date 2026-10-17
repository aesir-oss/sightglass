"""PEP 740 provenance from PyPI: which files are attested, who published them, and what built them.

PyPI verifies every attestation against the project's trusted publisher when it is uploaded, so the publisher and
certificate claims here are as trustworthy as PyPI itself. Sightglass doesn't verify the Sigstore bundles
independently yet; ``Attestation.verified`` stays False until it does (see docs/research/pypi-publisher-data.md).
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.db.names import normalize_name
from sightglass.ecosystems.http import Fetcher, NotFoundError
from sightglass.ecosystems.pypi import PYPI_URL, IndexDataError
from sightglass.log import get_logger

log = get_logger(__name__)

SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"
INTEGRITY_JSON = "application/vnd.pypi.integrity.v1+json"
MAX_SIMPLE_SIZE = 64 * 1024 * 1024
MAX_PROVENANCE_SIZE = 4 * 1024 * 1024

# Fulcio certificate extensions (https://github.com/sigstore/fulcio/blob/main/docs/oid-info.md).
_CLAIM_OIDS = {
    "build_signer_uri": "1.3.6.1.4.1.57264.1.9",
    "runner_environment": "1.3.6.1.4.1.57264.1.11",
    "source_repository": "1.3.6.1.4.1.57264.1.12",
    "source_commit": "1.3.6.1.4.1.57264.1.13",
    "source_ref": "1.3.6.1.4.1.57264.1.14",
    "build_trigger": "1.3.6.1.4.1.57264.1.20",
    "run_url": "1.3.6.1.4.1.57264.1.21",
}


@dataclass(frozen=True)
class Publisher:
    """The trusted publisher PyPI recorded. Fields a publisher kind doesn't have are None, meaning unknown."""

    kind: str
    repository: str | None = None
    workflow: str | None = None
    environment: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class CertificateClaims:
    """Build facts from the signing certificate. None means the certificate doesn't say."""

    build_signer_uri: str | None = None
    runner_environment: str | None = None
    source_repository: str | None = None
    source_commit: str | None = None
    source_ref: str | None = None
    build_trigger: str | None = None
    run_url: str | None = None


@dataclass(frozen=True)
class Attestation:
    """One attestation bundle's publisher and claims."""

    publisher: Publisher
    claims: CertificateClaims
    predicate_type: str | None
    subject_sha256s: tuple[str, ...]
    verified: bool = False

    def covers(self, sha256: str) -> bool:
        """Whether this attestation's statement names an artifact with ``sha256``."""
        return sha256 in self.subject_sha256s


@dataclass(frozen=True)
class Provenance:
    """What PyPI published about one file: absent, or present with its attestations and the raw response."""

    status: Literal["absent", "present"]
    attestations: tuple[Attestation, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


ABSENT = Provenance("absent")


class _Publisher(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    repository: str | None = None
    workflow: str | None = None
    environment: str | None = None
    email: str | None = None


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: str


class _VerificationMaterial(BaseModel):
    model_config = ConfigDict(extra="ignore")
    certificate: str


class _Attestation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    envelope: _Envelope
    verification_material: _VerificationMaterial


class _Bundle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    publisher: _Publisher
    attestations: list[_Attestation]


class _ProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: int
    attestation_bundles: list[_Bundle]


class _SimpleFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    filename: str
    provenance: str | None = None


class _SimpleProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    files: list[_SimpleFile]


def _der_utf8(value: bytes) -> str | None:
    """Decode a DER UTF8String; older Fulcio extensions are raw strings, which are returned as is."""
    if len(value) >= 2 and value[0] == 0x0C:
        length, offset = value[1], 2
        if length & 0x80:
            n = length & 0x7F
            length, offset = int.from_bytes(value[2 : 2 + n], "big"), 2 + n
        body = value[offset : offset + length]
        if len(body) != length:
            return None
        value = body
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def parse_certificate(der_b64: str) -> CertificateClaims:
    """Read the Fulcio build claims from a base64 DER certificate.

    The certificate isn't validated; see the module docstring.

    Args:
        der_b64: The bundle's ``verification_material.certificate``.

    Returns:
        The claims present in the certificate; an unreadable certificate gives empty claims.
    """
    try:
        cert = x509.load_der_x509_certificate(base64.b64decode(der_b64, validate=True))
    except (binascii.Error, ValueError) as exc:
        log.warning("attestation_certificate_unreadable", error=str(exc))
        return CertificateClaims()
    claims: dict[str, str | None] = {}
    for name, oid in _CLAIM_OIDS.items():
        try:
            ext = cert.extensions.get_extension_for_oid(ObjectIdentifier(oid))
        except x509.ExtensionNotFound:
            continue
        raw = ext.value.value if isinstance(ext.value, x509.UnrecognizedExtension) else None
        claims[name] = _der_utf8(raw) if raw is not None else None
    return CertificateClaims(**claims)


def _statement(envelope_b64: str) -> tuple[str | None, tuple[str, ...]]:
    try:
        statement = json.loads(base64.b64decode(envelope_b64, validate=True))
        subjects = statement.get("subject", [])
        digests = tuple(
            s["digest"]["sha256"] for s in subjects if isinstance(s, dict) and "sha256" in s.get("digest", {})
        )
        predicate = statement.get("predicateType")
        return (predicate if isinstance(predicate, str) else None), digests
    except (binascii.Error, ValueError, TypeError, AttributeError, KeyError) as exc:
        log.warning("attestation_statement_unreadable", error=str(exc))
        return None, ()


def parse_provenance(payload: bytes) -> Provenance:
    """Parse an Integrity API provenance response.

    Args:
        payload: The body of ``/integrity/<project>/<version>/<file>/provenance``.

    Returns:
        A present provenance with one entry per attestation, keeping the raw response for storage.

    Raises:
        IndexDataError: If the payload doesn't match the Integrity API's shape.
    """
    try:
        raw = json.loads(payload)
        parsed = _ProvenanceResponse.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise IndexDataError(f"unexpected Integrity API response: {exc}") from exc
    attestations = []
    for bundle in parsed.attestation_bundles:
        p = bundle.publisher
        publisher = Publisher(p.kind, p.repository, p.workflow, p.environment or None, p.email)
        for att in bundle.attestations:
            predicate, subjects = _statement(att.envelope.statement)
            claims = parse_certificate(att.verification_material.certificate)
            attestations.append(Attestation(publisher, claims, predicate, subjects))
    return Provenance("present", tuple(attestations), raw)


class IntegrityClient:
    """Reads which files are attested (Simple API) and their attestations (Integrity API)."""

    def __init__(self, fetcher: Fetcher, base_url: str = PYPI_URL) -> None:
        """Use ``fetcher`` for every request.

        Args:
            fetcher: A fetcher whose allowed hosts include the index.
            base_url: The index root, without a trailing slash.
        """
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    def provenance_urls(self, project: str) -> dict[str, str | None]:
        """Map each of a project's files to its provenance URL, or None when the file isn't attested.

        Args:
            project: The project name, in any spelling.

        Returns:
            File name to provenance URL.

        Raises:
            IndexDataError: If the Simple API response doesn't have the expected shape.
            sightglass.ecosystems.http.HttpError: For request failures.
        """
        url = f"{self.base_url}/simple/{normalize_name('pypi', project)}/"
        body = self.fetcher.get_bytes(url, MAX_SIMPLE_SIZE, accept=SIMPLE_JSON)
        try:
            simple = _SimpleProject.model_validate_json(body)
        except ValidationError as exc:
            raise IndexDataError(f"unexpected Simple API response: {exc.error_count()} errors") from exc
        return {f.filename: f.provenance for f in simple.files}

    def provenance(self, project: str, version: str, filename: str) -> Provenance:
        """Fetch one file's provenance. A file with no attestation gives :data:`ABSENT`, not an error.

        Args:
            project: The project name, in any spelling.
            version: The release version.
            filename: The artifact's file name.

        Returns:
            The provenance, present or absent.

        Raises:
            IndexDataError: If the response doesn't match the Integrity API.
            sightglass.ecosystems.http.HttpError: For request failures other than 404.
        """
        url = f"{self.base_url}/integrity/{normalize_name('pypi', project)}/{version}/{filename}/provenance"
        try:
            body = self.fetcher.get_bytes(url, MAX_PROVENANCE_SIZE, accept=INTEGRITY_JSON)
        except NotFoundError:
            return ABSENT
        return parse_provenance(body)


def record_provenance(session: Session, artifact_id: int, provenance: Provenance) -> None:
    """Store a file's provenance: its status on the artifact, and one row per attestation with the raw response.

    Replaces any attestation rows stored earlier for the artifact.

    Args:
        session: The session to write through; the caller commits.
        artifact_id: The artifact the provenance belongs to.
        provenance: What the Integrity API returned.
    """
    session.execute(
        update(models.Artifact).where(models.Artifact.id == artifact_id).values(provenance_status=provenance.status)
    )
    session.query(models.Attestation).filter(models.Attestation.artifact_id == artifact_id).delete()
    for att in provenance.attestations:
        session.add(
            models.Attestation(
                artifact_id=artifact_id,
                publisher_kind=att.publisher.kind,
                repository=att.publisher.repository,
                workflow=att.publisher.workflow,
                environment=att.publisher.environment,
                service_account_email=att.publisher.email,
                source_commit=att.claims.source_commit,
                source_ref=att.claims.source_ref,
                runner_environment=att.claims.runner_environment,
                build_trigger=att.claims.build_trigger,
                run_url=att.claims.run_url,
                verified=att.verified,
                bundle=provenance.raw,
            )
        )
