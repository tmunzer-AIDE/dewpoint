// SPDX-License-Identifier: Apache-2.0
import type { Plugin } from "vite";

/** Writes `third-party-notices.txt` into the build: see third-party-notices.mjs. */
export function thirdPartyNotices(options?: { overrides?: string }): Plugin;
