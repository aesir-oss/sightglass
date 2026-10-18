import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { ErrorPage } from "./ErrorPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Boom(): never {
  throw new Error('Duplicate key "orbit-2.0-cp310.whl" found in collection.');
}

test("a page that throws shows what failed and a way back", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const router = createMemoryRouter([{ path: "/", element: <Boom />, errorElement: <ErrorPage /> }]);
  render(<RouterProvider router={router} />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Something went wrong on this page");
  expect(screen.getByText(/Duplicate key/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Back to the start page" }).getAttribute("href")).toBe("/");
});

test("a thrown value that isn't an Error shows no details", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const router = createMemoryRouter([
    {
      path: "/",
      element: null,
      loader: () => {
        // React Router lets loaders throw Responses; this checks a non-Error value shows no details.
        // eslint-disable-next-line @typescript-eslint/only-throw-error
        throw new Response("nope", { status: 500 });
      },
      errorElement: <ErrorPage />,
    },
  ]);
  render(<RouterProvider router={router} />);
  return screen.findByRole("alert").then(() => {
    expect(screen.queryByText("Details")).toBeNull();
  });
});
