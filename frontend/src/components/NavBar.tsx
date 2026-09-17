"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/board", label: "Board" },
  { href: "/", label: "Projects" },
  { href: "/reports", label: "Reports" },
  { href: "/admin", label: "Admin", adminOnly: true },
];

export function NavBar() {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    api.me().then((u) => setIsAdmin(u.role === "admin")).catch(() => setIsAdmin(false));
  }, []);

  return (
    <header className="sticky top-0 z-10 bg-canvas">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-8">
          <span className="text-sm font-bold tracking-tight text-ink">⏱ TimeTrack</span>
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
        </div>
        <Link
          href="/login"
          className="rounded-xl px-3 py-1.5 text-sm font-semibold text-body hover:bg-canvas-soft"
        >
          Log in
        </Link>
      </div>
    </header>
  );
}
