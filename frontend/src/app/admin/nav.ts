/** Admin sub-navigation sections — single source of truth for the sidebar
 * (`layout.tsx`) and the index-route redirect (`page.tsx`). */
export const ADMIN_SECTIONS = [
  { href: "/admin/projects", label: "Projects" },
  { href: "/admin/custom-fields", label: "Custom Fields" },
  { href: "/admin/categories", label: "Categories" },
  { href: "/admin/priorities", label: "Priorities" },
  { href: "/admin/swim-lanes", label: "Swim Lanes" },
  { href: "/admin/users", label: "Users" },
] as const;
