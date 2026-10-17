"""GitHub as a source host: tag lists from git's ref advertisement, and archives by commit.

Tags come from the same request ``git ls-remote`` makes, so no API token or REST rate limit is involved.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sightglass.ecosystems.http import Fetcher, HttpError
from sightglass.log import get_logger

log = get_logger(__name__)

GITHUB_HOSTS = frozenset({"github.com", "codeload.github.com"})
MAX_REFS_SIZE = 32 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RefsFormatError(HttpError):
    """The ref advertisement isn't valid pkt-line data."""


class ArchiveTooLargeError(HttpError):
    """A source archive exceeded the size limit."""


@dataclass(frozen=True)
class Repository:
    """A GitHub repository."""

    owner: str
    name: str

    def __post_init__(self) -> None:
        """Refuse owner or repository names that could change the URLs built from them."""
        for part in (self.owner, self.name):
            if not _NAME_RE.match(part) or part in {".", ".."}:
                raise ValueError(f"invalid GitHub name: {part!r}")

    @property
    def slug(self) -> str:
        """``owner/name``."""
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class SourceArchive:
    """A downloaded archive of one commit."""

    path: Path
    sha256: str
    size: int


def parse_ref_advertisement(body: bytes) -> dict[str, str]:
    """Parse a smart-HTTP ``git-upload-pack`` ref advertisement into tag name to commit.

    Annotated tags resolve to the commit they point at (the ``^{}`` peeled line), not to the tag object.

    Args:
        body: The response of ``info/refs?service=git-upload-pack``.

    Returns:
        Tag name (without ``refs/tags/``) to commit SHA.

    Raises:
        RefsFormatError: If the body isn't pkt-line data.
    """
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    pos = 0
    while pos < len(body):
        try:
            length = int(body[pos : pos + 4], 16)
        except ValueError as exc:
            raise RefsFormatError(f"bad pkt-line length at byte {pos}") from exc
        if length == 0:
            pos += 4
            continue
        if length < 4 or pos + length > len(body):
            raise RefsFormatError(f"truncated pkt-line at byte {pos}")
        line = body[pos + 4 : pos + length].split(b"\0", 1)[0].rstrip(b"\n").decode("utf-8", "replace")
        pos += length
        sha, _, ref = line.partition(" ")
        if not ref.startswith("refs/tags/") or not _COMMIT_RE.match(sha):
            continue
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name.removesuffix("^{}")] = sha
        else:
            tags[name] = sha
    return {name: peeled.get(name, sha) for name, sha in tags.items()}


class GitHubClient:
    """Lists tags and downloads commit archives from GitHub."""

    def __init__(self, fetcher: Fetcher) -> None:
        """Use ``fetcher``, whose allowed hosts must include github.com and codeload.github.com."""
        self.fetcher = fetcher

    def tags(self, repo: Repository) -> dict[str, str]:
        """Return every tag of ``repo`` with the commit it points at.

        Raises:
            sightglass.ecosystems.http.NotFoundError: If the repository doesn't exist or isn't public.
            RefsFormatError: If the response isn't a ref advertisement.
            HttpError: For other request failures.
        """
        url = f"https://github.com/{repo.slug}.git/info/refs?service=git-upload-pack"
        body = self.fetcher.get_bytes(url, MAX_REFS_SIZE, accept="application/x-git-upload-pack-advertisement")
        return parse_ref_advertisement(body)

    def download_archive(
        self, repo: Repository, commit: str, dest_dir: Path, max_size: int = DEFAULT_MAX_ARCHIVE_SIZE
    ) -> SourceArchive:
        """Download the ``.tar.gz`` archive of one commit into ``dest_dir``.

        Args:
            repo: The repository.
            commit: Full commit SHA; branch and tag names aren't accepted, so the archive is immutable.
            dest_dir: Existing directory to write into.
            max_size: Largest archive accepted, in bytes.

        Returns:
            The archive's path, sha256 and size.

        Raises:
            ValueError: If ``commit`` isn't a full SHA.
            ArchiveTooLargeError: If the archive exceeds ``max_size``.
            HttpError: For request failures.
        """
        if not _COMMIT_RE.match(commit):
            raise ValueError(f"not a full commit SHA: {commit!r}")
        url = f"https://codeload.github.com/{repo.slug}/tar.gz/{commit}"
        fd, tmp_name = tempfile.mkstemp(dir=dest_dir, prefix=".source-")
        tmp_path = Path(tmp_name)
        try:
            hasher = hashlib.sha256()
            size = 0
            with os.fdopen(fd, "wb") as out, self.fetcher.stream(url) as response:
                for chunk in response.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > max_size:
                        raise ArchiveTooLargeError(f"{repo.slug}@{commit} archive exceeds {max_size} bytes")
                    hasher.update(chunk)
                    out.write(chunk)
            dest = dest_dir / f"{repo.owner}-{repo.name}-{commit}.tar.gz"
            os.replace(tmp_path, dest)
        finally:
            tmp_path.unlink(missing_ok=True)
        log.info("github_archive_downloaded", repository=repo.slug, commit=commit, size=size)
        return SourceArchive(dest, hasher.hexdigest(), size)
