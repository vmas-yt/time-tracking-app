"use client";

import type { CustomField } from "@/lib/types";
import { Input, Select } from "@/components/ui/Input";
import { activeOptions, selectOptionsFor } from "@/lib/options";

interface CustomFieldInputProps {
  field: CustomField;
  /** Current string value, wire format per
   * docs/design/custom-fields-admin-design.md §1.4 (numbers/booleans/dates
   * are all submitted as their string representation). */
  value: string;
  onChange: (value: string) => void;
  /** Fired when the edit is "done" for this input type — blur for
   * text/number/date, immediately for select/boolean. Callers that submit on
   * every change (e.g. `TaskDetailPanel`'s inline edit) hook this; callers
   * that batch into a single form submit (`AddTaskPanel`) can omit it. */
  onCommit?: (value: string) => void;
  disabled?: boolean;
}

/** Renders the one input per `field.field_type` the design doc's §1.4 table
 * specifies. Shared by `AddTaskPanel` (create) and `TaskDetailPanel` (inline
 * edit) so the two surfaces can never drift on how a given field type is
 * represented. */
export function CustomFieldInput({ field, value, onChange, onCommit, disabled }: CustomFieldInputProps) {
  switch (field.field_type) {
    case "text":
      return (
        <Input
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onCommit?.(e.target.value)}
        />
      );
    case "number":
      return (
        <Input
          type="number"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onCommit?.(e.target.value)}
        />
      );
    case "date":
      return (
        <Input
          type="date"
          value={value}
          disabled={disabled}
          onChange={(e) => {
            onChange(e.target.value);
            onCommit?.(e.target.value);
          }}
        />
      );
    case "boolean":
      return (
        <Select
          value={value === "true" ? "true" : value === "false" ? "false" : ""}
          disabled={disabled}
          onChange={(e) => {
            onChange(e.target.value);
            onCommit?.(e.target.value);
          }}
        >
          <option value="" disabled>
            Select…
          </option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </Select>
      );
    case "select": {
      const opts = selectOptionsFor(field.options, value);
      return (
        <Select
          value={value}
          disabled={disabled}
          onChange={(e) => {
            onChange(e.target.value);
            onCommit?.(e.target.value);
          }}
        >
          <option value="" disabled={value !== ""}>
            {activeOptions(field.options).length === 0 ? "No options defined" : "Select…"}
          </option>
          {opts.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </Select>
      );
    }
    default:
      return null;
  }
}
