// Page routes mirror the API paths without /api.
import type { RouteObject } from "react-router";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PackagePage } from "./pages/PackagePage";
import { ReleaseDiffPage } from "./pages/ReleaseDiffPage";
import { ReviewPage } from "./pages/ReviewPage";

export const routes: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  // A pull request's lockfile review.
  { path: "/reviews/:owner/:repo/:number", element: <ReviewPage /> },
  // The newest release compared with the one before it.
  { path: "/:ecosystem/:package", element: <PackagePage /> },
  // `<from>...<to>`, or one version compared with the release before it.
  { path: "/:ecosystem/:package/:versions", element: <ReleaseDiffPage /> },
  { path: "*", element: <NotFoundPage /> },
];
