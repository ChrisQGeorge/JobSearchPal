"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/timeline", label: "Career Timeline" },
  { href: "/history", label: "History Editor" },
  { href: "/organizations", label: "Organizations" },
  { href: "/jobs", label: "Job Tracker" },
  { href: "/studio", label: "Document Studio" },
  { href: "/samples", label: "Writing Samples" },
  { href: "/companion", label: "Companion" },
  { href: "/preferences", label: "Preferences & Identity" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-60 shrink-0 border-r border-corp-border bg-corp-surface min-h-screen flex flex-col">
      <div className="px-4 py-5 border-b border-corp-border">
        <div className="text-sm text-corp-muted uppercase tracking-wider">
          Career Development Division
        </div>
        <div className="text-lg font-semibold text-corp-accent">Job Search Pal</div>
      </div>
      <nav className="flex-1 py-3">
        {NAV.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
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
      <div className="px-4 py-3 border-t border-corp-border text-xs text-corp-muted">
        v0.1 · Not for the weak of career
      </div>
    </aside>
  );
}
