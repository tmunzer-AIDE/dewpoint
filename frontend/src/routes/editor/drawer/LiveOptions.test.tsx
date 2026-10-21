// SPDX-License-Identifier: Apache-2.0
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { literal } from "../../../lib/config";
import { REMOTE } from "../../../test/nodeTypes";
import { fakeApi, json, showFields } from "./harness";

afterEach(() => {
  vi.restoreAllMocks();
});

const C1 = "00000000-0000-4000-8000-0000000000c1";
const C2 = "00000000-0000-4000-8000-0000000000c2";
const CONNECTIONS = "GET /api/v1/t/t1/connections";
const OPTIONS = "POST /api/v1/t/t1/node-types/acme.sites@1/options";
const connection = (id: string, name: string) => ({
  id, name, type: "acme", status: "ok", revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore
const both = () => json([connection(C1, "Prod"), connection(C2, "Lab")]);

it("never loads on render", async () => {
  const sent = fakeApi({ [CONNECTIONS]: both });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" }); // what loads by itself has loaded
  expect(sent.map((r) => `${r.method} ${r.path}`)).toEqual([CONNECTIONS]);
});

it("asks for a connection before loading", () => {
  fakeApi({ [CONNECTIONS]: both });
  showFields(REMOTE);
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site" }).disabled).toBe(true);
  expect(screen.getByText("Choose the step's connection first: the choices come from it.")).toBeTruthy();
});

it("loads the choices on request, with the connection and the text typed, and sets the one chosen", async () => {
  const sent = fakeApi({
    [CONNECTIONS]: both,
    [OPTIONS]: () => json({ options: [{ value: "s1", label: "HQ" }, { value: "s2", label: "Lab" }] }),
  });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" }); // its revision known: the scope is settled
  await userEvent.type(screen.getByLabelText("Site"), "h");
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  const choices = await screen.findByRole("listbox", { name: "Choices for Site" });
  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "h" });
  await userEvent.click(within(choices).getByRole("option", { name: /^HQ/ }));
  expect(config().site_id).toBe("s1");
});

it("says why choices couldn't load, keeping a typed value", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ error: "plugin_calls_busy" }, 503) });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.type(screen.getByLabelText("Site"), "hq-1");
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  expect(await screen.findByText("Too many requests right now. Try again in a moment.")).toBeTruthy();
  expect(config().site_id).toBe("hq-1");
});

it("drops choices when their connection changes, and ignores an answer for the old one", async () => {
  let settle: (answer: Response) => void = () => undefined;
  let calls = 0;
  const sent = fakeApi({
    [CONNECTIONS]: both,
    [OPTIONS]: () => (++calls === 1 ? json({ options: [{ value: "s1", label: "HQ" }] }) : new Promise<Response>((resolve) => (settle = resolve))),
  });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  await screen.findByLabelText("Choices for Site"); // Prod's
  await userEvent.selectOptions(await screen.findByLabelText("Connection"), "Lab · verified");
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Prod's choices went with Prod
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" })); // Lab's, still on their way
  await userEvent.selectOptions(screen.getByLabelText("Connection"), "Prod · verified");
  settle(json({ options: [{ value: "s9", label: "Lab only" }] }));
  await vi.waitFor(() => expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site" }).disabled).toBe(false));
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Lab's answer never shows under Prod
  expect(sent.filter((r) => r.path.endsWith("/options")).map((r) => (r.body as { connection_id: string }).connection_id)).toEqual([C1, C2]);
  expect(config().connection).toBe(C1);
});

it("never shows an old answer when the connection changes away and back", async () => {
  let settle: (answer: Response) => void = () => undefined;
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => new Promise<Response>((resolve) => (settle = resolve)) });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" })); // Prod's, on their way
  const connection = screen.getByLabelText("Connection");
  await userEvent.selectOptions(connection, "Lab · verified");
  await userEvent.selectOptions(connection, "Prod · verified"); // the same scope again, a new era
  settle(json({ options: [{ value: "s1", label: "HQ" }] }));
  await new Promise((r) => setTimeout(r, 20)); // its answer has landed
  expect(screen.queryByLabelText("Choices for Site")).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site" }).disabled).toBe(false); // ask again
});

