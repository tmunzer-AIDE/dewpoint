// SPDX-License-Identifier: Apache-2.0
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { ApiError, api } from "../lib/api";
import { useAfterAuth } from "../lib/useAfterAuth";
import { authenticatePasskey } from "../lib/webauthn";

const MESSAGES: Record<string, string> = {
  invalid_code: "That code didn't work.",
  locked: "Too many attempts. Try again in a few minutes.",
  passkey_failed: "That passkey could not be verified.",
};

export function MfaPage() {
  const afterAuth = useAfterAuth();
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<{ state: string }>) {
    setBusy(true);
    setError(null);
    try {
      await afterAuth((await fn()).state);
    } catch (e) {
      setError(MESSAGES[e instanceof ApiError ? e.code : ""] ?? "Verification failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const path = recovery ? "/api/v1/auth/mfa/recovery" : "/api/v1/auth/mfa/totp";
    void run(() => api("POST", path, { code: code.trim() }));
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4">
        <h1 className="text-h1 font-semibold">Confirm it's you</h1>
        <Field
          label={recovery ? "Recovery code" : "Authenticator code"}
          inputMode={recovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          required
          value={code}
          onChange={(e) => setCode(e.target.value)}
          data-testid="totp-code"
        />
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
        <Button variant="primary" type="submit" disabled={busy} data-testid="totp-submit">Verify</Button>
        <Button type="button" disabled={busy} onClick={() => void run(() => authenticatePasskey("mfa"))}>
          Use a passkey instead
        </Button>
        <button type="button" className="self-start text-body text-accent-ink underline" onClick={() => setRecovery(!recovery)}>
          {recovery ? "Use an authenticator code" : "Use a recovery code"}
        </button>
      </form>
    </main>
  );
}
