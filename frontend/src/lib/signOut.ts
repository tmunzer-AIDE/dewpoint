// SPDX-License-Identifier: Apache-2.0
import { ApiError, api } from "./api";

export type SignOutResult = "signed_out" | "failed";

async function logout(): Promise<void> {
  await api("POST", "/api/v1/auth/logout");
}

/**
 * Ends the server session. Only reports "signed_out" when the server confirms (204) or the session is already
 * invalid (401); a network error or any other failure leaves the session alive, so the caller must stay put.
 * A stale CSRF token is refreshed from /auth/session once before retrying.
 */
export async function signOut(): Promise<SignOutResult> {
  try {
    await logout();
    return "signed_out";
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return "signed_out";
    if (!(e instanceof ApiError && e.code === "csrf")) return "failed";
  }
  try {
    await api("GET", "/api/v1/auth/session"); // api() stores the fresh csrf_token from this response
    await logout();
    return "signed_out";
  } catch (e) {
    return e instanceof ApiError && e.status === 401 ? "signed_out" : "failed";
  }
}
