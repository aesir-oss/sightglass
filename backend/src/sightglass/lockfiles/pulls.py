"""A public pull request's lockfile change, read through GitHub's REST API without the GitHub App.

The pull request names its head commit, the compare API gives the merge base (what "Files changed" diffs against),
and the files API says which lockfile changed. File contents come by commit from raw.githubusercontent.com, which
doesn't count against the REST rate limit. ``SIGHTGLASS_GITHUB_TOKEN`` raises that limit from 60 requests an hour.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from sightglass.ecosystems.github import Repository
from sightglass.ecosystems.http import USER_AGENT, Fetcher, MemoryCache, NotFoundError
from sightglass.lockfiles.pixi import MAX_LOCKFILE_SIZE
from sightglass.lockfiles.review import Snapshot, manifest_names

TOKEN_ENV = "SIGHTGLASS_GITHUB_TOKEN"
API_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})
MAX_API_SIZE = 8 * 1024 * 1024
MAX_MANIFEST_SIZE = 1024 * 1024
# The files API lists at most 3000 files, 100 to a page.
MAX_FILE_PAGES = 30
LOCKFILE_NAMES = ("pixi.lock", "uv.lock")
_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_PULL_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]{0,9})"
    r"(?:/[A-Za-z0-9_./-]*)?/?(?:[?#].*)?$"
)


class PullRequestError(Exception):
    """A pull request can't be reviewed, for a reason the person who asked can act on."""


class PullRequestNotFoundError(PullRequestError):
    """The pull request doesn't exist or isn't public."""


@dataclass(frozen=True)
class PullRequestRef:
    """A pull request named by its URL."""

    repository: Repository
    number: int


@dataclass(frozen=True)
class PullRequestChange:
    """A pull request's lockfile change: the commits to compare and the lockfile at each."""

    repository: str
    number: int
    base_sha: str
    head_sha: str
    lockfile_path: str
    base: Snapshot
    head: Snapshot


def parse_pull_url(url: str) -> PullRequestRef:
    """Read ``https://github.com/owner/name/pull/N`` (any tab of it).

    Raises:
        PullRequestError: If ``url`` isn't a GitHub pull request URL.
    """
    match = _PULL_URL_RE.match(url.strip())
    if match is None:
        raise PullRequestError("not a GitHub pull request URL, such as https://github.com/owner/name/pull/12")
    try:
        repository = Repository(match["owner"], match["name"].removesuffix(".git"))
    except ValueError as exc:
        raise PullRequestError(str(exc)) from exc
    return PullRequestRef(repository, int(match["number"]))


def choose_lockfile(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The changed lockfile to review: the shallowest, ``pixi.lock`` before ``uv.lock`` at the same depth."""
    lockfiles = [f for f in files if str(f.get("filename", "")).rsplit("/", 1)[-1] in LOCKFILE_NAMES]
    if not lockfiles:
        return None
    return min(
        lockfiles,
        key=lambda f: (
            f["filename"].count("/"),
            LOCKFILE_NAMES.index(f["filename"].rsplit("/", 1)[-1]),
            f["filename"],
        ),
    )


def _repository(full_name: object) -> str:
    """A repository's ``owner/name`` from an API response, checked before it goes into a URL."""
    owner, _, name = str(full_name).partition("/")
    try:
        return Repository(owner, name).slug
    except ValueError as exc:
        raise PullRequestError(f"GitHub returned an unexpected repository name {full_name!r}") from exc


def _sha(value: object) -> str:
    """A commit SHA from an API response, checked before it goes into a URL."""
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise PullRequestError(f"GitHub returned an unexpected commit {value!r}")
    return value


def default_fetcher() -> Fetcher:
    """A fetcher for the REST API and raw files, with the token when one is set and few retries."""
    headers = {"User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get(TOKEN_ENV):
        headers["Authorization"] = f"Bearer {token}"
    client = httpx.Client(headers=headers, timeout=30.0, follow_redirects=False)
    # A request waits for the answer, so a rate limit fails fast instead of backing off for long.
    return Fetcher(client, API_HOSTS, cache=MemoryCache(), max_attempts=2, max_backoff=5.0)


class PullRequestClient:
    """Reads a public pull request's lockfile change from GitHub."""

    def __init__(self, fetcher: Fetcher) -> None:
        """Use ``fetcher``, whose allowed hosts must include api.github.com and raw.githubusercontent.com."""
        self.fetcher = fetcher

    def _api(self, path: str) -> Any:
        body = self.fetcher.get_bytes(
            f"https://api.github.com{path}", MAX_API_SIZE, accept="application/vnd.github+json"
        )
        return json.loads(body)

    def _raw(self, slug: str, sha: str, path: str, max_size: int) -> bytes:
        return self.fetcher.get_bytes(f"https://raw.githubusercontent.com/{slug}/{sha}/{quote(path)}", max_size)

    def _snapshot(self, slug: str, sha: str, lockfile: str) -> Snapshot:
        content = self._raw(slug, sha, lockfile, MAX_LOCKFILE_SIZE)
        for name in manifest_names(lockfile):
            try:
                return Snapshot(content, (name, self._raw(slug, sha, name, MAX_MANIFEST_SIZE)))
            except NotFoundError:
                continue
        return Snapshot(content)

    def lockfile_change(self, ref: PullRequestRef) -> PullRequestChange:
        """Read the pull request, its merge base and its changed lockfile at both commits.

        Raises:
            PullRequestNotFoundError: If the pull request doesn't exist or isn't public.
            PullRequestError: If it changes no supported lockfile, or adds or removes the one it changes.
            sightglass.ecosystems.http.HttpError: If GitHub can't be reached or is rate limiting.
        """
        slug = ref.repository.slug
        try:
            pull = self._api(f"/repos/{slug}/pulls/{ref.number}")
        except NotFoundError as exc:
            raise PullRequestNotFoundError(f"no public pull request {slug}#{ref.number}") from exc
        base_repo = _repository(pull["base"]["repo"]["full_name"])
        # A deleted fork leaves no head repository; its commits stay reachable from the base.
        head_repo = _repository((pull["head"].get("repo") or {}).get("full_name") or base_repo)
        head_sha = _sha(pull["head"]["sha"])
        compare = self._api(f"/repos/{base_repo}/compare/{_sha(pull['base']['sha'])}...{head_sha}")
        base_sha = _sha(compare["merge_base_commit"]["sha"])
        files: list[dict[str, Any]] = []
        for page in range(1, MAX_FILE_PAGES + 1):
            batch = self._api(f"/repos/{base_repo}/pulls/{ref.number}/files?per_page=100&page={page}")
            files.extend(batch)
            if len(batch) < 100:
                break
        chosen = choose_lockfile(files)
        if chosen is None:
            raise PullRequestError(f"{base_repo}#{ref.number} doesn't change a pixi.lock or uv.lock")
        path = str(chosen["filename"])
        if chosen.get("status") in {"added", "removed"}:
            raise PullRequestError(f"{path} is {chosen['status']} by this pull request, so there's nothing to compare")
        before = str(chosen.get("previous_filename") or path)
        return PullRequestChange(
            repository=base_repo,
            number=ref.number,
            base_sha=base_sha,
            head_sha=head_sha,
            lockfile_path=path,
            base=self._snapshot(base_repo, base_sha, before),
            head=self._snapshot(head_repo, head_sha, path),
        )
