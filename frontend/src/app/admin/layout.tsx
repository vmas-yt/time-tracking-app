"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { ADMIN_SECTIONS } from "./nav";

/** Admin area shell: an always-on left sidebar sub-nav (mirrors the active
 * `NavBar`'s pill-tab tokens — `rounded-xl`, `bg-primary`/`text-on-primary`
 * for the active item — rather than introducing a second nav vocabulary)
 * plus the admin-only route gate. Every `/admin/*` page renders inside this
 * shell; the gate lives here so a non-admin hitting any admin URL sees the
 * same "Admin access required" message the old single-page `/admin` showed,
 * with no sidebar chrome rendered around it. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user: currentUser, authState } = useAuth();
  const pathname = usePathname();

  // AuthGate already guarantees `authState === "authenticated"` here — this
  // is "authenticated but not authorized" (a real, logged-in non-admin
  // hitting /admin), which is fine to render inline rather than redirect
  // away from (design doc §8.3).
  if (authState === "loading" || !currentUser) {
    return <main className="mx-auto max-w-6xl px-6 py-8 text-sm text-mute">Loading…</main>;
  }
  if (currentUser.role !== "admin") {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="rounded-xl bg-negative-bg px-4 py-3 text-sm text-canvas">
          Admin access required — log in as an admin to manage swim lanes, custom fields, and user roles.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-6xl gap-8 px-6 py-8">
      <aside className="w-52 shrink-0 space-y-4">
        <h1 className="px-3 text-2xl font-bold tracking-tight text-ink">Admin</h1>
        <nav className="space-y-1">
          {ADMIN_SECTIONS.map(({ href, label }) => {
            const active = pathname === href || pathname?.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "block rounded-xl px-3 py-2 text-sm font-semibold transition-colors",
                  active ? "bg-primary text-on-primary" : "text-body hover:bg-canvas-soft"
                )}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="min-w-0 flex-1 space-y-6">{children}</div>
    </main>
  );
}
