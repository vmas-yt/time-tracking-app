"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, CustomField, CustomFieldType, SwimlaneField } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Input";
import { UserManagement } from "./UserManagement";

export default function AdminPage() {
  const { user: currentUser, authState } = useAuth();
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("text");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.getBoardConfig().then(setBoardConfig).catch(console.error);
    api.listCustomFields().then(setCustomFields).catch(console.error);
  };

  useEffect(load, []);

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

  const handleSwimlaneChange = async (value: SwimlaneField) => {
    try {
      const updated = await api.updateBoardConfig(value);
      setBoardConfig(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update board config");
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

      <UserManagement currentUserId={currentUser.id} />
    </main>
  );
}
