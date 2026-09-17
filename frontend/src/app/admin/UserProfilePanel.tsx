"use client";

import { useEffect } from "react";
import type { User, UserRole } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { formatRelativeTime } from "@/board/format";

const ROLE_LABEL: Record<UserRole, string> = {
  employee: "Employee",
  manager: "Manager",
  admin: "Admin",
};

/** Read-only slide-over for one user's profile (docs/design/
 * custom-fields-admin-design.md §6.2), opened by clicking a name in
 * `UserManagement`'s table. Visually consistent with `TaskDetailPanel`'s
 * slide-over pattern. Everything shown is already loaded client-side from
 * `GET /users?include_inactive=true` — no new fetch. */
export function UserProfilePanel({
  user,
  users,
  onClose,
}: {
  user: User;
  users: User[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const manager = users.find((u) => u.id === user.manager_id);
  const directReports = users.filter((u) => u.manager_id === user.id);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="Close user profile"
        onClick={onClose}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px] animate-[fade-in_0.15s_ease-out]"
      />
      <div className="relative flex h-full w-full max-w-[420px] flex-col overflow-y-auto bg-canvas-soft shadow-2xl shadow-ink/25 animate-[slide-in_0.22s_cubic-bezier(0.16,1,0.3,1)]">
        <div className="flex items-start justify-between gap-4 border-b border-canvas px-6 py-5">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="brand">{ROLE_LABEL[user.role]}</Badge>
              {user.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Deactivated</Badge>}
            </div>
            <h2 className="text-xl font-bold leading-tight tracking-tight text-ink">{user.full_name}</h2>
            <p className="text-xs text-mute">{user.email}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-full p-1.5 text-mute hover:bg-canvas hover:text-ink"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="space-y-5 p-6">
          <Card>
            <CardHeader>
              <CardTitle>Profile</CardTitle>
            </CardHeader>
            <CardBody className="space-y-3 text-sm">
              <div className="flex justify-between gap-3">
                <span className="text-mute">Manager</span>
                <span className="text-right font-medium text-ink">
                  {manager ? (
                    <>
                      {manager.full_name}
                      <span className="block text-xs font-normal text-mute">{manager.email}</span>
                    </>
                  ) : (
                    "— none —"
                  )}
                </span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-mute">Status</span>
                <span className="text-right font-medium text-ink">
                  {user.is_active ? (
                    "Active"
                  ) : (
                    <>
                      Deactivated
                      {user.deactivated_at && (
                        <span className="block text-xs font-normal text-mute">
                          {formatRelativeTime(user.deactivated_at)}
                        </span>
                      )}
                    </>
                  )}
                </span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-mute">Member since</span>
                <span className="font-medium text-ink">{formatRelativeTime(user.created_at)}</span>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Direct reports ({directReports.length})</CardTitle>
            </CardHeader>
            <CardBody>
              {directReports.length === 0 ? (
                <p className="text-sm text-mute">No one reports to {user.full_name.split(" ")[0]}.</p>
              ) : (
                <ul className="space-y-2">
                  {directReports.map((r) => (
                    <li key={r.id} className="flex items-center justify-between text-sm">
                      <span className="font-medium text-ink">{r.full_name}</span>
                      <span className="text-xs text-mute">{r.email}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
      <style jsx global>{`
        @keyframes slide-in {
          from {
            transform: translateX(24px);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes fade-in {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}
