import { CompanionDock } from "@/components/CompanionDock";
import { Sidebar } from "@/components/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      {/* On mobile the top hamburger bar is fixed at 40px (py-2 + text) — push
          content down so it doesn't hide under it. Desktop leaves this at 0. */}
      <main className="flex-1 min-w-0 pt-10 md:pt-0">{children}</main>
      <CompanionDock />
    </div>
  );
}
