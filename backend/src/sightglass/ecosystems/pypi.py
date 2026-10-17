"""PyPI client: release history from the JSON API, and verified artifact downloads.

Index responses are untrusted input: they are parsed with strict types, file names are checked before they touch the
file system, download URLs must be on an allowed host, and every artifact is checked against the hash and size the
index lists before it is used.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError

from sightglass.db.names import normalize_name
from sightglass.ecosystems.http import Fetcher, HttpError, MemoryCache, default_client
from sightglass.log import get_logger

log = get_logger(__name__)

PYPI_URL = "https://pypi.org"
PYPI_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
MAX_METADATA_SIZE = 64 * 1024 * 1024
DEFAULT_MAX_ARTIFACT_SIZE = 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 64 * 1024

ArtifactKind = Literal["wheel", "sdist", "other"]


class ArtifactIntegrityError(HttpError):
    """A downloaded artifact doesn't match the hash or size the index lists."""


class ArtifactTooLargeError(HttpError):
    """An artifact is larger than the caller's limit."""


class IndexDataError(HttpError):
    """The index returned data that doesn't have the expected shape."""


@dataclass(frozen=True)
class PypiFile:
    """One file of a release, as the index describes it."""

    filename: str
    url: str
    sha256: str
    size: int
    uploaded_at: datetime
    kind: ArtifactKind
    yanked: bool
    yanked_reason: str | None
    requires_python: str | None


@dataclass(frozen=True)
class PypiRelease:
    """One version and its files."""

    version: str
    files: tuple[PypiFile, ...]

    @property
    def published_at(self) -> datetime | None:
        """Upload time of the release's first file, or None for a release with no files."""
        return min((f.uploaded_at for f in self.files), default=None)

    @property
    def yanked(self) -> bool:
        """Whether every file of the release is yanked."""
        return bool(self.files) and all(f.yanked for f in self.files)


@dataclass(frozen=True)
class Ownership:
    """The organization and accounts PyPI lists for a project right now."""

    organization: str | None
    roles: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PypiProject:
    """A project and its release history, oldest first."""

    name: str
    normalized_name: str
    project_urls: dict[str, str]
    home_page: str | None
    ownership: Ownership | None
    releases: tuple[PypiRelease, ...]


class _File(BaseModel):
    model_config = ConfigDict(extra="ignore")
    filename: str
    url: str
    digests: dict[str, str]
    size: int
    upload_time_iso_8601: datetime
    packagetype: str
    yanked: bool = False
    yanked_reason: str | None = None
    requires_python: str | None = None


