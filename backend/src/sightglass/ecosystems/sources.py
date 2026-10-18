"""Finding the source a release was built from: its repository, its commit, and an archive of that commit.

The rules follow docs/research/tag-discovery.md: an ordered list of tag patterns tried case-sensitively, with no loose
"any tag containing the version" fallback, then the commit a provenance attestation names. The tag comes first because
the attested commit is the one the publishing workflow ran on, which isn't always the one it built: packaging 26.3 was
published from a later commit that had already moved to 26.4.dev0. When nothing matches, the result says why the
source couldn't be compared instead of guessing.
"""

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sightglass import _core
from sightglass.db import models
from sightglass.db.names import normalize_name
from sightglass.ecosystems.github import GitHubClient, Repository
from sightglass.ecosystems.http import HttpError, NotFoundError
from sightglass.log import get_logger

log = get_logger(__name__)

_KEY_PREFERENCE = ("source", "source code", "repository", "code", "github", "homepage", "home")
_NON_SOURCE_KEYS = (
    "code of conduct",
    "funding",
    "sponsor",
    "donate",
    "documentation",
    "docs",
    "issue",
    "bug",
    "tracker",
)
_NOT_REPOSITORIES = {"sponsors", "orgs", "features", "apps", "marketplace", "topics", "settings"}
_GITHUB_URL_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", re.IGNORECASE)

Reason = Literal[
    "no_repository",
    "repository_not_found",
    "repository_unreachable",
    "no_matching_tag",
    "no_per_package_tags",
    "archive_unreadable",
    "archive_refused",
]


def find_repository(project_urls: dict[str, str], home_page: str | None = None) -> Repository | None:
    """Pick the GitHub repository a project links to, preferring source and repository links over others.

    Args:
        project_urls: The project's labelled URLs, from the index.
        home_page: The legacy home page field.

    Returns:
        The repository, or None if no usable GitHub link is listed.
    """
    urls = {key.strip().lower(): url for key, url in project_urls.items() if url}
    if home_page:
        urls.setdefault("home_page", home_page)

    def rank(key: str) -> int:
        return next((i for i, p in enumerate(_KEY_PREFERENCE) if key.startswith(p)), len(_KEY_PREFERENCE))

    for key in sorted(urls, key=rank):
        if key.startswith(_NON_SOURCE_KEYS):
            continue
        m = _GITHUB_URL_RE.match(urls[key].strip())
        if not m:
            continue
        owner, name = m.group(1), m.group(2).removesuffix(".git")
        if owner.lower() in _NOT_REPOSITORIES or name.lower() == ".github":
            continue
        try:
            return Repository(owner, name)
        except ValueError:
            log.warning("project_url_not_a_repository", key=key, url=urls[key])
    return None


def tag_candidates(project: str, version: str, repo_name: str) -> list[tuple[str, str]]:
    """Return ``(pattern, tag)`` pairs to try, in order, for a release.

    Args:
        project: The project name as published.
        version: The release version.
        repo_name: The repository's name, for monorepo patterns like ``{repo}-{version}``.

    Returns:
        Candidate tags with the pattern that produced each, most common patterns first.
    """
    normalized = normalize_name("pypi", project)
    names = list(dict.fromkeys([project, normalized, normalized.replace("-", "_")]))
    # A repository publishing several packages may tag them by the part after its own name: psycopg's `pool-3.3.1`.
    repo = normalize_name("pypi", repo_name)
    if normalized.startswith(f"{repo}-") and (short := normalized.removeprefix(f"{repo}-")):
        names.append(short)
    out = [("v{version}", f"v{version}"), ("{version}", version)]
    templates = ("{name}-v{version}", "{name}_{version}", "{name}=={version}", "{name}-{version}")
    for template in (*templates, "{name}/v{version}", "{name}/{version}"):
        out += [(template, template.format(name=n, version=version)) for n in names]
    if normalize_name("pypi", repo_name) != normalized:
        out += [("{repo}-{version}", f"{repo_name}-{version}"), ("{repo}-v{version}", f"{repo_name}-v{version}")]
    out += [
        ("release-{version}", f"release-{version}"),
        ("rel_{version_underscored}", "rel_" + version.replace(".", "_")),
    ]
    if version.count(".") == 1:
        out += [("v{version}.0", f"v{version}.0"), ("{version}.0", f"{version}.0")]
    return list(dict.fromkeys(out))


@dataclass(frozen=True)
class TagMatch:
    """A tag found for a release."""

    tag: str
    pattern: str
    commit: str


def match_tag(
    tags: dict[str, str], project: str, version: str, repo_name: str, preferred_pattern: str | None = None
) -> TagMatch | None:
    """Find the tag for a release among a repository's tags.

    Args:
        tags: Tag name to commit, from :meth:`GitHubClient.tags`.
        project: The project name as published.
        version: The release version.
        repo_name: The repository's name.
        preferred_pattern: The pattern that matched the project's previous release, tried first.

    Returns:
        The first candidate that exists, or None. When the project and repository names differ, a tag carrying the
        project's name comes first, even before the previous release's pattern: a repository that publishes several
        packages also has bare version tags, and they belong to another package (psycopg-pool's `pool-3.3.1` beside
        psycopg's `3.3.1`).
    """
    candidates = tag_candidates(project, version, repo_name)
    if normalize_name("pypi", project) != normalize_name("pypi", repo_name):
        for pattern, tag in candidates:
            if "{name}" in pattern and tag in tags:
                return TagMatch(tag, pattern, tags[tag])
    if preferred_pattern:
        candidates.sort(key=lambda c: c[0] != preferred_pattern)
    for pattern, tag in candidates:
        if tag in tags:
            return TagMatch(tag, pattern, tags[tag])
    return None


