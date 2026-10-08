// SPDX-License-Identifier: Apache-2.0
import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "e2e",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080", trace: "retain-on-failure" },
  projects: [
    { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
    {
      name: "workflows",
      testMatch: /workflows\.spec\.ts/,
      dependencies: ["foundations"],
      use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
    },
  ],
});
