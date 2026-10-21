// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { GROUPED, REMOTE } from "../../../test/nodeTypes";
import { fakeApi, showDrawer } from "./harness";

it("names a step's group under its title", () => {
  fakeApi({});
  showDrawer(GROUPED[2]!);
  expect(screen.getByText("Update org WLAN · acme.org_wlans.update@1")).toBeTruthy();
  expect(screen.getByText("Acme · Org WLANs")).toBeTruthy();
});

it("names none for a step outside a group", () => {
  fakeApi({ "GET /api/v1/t/t1/connections": () => new Response("[]", { headers: { "content-type": "application/json" } }) });
  showDrawer(REMOTE);
  expect(screen.getByText("Sites · acme.sites@1")).toBeTruthy();
  expect(screen.queryByText(/^Acme · /)).toBeNull();
});
