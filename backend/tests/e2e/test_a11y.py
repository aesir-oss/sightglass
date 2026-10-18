"""Phone layout and accessibility of the start page and the release diff page, in a real browser."""

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

VIEWPORTS = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 360, "height": 780}}
PAIR = "/pypi/orbit-client/2.4.1...2.5.0"
REVIEW = "/reviews/kestrel-weather/orbit/7"
PAGES = {
    "start": "/",
    "pair": PAIR,
    "pair, a file selected": f"{PAIR}?file=orbit%2Ftelemetry.py",
    "review": REVIEW,
}


def open_page(page: Page, path: str) -> None:
    """Open a page and wait until it has its content."""
    page.goto(path)
    if path.startswith(PAIR):
        expect(page.get_by_role("region", name="Signals")).to_be_visible()
    elif path.startswith(REVIEW):
        expect(page.get_by_role("listbox", name="Package changes")).to_be_visible()
    else:
        expect(page.get_by_role("heading", level=1)).to_be_visible()


@pytest.mark.e2e
@pytest.mark.parametrize("name", list(PAGES))
def test_no_horizontal_page_scroll_at_360(page: Page, name: str) -> None:
    """At 360 px wide nothing makes the page itself scroll sideways (wide charts scroll inside their panel)."""
    page.set_viewport_size(VIEWPORTS["phone"])
    open_page(page, PAGES[name])
    widths = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert widths[0] <= widths[1], f"page is {widths[0]} px wide in a {widths[1]} px viewport"


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("name", list(PAGES))
def test_no_axe_violations(
    page: Page, axe: Callable[[Any], list[dict[str, Any]]], name: str, viewport: str, theme: str
) -> None:
    """Axe finds no WCAG 2.1 A or AA violations, in either theme, on desktop or phone."""
    page.set_viewport_size(VIEWPORTS[viewport])
    page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    open_page(page, PAGES[name])
    assert axe(page) == []


FOCUS_STYLE = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const visible = (node) => {
    const s = getComputedStyle(node);
    return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
  };
  const svg = el instanceof SVGElement;
  const control = el.closest(".picker-control");
  return {
    tag: el.tagName.toLowerCase(),
    name: el.getAttribute("aria-label") || el.textContent.trim().slice(0, 40),
    svg,
    visible: svg || visible(el) || (control !== null && visible(control)),
  };
}"""


@pytest.mark.e2e
def test_keyboard_reaches_every_section_with_visible_focus(page: Page) -> None:
    """Tabbing through the pair page reaches each section's controls, and every focused control shows focus."""
    page.set_viewport_size(VIEWPORTS["desktop"])
    open_page(page, PAIR)
    stops: list[dict[str, Any]] = []
    for _ in range(40):
        page.keyboard.press("Tab")
        stop = page.evaluate(FOCUS_STYLE)
        if stop is None:
            break
        stops.append(stop)
    names = [s["name"] for s in stops]
    hidden = [s["name"] for s in stops if not s["visible"]]
    assert hidden == [], f"focus isn't visible on: {hidden}"
    for expected in ("Copy link", "Map", "Previous release"):
        assert expected in names, f"{expected!r} wasn't reachable by Tab; reached {names}"
    assert any(n.startswith("2.5.0,") for n in names), "the timeline isn't reachable by Tab"
    assert any(n.startswith("orbit/telemetry.py") for n in names), "the evidence link or file map isn't reachable"
    assert sum(1 for s in stops if s["tag"] == "input") >= 2, "the version pickers aren't reachable"