class _Info(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    project_urls: dict[str, str] | None = None
    home_page: str | None = None


class _Role(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    user: str


class _Ownership(BaseModel):
    model_config = ConfigDict(extra="ignore")
    organization: str | None = None
    roles: list[_Role] = []


class _Project(BaseModel):
    model_config = ConfigDict(extra="ignore")
    info: _Info
    releases: dict[str, list[_File]]
    ownership: _Ownership | None = None


def safe_filename(name: str) -> str:
    """Return ``name`` if it is safe to use as a file name in a download directory.

    Args:
        name: A file name from an index response.

    Returns:
        The same name.

    Raises:
        IndexDataError: If it is empty, a dot name, or contains a path separator or NUL.
    """
    if not name or name in {".", ".."} or any(c in name for c in "/\\\0") or name.startswith("."):
        raise IndexDataError(f"unsafe file name from index: {name!r}")
    return name


def _kind(packagetype: str) -> ArtifactKind:
    if packagetype == "bdist_wheel":
        return "wheel"
    if packagetype == "sdist":
        return "sdist"
    return "other"


def parse_project(payload: bytes) -> PypiProject:
    """Parse a JSON API project response.

    Files without a valid sha256 digest are dropped, because they can't be verified.

    Args:
        payload: The body of ``/pypi/<project>/json``.

    Returns:
        The project with releases ordered by publish time, oldest first; releases without files come last.

    Raises:
        IndexDataError: If the payload doesn't match the JSON API's shape.
    """
    try:
        raw = _Project.model_validate_json(payload)
    except ValidationError as exc:
        raise IndexDataError(f"unexpected JSON API response: {exc.error_count()} errors") from exc
    releases = []
    for version, files in raw.releases.items():
        kept = []
        for f in files:
            sha256 = f.digests.get("sha256", "")
            if not _SHA256_RE.match(sha256):
                log.warning("pypi_file_without_sha256", project=raw.info.name, filename=f.filename)
                continue
            kept.append(
                PypiFile(
                    filename=safe_filename(f.filename),
                    url=f.url,
                    sha256=sha256,
                    size=f.size,
                    uploaded_at=f.upload_time_iso_8601,
                    kind=_kind(f.packagetype),
                    yanked=f.yanked,
                    yanked_reason=f.yanked_reason,
                    requires_python=f.requires_python,
                )
            )
        releases.append(PypiRelease(version, tuple(sorted(kept, key=lambda f: f.filename))))
    releases.sort(key=lambda r: (r.published_at is None, r.published_at or datetime.min, r.version))
    ownership = (
        Ownership(raw.ownership.organization, tuple((r.user, r.role) for r in raw.ownership.roles))
        if raw.ownership
        else None
    )
    return PypiProject(
        name=raw.info.name,
        normalized_name=normalize_name("pypi", raw.info.name),
        project_urls=raw.info.project_urls or {},
        home_page=raw.info.home_page,
        ownership=ownership,
        releases=tuple(releases),
    )


class PypiClient:
    """Reads project metadata from PyPI and downloads artifacts with verification."""

    def __init__(self, fetcher: Fetcher, base_url: str = PYPI_URL) -> None:
        """Use ``fetcher`` for every request.

        Args:
            fetcher: A fetcher whose allowed hosts include the index and its file host.
            base_url: The index root, without a trailing slash.
        """
        self.fetcher = fetcher
        self.base_url = base_url.rstrip("/")

    @classmethod
    def default(cls) -> Self:
        """A client for pypi.org with the default HTTP settings and an in-process response cache."""
        return cls(Fetcher(default_client(), PYPI_HOSTS, cache=MemoryCache()))

    def project(self, name: str) -> PypiProject:
        """Fetch a project's release history.

        Args:
            name: The project name, in any spelling; it is normalized before the request.

        Returns:
            The parsed project.

        Raises:
            sightglass.ecosystems.http.NotFoundError: If PyPI has no such project.
            IndexDataError: If the response doesn't match the JSON API.
            HttpError: For any other request failure.
        """
        url = f"{self.base_url}/pypi/{normalize_name('pypi', name)}/json"
        return parse_project(self.fetcher.get_bytes(url, MAX_METADATA_SIZE, accept="application/json"))

    def download(self, file: PypiFile, dest_dir: Path, max_size: int = DEFAULT_MAX_ARTIFACT_SIZE) -> Path:
        """Download an artifact into ``dest_dir`` and verify it against the index.

        The file is written under a temporary name and renamed only after its size and sha256 match, so a path in
        ``dest_dir`` named after an artifact always holds verified content.

        Args:
            file: The artifact, from :meth:`project`.
            dest_dir: Existing directory to write into.
            max_size: Largest artifact accepted, in bytes.

        Returns:
            The path of the verified file.

        Raises:
            ArtifactTooLargeError: If the index lists, or the server sends, more than ``max_size`` bytes.
            ArtifactIntegrityError: If the size or sha256 don't match the index.
            HttpError: For request failures, including a URL on a host that isn't allowed.
        """
        filename = safe_filename(file.filename)
        if file.size > max_size:
            raise ArtifactTooLargeError(f"{filename} is {file.size} bytes, over the {max_size} limit")
        fd, tmp_name = tempfile.mkstemp(dir=dest_dir, prefix=".download-")
        tmp_path = Path(tmp_name)
        try:
            hasher = hashlib.sha256()
            received = 0
            with os.fdopen(fd, "wb") as out, self.fetcher.stream(file.url) as response:
                for chunk in response.iter_bytes(_CHUNK):
                    received += len(chunk)
                    if received > file.size:
                        raise ArtifactIntegrityError(f"{filename}: server sent more than the {file.size} bytes listed")
                    hasher.update(chunk)
                    out.write(chunk)
            if received != file.size:
                raise ArtifactIntegrityError(f"{filename}: received {received} bytes, index lists {file.size}")
            if hasher.hexdigest() != file.sha256:
                raise ArtifactIntegrityError(f"{filename}: sha256 {hasher.hexdigest()} doesn't match the index")
            dest = dest_dir / filename
            os.replace(tmp_path, dest)
        finally:
            tmp_path.unlink(missing_ok=True)
        log.info("pypi_downloaded", filename=filename, size=received)
        return dest
