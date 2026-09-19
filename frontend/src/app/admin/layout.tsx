"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { ADMIN_SECTIONS } from "./nav";

/** Admin area shell: an always-on left sidebar sub-nav (mirrors the active
 * `NavBar`'s pill-tab tokens — `rounded-xl`, `bg-primary`/`text-on-primary`
 * for the active item — rather than introducing a second nav vocabulary)
 * plus the route gate. Every `/admin/*` page renders inside this shell.
 *
 * Round C QA found this gate still checked `role !== "admin"` literally —
 * the exact bug Round B3/C's `can_manage`/`has_permission()` work was meant
 * to eliminate, just one layer up: a custom role holding e.g.
 * `manage_board_config` could `PATCH /teams/{id}/board-config` directly but
 * could never reach `/admin/swim-lanes` in the first place to do so through
 * the UI. Fixed by letting in anyone holding *any* grantable permission
 * (via their assigned role's `permission_keys`, `GET /roles` — open-read,
 * §2.1 of the custom-roles design), not just a floor admin. Each individual
 * admin page still gates its own actions with its own permission check
 * (`can_manage`, `assert_has_permission`, etc.) exactly as before — this
 * only decides whether the *shell* renders at all instead of the "Admin
 * access required" message. `manage_users`/`manage_roles_permissions`
 * remain floor-admin-only by design (custom-roles design §1.1/§1.5), so a
 * permission holder who isn't a floor admin still can't do anything on
 * `/admin/users`/`/admin/roles` — they just aren't blocked from every other
 * admin page too. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user: currentUser, authState } = useAuth();
  const pathname = usePathname();
  const [hasAnyPermission, setHasAnyPermission] = useState<boolean | null>(null);

  useEffect(() => {
    if (!currentUser || currentUser.role === "admin") return;
    let cancelled = false;
    api
      .getRoles()
      .then((roles) => {
        if (cancelled) return;
        const role = roles.find((r) => r.id === currentUser.role_id);
        setHasAnyPermission((role?.permission_keys.length ?? 0) > 0);
      })
      .catch(() => {
        if (!cancelled) setHasAnyPermission(false);
      });
    return () => {
      cancelled = true;
    };
  }, [currentUser]);

  // AuthGate already guarantees `authState === "authenticated"` here — this
  // is "authenticated but not authorized" (a real, logged-in user with no
  // admin-relevant permission hitting /admin), which is fine to render
  // inline rather than redirect away from (design doc §8.3).
  const isAdmin = currentUser?.role === "admin";
  if (authState === "loading" || !currentUser || (!isAdmin && hasAnyPermission === null)) {
    return <main className="mx-auto max-w-6xl px-6 py-8 text-sm text-mute">Loading…</main>;
  }
  if (!isAdmin && !hasAnyPermission) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="rounded-xl bg-negative-bg px-4 py-3 text-sm text-canvas">
          Admin access required — log in as an admin, or with a role granted an admin permission, to manage swim
          lanes, custom fields, and user roles.
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
