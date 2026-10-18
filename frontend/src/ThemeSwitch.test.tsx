import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { applyTheme, savedTheme, THEME_KEY } from "./theme";
import { ThemeSwitch } from "./ThemeSwitch";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const button = () => screen.getByRole("button", { name: /^Theme: / });

test("auto is the default, and the button names the current choice", () => {
  render(<ThemeSwitch />);
  expect(button().getAttribute("aria-label")).toBe("Theme: Auto");
  expect(button().getAttribute("title")).toBe("Theme: Auto. Switch to Light.");
});

test("each press steps light, dark, auto; light and dark are remembered and auto clears the override", () => {
  render(<ThemeSwitch />);
  fireEvent.click(button());
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem(THEME_KEY)).toBe("light");
  fireEvent.click(button());
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(button().getAttribute("aria-label")).toBe("Theme: Dark");
  fireEvent.click(button());
  expect(document.documentElement.dataset.theme).toBeUndefined();
  expect(localStorage.getItem(THEME_KEY)).toBeNull();
  expect(button().getAttribute("aria-label")).toBe("Theme: Auto");
});

test("a saved choice is read back; anything else is auto", () => {
  localStorage.setItem(THEME_KEY, "dark");
  expect(savedTheme()).toBe("dark");
  render(<ThemeSwitch />);
  expect(button().getAttribute("aria-label")).toBe("Theme: Dark");
  localStorage.setItem(THEME_KEY, "sepia");
  expect(savedTheme()).toBe("auto");
});

test("blocked storage falls back to auto and still applies the choice to the page", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(savedTheme()).toBe("auto");
  applyTheme("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});
