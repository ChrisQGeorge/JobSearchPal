"use client";

// Tiny client-side paginator. The dataset volumes here are user-scale
// (low thousands at most), so client-side slicing is cheaper than
// teaching every list endpoint to paginate. Page-size choice is
// persisted per-page via localStorage so the user's preference sticks.

import { useEffect, useMemo, useState } from "react";

export type PageSize = 10 | 30 | 100 | "all";

export const PAGE_SIZE_OPTIONS: PageSize[] = [10, 30, 100, "all"];

const DEFAULT_PAGE_SIZE: PageSize = 30;

function _parseSaved(raw: string | null): PageSize | null {
  if (raw === null) return null;
  if (raw === "all") return "all";
  const n = Number.parseInt(raw, 10);
  if (PAGE_SIZE_OPTIONS.includes(n as PageSize)) return n as PageSize;
  return null;
}

/**
 * Slice a list into a current page + manage page-size persistence.
 *
 * `storageKey` is appended to "jsp:paginate:" so different pages don't
 * stomp each other. Pass something stable per page (e.g. "jobs",
 * "organizations", "skills").
 *
 * Returns `visibleItems` (the current slice — the same `items` ref when
 * pageSize is "all"), plus `controls` to render at the bottom of the list.
 */
export function usePagination<T>(
  items: readonly T[],
  storageKey: string,
  defaultPageSize: PageSize = DEFAULT_PAGE_SIZE,
) {
  const [pageSize, setPageSizeState] = useState<PageSize>(() => {
    if (typeof window === "undefined") return defaultPageSize;
    return _parseSaved(window.localStorage.getItem(`jsp:paginate:${storageKey}`)) ?? defaultPageSize;
  });
  const [page, setPage] = useState(0);

  // Reset page when the dataset shrinks past the current cursor (e.g.
  // after applying a filter that drops most rows).
  useEffect(() => {
    if (pageSize === "all") {
      if (page !== 0) setPage(0);
      return;
    }
    const lastValidPage = Math.max(0, Math.ceil(items.length / pageSize) - 1);
    if (page > lastValidPage) setPage(lastValidPage);
  }, [items.length, pageSize, page]);

  function setPageSize(next: PageSize) {
    setPageSizeState(next);
    setPage(0);
    try {
      window.localStorage.setItem(
        `jsp:paginate:${storageKey}`,
        next === "all" ? "all" : String(next),
      );
    } catch {
      /* storage unavailable — non-fatal */
    }
  }

  const total = items.length;
  const visibleItems = useMemo(() => {
    if (pageSize === "all") return items;
    const start = page * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, page, pageSize]);

  const totalPages =
    pageSize === "all" ? 1 : Math.max(1, Math.ceil(total / pageSize));

  return {
    visibleItems,
    page,
    pageSize,
    setPage,
    setPageSize,
    total,
    totalPages,
  };
}

/** Visual paginator. Mounts at the bottom of a list — shows
 * "n-m of total", prev/next, jump-to-page, and the size selector. */
export function Paginator({
  page,
  pageSize,
  setPage,
  setPageSize,
  total,
  totalPages,
  className,
}: {
  page: number;
  pageSize: PageSize;
  setPage: (n: number) => void;
  setPageSize: (s: PageSize) => void;
  total: number;
  totalPages: number;
  className?: string;
}) {
  const start =
    pageSize === "all" || total === 0 ? (total === 0 ? 0 : 1) : page * pageSize + 1;
  const end =
    pageSize === "all"
      ? total
      : Math.min(total, page * pageSize + pageSize);

  const canPrev = pageSize !== "all" && page > 0;
  const canNext = pageSize !== "all" && page + 1 < totalPages;

  return (
    <div
      className={`flex flex-wrap items-center gap-2 mt-3 text-[11px] text-corp-muted ${
        className ?? ""
      }`}
      role="navigation"
      aria-label="Pagination"
    >
      <span className="tabular-nums">
        {total === 0 ? "0 rows" : `${start}-${end} of ${total}`}
      </span>
      <div className="flex items-center gap-1 ml-auto">
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={() => setPage(Math.max(0, page - 1))}
          disabled={!canPrev}
          aria-label="Previous page"
        >
          ← Prev
        </button>
        {pageSize !== "all" && totalPages > 1 ? (
          <span className="px-1 tabular-nums">
            page {page + 1} / {totalPages}
          </span>
        ) : null}
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
          disabled={!canNext}
          aria-label="Next page"
        >
          Next →
        </button>
      </div>
      <label className="flex items-center gap-1.5 ml-2">
        <span className="text-[10px] uppercase tracking-wider">Per page</span>
        <select
          className="jsp-input py-0.5 text-xs w-[5.5rem]"
          value={pageSize === "all" ? "all" : String(pageSize)}
          onChange={(e) => {
            const v = e.target.value;
            setPageSize(v === "all" ? "all" : (Number(v) as PageSize));
          }}
        >
          {PAGE_SIZE_OPTIONS.map((s) => (
            <option key={String(s)} value={s === "all" ? "all" : String(s)}>
              {s === "all" ? "All" : s}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
