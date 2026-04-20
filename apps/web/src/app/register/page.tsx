"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { UserOut } from "@/lib/types";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post<UserOut>("/api/v1/auth/register", {
        email,
        display_name: displayName,
        password,
      });
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError("That email is already enrolled. Try signing in instead.");
        } else if (err.status === 422) {
          setError("Please check your inputs. Password must be at least 10 characters.");
        } else {
          setError(`Enrollment failed (${err.status}).`);
        }
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
          <div className="text-xs text-corp-muted uppercase tracking-wider">
            New Associate Enrollment
          </div>
          <h1 className="text-2xl font-semibold text-corp-accent">Create account</h1>
          <p className="text-xs text-corp-muted mt-1">
            Your data stays on this deployment. Honest.
          </p>
        </div>

        <div>
          <label className="jsp-label" htmlFor="displayName">Display name</label>
          <input
            id="displayName"
            type="text"
            className="jsp-input"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
          />
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
          <label className="jsp-label" htmlFor="password">Password (≥ 10 chars)</label>
          <input
            id="password"
            type="password"
            className="jsp-input"
            autoComplete="new-password"
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {error ? <div className="text-sm text-corp-danger">{error}</div> : null}

        <button type="submit" className="jsp-btn-primary w-full" disabled={submitting}>
          {submitting ? "Enrolling..." : "Enroll"}
        </button>

        <p className="text-xs text-corp-muted text-center">
          Already have an account?{" "}
          <Link href="/login" className="text-corp-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}
