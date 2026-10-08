// SPDX-License-Identifier: Apache-2.0
/** The signed-in admin's browser state, saved by the foundations flow (which enrolls the authenticator) for the
 * projects that depend on it: a second TOTP sign-in in one step would be refused as a replay. */
export const ADMIN_STATE = "test-results/admin-state.json";
