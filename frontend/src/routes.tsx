// Page routes mirror the API paths without /api.
import type { RouteObject } from "react-router";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ReleaseDiffPage } from "./pages/ReleaseDiffPage";

export const routes: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  // `<from>...<to>`, or one version compared with the release before it.
  { path: "/:ecosystem/:package/:versions", element: <ReleaseDiffPage /> },
  { path: "*", element: <NotFoundPage /> },
];