@dataclass(frozen=True)
class SourceSnapshot:
    """An archive of the commit a release was built from, indexed unless it was kept for the caller to extract."""

    repository: Repository
    commit: str
    ref: str | None
    origin: Literal["attestation", "tag"]
    tag_pattern: str | None
    archive_sha256: str
    entries: tuple[_core.ArchiveEntry, ...] = field(repr=False)
    prefix: str = ""
    # The downloaded archive, when it was kept in a work directory.
    archive: Path | None = None

    def relative_path(self, entry: _core.ArchiveEntry) -> str:
        """An entry's path with the archive's top-level ``<repo>-<commit>/`` directory removed."""
        return entry.path.removeprefix(self.prefix)


@dataclass(frozen=True)
class CouldNotCompare:
    """Why there is no source to compare a release with."""

    reason: Reason
    detail: str
    repository: Repository | None = None


def _common_prefix(entries: list[_core.ArchiveEntry]) -> str:
    tops = {e.path.split("/", 1)[0] for e in entries}
    if len(tops) == 1 and all("/" in e.path for e in entries):
        return tops.pop() + "/"
    return ""


def fetch_source(
    github: GitHubClient,
    *,
    project: str,
    version: str,
    repository: Repository | None,
    attested_commit: str | None = None,
    attested_ref: str | None = None,
    preferred_pattern: str | None = None,
    work_dir: Path | None = None,
    limits: _core.Limits | None = None,
) -> SourceSnapshot | CouldNotCompare:
    """Find, download and index the source a release was built from.

    Args:
        github: Client for the source host.
        project: The project name as published.
        version: The release version.
        repository: The repository from :func:`find_repository`, or the attestation's.
        attested_commit: The commit a provenance attestation names, used when no tag matches.
        attested_ref: The attestation's source ref, recorded with the snapshot.
        preferred_pattern: The tag pattern that matched the previous release.
        work_dir: Where to keep the archive for the caller to extract, unindexed; when None, a temporary directory
            and the snapshot carries the archive's index.
        limits: Unpacker limits for the archive.

    Returns:
        The indexed snapshot, or why the source couldn't be compared.
    """
    if repository is None:
        return CouldNotCompare("no_repository", "the project lists no GitHub repository")
    if normalize_name("pypi", project).startswith("types-") and repository.slug.lower() == "python/typeshed":
        return CouldNotCompare("no_per_package_tags", "typeshed stubs aren't tagged per package", repository)

    origin: Literal["attestation", "tag"]
    ref: str | None
    pattern: str | None
    match: TagMatch | None = None
    try:
        tags = github.tags(repository)
    except NotFoundError:
        failure = CouldNotCompare(
            "repository_not_found", f"{repository.slug} doesn't exist or isn't public", repository
        )
    except HttpError as exc:
        failure = CouldNotCompare("repository_unreachable", str(exc), repository)
    else:
        match = match_tag(tags, project, version, repository.name, preferred_pattern)
        tried = ", ".join(t for _, t in tag_candidates(project, version, repository.name)[:6])
        failure = CouldNotCompare("no_matching_tag", f"no tag matched (tried {tried}, ...)", repository)
    if match is not None:
        commit, ref, origin, pattern = match.commit, f"refs/tags/{match.tag}", "tag", match.pattern
    elif attested_commit:
        commit, ref, origin, pattern = attested_commit, attested_ref, "attestation", None
    else:
        return failure

    with tempfile.TemporaryDirectory(prefix="sg-source-") as tmp:
        dest = work_dir or Path(tmp)
        try:
            archive = github.download_archive(repository, commit, dest)
            # A kept archive is extracted by the caller, which checks every entry as it writes it; indexing it here
            # too would read a large repository twice.
            entries = [] if work_dir else _core.index_archive(archive.path, limits)
        except HttpError as exc:
            return CouldNotCompare("repository_unreachable", str(exc), repository)
        except _core.UnsafeArchiveError as exc:
            return CouldNotCompare("archive_refused", str(exc), repository)
        except _core.ArchiveFormatError as exc:
            return CouldNotCompare("archive_unreadable", str(exc), repository)
    return SourceSnapshot(
        repository=repository,
        commit=commit,
        ref=ref,
        origin=origin,
        tag_pattern=pattern,
        archive_sha256=archive.sha256,
        entries=tuple(entries),
        prefix=_common_prefix(entries),
        archive=archive.path if work_dir else None,
    )


def record_source_snapshot(session: Session, package_id: int, snapshot: SourceSnapshot) -> int:
    """Store a ``source_snapshot`` row, reusing the existing one for the same repository and commit.

    Args:
        session: The session to write through; the caller commits.
        package_id: The package the source belongs to.
        snapshot: The fetched snapshot.

    Returns:
        The row's id.
    """
    stmt = (
        insert(models.SourceSnapshot)
        .values(
            package_id=package_id,
            repository=snapshot.repository.slug,
            ref=snapshot.ref,
            commit=snapshot.commit,
            archive_sha256=snapshot.archive_sha256,
            origin=snapshot.origin,
            tag_pattern=snapshot.tag_pattern,
        )
        .on_conflict_do_update(
            index_elements=["package_id", "repository", "commit"],
            set_={"archive_sha256": snapshot.archive_sha256},
        )
        .returning(models.SourceSnapshot.id)
    )
    return int(session.execute(stmt).scalar_one())


def repository_from_attestation(source_repository: str | None) -> Repository | None:
    """Turn an attestation's ``https://github.com/<owner>/<repo>`` claim into a repository, if it is one."""
    if not source_repository:
        return None
    parts = urlsplit(source_repository)
    if (parts.hostname or "").lower() != "github.com":
        return None
    return find_repository({"source": source_repository})
