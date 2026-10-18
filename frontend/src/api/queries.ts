// TanStack Query hooks for the API. A pending pair is polled until its analysis is done.
import { QueryClient, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  fetchFileDiff,
  fetchPairAnalysis,
  fetchReleaseHistory,
  fetchReview,
  fetchReviews,
  type Artifact,
} from "./client";
import type { Review } from "./types";

export const POLL_MS = 3000;

/** Poll every POLL_MS while the analysis is pending; stop once it is done or failed. */
export function pollWhilePending(data: { status: string } | undefined): number | false {
  return data?.status === "pending" ? POLL_MS : false;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        // Client errors (unknown package or version) won't change on retry.
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}

export function useReleaseHistory(ecosystem: string, pkg: string) {
  return useQuery({
    queryKey: ["releases", ecosystem, pkg],
    queryFn: () => fetchReleaseHistory(ecosystem, pkg),
  });
}

export function usePairAnalysis(ecosystem: string, pkg: string, versions: string, artifact: Artifact = {}) {
  return useQuery({
    queryKey: ["pair", ecosystem, pkg, versions, artifact.kind ?? null, artifact.wheel ?? null],
    queryFn: () => fetchPairAnalysis(ecosystem, pkg, versions, artifact),
    refetchInterval: (query) => pollWhilePending(query.state.data),
  });
}

export function useFileDiff(
  ecosystem: string,
  pkg: string,
  versions: string,
  path: string | null,
  base: "previous" | "source",
  artifact: Artifact = {},
) {
  return useQuery({
    queryKey: ["file", ecosystem, pkg, versions, path, base, artifact.kind ?? null, artifact.wheel ?? null],
    queryFn: () => fetchFileDiff(ecosystem, pkg, versions, path ?? "", base, artifact),
    enabled: path !== null,
  });
}

/** Poll every POLL_MS while any change's analysis is still pending. */
export function pollWhileAnalyzing(data: Review | undefined): number | false {
  return data?.changes.some((c) => c.analysis.state === "pending") ? POLL_MS : false;
}

export function useReviews() {
  return useQuery({ queryKey: ["reviews"], queryFn: fetchReviews });
}

export function useReview(owner: string, repo: string, number: number) {
  return useQuery({
    queryKey: ["review", owner, repo, number],
    queryFn: () => fetchReview(owner, repo, number),
    refetchInterval: (query) => pollWhileAnalyzing(query.state.data),
    enabled: Number.isInteger(number) && number > 0,
  });
}
