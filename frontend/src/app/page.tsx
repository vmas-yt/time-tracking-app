"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The standalone Projects page has been removed (docs/design/
// custom-fields-admin-design.md §3) — projects are now a lightweight,
// optional attribute of a task (per the PRD: "Employees mostly create and
// start their own tasks without needing a project"), managed from the
// admin page's new "Projects" section, and picked from a dropdown on the
// Add/Edit Task panel. `/board` is the effective home for every route that
// used to point at `/`.
export default function HomeRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/board");
  }, [router]);
  return null;
}
