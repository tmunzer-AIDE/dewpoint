// SPDX-License-Identifier: Apache-2.0
import QRCode from "qrcode";
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { ApiError, api } from "../lib/api";
import { useAfterAuth } from "../lib/useAfterAuth";
import { registerPasskey } from "../lib/webauthn";

/** Two-step TOTP setup: show the QR code and secret, then confirm a code. Reused by the security page. */
export function TotpSetup({
  onConfirmed,
  onReauth,
}: {
  onConfirmed: (codes: string[], state: string) => void;
  /** Called with a retry when the server wants a fresh second factor first (active sessions only). */
  onReauth?: (retry: () => Promise<void>) => void;
}) {
  const [uri, setUri] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const secret = uri ? (new URL(uri).searchParams.get("secret") ?? "") : "";

  async function start() {
    setError(null);
    try {
      const r = await api<{ otpauth_uri: string }>("POST", "/api/v1/auth/mfa/totp/enroll");
      setUri(r.otpauth_uri);
      setQr(await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 192 }));
    } catch (e) {
      if (onReauth && e instanceof ApiError && e.code === "reauth_required") onReauth(start);
      else setError("Couldn't start setup. Try again.");
    }
  }

  async function confirm(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    try {
      const r = await api<{ recovery_codes: string[]; state: string }>("POST", "/api/v1/auth/mfa/totp/confirm", {
        code: code.trim(),
      });
      onConfirmed(r.recovery_codes, r.state);
    } catch (err) {
      if (onReauth && err instanceof ApiError && err.code === "reauth_required") onReauth(() => confirm());
      else setError("That code didn't work. Check the time on your device and try again.");
    }
  }

  if (!uri) {
    return (
      <Button onClick={() => void start()} data-testid="totp-start">
        Authenticator app
      </Button>
    );
  }
  return (
    <form onSubmit={(e) => void confirm(e)} className="flex flex-col gap-4">
      {qr && <img src={qr} alt="QR code for your authenticator app" width={192} height={192} />}
      <p className="text-sm text-muted">
        Or enter this key manually:{" "}
        <code className="font-mono text-ink" data-testid="totp-secret">{secret}</code>
      </p>
      <Field label="Code from the app" inputMode="numeric" autoComplete="one-time-code" required value={code}
        onChange={(e) => setCode(e.target.value)} data-testid="totp-code" />
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <Button variant="primary" type="submit" data-testid="totp-submit">Confirm</Button>
    </form>
  );
}

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [ack, setAck] = useState(false);
  function download() {
    const url = URL.createObjectURL(new Blob([codes.join("\n") + "\n"], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "dewpoint-recovery-codes.txt" });
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Save your recovery codes</h2>
      <p className="text-sm text-muted">Each code works once if you lose your authenticator. They won't be shown again.</p>
      <ul data-testid="recovery-codes" className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-surface-2 p-4 font-mono text-sm">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <Button type="button" onClick={download}>Download .txt</Button>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="recovery-ack" />
        I saved these codes
      </label>
      <Button variant="primary" disabled={!ack} onClick={onDone}>Continue</Button>
    </div>
  );
}

export function EnrollPage() {
  const afterAuth = useAfterAuth();
  const [codes, setCodes] = useState<{ list: string[]; state: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function passkey() {
    setError(null);
    try {
      await afterAuth((await registerPasskey("This device")).state);
    } catch {
      setError("Passkey setup was cancelled or failed.");
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="flex w-full max-w-md flex-col gap-6">
        {codes ? (
          <RecoveryCodes codes={codes.list} onDone={() => void afterAuth(codes.state)} />
        ) : (
          <>
            <div>
              <h1 className="text-2xl font-semibold">Set up a second factor</h1>
              <p className="mt-1 text-sm text-muted">Required for every account.</p>
            </div>
            <Button variant="primary" onClick={() => void passkey()}>Passkey (recommended)</Button>
            <TotpSetup onConfirmed={(list, state) => setCodes({ list, state })} />
            {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          </>
        )}
      </div>
    </main>
  );
}
