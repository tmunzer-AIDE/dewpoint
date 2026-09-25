// SPDX-License-Identifier: Apache-2.0
import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { api } from "./api";

type CreationOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
type RequestOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];
const BASE = "/api/v1/auth/passkeys";
interface Challenge<T> {
  options: T;
  challenge_id: string;
}
interface Verified {
  state: string;
  csrf_token: string;
}

export async function registerPasskey(name = "Passkey"): Promise<Verified> {
  const o = await api<Challenge<CreationOptions>>("POST", `${BASE}/register/options`);
  const credential = await startRegistration({ optionsJSON: o.options });
  return api<Verified>("POST", `${BASE}/register/verify`, { challenge_id: o.challenge_id, credential, name });
}

export async function authenticatePasskey(kind: "login" | "mfa" | "stepup"): Promise<Verified> {
  const o = await api<Challenge<RequestOptions>>("POST", `${BASE}/${kind}/options`);
  const credential = await startAuthentication({ optionsJSON: o.options });
  return api<Verified>("POST", `${BASE}/${kind}/verify`, { challenge_id: o.challenge_id, credential });
}
