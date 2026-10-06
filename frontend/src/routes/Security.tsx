// SPDX-License-Identifier: Apache-2.0
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { ApiError, api } from "../lib/api";
import { needsReauth } from "../lib/reauth";
import { useSession } from "../lib/session";
import { authenticatePasskey, registerPasskey } from "../lib/webauthn";
import { RecoveryCodes, TotpSetup } from "./Enroll";

interface Passkey {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

/** Prove a second factor again, then retry the action that asked for it. */
function ReauthPrompt({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function viaTotp(e: FormEvent) {
    e.preventDefault();
    try {
      await api("POST", "/api/v1/auth/mfa/totp/reauth", { code: code.trim() });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.code === "locked" ? "Too many attempts." : "That code didn't work.");
    }
  }
  async function viaPasskey() {
    try {
      await authenticatePasskey("stepup");
      onDone();
    } catch {
      setError("That passkey could not be verified.");
    }
  }
  return (
    <form onSubmit={(e) => void viaTotp(e)} role="dialog" aria-label="Confirm it's you"
      className="flex max-w-md flex-col gap-3 rounded-lg border border-line bg-surface p-5">
      <p className="text-body">Confirm it's you before changing sign-in methods.</p>
      <Field label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" value={code}
        onChange={(e) => setCode(e.target.value)} data-testid="reauth-code" />
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      <div className="flex gap-2">
        <Button variant="primary" type="submit">Confirm</Button>
        <Button type="button" onClick={() => void viaPasskey()}>Use passkey</Button>
        <Button type="button" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

export function SecurityPage() {
  const qc = useQueryClient();
  const session = useSession();
  const passkeys = useQuery({ queryKey: ["passkeys"], queryFn: () => api<Passkey[]>("GET", "/api/v1/auth/passkeys") });
  const [pending, setPending] = useState<(() => Promise<void>) | null>(null);
  const [totpOpen, setTotpOpen] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pw, setPw] = useState({ current: "", next: "" });

  /** Run a factor change; if the server wants fresh reauth, ask for it and retry once confirmed. */
  async function guarded(action: () => Promise<void>) {
    setMessage(null);
    try {
      await action();
    } catch (e) {
      if (needsReauth(e)) setPending(() => action);
      else setMessage("That didn't work. Try again.");
    }
  }

  async function addPasskey() {
    const name = window.prompt("Name this passkey", "Passkey") ?? "Passkey";
    await registerPasskey(name);
    await qc.invalidateQueries({ queryKey: ["passkeys"] });
    await qc.invalidateQueries({ queryKey: ["session"] });
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    try {
      await api("POST", "/api/v1/auth/password", { current_password: pw.current, new_password: pw.next });
      setPw({ current: "", next: "" });
      setMessage("Password changed. Other sessions were signed out.");
    } catch (err) {
      setMessage(err instanceof ApiError && err.code === "password_policy" ? "That password is too weak." : "Password not changed.");
    }
  }

  return (
    <section className="flex max-w-3xl flex-col gap-8 p-6">
      <div>
        <h1 className="text-h1 font-semibold">Security</h1>
        <p className="mt-1 text-small text-muted">
          This session signed in with: {session.data?.auth_methods.join(", ") ?? "…"}
        </p>
      </div>
      {pending && (
        <ReauthPrompt
          onCancel={() => setPending(null)}
          onDone={() => {
            const retry = pending;
            setPending(null);
            void guarded(retry);
          }}
        />
      )}
      {message && <p role="status" className="text-body">{message}</p>}

      <div className="flex flex-col gap-3">
        <h2 className="text-body-lg font-semibold">Passkeys</h2>
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {passkeys.data?.map((p) => (
            <li key={p.id} className="flex justify-between p-3 text-body">
              <span>{p.name}</span>
              <span className="text-muted">added {new Date(p.created_at).toLocaleDateString()}</span>
            </li>
          ))}
          {passkeys.data?.length === 0 && <li className="p-3 text-body text-muted">No passkeys yet.</li>}
        </ul>
        <Button onClick={() => void guarded(addPasskey)} data-testid="passkey-add" className="self-start">Add a passkey</Button>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-body-lg font-semibold">Authenticator app</h2>
        {codes ? (
          <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
        ) : totpOpen ? (
          <TotpSetup
            onConfirmed={(list) => {
              setTotpOpen(false);
              setCodes(list);
            }}
            onReauth={(retry) => setPending(() => retry)}
          />
        ) : (
          <Button className="self-start" onClick={() => setTotpOpen(true)}>Set up or replace authenticator app</Button>
        )}
      </div>

      <form onSubmit={(e) => void changePassword(e)} className="flex max-w-md flex-col gap-4">
        <h2 className="text-body-lg font-semibold">Change password</h2>
        <Field label="Current password" type="password" autoComplete="current-password" required value={pw.current}
          onChange={(e) => setPw({ ...pw, current: e.target.value })} />
        <Field label="New password" type="password" autoComplete="new-password" required minLength={12} value={pw.next}
          onChange={(e) => setPw({ ...pw, next: e.target.value })} hint="At least 12 characters." />
        <Button variant="primary" type="submit" className="self-start">Change password</Button>
      </form>
    </section>
  );
}
