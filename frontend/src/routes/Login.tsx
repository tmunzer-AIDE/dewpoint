// SPDX-License-Identifier: Apache-2.0
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { Mark } from "../components/Mark";
import { ApiError, api } from "../lib/api";
import { authenticatePasskey } from "../lib/webauthn";

const MESSAGES: Record<string, string> = {
  invalid_credentials: "Email or password is incorrect.",
  locked: "Too many attempts. Try again in a few minutes.",
  passkey_failed: "That passkey could not be verified.",
};

export function LoginForm({ onDone }: { onDone: (state: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<{ state: string }>) {
    setBusy(true);
    setError(null);
    try {
      onDone((await fn()).state);
    } catch (e) {
      setError(MESSAGES[e instanceof ApiError ? e.code : ""] ?? "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void run(() => api("POST", "/api/v1/auth/login", { email, password }));
  }

  return (
    <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4">
      <Field label="Email" type="email" autoComplete="username webauthn" required value={email}
        onChange={(e) => setEmail(e.target.value)} data-testid="login-email" />
      <Field label="Password" type="password" autoComplete="current-password" required value={password}
        onChange={(e) => setPassword(e.target.value)} data-testid="login-password" />
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      <Button variant="primary" type="submit" disabled={busy} data-testid="login-submit">Sign in</Button>
      <Button type="button" disabled={busy} onClick={() => void run(() => authenticatePasskey("login"))}
        data-testid="login-passkey">Sign in with a passkey</Button>
    </form>
  );
}

export function LoginPage({ navigateByState }: { navigateByState: (s: string) => void }) {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <Mark seam="ground" />
        <h1 className="text-h1 font-semibold">Sign in to Dewpoint</h1>
        <LoginForm onDone={navigateByState} />
      </div>
    </main>
  );
}
