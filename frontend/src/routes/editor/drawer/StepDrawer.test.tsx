// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { CREATE, GROUPED, REMOTE, UPDATE } from "../../../test/nodeTypes";
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

const CONNECTIONS = { "GET /api/v1/t/t1/connections": () => new Response("[]", { headers: { "content-type": "application/json" } }) };

it("draws an update's changes on Setup, and says so on Options (4f-2b)", async () => {
  fakeApi(CONNECTIONS);
  showDrawer(UPDATE);
  const setup = screen.getByRole("tabpanel", { name: /Setup/ });
  expect(["/connection", "/thing_id", "/body", "/mode", "/clear"].map((p) => setup.querySelector(`[data-pointer="${p}"]`) !== null)).toEqual([true, true, true, true, true]);
  await userEvent.click(screen.getByRole("tab", { name: /Options/ }));
  expect(screen.getByText("The changes are on Setup.")).toBeTruthy();
});

it("draws a create's settings on Setup, and says so on Options (4f-2b)", async () => {
  fakeApi(CONNECTIONS);
  showDrawer(CREATE);
  expect(screen.getByRole("tabpanel", { name: /Setup/ }).querySelector('[data-pointer="/body"]')).not.toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: /Options/ }));
  expect(screen.getByText("The settings are on Setup.")).toBeTruthy();
});
