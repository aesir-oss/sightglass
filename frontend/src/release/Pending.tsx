import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, retryPairAnalysis, type Artifact } from "../api/client";
import type { PairPending } from "../api/types";
import "./release.css";

const LABELS: Record<string, string> = {
  downloading: "Downloading and unpacking",
  provenance: "Reading attestations",
  diffing: "Comparing files",
  source: "Checking the source",
  rules: "Running the rules",
};

/** Progress of a queued or running analysis: which step it is on. The page polls while it is pending. */
export function Progress({ pending }: { pending: PairPending }) {
  const current = pending.step ? pending.steps.indexOf(pending.step) : -1;
  return (
    <div className="notice" role="status">
      <p style={{ margin: 0 }}>
        {current < 0 ? "Queued: " : "Analyzing: "}
        {pending.artifact.old_filename} and {pending.artifact.new_filename}. This page updates when it is done.
      </p>
      <ol className="steps" aria-label="Analysis steps">
        {pending.steps.map((step, i) => {
          const state = i < current ? "done" : i === current ? "current" : "todo";
          return (
            <li key={step} data-state={state} aria-current={state === "current" ? "step" : undefined}>
              {state === "done" ? "✓ " : ""}
              {LABELS[step] ?? step}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface FailedProps {
  ecosystem: string;
  pkg: string;
  versions: string;
  artifact: Artifact;
  error: string | null | undefined;
}

/** A failed analysis: the reason, and a button that queues it again. */
export function Failed({ ecosystem, pkg, versions, artifact, error }: FailedProps) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryPairAnalysis(ecosystem, pkg, versions, artifact),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pair", ecosystem, pkg] });
    },
  });
  return (
    <div className="notice" data-tone="warn" role="alert">
      <p style={{ margin: 0 }}>This pair couldn&apos;t be analyzed: {error}</p>
      <p style={{ margin: "8px 0 0" }}>
        <button
          type="button"
          disabled={retry.isPending}
          onClick={() => {
            retry.mutate();
          }}
        >
          {retry.isPending ? "Retrying…" : "Retry"}
        </button>{" "}
        {retry.isError && (retry.error instanceof ApiError ? retry.error.message : "The retry couldn't be started.")}
      </p>
    </div>
  );
}
