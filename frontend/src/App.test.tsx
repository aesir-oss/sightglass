import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { App } from "./App";

afterEach(cleanup);

test("renders the product name as the page heading", () => {
  render(<App />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sightglass");
});
