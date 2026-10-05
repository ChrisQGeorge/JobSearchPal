// Thin fetch wrapper that always sends cookies and surfaces structured errors.
//
// API URLs are same-origin by default — the web server (Next.js) proxies
// /api/* and /health/* to the api container via rewrites in next.config.mjs.
// That way the browser only ever talks to WEB_PORT, CORS isn't a concern,
// and changing API_PORT in .env doesn't require a frontend rebuild.
//
// NEXT_PUBLIC_API_URL remains an escape hatch: if set, requests go there
// instead of the relative path. Useful when fronting with a reverse proxy
// that doesn't sit on the same origin.
function resolveBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  if (fromEnv && fromEnv.trim()) return fromEnv.replace(/\/$/, "");
  return ""; // relative → same-origin → proxied via Next.js rewrites.
}

/** Absolute-or-relative URL builder — used for APIs consumed via EventSource,
 * iframes, or <a href>. Relative paths work fine for same-origin proxying. */
export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${resolveBaseUrl()}${path}`;
}

/** Structured error block every API error response carries (see
 * apps/api/app/core/errors.py). */
export type ApiErrorInfo = {
  code: string;
  message: string;
  hint?: string | null;
  request_id?: string | null;
  path?: string | null;
};

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  info: ApiErrorInfo;
  constructor(status: number, message: string, detail?: unknown, info?: ApiErrorInfo) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.info = info ?? { code: `HTTP_${status}`, message };
  }
}

/** Fired on window for server-side failures (5xx / unreachable) so the
 * app-wide error banner can show what went wrong. */
export const API_ERROR_EVENT = "jsp:api-error";

function emitApiError(status: number, info: ApiErrorInfo) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, { detail: { status, ...info } }));
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${resolveBaseUrl()}${path}`;
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(url, {
      ...options,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  } catch (e) {
    const info: ApiErrorInfo = {
      code: "NETWORK_ERROR",
      message: `Couldn't reach the server (${e instanceof Error ? e.message : "network error"}).`,
      hint: "Check that the server is up and your connection to it works.",
      path: `${method} ${path}`,
    };
    emitApiError(0, info);
    throw new ApiError(0, info.message, undefined, info);
  }
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = await res.json();
    } catch {
      /* non-JSON body */
    }
    const block =
      detail && typeof detail === "object" && "error" in detail
        ? ((detail as { error: ApiErrorInfo }).error as ApiErrorInfo)
        : null;
    let info: ApiErrorInfo;
    if (block?.code) {
      info = { ...block, path: block.path ?? `${method} ${path}` };
    } else if (res.status >= 500) {
      // No structured body: the request never got an answer from the API
      // process — the web server's proxy produced this status itself.
      info = {
        code: "API_UNREACHABLE",
        message: `The API server didn't answer (proxy returned ${res.status}).`,
        hint:
          "The API is down, restarting, or too busy to respond. Open /health/deep " +
          "for diagnostics, or check `docker logs jsp-api`.",
        request_id: res.headers.get("x-request-id"),
        path: `${method} ${path}`,
      };
    } else {
      const d = (detail as { detail?: unknown } | undefined)?.detail;
      info = {
        code: `HTTP_${res.status}`,
        message: typeof d === "string" ? d : `HTTP ${res.status}`,
        path: `${method} ${path}`,
      };
    }
    if (res.status >= 500) emitApiError(res.status, info);
    throw new ApiError(res.status, `${info.code}: ${info.message}`, detail, info);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/**
 * Run `fn` over `items` with at most `limit` in flight at once, mirroring
 * Promise.allSettled's result shape (settled in input order).
 *
 * Why this exists: bulk actions (tailor / status-change across a multi-select)
 * used to fire every request at once via Promise.allSettled. Selecting ~25
 * jobs × 2 doc types = 50 simultaneous POSTs, each holding a DB pool
 * connection — well past the API's 30-connection pool, so the pool times out
 * and unrelated requests (even /auth/me) 500 in the crossfire. Capping
 * concurrency keeps the burst under the pool ceiling while still parallelizing.
 */
export async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let cursor = 0;
  const worker = async (): Promise<void> => {
    while (cursor < items.length) {
      const i = cursor++;
      try {
        results[i] = { status: "fulfilled", value: await fn(items[i], i) };
      } catch (reason) {
        results[i] = { status: "rejected", reason };
      }
    }
  };
  const workers = Array.from(
    { length: Math.max(1, Math.min(limit, items.length)) },
    () => worker(),
  );
  await Promise.all(workers);
  return results;
}
