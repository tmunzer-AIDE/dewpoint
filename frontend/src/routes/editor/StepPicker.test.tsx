// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { GROUPED, IF, typeWith } from "../../test/nodeTypes";
import { fakeApi, json } from "./drawer/harness";
import { StepPicker, type PickMode } from "./StepPicker";

afterEach(() => {
  vi.restoreAllMocks();
});

const t = (ref: string, kind: "control" | "action", ports: string[], extra = {}) => ({
  ref, type: ref.split("@")[0], version: 1, kind, state: "active", title: ref.split("@")[0]!.split(".").pop(), description: `does ${ref}`,
  ports, dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none", credentials: [], capabilities: [],
  retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] }, timeout_s: 60, ...extra,
}) as never;  // prettier-ignore
const TYPES = [
  t("flow.transform@1", "control", ["out"]),
  t("flow.if@1", "control", ["true", "false"]),
  t("flow.old@1", "control", ["out"], { state: "deprecated" }),
  t("testkit.http_call@1", "action", ["out"], { side_effect: "idempotent", credentials: ["testkit"] }),
];
const EDGE = { from: { node: "a", port: "out" }, to: { node: "b" } };
const AFTER: PickMode = { kind: "after", from: { node: "a", port: "out" } };
const KINDS = "GET /api/v1/connection-types";

function show(mode: PickMode, types: unknown[], more: { onPick?: () => void; onConnect?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StepPicker mode={mode} types={types as never} onPick={more.onPick ?? vi.fn()} onConnect={more.onConnect} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

it("offers every active type after a port, in Flow and Actions, with what an action changes and needs", async () => {
  fakeApi({});
  const onPick = vi.fn();
  show(AFTER, TYPES, { onPick, onConnect: vi.fn() });
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /flow\.old@1/ })).toBeNull(); // deprecated: new versions shouldn't use it
  const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
  expect(call.textContent).toContain("Changes things; safe to repeat");
  expect(call.textContent).toContain("Uses a testkit connection"); // its type's label unknown: its key
  await userEvent.click(screen.getByRole("option", { name: /flow\.if@1/ }));
  expect(onPick).toHaveBeenCalledWith(TYPES[1]);
});

it("names a step's connection by its type's label", async () => {
  fakeApi({ [KINDS]: () => json([{ key: "testkit", label: "Test Kit", config_schema: {}, secret_fields: [], clouds: null }]) });
  show(AFTER, TYPES);
  const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
  await vi.waitFor(() => expect(call.textContent).toContain("Uses a Test Kit connection"));
});

it("offers only steps that continue the flow mid-edge, and says why", () => {
  fakeApi({});
  show({ kind: "insert", edge: EDGE }, TYPES);
  expect(screen.queryByRole("option", { name: /flow\.if@1/ })).toBeNull();
  expect(screen.getByRole("option", { name: /flow\.transform@1/ })).toBeTruthy();
  expect(screen.getByText("Only steps that continue the flow can go here.")).toBeTruthy();
});

it("offers to connect an existing step instead, after a port", async () => {
  fakeApi({});
  const onConnect = vi.fn();
  show(AFTER, TYPES, { onConnect });
  await userEvent.click(screen.getByRole("option", { name: "Connect to an existing step…" }));
  expect(onConnect).toHaveBeenCalled();
});

it("shows a plugin's groups in place of its steps, with how many and what they do", () => {
  fakeApi({});
  show(AFTER, [IF, ...GROUPED]);
  expect(screen.getByText("Acme: 3 resources, type to find one")).toBeTruthy();
  expect(screen.getByPlaceholderText("Type a step's name or a Acme resource")).toBeTruthy();
  const wlans = screen.getByRole("option", { name: /^Org WLANs/ });
  expect(wlans.textContent).toContain("4 actions");
  expect(wlans.textContent).toContain("Create, Delete, List, Update");
  expect(screen.getAllByRole("option").map((o) => o.textContent?.split(/\d+ actions?|flow\./)[0])).toEqual(["If", "Org WLANs", "Site settings", "Site WLANs"]);
  expect(screen.queryByRole("option", { name: /Update org WLAN/ })).toBeNull();
});

