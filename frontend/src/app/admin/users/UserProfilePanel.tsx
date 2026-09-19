"use client";

import type { User } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";
import { formatRelativeTime } from "@/board/format";

/** Read-only slide-over for one user's profile, opened by clicking a name in
 * the Users table. Built on the shared `SlideOver` primitive — the same
 * pattern every admin create/edit panel and the Add/Edit Task panels use. */
export function UserProfilePanel({
  user,
  users,
  onClose,
}: {
  user: User;
  users: User[];
  onClose: () => void;
}) {
  const manager = users.find((u) => u.id === user.manager_id);
  const directReports = users.filter((u) => u.manager_id === user.id);

  return (
    <SlideOver open onClose={onClose} widthClassName="max-w-[420px]" closeLabel="Close user profile">
      <SlideOverHeader onClose={onClose}>
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="brand">{user.role_name}</Badge>
            {user.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Deactivated</Badge>}
          </div>
          <h2 className="text-xl font-bold leading-tight tracking-tight text-ink">{user.full_name}</h2>
          <p className="text-xs text-mute">{user.email}</p>
        </div>
      </SlideOverHeader>

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
    </SlideOver>
  );
}
