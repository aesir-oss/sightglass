"""End-to-end flows on the release diff page, on desktop and phone: pending, done and error states."""

import re

import pytest
from playwright.sync_api import Page, expect

VIEWPORTS = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 360, "height": 780}}
DONE = "/pypi/orbit-client/2.4.1...2.5.0"
# Each viewport gets a pair of its own, so one run's analysis doesn't make the other's page already done.
PENDING = {"desktop": "/pypi/orbit-client/2.5.0...2.6.0", "phone": "/pypi/orbit-client/2.4.1...2.6.0"}
VIEWPORT_NAMES = list(VIEWPORTS)


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_pending_pair_updates_when_the_analysis_finishes(page: Page, live: object, viewport: str) -> None:
    """A new pair is queued, the page says so, and it shows the analysis once a worker finishes it."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto(PENDING[viewport])
    expect(page.get_by_role("status").filter(has_text="Queued")).to_be_visible()
    expect(page.get_by_role("list", name="Analysis steps")).to_be_visible()
    live.run_queued()  # type: ignore[attr-defined]
    # The page polls every few seconds; no reload.
    expect(page.get_by_role("region", name="Signals")).to_be_visible(timeout=15_000)
    expect(page.get_by_role("region", name="Release facts")).to_be_visible()


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_done_pair_signals_files_and_diff(page: Page, viewport: str) -> None:
    """The analyzed pair shows its signals; evidence and file selection drive the diff, and the base toggles."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto(DONE)
    signals = page.get_by_role("region", name="Signals")
    expect(signals).to_contain_text("orbit/telemetry.py isn't in tag v2.5.0")
    expect(signals).to_contain_text("requests.post")

    signals.get_by_role("link", name=re.compile(r"orbit\/telemetry\.py:5")).first.click()
    expect(page).to_have_url(re.compile(r"file=orbit%2Ftelemetry\.py&line=5"))
    diff = page.get_by_role("region", name="Diff", exact=True)
    expect(diff.locator("tr.hit")).to_contain_text("requests.post")

    files = page.get_by_role("region", name="Files")
    files.get_by_role("button", name=re.compile(r"^orbit\/__init__\.py, changed")).click()
    expect(page).to_have_url(re.compile(r"file=orbit%2F__init__\.py"))
    expect(diff).to_contain_text("compared with release 2.4.1")
    diff.get_by_role("button", name="Source").click()
    expect(diff).to_contain_text("compared with tag v2.5.0 (src/orbit/__init__.py)")
    expect(diff).to_contain_text("The contents are identical.")

    files.get_by_role("button", name="List").click()
    expect(files.get_by_role("list", name="Files").get_by_role("button").first).to_contain_text("orbit/telemetry.py")


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_versions_change_from_the_timeline_and_pickers(page: Page, viewport: str) -> None:
    """Choosing releases from the timeline or the pickers navigates to that pair."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto(DONE)
    page.get_by_role("button", name=re.compile(r"^2\.6\.0,")).click()
    expect(page).to_have_url(re.compile(r"/pypi/orbit-client/2\.5\.0\.\.\.2\.6\.0$"))
    page.goto(DONE)
    page.get_by_role("button", name=re.compile(r"Show compare versions")).click()
    page.get_by_role("option", name="2.6.0").click()
    expect(page).to_have_url(re.compile(r"/pypi/orbit-client/2\.6\.0\.\.\.2\.5\.0$"))


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_unknown_package_and_version(page: Page, viewport: str) -> None:
    """Unknown packages and versions say so plainly."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto("/pypi/tidepool/1.0...1.1")
    expect(page.get_by_role("alert")).to_have_text("tidepool isn't on PyPI")
    page.goto("/pypi/orbit-client/2.4.1...9.9.9")
    expect(page.get_by_role("alert")).to_contain_text("has no release '9.9.9'")


@pytest.mark.e2e
def test_failed_analysis_can_be_retried(page: Page, live: object) -> None:
    """A pair whose download doesn't match the index fails with the reason; Retry queues it again."""
    page.goto("/pypi/orbit-client/2.6.0...2.7.0")
    expect(page.get_by_role("status").filter(has_text="Queued")).to_be_visible()
    live.run_queued()  # type: ignore[attr-defined]
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("ArtifactIntegrityError", timeout=15_000)
    with page.expect_response(lambda r: r.url.endswith("/retry")) as retried:
        alert.get_by_role("button", name="Retry").click()
    assert retried.value.status == 202, retried.value.text()
    expect(page.get_by_role("status").filter(has_text="Queued")).to_be_visible()
    assert len(live.queued) == 1  # type: ignore[attr-defined]
    live.queued.clear()  # type: ignore[attr-defined]


