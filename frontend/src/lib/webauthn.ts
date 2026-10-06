// SPDX-License-Identifier: Apache-2.0
import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { client, ok } from "./client";

type CreationOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
type RequestOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];
interface Verified {
  state: string;
  csrf_token: string;
}

export async function registerPasskey(name = "Passkey"): Promise<Verified> {
  const o = await ok(client.POST("/api/v1/auth/passkeys/register/options"));
  const credential = await startRegistration({ optionsJSON: o.options as unknown as CreationOptions });
  return ok(client.POST("/api/v1/auth/passkeys/register/verify", { body: { challenge_id: o.challenge_id, credential: credential as unknown as Record<string, unknown>, name } }));
}

/** Each kind's own routes, by their literal paths, so the client types every call. */
const OPTIONS = {
  login: () => client.POST("/api/v1/auth/passkeys/login/options"),
  mfa: () => client.POST("/api/v1/auth/passkeys/mfa/options"),
  stepup: () => client.POST("/api/v1/auth/passkeys/stepup/options"),
};
type Kind = keyof typeof OPTIONS;
const VERIFY = {
  login: (body: { challenge_id: string; credential: Record<string, unknown> }) =>
    client.POST("/api/v1/auth/passkeys/login/verify", { body }),
  mfa: (body: { challenge_id: string; credential: Record<string, unknown> }) =>
    client.POST("/api/v1/auth/passkeys/mfa/verify", { body }),
  stepup: (body: { challenge_id: string; credential: Record<string, unknown> }) =>
    client.POST("/api/v1/auth/passkeys/stepup/verify", { body }),
} satisfies Record<Kind, unknown>;

export async function authenticatePasskey(kind: Kind): Promise<Verified> {
  const o = await ok(OPTIONS[kind]());
  const credential = await startAuthentication({ optionsJSON: o.options as unknown as RequestOptions });
  return ok(VERIFY[kind]({ challenge_id: o.challenge_id, credential: credential as unknown as Record<string, unknown> }));
}
