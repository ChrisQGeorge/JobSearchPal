"use client";

// SWR setup. One place to configure caching + a tiny helper so pages
// don't have to repeat the same `useSWR("/api/v1/...", api.get)` boilerplate.
//
// Why we cache: every previous page rendered did `useEffect(() =>
// api.get(...))` on mount, so switching back to a page you'd just left
// always paid the full network roundtrip. With SWR the cached response
// renders instantly while a background revalidation keeps it fresh.

import { ReactNode } from "react";
import useSWR, { SWRConfig, type SWRConfiguration, type SWRResponse } from "swr";
import { api } from "./api";

// Tuned for "switching between pages should be instant":
//   - revalidateOnFocus OFF — refetching every time the user clicks back
//     into the tab is more flicker than insight.
//   - revalidateOnReconnect ON — coming back from network blips should refresh.
//   - keepPreviousData ON — show stale rows while the new request is in
//     flight instead of going blank, so the table doesn't flash empty.
//   - dedupingInterval 2 s — coalesces the typical render-twice-in-a-row case
//     React's Strict Mode produces in dev.
const DEFAULTS: SWRConfiguration = {
  revalidateOnFocus: false,
  revalidateOnReconnect: true,
  keepPreviousData: true,
  dedupingInterval: 2000,
  shouldRetryOnError: false,
};

export function SwrProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ ...DEFAULTS, fetcher: ((path: string) => api.get(path)) as SWRConfiguration["fetcher"] }}>
      <HotListPrefetcher />
      {children}
    </SWRConfig>
  );
}

/**
 * Mount-once helper that warms the SWR cache for the lists the user is
 * likely to open during a session — review queue + apply queue. Renders
 * nothing visible; the prefetched data lands in the SWR cache so the
 * consuming pages render from cache on first visit.
 */
function HotListPrefetcher() {
  usePrefetchHotLists();
  return null;
}

/**
 * Thin wrapper around useSWR that types the response and uses the shared
 * fetcher. Pass `null` as the key to skip — same semantics as raw SWR.
 *
 * Returned shape matches SWRResponse so callers can also reach for
 * `mutate`, `isValidating`, `isLoading`, etc.
 */
export function useApi<T>(
  key: string | null | false,
): SWRResponse<T, Error> {
  return useSWR<T, Error>(key, ((path: string) => api.get<T>(path)) as never);
}

/**
 * Background-warm the lists the user is *likely* to open during a
 * session. Lives in the app layout so the cache is populated as soon
 * as they enter the app — by the time they click into /jobs/pipeline,
 * both queues are already in memory.
 *
 * Concretely we prefetch the review + apply queues here. Adding more
 * endpoints to this hook is the right place to widen the warming set.
 */
export function usePrefetchHotLists(): void {
  // Use the same SWR cache keys the consuming pages use; the call here
  // populates the cache and the consumer's useApi gets a cache hit on
  // first render. The data itself is discarded — we don't render any
  // of it from the layout.
  useSWR("/api/v1/jobs/review-queue", ((p: string) => api.get(p)) as never);
  useSWR("/api/v1/jobs/apply-queue", ((p: string) => api.get(p)) as never);
}
