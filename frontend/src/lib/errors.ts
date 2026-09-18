import { ApiError } from "./api";

/** Shared "turn a caught error into a user-facing string" helper — was
 * previously copy-pasted verbatim in `admin/page.tsx`, `UserManagement.tsx`,
 * and `DropdownOptionsEditor.tsx`. Centralized here so every admin
 * screen surfaces `ApiError` messages (e.g. the 409 "has tasks linked to
 * it" project-delete guard, or the built-in-option protection message)
 * identically. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}
