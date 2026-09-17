"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export type AuthState = "loading" | "anonymous" | "authenticated";

export interface AuthContextValue {
  user: User | null;
  authState: AuthState;
  /** Re-runs the `GET /users/me` check (e.g. after an admin edits their own
   * profile) without a full page reload. */
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Single source of truth for "who is logged in", replacing the previously
 * duplicated `api.me()` calls in NavBar, admin/page.tsx, and
 * board/session.ts's useTimerSession (see docs/design/auth-rbac-design.md
 * §8.2). Resolves auth state from the token in localStorage on mount.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [authState, setAuthState] = useState<AuthState>("loading");

  const resolve = useCallback(async () => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) {
      setUser(null);
      setAuthState("anonymous");
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
      setAuthState("authenticated");
    } catch {
      // Invalid/expired token, or the deactivated-account 401 from
      // get_current_user (see design doc §4.1) — either way, the token is
      // no longer usable, so drop it and fall back to anonymous.
      localStorage.removeItem("token");
      setUser(null);
      setAuthState("anonymous");
    }
  }, []);

  useEffect(() => {
    resolve();
  }, [resolve]);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setUser(null);
    setAuthState("anonymous");
  }, []);

  const value = useMemo(
    () => ({ user, authState, refresh: resolve, logout }),
    [user, authState, resolve, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
