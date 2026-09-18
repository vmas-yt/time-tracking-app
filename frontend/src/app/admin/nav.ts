/** Admin sub-navigation sections — single source of truth for the sidebar
 * (`layout.tsx`) and the index-route redirect (`page.tsx`). Departments and
 * Teams sit first — org structure is foundational (Users and Tasks both hang
 * off a Team) — followed by Users, then the rest in their existing order. */
export const ADMIN_SECTIONS = [
  { href: "/admin/departments", label: "Departments" },
  { href: "/admin/teams", label: "Teams" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/projects", label: "Projects" },
  { href: "/admin/custom-fields", label: "Custom Fields" },
  { href: "/admin/categories", label: "Categories" },
  { href: "/admin/priorities", label: "Priorities" },
  { href: "/admin/swim-lanes", label: "Swim Lanes" },
] as const;
