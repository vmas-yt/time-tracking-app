"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/board", label: "Board" },
  { href: "/", label: "Projects" },
  { href: "/reports", label: "Reports" },
  { href: "/admin", label: "Admin" },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 border-b border-gray-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-8">
          <span className="text-sm font-semibold tracking-tight text-gray-900">
            ⏱ TimeTrack
          </span>
          <nav className="flex items-center gap-1">
            {LINKS.map(({ href, label }) => {
              const active = pathname === href || (href !== "/" && pathname?.startsWith(href));
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    active ? "bg-brand-50 text-brand-700" : "text-gray-600 hover:bg-gray-100"
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
          className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-100"
        >
          Log in
        </Link>
      </div>
    </header>
  );
}
