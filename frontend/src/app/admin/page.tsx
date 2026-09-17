"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, CustomField, CustomFieldType, SwimlaneField, User, UserRole } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Input";

export default function AdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("text");
  const [error, setError] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [meError, setMeError] = useState<string | null>(null);

  const load = () => {
    api.listUsers().then(setUsers).catch((e) => setError(e.message));
    api.getBoardConfig().then(setBoardConfig).catch(console.error);
    api.listCustomFields().then(setCustomFields).catch(console.error);
  };

  useEffect(() => {
    api.me().then(setCurrentUser).catch((e) => setMeError(e.message));
  }, []);
  useEffect(load, []);

  if (!currentUser && !meError) {
    return <main className="mx-auto max-w-6xl px-6 py-8 text-sm text-mute">Loading…</main>;
  }
  if (!currentUser || currentUser.role !== "admin") {
    return (
      <main className="mx-auto max-w-6xl px-6 py-8">
        <p className="rounded-xl bg-negative-bg px-4 py-3 text-sm text-canvas">
          Admin access required — log in as an admin to manage swim lanes, custom fields, and user roles.
        </p>
      </main>
    );
  }

  const handleSwimlaneChange = async (value: SwimlaneField) => {
    try {
      const updated = await api.updateBoardConfig(value);
      setBoardConfig(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update board config");
    }
  };

  const handleRoleChange = async (userId: string, role: UserRole) => {
    try {
      const updated = await api.updateUser(userId, { role });
      setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update user");
    }
  };

  const handleManagerChange = async (userId: string, managerId: string) => {
    try {
      const updated = await api.updateUser(userId, { manager_id: managerId || null });
      setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update user");
    }
  };

  const handleCreateField = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFieldName.trim()) return;
    try {
      const field = await api.createCustomField({ name: newFieldName.trim(), field_type: newFieldType });
      setCustomFields((prev) => [...prev, field]);
      setNewFieldName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create custom field");
    }
  };

  const handleDeleteField = async (fieldId: string) => {
    await api.deleteCustomField(fieldId);
    setCustomFields((prev) => prev.filter((f) => f.id !== fieldId));
  };

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-ink">Admin</h1>
      {error && (
        <p
          className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
          onClick={() => setError(null)}
        >
          {error} <span className="opacity-70">(click to dismiss — admin actions require the admin role)</span>
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Kanban board</CardTitle>
        </CardHeader>
        <CardBody>
          <label className="flex items-center gap-3 text-sm text-body">
            Swim lanes grouped by
            <Select
              value={boardConfig?.swimlane_field ?? "assignee"}
              onChange={(e) => handleSwimlaneChange(e.target.value as SwimlaneField)}
              className="w-auto"
            >
              {SWIMLANE_FIELDS.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </label>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Custom fields</CardTitle>
        </CardHeader>
        <CardBody className="space-y-4">
          <form onSubmit={handleCreateField} className="flex gap-2">
            <Input
              placeholder="Field name"
              value={newFieldName}
              onChange={(e) => setNewFieldName(e.target.value)}
            />
            <Select
              value={newFieldType}
              onChange={(e) => setNewFieldType(e.target.value as CustomFieldType)}
              className="w-auto"
            >
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="select">Select</option>
              <option value="date">Date</option>
              <option value="boolean">Boolean</option>
            </Select>
            <Button variant="primary" type="submit">
              + Add field
            </Button>
          </form>
          {customFields.length === 0 ? (
            <p className="text-sm text-mute">No custom fields defined yet.</p>
          ) : (
            <ul className="space-y-2">
              {customFields.map((f) => (
                <li
                  key={f.id}
                  className="flex items-center justify-between rounded-xl bg-canvas-soft px-3 py-2"
                >
                  <span className="flex items-center gap-2 text-sm text-body">
                    {f.name} <Badge>{f.field_type}</Badge>
                  </span>
                  <Button variant="danger" size="sm" onClick={() => handleDeleteField(f.id)}>
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
        </CardHeader>
        <CardBody className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                <th className="py-2 font-semibold">Name</th>
                <th className="py-2 font-semibold">Email</th>
                <th className="py-2 font-semibold">Role</th>
                <th className="py-2 font-semibold">Manager</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-canvas-soft last:border-0">
                  <td className="py-2 font-medium text-ink">{u.full_name}</td>
                  <td className="py-2 text-mute">{u.email}</td>
                  <td className="py-2">
                    <Select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u.id, e.target.value as UserRole)}
                      className="w-auto py-1"
                    >
                      <option value="employee">Employee</option>
                      <option value="manager">Manager</option>
                      <option value="admin">Admin</option>
                    </Select>
                  </td>
                  <td className="py-2">
                    <Select
                      value={u.manager_id ?? ""}
                      onChange={(e) => handleManagerChange(u.id, e.target.value)}
                      className="w-auto py-1"
                    >
                      <option value="">— none —</option>
                      {users
                        .filter((m) => m.id !== u.id)
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.full_name}
                          </option>
                        ))}
                    </Select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </main>
  );
}
