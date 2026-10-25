// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WORDS } from "../../../lib/changes";
import { UPDATE } from "../../../test/nodeTypes";
import { fakeApi, json, problem, showDrawer } from "./harness";

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
  await userEvent.click(within(at("/body/rogue")).getByRole("button", { name: "Remove Rogue › Enabled" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/rogue")).getByText(WORDS.pending)).toBeTruthy();
});

it("says how merge and replace treat the parts not given", async () => {
  showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
  expect(within(at("/body/rogue")).getByText(`AP threat detection settings for the site ${WORDS.partsMerge}`)).toBeTruthy(); // #140 item 1
  await userEvent.click(screen.getByRole("radio", { name: WORDS.replace }));
  expect(within(at("/body/rogue")).getByText(`AP threat detection settings for the site ${WORDS.partsReplace}`)).toBeTruthy();
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
  await userEvent.click(screen.getByRole("button", { name: "Move down: Networks › item 1" }));
  expect(config()).toEqual({ body: { networks: [{}, { name: "a" }] } });
});

it("keeps a secret one field, never its parts", () => {
  showDrawer(UPDATE, { config: { body: { api_secret: "x", radius: { host: "h" } } } });
  expect(within(at("/body/api_secret")).queryByRole("button", { name: /Another setting/ })).toBeNull();
  expect(within(at("/body/radius")).getByLabelText("Host")).toBeTruthy(); // a part is a secret, not the whole
});

// The final review's findings.
it("finds a setting through a list or a map from ＋ Another setting of …", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true } } } });
  const another = async (word: string, option: RegExp) => {
    await userEvent.click(within(at("/body/auto_upgrade")).getByRole("button", { name: "＋ Another setting of Auto upgrade" }));
    await userEvent.type(within(at("/body/auto_upgrade")).getByRole("combobox", { name: "Find a setting of Auto upgrade" }), word);
    await userEvent.click(within(at("/body/auto_upgrade")).getByRole("option", { name: option }));
  };
  await another("day", /Schedules › an item › Day/);
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true, schedules: [{}] } } }); // the item's place is written
  const day = within(at("/body/auto_upgrade/schedules/0")).getByLabelText("Day");
  await vi.waitFor(() => expect(document.activeElement).toBe(day));
  await userEvent.type(day, "sun");
  await another("channel", /Profiles › an entry › Channel/);
  await userEvent.type(screen.getByLabelText("Name of the new entry"), "ap{Enter}");
  await userEvent.type(within(at("/body/auto_upgrade/profiles/ap")).getByLabelText("Channel"), "6");
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true, schedules: [{ day: "sun" }], profiles: { ap: { channel: "6" } } } } });
});

it("shows a problem at a part it doesn't draw on the part that holds it", () => {
  showDrawer(UPDATE, { config: { body: { networks: [{ id: "n1", name: "a" }] } }, problems: [problem("/body/networks/0/id", "Mist sets it.")] });
  expect(within(at("/body/networks/0")).getByText("Mist sets it.")).toBeTruthy();
});

it("keeps focus after a Remove, on ＋ Another setting of …", async () => {
  showDrawer(UPDATE, { config: { body: { rogue: { enabled: true, min_rogue_rssi: -80 } } } });
  await userEvent.click(within(at("/body/rogue")).getByRole("button", { name: "Remove Rogue › Enabled" }));
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/rogue")).getByRole("button", { name: "＋ Another setting of Rogue" })));
});

// F1: a place a Remove empties (#140-8, #140-9).
it("sends no list its last item's Remove empties: the setting goes back to nothing given, focus on ＋ Add an item", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { networks: [{ name: "a" }] } } });
  await userEvent.click(within(at("/body/networks")).getByRole("button", { name: "Remove: Networks › item 1" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/networks")).getByText(WORDS.pending)).toBeTruthy();
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/networks")).getByRole("button", { name: "＋ Add an item" })));
});

it("sends nothing for a list found, an item added and removed again", async () => {
  const { config } = showDrawer(UPDATE, { config: {} });
  await userEvent.type(screen.getByRole("combobox", { name: "Find a setting" }), "networks");
  await userEvent.click(screen.getByRole("option", { name: /^Networks(?! ›)/ }));
  await userEvent.click(within(at("/body/networks")).getByRole("button", { name: "＋ Add an item" }));
  expect(config()).toEqual({ body: { networks: [{}] } });
  await userEvent.click(within(at("/body/networks")).getByRole("button", { name: "Remove: Networks › item 1" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/networks")).getByText(WORDS.pending)).toBeTruthy();
});

it("keeps a list emptied inside an object drawn there, nothing given, focus on its ＋ Add an item", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, schedules: [{ day: "sun" }] } } } });
  await userEvent.click(within(at("/body/auto_upgrade/schedules")).getByRole("button", { name: "Remove: Schedules › item 1" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  expect(within(at("/body/auto_upgrade/schedules")).getByText(WORDS.pending)).toBeTruthy();
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/schedules")).getByRole("button", { name: "＋ Add an item" })));
});

it("sends no plain list its last item's Remove empties: its row stays, nothing given, focus on its Add", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { tags: ["x"] } } });
  await userEvent.click(within(at("/body/tags")).getByRole("button", { name: "Remove: Tags, item 1" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/tags")).getByText(WORDS.pending)).toBeTruthy();
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/tags")).getByRole("button", { name: "Add to Tags" })));
});

it("keeps an object a Remove empties drawn in its own, focus on its ＋ Another setting of …", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, custom: { ap41: "1.2" } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/custom")).getByRole("button", { name: "Remove Custom versions › AP41" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/custom")).getByRole("button", { name: "＋ Another setting of Custom versions" })));
});

