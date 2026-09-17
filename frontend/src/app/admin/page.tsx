"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, CustomField, CustomFieldType, Project, SwimlaneField } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input, Select } from "@/components/ui/Input";
import { DropdownOptionsEditor } from "./DropdownOptionsEditor";
import { UserManagement } from "./UserManagement";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}

function ProjectsSection() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listProjects()
      .then((list) => {
        setProjects(list);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const created = await api.createProject(name.trim(), description.trim() || undefined);
      setProjects((prev) => [...prev, created]);
      setName("");
      setDescription("");
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    try {
      await api.deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
      setError(null);
    } catch (err) {
      // Most likely the 409 "has tasks linked to it" guard — surface it
      // plainly rather than silently failing.
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Projects</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <p className="text-xs text-mute">
          Optional groupings for tasks — most work happens directly on the board without a project. Employees pick
          from this list on the Add/Edit Task panel; only admins can create or remove projects here.
        </p>
        {error && (
          <p
            className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
            onClick={() => setError(null)}
          >
            {error} <span className="opacity-70">(click to dismiss)</span>
          </p>
        )}
        <form onSubmit={handleCreate} className="flex flex-wrap gap-2">
          <Input
            placeholder="Project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="max-w-xs"
          />
          <Input
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="max-w-xs"
          />
          <Button variant="primary" type="submit" disabled={!name.trim()}>
            + Add project
          </Button>
        </form>
        {loading ? (
          <p className="text-sm text-mute">Loading projects…</p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-mute">No projects yet.</p>
        ) : (
          <ul className="space-y-2">
            {projects.map((p) => (
              <li key={p.id} className="flex items-center justify-between rounded-xl bg-canvas-soft px-3 py-2">
                <div>
                  <span className="text-sm font-semibold text-ink">{p.name}</span>
                  {p.description && <span className="ml-2 text-xs text-mute">{p.description}</span>}
                </div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setConfirmingId(p.id)}
                  disabled={busyId === p.id}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
      <ConfirmDialog
        open={confirmingId !== null}
        title="Remove this project?"
        description="Fails instead of removing anything if tasks are still linked to it — move or unlink them first."
        confirmLabel="Remove"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDelete(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}

function CustomFieldsSection({
  customFields,
  setCustomFields,
  setError,
}: {
  customFields: CustomField[];
  setCustomFields: React.Dispatch<React.SetStateAction<CustomField[]>>;
  setError: (message: string | null) => void;
}) {
  const [newFieldName, setNewFieldName] = useState("");
  const [newFieldType, setNewFieldType] = useState<CustomFieldType>("text");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleCreateField = async (e: FormEvent) => {
    e.preventDefault();
    if (!newFieldName.trim()) return;
    try {
      const field = await api.createCustomField({ name: newFieldName.trim(), field_type: newFieldType });
      setCustomFields((prev) => [...prev, field]);
      setNewFieldName("");
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleDeleteField = async (fieldId: string) => {
    setBusyId(fieldId);
    try {
      await api.deleteCustomField(fieldId);
      setCustomFields((prev) => prev.filter((f) => f.id !== fieldId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Custom fields</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <form onSubmit={handleCreateField} className="flex flex-wrap gap-2">
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
              <li key={f.id} className="rounded-xl bg-canvas-soft px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm text-body">
                    {f.name} <Badge>{f.field_type}</Badge>
                  </span>
                  <div className="flex gap-1.5">
                    {f.field_type === "select" && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}
                      >
                        {expandedId === f.id ? "Hide options" : "Manage options"}
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => setConfirmingId(f.id)}
                      disabled={busyId === f.id}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
                {expandedId === f.id && f.field_type === "select" && (
                  <div className="mt-3 border-t border-canvas pt-3">
                    <DropdownOptionsEditor
                      scope="custom_field"
                      customFieldId={f.id}
                      emptyLabel="No options yet — add at least one before using this field on a task."
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
      <ConfirmDialog
        open={confirmingId !== null}
        title="Remove this custom field?"
        description="Deletes it from every task it's set on, along with its options. This can't be undone."
        confirmLabel="Remove"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDeleteField(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}

export default function AdminPage() {
  const { user: currentUser, authState } = useAuth();
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getBoardConfig().then(setBoardConfig).catch(console.error);
    api.listCustomFields().then(setCustomFields).catch(console.error);
  }, []);

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
      setError(errorMessage(err));
    }
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
          <CardTitle>Swim lanes</CardTitle>
        </CardHeader>
        <CardBody className="space-y-2">
          <label className="flex items-center gap-3 text-sm text-body">
            Group board cards into swim lanes by
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
          <p className="text-xs text-mute">
            The five status columns (Backlog → To Do → In Progress → On Hold → Completed) are fixed and not
            configurable here — this setting only controls the horizontal grouping within each column.
          </p>
        </CardBody>
      </Card>

      <ProjectsSection />

      <CustomFieldsSection customFields={customFields} setCustomFields={setCustomFields} setError={setError} />

      <Card>
        <CardHeader>
          <CardTitle>Category options</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="mb-3 text-xs text-mute">
            The 7 PRD categories plus &ldquo;Others&rdquo; are built-in and can&rsquo;t be removed. Add more below if
            Operations needs a category the PRD list doesn&rsquo;t cover.
          </p>
          <DropdownOptionsEditor scope="task_category" />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Priority options</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="mb-3 text-xs text-mute">
            Normal and Expedite are built-in and can&rsquo;t be removed.
          </p>
          <DropdownOptionsEditor scope="task_priority" />
        </CardBody>
      </Card>

      <UserManagement currentUserId={currentUser.id} />
    </main>
  );
}
