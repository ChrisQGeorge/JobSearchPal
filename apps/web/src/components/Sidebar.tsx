"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/timeline", label: "Career Timeline" },
  { href: "/history", label: "History Editor" },
  { href: "/organizations", label: "Organizations" },
  { href: "/jobs", label: "Job Tracker" },
  { href: "/leads", label: "Job Leads" },
  { href: "/jobs/review", label: "Review Queue" },
  { href: "/jobs/apply", label: "Apply Queue" },
  { href: "/inbox", label: "Email Inbox" },
  { href: "/browser", label: "Browser" },
  { href: "/applications", label: "Applications" },
  { href: "/auto-apply", label: "Auto-Apply" },
  { href: "/answers", label: "Answer Bank" },
  { href: "/queue", label: "Companion Activity" },
  { href: "/studio", label: "Document Studio" },
  { href: "/samples", label: "Writing Samples" },
  { href: "/cover-letter-library", label: "Cover Letter Library" },
  { href: "/companion", label: "Companion" },
  { href: "/preferences", label: "Preferences & Identity" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Close drawer on route change.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // The nav entry whose href is the longest prefix of the current path wins.
  // Without this, `/jobs/review` lights up both "Job Tracker" and "Review
  // Queue" because both pass `startsWith`.
  const activeHref = (() => {
    if (!pathname) return null;
    if (pathname === "/") return "/";
    let best: string | null = null;
    for (const item of NAV) {
      if (item.href === "/") continue;
      if (pathname === item.href || pathname.startsWith(item.href + "/")) {
        if (!best || item.href.length > best.length) best = item.href;
      }
    }
    return best;
  })();

  const navItems = (
    <nav className="flex-1 py-3" aria-label="Primary navigation">
      {NAV.map((item) => {
        const active = item.href === activeHref;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`block px-4 py-2 text-sm transition-colors ${
              active
                ? "bg-corp-surface2 text-corp-accent border-l-2 border-corp-accent"
                : "text-corp-text hover:bg-corp-surface2"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  const brandBlock = (
    <div className="px-4 py-5 border-b border-corp-border">
      <div className="text-sm text-corp-muted uppercase tracking-wider">
        Career Development Division
      </div>
      <div className="text-lg font-semibold text-corp-accent">Job Search Pal</div>
    </div>
  );

  const footer = (
    <div className="px-4 py-3 border-t border-corp-border text-xs text-corp-muted">
      v0.1 · Not for the weak of career
    </div>
  );

  return (
    <>
      {/* Mobile top bar — hamburger + current section label */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-30 flex items-center justify-between bg-corp-surface border-b border-corp-border px-3 py-2">
        <button
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          className="jsp-btn-ghost text-xs"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Close" : "Menu"}
        </button>
        <div className="text-sm font-semibold text-corp-accent">Job Search Pal</div>
        <div className="w-16" />
      </div>

      {/* Mobile drawer */}
      {open ? (
        <button
          type="button"
          aria-label="Close navigation backdrop"
          className="md:hidden fixed inset-0 z-20 bg-black/60"
          onClick={() => setOpen(false)}
        />
      ) : null}
      <aside
        className={`md:hidden fixed top-0 left-0 bottom-0 z-30 w-60 border-r border-corp-border bg-corp-surface flex flex-col transition-transform duration-200 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {brandBlock}
        {navItems}
        {footer}
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-60 shrink-0 border-r border-corp-border bg-corp-surface min-h-screen flex-col">
        {brandBlock}
        {navItems}
        {footer}
      </aside>
    </>
  );
}
