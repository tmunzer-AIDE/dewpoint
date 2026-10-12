// SPDX-License-Identifier: Apache-2.0
import { act, screen } from "@testing-library/react";
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
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(true);
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
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  const choices = await screen.findByLabelText<HTMLSelectElement>("Choices for Site");
  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "h" });
  await userEvent.selectOptions(choices, "HQ (s1)");
  expect(config().site_id).toBe("s1");
});

it("says why choices couldn't load, keeping a typed value", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ error: "plugin_calls_busy" }, 503) });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.type(screen.getByLabelText("Site"), "hq-1");
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
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
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  await screen.findByLabelText("Choices for Site"); // Prod's
  await userEvent.selectOptions(await screen.findByLabelText("Connection"), "Lab · verified");
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Prod's choices went with Prod
  await userEvent.click(screen.getByRole("button", { name: "Show choices" })); // Lab's, still on their way
  await userEvent.selectOptions(screen.getByLabelText("Connection"), "Prod · verified");
  settle(json({ options: [{ value: "s9", label: "Lab only" }] }));
  await vi.waitFor(() => expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(false));
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Lab's answer never shows under Prod
  expect(sent.filter((r) => r.path.endsWith("/options")).map((r) => (r.body as { connection_id: string }).connection_id)).toEqual([C1, C2]);
  expect(config().connection).toBe(C1);
});

it("never shows an old answer when the connection changes away and back", async () => {
  let settle: (answer: Response) => void = () => undefined;
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => new Promise<Response>((resolve) => (settle = resolve)) });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices" })); // Prod's, on their way
  const connection = screen.getByLabelText("Connection");
  await userEvent.selectOptions(connection, "Lab · verified");
  await userEvent.selectOptions(connection, "Prod · verified"); // the same scope again, a new era
  settle(json({ options: [{ value: "s1", label: "HQ" }] }));
  await new Promise((r) => setTimeout(r, 20)); // its answer has landed
  expect(screen.queryByLabelText("Choices for Site")).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(false); // ask again
});

it("keeps loading off when a refresh of the connections fails", async () => {
  let calls = 0;
  fakeApi({ [CONNECTIONS]: () => (++calls === 1 ? both() : json({ error: "http_error" }, 500)) });
  const { client } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await act(() => client.invalidateQueries()); // refreshed, and failed: the old list stays cached
  expect(await screen.findByText("Connections couldn't load, so the choices can't either.")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(true);
});

it("releases text a write turned away once a choice is written", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ options: [{ value: "s1", label: "HQ" }] }) });
  const { config, held, refuse } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  refuse("Not written: the draft can't be changed now.");
  await userEvent.type(screen.getByLabelText("Site"), "old-text"); // held, never written
  refuse(null);
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  await userEvent.selectOptions(await screen.findByLabelText("Choices for Site"), "HQ (s1)");
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
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(true);
});
