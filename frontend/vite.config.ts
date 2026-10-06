// SPDX-License-Identifier: Apache-2.0
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { thirdPartyNotices } from "./scripts/third-party-notices.mjs";

export default defineConfig({
  plugins: [react(), tailwindcss(), thirdPartyNotices()], // the notices ship in dist, so in the web image
  server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    // Tests read the stylesheets as text (`?raw`): the token sheet's contrast, and the AI-tells guard.
    css: { include: [/\/src\/.+\.css(?:\?|$)/] }, // an id may end in `?raw`
  },
});
