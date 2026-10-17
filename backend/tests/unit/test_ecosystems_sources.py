"""Tests for repository discovery and tag matching, with no network."""

import pytest

from sightglass.ecosystems.github import Repository
from sightglass.ecosystems.sources import (
    TagMatch,
    find_repository,
    match_tag,
    repository_from_attestation,
    tag_candidates,
)

C = "c" * 40
ORBIT = Repository("kestrel-weather", "orbit-client")


@pytest.mark.parametrize(
    ("urls", "home", "expected"),
    [
        ({"Source": "https://github.com/kestrel-weather/orbit-client"}, None, ORBIT),
        ({"Repository": "https://github.com/kestrel-weather/orbit-client.git"}, None, ORBIT),
        ({"Code": "https://www.github.com/kestrel-weather/orbit-client/tree/main/src"}, None, ORBIT),
        ({"Homepage": "https://github.com/kestrel-weather/orbit-client#readme"}, None, ORBIT),
        ({}, "https://github.com/kestrel-weather/orbit-client", ORBIT),
        (
            {
                "Homepage": "https://github.com/kestrel-weather/website",
                "Source": "https://github.com/kestrel-weather/orbit-client",
            },
            None,
            ORBIT,
        ),
        (
            {
                "Code of Conduct": "https://github.com/kestrel-weather/.github/blob/main/CODE_OF_CONDUCT.md",
                "Changelog": "https://github.com/kestrel-weather/orbit-client/blob/main/CHANGES.md",
            },
            None,
            ORBIT,
        ),
        ({"Documentation": "https://github.com/kestrel-weather/orbit-docs"}, None, None),
        ({"Funding": "https://github.com/sponsors/kestrel-dev"}, None, None),
        ({"Source": "https://github.com/kestrel-weather/.github"}, None, None),
        ({"Source": "https://gitlab.example.net/kestrel/orbit"}, None, None),
        ({"Source": ""}, None, None),
        ({"Source": "https://github.com/kestrel-weather/orbit%20client"}, None, None),
    ],
)
def test_find_repository(urls: dict[str, str], home: str | None, expected: Repository | None) -> None:
    """Source links win over home pages; docs, funding, conduct and org-profile links are skipped."""
    assert find_repository(urls, home) == expected


def test_tag_candidates_order() -> None:
    """The most common patterns come first, then name and repo variants, then rarer forms and .0 padding."""
    candidates = [tag for _, tag in tag_candidates("Orbit_Client", "2.5", "orbit")]
    assert candidates[:2] == ["v2.5", "2.5"]
    assert "Orbit_Client-v2.5" in candidates and "orbit-client-v2.5" in candidates and "orbit_client_2.5" in candidates
    assert candidates.index("orbit-2.5") > candidates.index("orbit-client/2.5")
    assert candidates[-4:] == ["release-2.5", "rel_2_5", "v2.5.0", "2.5.0"]
    assert len(candidates) == len(set(candidates))


def test_repo_patterns_only_when_repo_name_differs() -> None:
    """``{repo}-{version}`` is only tried when the repository isn't named after the package."""
    patterns = {p for p, _ in tag_candidates("orbit-client", "1.0.0", "orbit-client")}
    assert "{repo}-{version}" not in patterns
    assert "{version}.0" not in patterns


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"v2.5.0": C}, TagMatch("v2.5.0", "v{version}", C)),
        ({"2.5.0": C, "v2.5.0": "d" * 40}, TagMatch("v2.5.0", "v{version}", "d" * 40)),
        ({"orbit-client-v2.5.0": C}, TagMatch("orbit-client-v2.5.0", "{name}-v{version}", C)),
        ({"orbit_client_2.5.0": C}, TagMatch("orbit_client_2.5.0", "{name}_{version}", C)),
        ({"V2.5.0": C}, None),
        ({"2.5.0rc1": C, "py-2.5.0": C}, None),
    ],
)
def test_match_tag(tags: dict[str, str], expected: TagMatch | None) -> None:
    """Matching is ordered and case-sensitive, with no loose fallback."""
    assert match_tag(tags, "orbit-client", "2.5.0", "orbit-client") == expected


def test_preferred_pattern_is_tried_first() -> None:
    """The pattern that matched the previous release wins when several tags exist."""
    tags = {"v2.5.0": C, "orbit-client-2.5.0": "d" * 40}
    match = match_tag(tags, "orbit-client", "2.5.0", "orbit-client", preferred_pattern="{name}-{version}")
    assert match == TagMatch("orbit-client-2.5.0", "{name}-{version}", "d" * 40)


def test_package_named_tag_wins_in_a_repository_of_several_packages() -> None:
    """A tag carrying the package's name beats the repository's bare version tag, even the previous release's."""
    tags = {"3.3.1": C, "pool-3.3.1": "d" * 40}
    match = match_tag(tags, "psycopg-pool", "3.3.1", "psycopg", preferred_pattern="{version}")
    assert match == TagMatch("pool-3.3.1", "{name}-{version}", "d" * 40)
    assert match_tag({"3.3.1": C}, "psycopg-pool", "3.3.1", "psycopg") == TagMatch("3.3.1", "{version}", C)


def test_one_package_repository_keeps_bare_version_tags() -> None:
    """A repository named after its package uses v{version} or {version}; a repository with another name too."""
    assert match_tag({"v1.2.0": C}, "orbit-client", "1.2.0", "orbit-client") == TagMatch("v1.2.0", "v{version}", C)
    assert match_tag({"1.2.0": C}, "python-dateutil", "1.2.0", "dateutil") == TagMatch("1.2.0", "{version}", C)


def test_padded_two_part_version() -> None:
    """A two-part version can match a tag padded with .0."""
    assert match_tag({"3.11.0": C}, "tidepool", "3.11", "tidepool") == TagMatch("3.11.0", "{version}.0", C)


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("https://github.com/kestrel-weather/orbit-client", ORBIT),
        ("https://gitlab.com/kestrel/orbit", None),
        (None, None),
    ],
)
def test_repository_from_attestation(claim: str | None, expected: Repository | None) -> None:
    """Only GitHub source repository claims become repositories."""
    assert repository_from_attestation(claim) == expected
