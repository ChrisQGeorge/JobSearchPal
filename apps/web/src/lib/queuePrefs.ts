/** Shared preference for the review / apply workflows: only cycle through
 * jobs that already have a fit score. Persisted in localStorage under one
 * key so the pipeline panels' toggle and the job-detail "Next →" nav
 * (which fetches the same queues) always agree on what "next" means. */

const KEY = "jsp:queues:scored_only";

export function getScoredOnly(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setScoredOnly(v: boolean): void {
  try {
    window.localStorage.setItem(KEY, v ? "1" : "0");
  } catch {
    /* storage blocked — session-only behavior, non-fatal */
  }
}

/** Query-string suffix for the review-queue / apply-queue endpoints. */
export function scoredOnlyParam(): string {
  return getScoredOnly() ? "?scored_only=true" : "";
}
