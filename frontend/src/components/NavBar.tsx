"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/board", label: "Board" },
  { href: "/reports", label: "Reports" },
  { href: "/admin", label: "Admin", adminOnly: true },
];

export function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, authState, logout } = useAuth();

  // The login page renders its own chrome-free layout; don't show the app
  // nav (with links that all 404-redirect an anonymous visitor) above it.
  if (pathname === "/login") return null;

  const isAdmin = user?.role === "admin";

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <header className="sticky top-0 z-10 bg-canvas">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-8">
          <span className="text-sm font-bold tracking-tight text-ink">⏱ TimeTrack</span>
          {authState === "authenticated" && (
            <nav className="flex items-center gap-1">
              {LINKS.filter((l) => !l.adminOnly || isAdmin).map(({ href, label }) => {
                const active = pathname === href || (href !== "/" && pathname?.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors",
                      active ? "bg-primary text-on-primary" : "text-body hover:bg-canvas-soft"
                    )}
                  >
                    {label}
                  </Link>
                );
              })}
            </nav>
          )}
        </div>
        {authState === "authenticated" && user ? (
          <div className="flex items-center gap-3">
            <span className="text-sm text-body">
              <span className="font-semibold text-ink">{user.full_name}</span>
              <span className="ml-1.5 text-xs text-mute">({user.role})</span>
            </span>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-xl px-3 py-1.5 text-sm font-semibold text-body hover:bg-canvas-soft"
            >
              Log out
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="rounded-xl px-3 py-1.5 text-sm font-semibold text-body hover:bg-canvas-soft"
          >
            Log in
          </Link>
        )}
      </div>
    </header>
  );
}