it("finds groups by each word typed, and a step by the start of its title", async () => {
  fakeApi({});
  show(AFTER, [IF, ...GROUPED]);
  const search = screen.getByRole("combobox");
  await userEvent.type(search, "wlan");
  expect(screen.getAllByRole("option").map((o) => o.textContent?.split(/\d+ actions?/)[0])).toEqual(["Org WLANs", "Site WLANs"]);
  expect(screen.getByText("Acme resources")).toBeTruthy();
  await userEvent.clear(search);
  await userEvent.type(search, "update org wlan");
  const step = within(screen.getByRole("group", { name: "Acme step" })).getByRole("option");
  expect(step.textContent).toContain("Update org WLAN");
  expect(within(screen.getByRole("group", { name: "Acme resources" })).getByRole("option", { name: /^Org WLANs/ })).toBeTruthy();
});

it("leaves out a group mid-edge when none of its steps continues the flow", () => {
  fakeApi({});
  const ends = typeWith({ "x-group": { plugin: "Acme", title: "Org alarms" } }, { ref: "acme.org_alarms.ack@1", title: "Ack org alarm", ports: [] });
  show({ kind: "insert", edge: EDGE }, [...GROUPED, ends]);
  expect(screen.getByText("Acme: 3 resources, type to find one")).toBeTruthy();
  expect(screen.queryByRole("option", { name: /^Org alarms/ })).toBeNull();
});

it("lists a grouped step itself when its ref is typed", async () => {
  fakeApi({});
  const onPick = vi.fn();
  show(AFTER, [IF, ...GROUPED], { onPick });
  await userEvent.type(screen.getByRole("combobox"), "acme.org_wlans.update");
  const step = within(screen.getByRole("group", { name: "Acme step" })).getByRole("option");
  expect(step.textContent).toContain("acme.org_wlans.update@1");
  await userEvent.click(step);
  expect(onPick).toHaveBeenCalledWith(GROUPED[2]);
});

it("opens a group's steps by title, and goes back with Back or Backspace", async () => {
  fakeApi({});
  const onPick = vi.fn();
  show(AFTER, [IF, ...GROUPED], { onPick });
  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
  expect(screen.getByRole("dialog", { name: "Add a step: Org WLANs" })).toBeTruthy();
  expect(screen.getAllByRole("option").map((o) => o.textContent?.split("acme.")[0])).toEqual(["Create org WLAN", "Delete org WLAN", "List org WLANs", "Update org WLAN"]);
  await userEvent.click(screen.getByRole("button", { name: "Back to every step" }));
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
  await userEvent.type(screen.getByRole("combobox"), "u{Backspace}"); // a character typed goes first, the group stays
  expect(screen.getByRole("dialog", { name: "Add a step: Org WLANs" })).toBeTruthy();
  await userEvent.keyboard("{Backspace}");
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
  await userEvent.type(screen.getByRole("combobox"), "upd{Enter}");
  expect(onPick).toHaveBeenCalledWith(GROUPED[2]);
});

it("selects the group's row again after Back, with or without text typed in its view (the final review)", async () => {
  fakeApi({});
  const onPick = vi.fn();
  show(AFTER, [IF, ...GROUPED], { onPick });
  const row = () => screen.getByRole("option", { name: /^Site WLANs/ });
  await userEvent.click(row());
  await userEvent.keyboard("{Backspace}");
  await vi.waitFor(() => expect(row().getAttribute("aria-selected")).toBe("true"));
  await userEvent.click(row());
  await userEvent.type(screen.getByRole("combobox"), "lis");
  await userEvent.click(screen.getByRole("button", { name: "Back to every step" }));
  await vi.waitFor(() => expect(row().getAttribute("aria-selected")).toBe("true")); // not Flow's first step
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("dialog", { name: "Add a step: Site WLANs" })).toBeTruthy();
  expect(onPick).not.toHaveBeenCalled();
});
