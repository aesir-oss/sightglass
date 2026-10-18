// Page routes mirror the API paths without /api.
import type { RouteObject } from "react-router";
import { ErrorPage } from "./pages/ErrorPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PackagePage } from "./pages/PackagePage";
import { ReleaseDiffPage } from "./pages/ReleaseDiffPage";
import { ReviewPage } from "./pages/ReviewPage";
import { ReviewsPage } from "./pages/ReviewsPage";

const pages: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  // Each reviewed pull request, newest first.
  { path: "/reviews", element: <ReviewsPage /> },
  // A pull request's lockfile review.
  { path: "/reviews/:owner/:repo/:number", element: <ReviewPage /> },
  // The newest release compared with the one before it.
  { path: "/:ecosystem/:package", element: <PackagePage /> },
  // `<from>...<to>`, or one version compared with the release before it.
  { path: "/:ecosystem/:package/:versions", element: <ReleaseDiffPage /> },
  { path: "*", element: <NotFoundPage /> },
];

// A page that throws while rendering shows the error page rather than React Router's developer screen.
export const routes: RouteObject[] = pages.map((route) => ({ ...route, errorElement: <ErrorPage /> }));
