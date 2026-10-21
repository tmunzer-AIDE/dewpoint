// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WORDS } from "../../../lib/changes";
import { UPDATE } from "../../../test/nodeTypes";
import { fakeApi, json, showDrawer } from "./harness";

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
});
afterEach(() => {
  vi.restoreAllMocks();
});

const at = (pointer: string) => [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === pointer)!;

it("shows an object's parts given, and finds the others; one added is written only once given", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
  const rogue = () => at("/body/rogue");
  expect(within(rogue()).getByLabelText("Enabled")).toBeTruthy();
  expect(within(rogue()).queryByLabelText("Min rogue RSSI")).toBeNull();
  await userEvent.click(within(rogue()).getByRole("button", { name: "＋ Another setting of Rogue" }));
  const find = within(rogue()).getByRole("combobox", { name: "Find a setting of Rogue" });
  expect(document.activeElement).toBe(find);
  await userEvent.type(find, "rssi");
  await userEvent.click(within(rogue()).getByRole("option", { name: /Min rogue RSSI/ }));
  expect(config()).toEqual({ body: { rogue: { enabled: true } } });
  await userEvent.type(within(rogue()).getByLabelText("Min rogue RSSI"), "-80");
  expect(config()).toEqual({ body: { rogue: { enabled: true, min_rogue_rssi: -80 } } });
});

it("takes a part off with Remove, never Clear; a setting emptied keeps its row, nothing given", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
  expect(within(at("/body/rogue")).queryByRole("button", { name: "Clear Enabled" })).toBeNull();
  await userEvent.click(within(at("/body/rogue")).getByRole("button", { name: "Remove Enabled" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/rogue")).getByText(WORDS.pending)).toBeTruthy();
});

it("says how merge and replace treat the parts not given", async () => {
  showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
  expect(within(at("/body/rogue")).getByText(WORDS.partsMerge)).toBeTruthy();
  await userEvent.click(screen.getByRole("radio", { name: WORDS.replace }));
  expect(within(at("/body/rogue")).getByText(WORDS.partsReplace)).toBeTruthy();
});

it("adds a nested setting from Find, each object on its way opened, focus on it", async () => {
  const { config } = showDrawer(UPDATE, { config: {} });
  await userEvent.type(screen.getByRole("combobox", { name: "Find a setting" }), "ap41");
  await userEvent.click(screen.getByRole("option", { name: /AP41/ }));
  const ap41 = within(at("/body/auto_upgrade/custom")).getByLabelText("AP41");
  await vi.waitFor(() => expect(document.activeElement).toBe(ap41));
  expect(config()).toEqual({});
  await userEvent.type(ap41, "1.2");
  expect(config()).toEqual({ body: { auto_upgrade: { custom: { ap41: "1.2" } } } });
});

it("draws a map's entries by key, a new one's key first, a setting found in one too", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { port_usages: { trunk: { mode: "trunk" } } } } });
  expect(within(at("/body/port_usages/trunk")).getByLabelText("Mode")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "＋ Add an entry" }));
  await userEvent.type(screen.getByLabelText("Name of the new entry"), "trunk{Enter}");
  expect(screen.getByText("Port usages has an entry named trunk already.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Name of the new entry"));
  await userEvent.type(screen.getByLabelText("Name of the new entry"), "uplink{Enter}");
  const own = within(at("/body/port_usages/uplink")).getByRole("combobox", { name: "Find a setting of Port usages › uplink" });
  await vi.waitFor(() => expect(document.activeElement).toBe(own)); // its own list, focused
  expect(config()).toEqual({ body: { port_usages: { trunk: { mode: "trunk" } } } });
  await userEvent.type(screen.getByRole("combobox", { name: "Find a setting" }), "port vlan");
  await userEvent.click(screen.getByRole("option", { name: /Port usages › an entry › Port VLAN/ }));
  await userEvent.type(screen.getByLabelText("Name of the new entry"), "access{Enter}");
  await userEvent.type(within(at("/body/port_usages/access")).getByLabelText("Port VLAN"), "10");
  expect(config()).toEqual({ body: { port_usages: { trunk: { mode: "trunk" }, access: { port_vlan: 10 } } } });
});

it("draws a list's items by number, an item added written empty, and says a list is sent whole", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { networks: [{ name: "a" }] } } });
  expect(within(at("/body/networks/0")).getByLabelText("Name")).toBeTruthy();
  expect(within(at("/body/networks")).getByText(WORDS.wholeList)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "＋ Add an item" }));
  expect(config()).toEqual({ body: { networks: [{ name: "a" }, {}] } });
  await userEvent.click(screen.getByRole("button", { name: "Move down: item 1" }));
  expect(config()).toEqual({ body: { networks: [{}, { name: "a" }] } });
});

it("keeps a secret one field, never its parts", () => {
  showDrawer(UPDATE, { config: { body: { api_secret: "x", radius: { host: "h" } } } });
  expect(within(at("/body/api_secret")).queryByRole("button", { name: /Another setting/ })).toBeNull();
  expect(within(at("/body/radius")).getByLabelText("Host")).toBeTruthy(); // a part is a secret, not the whole
});
