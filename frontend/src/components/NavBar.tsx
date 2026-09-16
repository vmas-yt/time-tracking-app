"use client";

import Link from "next/link";

export function NavBar() {
  return (
    <nav className="navbar">
      <Link href="/board">Board</Link>
      <Link href="/">Projects</Link>
      <Link href="/reports">Reports</Link>
      <Link href="/admin">Admin</Link>
      <Link href="/login">Log in</Link>
    </nav>
  );
}