it("keeps each object a Remove empties drawn, up to its setting's row, nothing given", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { custom: { ap41: "1.2" } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/custom")).getByRole("button", { name: "Remove Custom versions › AP41" }));
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/auto_upgrade")).getAllByText(WORDS.pending)).toHaveLength(2); // the row's, and Custom versions'
  expect(within(at("/body/auto_upgrade/custom")).getByText(WORDS.pending)).toBeTruthy();
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/custom")).getByRole("button", { name: "＋ Another setting of Custom versions" })));
});

it("keeps a map its last entry's Remove empties drawn in its object, focus on its ＋ Add an entry", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, profiles: { ap: { channel: "6" } } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/profiles")).getByRole("button", { name: "Remove Profiles › ap" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/profiles")).getByRole("button", { name: "＋ Add an entry" })));
});

it("keeps a plain map its last entry's Remove empties drawn in its object, focus on its Add", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, labels: { hq: ["a"] } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Remove: hq" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Add to Labels" })));
});

it("takes out a plain map's entry its last item's Remove empties, focus on the map's Add", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, labels: { hq: ["a"], lab: ["b"] } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Remove: hq, item 1" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true, labels: { lab: ["b"] } } } });
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Add to Labels" })));
});

it("keeps a plain map its only entry's last item empties drawn, focus on its Add", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, labels: { hq: ["a"] } } } } });
  await userEvent.click(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Remove: hq, item 1" }));
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  await vi.waitFor(() => expect(document.activeElement).toBe(within(at("/body/auto_upgrade/labels")).getByRole("button", { name: "Add to Labels" })));
});

it("keeps a part whose value is cleared drawn, nothing given, focus in it: typing goes on", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { enabled: true, min_rogue_rssi: -80 } } } });
  const rssi = within(at("/body/rogue")).getByLabelText("Min rogue RSSI");
  await userEvent.clear(rssi);
  expect(config()).toEqual({ body: { rogue: { enabled: true } } });
  expect(within(at("/body/rogue/min_rogue_rssi")).getByText(WORDS.pending)).toBeTruthy();
  expect(document.activeElement).toBe(rssi);
  await userEvent.type(rssi, "-70");
  expect(config()).toEqual({ body: { rogue: { enabled: true, min_rogue_rssi: -70 } } });
});

it("keeps a row whose value is cleared, nothing given, focus in it", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" } } });
  const name = within(at("/body/name")).getByLabelText("Name");
  await userEvent.clear(name);
  expect(config()).toEqual({ body: {} });
  expect(within(at("/body/name")).getByText(WORDS.pending)).toBeTruthy();
  expect(document.activeElement).toBe(name);
});

it("keeps each object a cleared part empties drawn, focus in the part", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, custom: { ap41: "1.2" } } } } });
  const ap41 = within(at("/body/auto_upgrade/custom")).getByLabelText("AP41");
  await userEvent.clear(ap41);
  expect(config()).toEqual({ body: { auto_upgrade: { enabled: true } } });
  expect(document.activeElement).toBe(ap41);
});

it("sends no list edited as JSON to []: it stays drawn, nothing given, up to its row", async () => {
  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { whitelisted_ssids: ["a"] }, name: "hq" } } });
  await userEvent.click(within(at("/body/rogue/whitelisted_ssids")).getByRole("button", { name: "Edit as JSON" }));
  const box = within(at("/body/rogue/whitelisted_ssids")).getByRole("textbox");
  await userEvent.clear(box);
  await userEvent.type(box, "[[]");
  await userEvent.tab();
  expect(config()).toEqual({ body: { name: "hq" } });
  expect(within(at("/body/rogue")).getAllByText(WORDS.pending)).toHaveLength(2); // the row's, and the list's
  expect(within(at("/body/rogue/whitelisted_ssids")).getByText(WORDS.pending)).toBeTruthy();
});

// F5 (#140): words and names.
it("names a part's Remove by its object too, so two Enabled parts are told apart (#140 N8)", () => {
  showDrawer(UPDATE, { config: { body: { rogue: { enabled: true }, auto_upgrade: { enabled: true } } } });
  expect(screen.getByRole("button", { name: "Remove Rogue › Enabled" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Remove Auto upgrade › Enabled" })).toBeTruthy();
});

it("ties a new entry's refusal to its name field (#140 item 6a)", async () => {
  showDrawer(UPDATE, { config: { body: { port_usages: { trunk: { mode: "trunk" } } } } });
  await userEvent.click(screen.getByRole("button", { name: "＋ Add an entry" }));
  const name = screen.getByLabelText("Name of the new entry");
  await userEvent.type(name, "trunk{Enter}");
  expect(document.getElementById(name.getAttribute("aria-describedby") ?? "")?.textContent).toBe("Port usages has an entry named trunk already.");
});

it("says “· In Changes” in an object's own Find for a part drawn under it, nested too, never through a list's item (#140 item 5)", async () => {
  showDrawer(UPDATE, { config: { body: { auto_upgrade: { enabled: true, custom: { ap41: "1.2" }, schedules: [{ day: "sun" }] } } } });
  await userEvent.click(within(at("/body/auto_upgrade")).getByRole("button", { name: "＋ Another setting of Auto upgrade" }));
  const find = within(at("/body/auto_upgrade")).getByRole("combobox", { name: "Find a setting of Auto upgrade" });
  const hit = (name: RegExp) => within(at("/body/auto_upgrade")).getByRole("option", { name }).textContent;
  await userEvent.type(find, "ap41");
  expect(hit(/^Custom versions › AP41/)).toContain("· In Changes");
  await userEvent.clear(find);
  await userEvent.type(find, "day");
  expect(hit(/^Schedules › an item › Day/)).not.toContain("· In Changes");
});
