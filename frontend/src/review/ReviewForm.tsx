import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";
import { ApiError, createReview } from "../api/client";
import "./review.css";

/** A pull request URL in, its review page out: Sightglass reads the lockfile change from GitHub. */
export function ReviewForm() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const review = useMutation({
    mutationFn: createReview,
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["reviews"] });
      await queryClient.invalidateQueries({ queryKey: ["review"] });
      await navigate(`/reviews/${created.repository}/${String(created.number)}`);
    },
  });

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (url.trim()) review.mutate(url.trim());
  }

  return (
    <form onSubmit={submit} aria-label="Review a pull request" className="panel url-form">
      <label>
        <span>Pull request on GitHub</span>
        <input
          className="field"
          name="url"
          type="url"
          placeholder="https://github.com/owner/name/pull/12"
          autoComplete="off"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
          }}
          required
        />
      </label>
      <button type="submit" className="btn primary" disabled={review.isPending}>
        {review.isPending ? "Reading…" : "Review"}
      </button>
      {review.isError && (
        <p className="url-form-error" role="alert">
          {review.error instanceof ApiError ? review.error.message : "Sightglass couldn't start this review."}
        </p>
      )}
    </form>
  );
}
