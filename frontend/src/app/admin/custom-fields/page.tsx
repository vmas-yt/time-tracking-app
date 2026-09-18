"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CustomField } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CustomFieldFormPanel } from "./CustomFieldFormPanel";

/** Custom fields list/table — was previously an inline create-form + `<ul>`
 * with an inline-expand row for managing a select field's options. Create
 * and "manage" (view + options) both now open the shared slide-over via
 * `CustomFieldFormPanel`; delete stays a table action since it isn't a
 * create/edit flow. */
export default function CustomFieldsPage() {
  const [fields, setFields] = useState<CustomField[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelMode, setPanelMode] = useState<"create" | "manage">("create");
  const [activeField, setActiveField] = useState<CustomField | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listCustomFields()
      .then((list) => {
        setFields(list);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleDelete = async (fieldId: string) => {
    setBusyId(fieldId);
    try {
      await api.deleteCustomField(fieldId);
      setFields((prev) => prev.filter((f) => f.id !== fieldId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Custom fields</CardTitle>
          <p className="mt-1 text-xs text-mute">ClickUp-style fields admins can add to every task.</p>
        </div>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setPanelMode("create");
            setActiveField(null);
            setPanelOpen(true);
          }}
        >
          + Add field
        </Button>
      </CardHeader>
      <CardBody className="space-y-4">
        {error && (
          <p
            className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
            onClick={() => setError(null)}
          >
            {error} <span className="opacity-70">(click to dismiss)</span>
          </p>
        )}

        {loading ? (
          <p className="text-sm text-mute">Loading custom fields…</p>
        ) : fields.length === 0 ? (
          <p className="text-sm text-mute">No custom fields defined yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Type</th>
                  <th className="py-2 font-semibold">Options</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.id} className="border-b border-canvas-soft last:border-0">
                    <td className="py-2 font-medium text-ink">{f.name}</td>
                    <td className="py-2">
                      <Badge>{f.field_type}</Badge>
                    </td>
                    <td className="py-2 text-body">
                      {f.field_type === "select" ? `${f.options?.length ?? 0} option(s)` : "—"}
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setPanelMode("manage");
                            setActiveField(f);
                            setPanelOpen(true);
                          }}
                        >
                          {f.field_type === "select" ? "Manage" : "View"}
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => setConfirmingId(f.id)}
                          disabled={busyId === f.id}
                        >
                          Remove
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>

      <CustomFieldFormPanel
        open={panelOpen}
        mode={panelMode}
        field={activeField}
        onClose={() => setPanelOpen(false)}
        onCreated={(created) => {
          setFields((prev) => [...prev, created]);
          setPanelOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingId !== null}
        title="Remove this custom field?"
        description="Deletes it from every task it's set on, along with its options. This can't be undone."
        confirmLabel="Remove"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDelete(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}
