"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = await api.login(email, password);
      localStorage.setItem("token", access_token);
      await refresh();
      router.replace("/board");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas-soft px-4">
      <Card className="w-full max-w-sm">
        <CardBody className="space-y-5">
          <div>
            <h1 className="text-lg font-bold text-ink">Welcome back</h1>
            <p className="mt-1 text-sm text-mute">
              Log in to track time against your tasks. Accounts are created by an admin — contact yours if
              you don&rsquo;t have one yet.
            </p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input
              placeholder="Email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Input
              placeholder="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <p className="text-sm text-negative">{error}</p>}
            <Button variant="primary" type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Logging in…" : "Log in"}
            </Button>
          </form>
        </CardBody>
      </Card>
    </main>
  );
}
