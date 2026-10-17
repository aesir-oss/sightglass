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

test("auto is the default and the current choice is checked", () => {
  render(<ThemeSwitch />);
  const group = screen.getByRole("group", { name: "Theme" });
  expect(group).toBeTruthy();
  expect(screen.getByRole<HTMLInputElement>("radio", { name: "Auto" }).checked).toBe(true);
});

test("choosing light or dark applies and remembers it; auto clears the override", () => {
  render(<ThemeSwitch />);
  fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(screen.getByRole<HTMLInputElement>("radio", { name: "Dark" }).checked).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: "Light" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  fireEvent.click(screen.getByRole("radio", { name: "Auto" }));
  expect(document.documentElement.dataset.theme).toBeUndefined();
  expect(localStorage.getItem(THEME_KEY)).toBeNull();
});

test("a saved choice is read back; anything else is auto", () => {
  localStorage.setItem(THEME_KEY, "dark");
  expect(savedTheme()).toBe("dark");
  render(<ThemeSwitch />);
  expect(screen.getByRole<HTMLInputElement>("radio", { name: "Dark" }).checked).toBe(true);
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
