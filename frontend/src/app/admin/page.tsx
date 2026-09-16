"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, CustomField, CustomFieldType, SwimlaneField, User, UserRole } from "@/lib/types";

export default function AdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("text");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.listUsers().then(setUsers).catch((e) => setError(e.message));
    api.getBoardConfig().then(setBoardConfig).catch(console.error);
    api.listCustomFields().then(setCustomFields).catch(console.error);
  };

  useEffect(load, []);

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
    <main className="page">
      <h1>Admin</h1>
      {error && (
        <p className="board-error" onClick={() => setError(null)}>
          {error} (click to dismiss — admin actions require the admin role)
        </p>
      )}

      <section>
        <h2>Kanban board</h2>
        <label>
          Swim lanes grouped by:{" "}
          <select
            value={boardConfig?.swimlane_field ?? "assignee"}
            onChange={(e) => handleSwimlaneChange(e.target.value as SwimlaneField)}
          >
            {SWIMLANE_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section>
        <h2>Custom fields</h2>
        <form onSubmit={handleCreateField} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            placeholder="Field name"
            value={newFieldName}
            onChange={(e) => setNewFieldName(e.target.value)}
          />
          <select value={newFieldType} onChange={(e) => setNewFieldType(e.target.value as CustomFieldType)}>
            <option value="text">Text</option>
            <option value="number">Number</option>
            <option value="select">Select</option>
            <option value="date">Date</option>
            <option value="boolean">Boolean</option>
          </select>
          <button className="timer-btn timer-btn--start" type="submit">
            + Add field
          </button>
        </form>
        <ul className="task-detail__list">
          {customFields.map((f) => (
            <li key={f.id}>
              {f.name} <span className="badge">{f.field_type}</span>{" "}
              <button className="timer-btn timer-btn--stop" onClick={() => handleDeleteField(f.id)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Users</h2>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Name</th>
              <th style={{ textAlign: "left" }}>Email</th>
              <th style={{ textAlign: "left" }}>Role</th>
              <th style={{ textAlign: "left" }}>Manager</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.full_name}</td>
                <td>{u.email}</td>
                <td>
                  <select value={u.role} onChange={(e) => handleRoleChange(u.id, e.target.value as UserRole)}>
                    <option value="employee">Employee</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td>
                  <select
                    value={u.manager_id ?? ""}
                    onChange={(e) => handleManagerChange(u.id, e.target.value)}
                  >
                    <option value="">— none —</option>
                    {users
                      .filter((m) => m.id !== u.id)
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.full_name}
                        </option>
                      ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