@pytest.mark.e2e
def test_start_page_and_package_page(page: Page) -> None:
    """The start page compares two releases; a package without versions opens its newest release."""
    page.goto("/")
    page.get_by_label("PyPI package").fill("orbit-client")
    page.get_by_label("Releases", exact=True).fill("2.4.1...2.5.0")
    page.get_by_role("button", name="Compare").click()
    expect(page).to_have_url(re.compile(r"/pypi/orbit-client/2\.4\.1\.\.\.2\.5\.0$"))
    expect(page.get_by_role("region", name="Signals")).to_be_visible()
    page.goto("/pypi/orbit-client")
    expect(page).to_have_url(re.compile(r"/pypi/orbit-client/2\.7\.0$"))


@pytest.mark.e2e
def test_theme_choice_persists_and_applies_before_render(page: Page) -> None:
    """The theme button steps to Dark, which stays across reloads and is set before render; Auto hands back."""
    page.emulate_media(color_scheme="light")
    page.goto(DONE)
    theme = page.get_by_role("button", name=re.compile(r"^Theme: "))
    expect(theme).to_have_accessible_name("Theme: Auto")
    theme.click()
    theme.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    # The pre-paint script in index.html sets the theme from storage before the app's bundle runs.
    page.reload(wait_until="domcontentloaded")
    assert page.evaluate("() => document.documentElement.dataset.theme") == "dark"
    expect(theme).to_have_accessible_name("Theme: Dark")
    assert page.evaluate("() => getComputedStyle(document.body).backgroundColor") == background
    theme.click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", re.compile(r".+"))
    page.reload()
    expect(theme).to_have_accessible_name("Theme: Auto")


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_long_history_scrolls_and_opens_at_the_pair(page: Page, viewport: str) -> None:
    """A long release history keeps its spacing, scrolls sideways, and opens with the compared pair in view."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto("/pypi/longhaul/1.0.148...1.0.149")
    timeline = page.get_by_role("group", name="Timeline of longhaul releases")
    expect(timeline).to_be_visible()
    marks = timeline.get_by_role("button")
    expect(marks).to_have_count(150)
    sizes = page.evaluate(
        """() => { const el = document.querySelector(".tl");
                   return [el.scrollWidth, el.clientWidth, el.scrollLeft]; }"""
    )
    assert sizes[0] > 4000 and sizes[0] > sizes[1] and sizes[2] > 0
    first, second = marks.nth(0).bounding_box(), marks.nth(1).bounding_box()
    assert first is not None and second is not None and second["x"] - first["x"] >= 25
    newest = marks.last.bounding_box()
    width = VIEWPORTS[viewport]["width"]
    assert newest is not None and 0 <= newest["x"] <= width


@pytest.mark.e2e
@pytest.mark.parametrize("viewport", VIEWPORT_NAMES)
def test_review_queue_with_keyboard_and_platform_filter(page: Page, viewport: str) -> None:
    """The review queue puts the analyzed change first; arrow keys move the selection and a platform filters it."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto("/reviews/kestrel-weather/orbit/7")
    queue = page.get_by_role("listbox", name="Package changes")
    options = queue.get_by_role("option")
    expect(options).to_have_count(2)
    expect(options.first).to_contain_text("orbit-client")
    expect(options.first).to_have_attribute("aria-selected", "true")
    detail = page.get_by_role("region", name="Package detail")
    expect(detail.get_by_role("link")).to_have_attribute("href", "/pypi/orbit-client/2.4.1...2.5.0")
    options.first.focus()
    page.keyboard.press("ArrowDown")
    expect(options.nth(1)).to_have_attribute("aria-selected", "true")
    expect(page).to_have_url(re.compile(r"package=conda%3Atidepool"))
    expect(detail).to_contain_text("not every platform the environment resolves")
    page.get_by_role("button", name="osx-arm64").click()
    expect(options).to_have_count(1)
