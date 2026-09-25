// SPDX-License-Identifier: Apache-2.0
import { ApiError } from "./api";

/** True when the server asks the user to prove a second factor again before a factor change. */
export function needsReauth(e: unknown): boolean {
  return e instanceof ApiError && e.status === 403 && e.code === "reauth_required";
}
