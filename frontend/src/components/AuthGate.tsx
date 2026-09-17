"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AuthProvider, useAuth } from "@/lib/auth";

const LOGIN_ROUTE = "/login";

function Spinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas-soft">
      <div
        className="h-8 w-8 animate-spin rounded-full border-2 border-ink/15 border-t-ink"
        role="status"
        aria-label="Loading"
      />
    </div>
  );
}

function AuthRouter({ children }: { children: React.ReactNode }) {
  const { authState } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isLoginRoute = pathname === LOGIN_ROUTE;

  useEffect(() => {
    if (authState === "anonymous" && !isLoginRoute) {
      router.replace(LOGIN_ROUTE);
    } else if (authState === "authenticated" && isLoginRoute) {
      router.replace("/board");
    }
  }, [authState, isLoginRoute, router]);

  // While resolving the token, never render the page shell underneath —
  // this is the actual fix for pages firing data fetches before an auth
  // check completes (design doc §8.1/§8.2).
  if (authState === "loading") return <Spinner />;

  if (authState === "anonymous" && !isLoginRoute) return <Spinner />;
  if (authState === "authenticated" && isLoginRoute) return <Spinner />;

  return <>{children}</>;
}

/** Wraps the root layout. Redirects anonymous visitors to /login from every
 * other route, and redirects already-authenticated visitors away from
 * /login. See docs/design/auth-rbac-design.md §8.2. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthRouter>{children}</AuthRouter>
    </AuthProvider>
  );
}