it("keeps loading off when a refresh of the connections fails", async () => {
  let calls = 0;
  fakeApi({ [CONNECTIONS]: () => (++calls === 1 ? both() : json({ error: "http_error" }, 500)) });
  const { client } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await act(() => client.invalidateQueries()); // refreshed, and failed: the old list stays cached
  expect(await screen.findByText("Connections couldn't load, so the choices can't either.")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site" }).disabled).toBe(true);
});

it("releases text a write turned away once a choice is written", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ options: [{ value: "s1", label: "HQ" }] }) });
  const { config, held, refuse } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  refuse("Not written: the draft can't be changed now.");
  await userEvent.type(screen.getByLabelText("Site"), "old-text"); // held, never written
  refuse(null);
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  await userEvent.click(within(await screen.findByRole("listbox", { name: "Choices for Site" })).getByRole("option", { name: /^HQ/ }));
  expect(config().site_id).toBe("s1");
  expect(screen.getByLabelText<HTMLInputElement>("Site").value).toBe("s1");
  expect(held()).toEqual([]);
});

it("keeps a literal's reading for text a write turned away, through an undo and Apply here", async () => {
  fakeApi({ [CONNECTIONS]: both });
  const { config, refuse, replace } = showFields(REMOTE, { config: { connection: C1, site_id: literal("old") } });
  await screen.findByRole("option", { name: "Prod · verified" });
  refuse("Not written: the draft can't be changed now.");
  await userEvent.clear(screen.getByLabelText("Site"));
  await userEvent.type(screen.getByLabelText("Site"), "new"); // held, as a literal's
  refuse(null);
  replace({ connection: C1, site_id: "plain" }); // an undo: plain data now
  await userEvent.click(screen.getByRole("button", { name: "Apply here: Site" }));
  expect(config().site_id).toEqual(literal("new"));
});

it("keeps loading off while the connection's revision isn't known", async () => {
  fakeApi({ [CONNECTIONS]: () => json({ error: "http_error" }, 500) });
  showFields(REMOTE, { config: { connection: C1 } });
  expect(await screen.findByText("Connections couldn't load, so the choices can't either.")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site" }).disabled).toBe(true);
});

it("names each Show choices button by its field, its visible text first (#73)", () => {
  fakeApi({ [CONNECTIONS]: both });
  const properties = { ...(REMOTE.config_schema.properties as object), device_id: { type: "string", title: "Device", "x-dewpoint-options": true } };
  const two = { ...REMOTE, config_schema: { ...REMOTE.config_schema, properties }, options: ["site_id", "device_id"] };
  showFields(two, { config: { connection: C1 } });
  const buttons = screen.getAllByRole("button", { name: /^Show choices/ });
  expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Show choices: Site", "Show choices: Device"]);
  expect(buttons.map((b) => b.textContent)).toEqual(["Show choices", "Show choices"]);
});

const ID = "5c1e0b1a-3f7d-4a1e-9b8c-2d4e6f8a0b1c";
const sites = () => json({ options: [{ value: ID, label: "HQ Paris" }, { value: "s2", label: "Lab" }] });

it("takes a value from an earlier step, and then asks for every choice", async () => {
  const sent = fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
  const site = { $value: { kind: "template", parts: [{ ref: "steps.get_site.output.id" }] } };
  const { config } = showFields(REMOTE, { config: { connection: C1, site_id: site } });
  await screen.findByRole("option", { name: "Prod · verified" });
  const field = within(document.querySelector<HTMLElement>('[data-pointer="/site_id"]')!);
  expect(field.getByRole("button", { name: "Text" }).getAttribute("aria-pressed")).toBe("true");
  expect(field.getByRole("button", { name: "＋ Data" })).toBeTruthy();
  expect(screen.getByText(/A value from an earlier step, or one of the connection's choices: Show choices lists them\./)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "" });
  await userEvent.click(within(list).getByRole("option", { name: /^HQ Paris/ }));
  expect(config().site_id).toBe(ID); // the pick replaces the value from the step
});

it("shows a choice known only by its id once", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ options: [{ value: "s9", label: "s9" }] }) });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
  expect(within(list).getByRole("option").textContent).toBe("s9");
  expect(screen.getByRole("status").textContent).toBe("1 choice");
});

it("shows each choice's name and the start of its id, and names a pick until the value changes", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
  expect(screen.getByRole("status").textContent).toBe("2 choices");
  const hq = within(list).getByRole("option", { name: /^HQ Paris/ });
  expect(hq.textContent).toBe("HQ Paris5c1e0b1a…");
  await userEvent.click(hq);
  expect(config().site_id).toBe(ID);
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(screen.getByText("HQ Paris, picked from the choices.")).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Site"), "x");
  expect(screen.queryByText("HQ Paris, picked from the choices.")).toBeNull();
});

it("moves through the choices by keyboard, and Escape closes them without a pick", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
  expect(document.activeElement).toBe(list);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(config().site_id).toBeUndefined();
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Site")));
  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
  await screen.findByRole("listbox", { name: "Choices for Site" });
  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(config().site_id).toBe("s2");
  expect(screen.getByText("Lab, picked from the choices.")).toBeTruthy();
});
