"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** `/admin` itself has nothing to show now that every section lives at its
 * own route — land on the first sub-section. A client-side redirect (rather
 * than `next/navigation`'s server `redirect()`) so this only ever fires once
 * `AdminLayout` has already mounted us — i.e. only for a confirmed admin —
 * instead of racing the layout's auth gate. */
export default function AdminIndexPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/admin/departments");
  }, [router]);

  return null;
}
