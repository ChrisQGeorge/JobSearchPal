"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { UserOut } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post<UserOut>("/api/v1/auth/login", { email, password });
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "Invalid email or password." : `Error: ${err.status}`);
      } else {
        setError("Unexpected error.");
      }
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={onSubmit} className="jsp-card p-8 w-full max-w-sm space-y-4">
        <div>
          <div className="text-xs text-corp-muted uppercase tracking-wider">Personnel Access</div>
          <h1 className="text-2xl font-semibold text-corp-accent">Sign in</h1>
          <p className="text-xs text-corp-muted mt-1">
            Credentials are required to access your career record.
          </p>
        </div>

        <div>
          <label className="jsp-label" htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            className="jsp-input"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="jsp-label" htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="jsp-input"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {error ? <div className="text-sm text-corp-danger">{error}</div> : null}

        <button type="submit" className="jsp-btn-primary w-full" disabled={submitting}>
          {submitting ? "Authenticating..." : "Sign in"}
        </button>

        <p className="text-xs text-corp-muted text-center">
          No account?{" "}
          <Link href="/register" className="text-corp-accent hover:underline">
            Enroll
          </Link>
        </p>
      </form>
    </main>
  );
}
