// Thin fetch wrapper that always sends cookies and surfaces structured errors.

// LAN-friendly API URL resolution:
//   1. If NEXT_PUBLIC_API_URL is set at build time, use it verbatim.
//   2. Otherwise, on the client, derive from window.location so the API is
//      reached on the same host the browser used — works for localhost access
//      and access from other devices on the LAN.
//   3. Server-side fallback (never actually called in this app) is localhost.
const API_PORT =
  process.env.NEXT_PUBLIC_API_PORT && process.env.NEXT_PUBLIC_API_PORT.trim()
    ? process.env.NEXT_PUBLIC_API_PORT
    : "8000";

function resolveBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  if (fromEnv && fromEnv.trim()) return fromEnv.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
  }
  return `http://localhost:${API_PORT}`;
}

/** Absolute URL builder — used for APIs consumed via EventSource or iframe. */
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
