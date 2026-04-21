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

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${resolveBaseUrl()}${path}`;
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, `HTTP ${res.status}`, detail);
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
