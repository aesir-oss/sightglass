// A fetch client typed from the generated OpenAPI schema, and the calls the pages make.
import createClient from "openapi-fetch";
import type { paths } from "./schema";
import type { FileDiff, PairAnalysis, PairPending, ReleaseHistory, Review } from "./types";

export const api = createClient<paths>({
  // Same origin as the page; the dev server proxies /api to FastAPI.
  baseUrl: globalThis.location.origin,
  // Looked up per request rather than captured once, so tests can replace it.
  fetch: (request) => globalThis.fetch(request),
});

/** An API error with the HTTP status and the server's detail message. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detail(error: unknown, status: number): ApiError {
  const message =
    typeof error === "object" && error !== null && "detail" in error && typeof error.detail === "string"
      ? error.detail
      : `request failed with status ${String(status)}`;
  return new ApiError(status, message);
}

export interface Artifact {
  kind?: "wheel" | "sdist";
  wheel?: string;
}

export async function fetchReleaseHistory(ecosystem: string, pkg: string): Promise<ReleaseHistory> {
  const { data, error, response } = await api.GET("/api/{ecosystem}/{package}/releases", {
    params: { path: { ecosystem, package: pkg } },
  });
  if (!data) throw detail(error, response.status);
  return data;
}

export async function fetchReview(owner: string, repo: string, number: number): Promise<Review> {
  const { data, error, response } = await api.GET("/api/reviews/{owner}/{repo}/{number}", {
    params: { path: { owner, repo, number } },
  });
  if (!data) throw detail(error, response.status);
  return data;
}

export async function fetchPairAnalysis(
  ecosystem: string,
  pkg: string,
  versions: string,
  artifact: Artifact = {},
): Promise<PairAnalysis | PairPending> {
  const { data, error, response } = await api.GET("/api/{ecosystem}/{package}/{versions}", {
    params: { path: { ecosystem, package: pkg, versions }, query: artifact },
  });
  if (!data) throw detail(error, response.status);
  return data;
}

export async function fetchFileDiff(
  ecosystem: string,
  pkg: string,
  versions: string,
  path: string,
  base: "previous" | "source",
  artifact: Artifact = {},
): Promise<FileDiff> {
  const { data, error, response } = await api.GET("/api/{ecosystem}/{package}/{versions}/files/{path}", {
    params: { path: { ecosystem, package: pkg, versions, path }, query: { base, ...artifact } },
  });
  if (!data) throw detail(error, response.status);
  return data;
}

/** The artifact choice from a page's `?kind=` and `?wheel=` query parameters. */
export function artifactFromSearch(search: URLSearchParams): Artifact {
  const artifact: Artifact = {};
  const kind = search.get("kind");
  if (kind === "wheel" || kind === "sdist") artifact.kind = kind;
  const wheel = search.get("wheel");
  if (wheel) artifact.wheel = wheel;
  return artifact;
}

export async function retryPairAnalysis(
  ecosystem: string,
  pkg: string,
  versions: string,
  artifact: Artifact = {},
): Promise<PairPending> {
  const { data, error, response } = await api.POST("/api/{ecosystem}/{package}/{versions}/retry", {
    params: { path: { ecosystem, package: pkg, versions }, query: artifact },
  });
  if (!data) throw detail(error, response.status);
  return data;
}
