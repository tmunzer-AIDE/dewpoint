// SPDX-License-Identifier: Apache-2.0
import { ApiError, client, ok } from "./client";

export type SignOutResult = "signed_out" | "failed";

class UnexpectedLogoutResponse extends Error {}

async function logout(): Promise<void> {
  const answer = await client.POST("/api/v1/auth/logout");
  await ok(Promise.resolve(answer)); // an error answer throws its ApiError
  const { status } = answer.response;
  if (status !== 204) throw new UnexpectedLogoutResponse(`logout returned ${status}`); // only 204 ends a session
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
    await ok(client.GET("/api/v1/auth/session")); // ok() keeps the fresh csrf_token this answer carries
    await logout();
    return "signed_out";
  } catch (e) {
    return e instanceof ApiError && e.status === 401 ? "signed_out" : "failed";
  }
}
