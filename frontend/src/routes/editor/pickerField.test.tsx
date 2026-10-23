// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/client";
import type { StartField } from "../../lib/triggers";
import type { Option } from "./choices";
import { fakeApi, json } from "./drawer/harness";
import { PickerProvider, failedWords, isPicker, labelWord, statusWords, usePicks, type PickerForm, type Picks } from "./pickerField";
import { InputControl } from "./startInput";

afterEach(() => vi.restoreAllMocks());

const C1 = "00000000-0000-4000-8000-0000000000c1";
const SITE: StartField = {
  name: "site_id", title: "Site ID", type: "string", required: true, sensitive: false, description: "The site to onboard.",
  picker: { node: "acme.sites.get@1", field: "site_id", connection: C1, list: { plugin: "Acme", title: "Org sites", noun: "sites" } },
};  // prettier-ignore
const LYON: Option[] = [
  { value: "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d", label: "Lyon DC" },
  { value: "1b6e93f2-0000-4000-8000-000000000002", label: "Lyon store 4" },
];
const connection = (id: string, name: string) => ({
  id, name, type: "acme", status: "ok", revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore

/** A start form of one field, its picks kept as a form keeps them. */
function Form({ f = SITE, over = {}, first, onSubmit }: { f?: StartField; over?: Partial<PickerForm>; first?: Picks; onSubmit: () => void }) {
  const [value, setValue] = useState<string | undefined>(first?.get(f.name)?.value);
  const { picks, onPick } = usePicks(first);
  const form: PickerForm = { tenantId: "t1", scope: "v7", read: () => Promise.resolve(LYON), draft: false, simulated: false, picks, onPick, ...over };
  return (
    <PickerProvider value={form}>
      <form onSubmit={(e) => (e.preventDefault(), onSubmit())}>
        <InputControl f={f} value={value} onChange={setValue} />
      </form>
    </PickerProvider>
  );
}

function show(props: { f?: StartField; over?: Partial<PickerForm>; first?: Picks } = {}, connections = [connection(C1, "Acme Prod")]) {
  fakeApi({ "GET /api/v1/t/t1/connections": () => json(connections) });
  const onSubmit = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const shown = (over: typeof props) => (
    <QueryClientProvider client={qc}>
      <Form {...over} onSubmit={onSubmit} />
    </QueryClientProvider>
  );
  const { rerender } = render(shown(props));
  return { onSubmit, rerender: (over: typeof props) => rerender(shown(over)) };
}
const field = () => screen.getByRole("combobox", { name: "Site ID (required)" });
const status = () => screen.getByRole("status").textContent;
const ready = () => screen.findByText("One of Acme Prod's sites: type part of its name, then Show choices.");

describe("a picker field (the 4f-3 design §5.2)", () => {
  it("is one only for a string with a complete picker and no values, default or sensitivity", () => {
    expect(isPicker(SITE)).toBe(true);
    const others: Partial<StartField>[] = [
      { type: "integer" }, { picker: null }, { picker: undefined }, { enum: ["s1"] }, { enum_masked: true }, { default: "s1" },
      { default_masked: true }, { sensitive: true },
    ];  // prettier-ignore
    for (const over of others) expect(isPicker({ ...SITE, ...over })).toBe(false);
  });

  it("is a plain text field in a form that lists nothing", () => {
    render(<InputControl f={SITE} value="" onChange={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Site ID (required)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Show choices/ })).toBeNull();
  });

  it("says whose choices it lists before any listing, its status line describing the field", async () => {
    show();
    await ready();
    expect(field().getAttribute("aria-expanded")).toBe("false");
    const described = field().getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)?.textContent);
    expect(described).toEqual(["The site to onboard.", "One of Acme Prod's sites: type part of its name, then Show choices."]);
  });

  it("calls the connection “the connection” when the tenant's list doesn't hold it, and its list “choices” when unknown", async () => {
    show({ f: { ...SITE, picker: { ...SITE.picker!, list: null } } }, []);
    expect(await screen.findByText("One of the connection's choices: type part of its name, then Show choices.")).toBeTruthy();
  });

  it("lists what's typed on Enter, never submitting the form, the list under the field and focus in it", async () => {
    const read = vi.fn(() => Promise.resolve(LYON));
    const { onSubmit } = show({ over: { read } });
    await ready();
    await userEvent.type(field(), "ly{Enter}");
    const list = await screen.findByRole("listbox", { name: "Choices for Site ID" });
    expect(read).toHaveBeenCalledWith(SITE, SITE.picker, "ly");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(status()).toBe("2 of Acme Prod's sites have “ly” in their name.");
    expect(document.activeElement).toBe(field()); // the list waits for Down
    expect(field().getAttribute("aria-expanded")).toBe("true");
    expect(field().getAttribute("aria-controls")).toBe(list.id);
  });

  it("lists on Show choices too, saying it's reading meanwhile, Show choices waiting", async () => {
    let settle: (o: Option[]) => void = () => undefined;
    show({ over: { read: () => new Promise<Option[]>((resolve) => (settle = resolve)) } });
    await ready();
    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Show choices: Site ID" });
    expect(button.className).toContain("max-sm:min-h-[44px]");
    await userEvent.click(button);
    expect(status()).toBe("Reading Acme Prod's sites…");
    expect(button.disabled).toBe(true);
    await act(async () => {
      settle(LYON);
      await Promise.resolve();
    });
    expect(status()).toBe("2 of Acme Prod's sites.");
    expect(screen.getAllByRole("option")[0]!.className).toContain("max-sm:min-h-[44px]");
  });

  it("moves into the list on Down; Enter picks, writes the id, names it and returns to the field", async () => {
    show();
    await ready();
    await userEvent.type(field(), "ly{Enter}");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByRole("listbox"));
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(field()).toHaveProperty("value", LYON[1]!.value);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field());
    expect(status()).toBe("Lyon store 4, picked from Acme Prod's sites.");
  });

  it("closes only the list on Escape, from the field or the list, and returns to the field", async () => {
    show();
    await ready();
    const escapes = vi.fn();
    const outer = (e: KeyboardEvent) => {
      if (e.key === "Escape") escapes();
    };
    document.addEventListener("keydown", outer);
    await userEvent.type(field(), "ly{Enter}");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field());
    await userEvent.keyboard("{Enter}");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field());
    expect(escapes).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}"); // no list: the form's, or its dialog's
    expect(escapes).toHaveBeenCalledOnce();
    document.removeEventListener("keydown", outer);
  });

  it("takes Down and Escape on Show choices as in the field: into the list, or closing only it", async () => {
    show();
    await ready();
    const escapes = vi.fn();
    const outer = (e: KeyboardEvent) => {
      if (e.key === "Escape") escapes();
    };
    document.addEventListener("keydown", outer);
    await userEvent.click(screen.getByRole("button", { name: "Show choices: Site ID" }));
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByRole("listbox"));
    await userEvent.click(screen.getByRole("button", { name: "Show choices: Site ID" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field());
    expect(escapes).not.toHaveBeenCalled();
    document.removeEventListener("keydown", outer);
  });

  it("drops a listing on its way on Escape, never closing the form, and ignores its answer (the final review)", async () => {
    let settle: (o: Option[]) => void = () => undefined;
    show({ over: { read: () => new Promise<Option[]>((resolve) => (settle = resolve)) } });
    await ready();
    const escapes = vi.fn();
    const outer = (e: KeyboardEvent) => {
      if (e.key === "Escape") escapes();
    };
    document.addEventListener("keydown", outer);
    await userEvent.type(field(), "ly{Enter}");
    expect(status()).toBe("Reading Acme Prod's sites…");
    await userEvent.keyboard("{Escape}");
    expect(escapes).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(field());
    expect(status()).toBe("One of Acme Prod's sites: type part of its name, then Show choices.");
    await act(async () => {
      settle(LYON);
      await Promise.resolve();
    });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(status()).toBe("One of Acme Prod's sites: type part of its name, then Show choices.");
    document.removeEventListener("keydown", outer);
  });

  it("drops a pick's name once its value is typed over, even typed back (the owner's call, round 2)", async () => {
    show();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: "Show choices: Site ID" }));
    await userEvent.click(await screen.findByRole("option", { name: /^Lyon DC/ }));
    expect(status()).toBe("Lyon DC, picked from Acme Prod's sites.");
    await userEvent.type(field(), "x{Backspace}");
    expect(field()).toHaveProperty("value", LYON[0]!.value);
    expect(status()).toBe("One of Acme Prod's sites: type part of its name, then Show choices.");
  });

  it("names a re-run's value as picked for the first run", async () => {
    show({ first: new Map([["site_id", { value: LYON[0]!.value, label: "Lyon DC", first: true }]]) });
    expect(await screen.findByText("Lyon DC, as picked for the first run.")).toBeTruthy();
  });

  it("keeps what's typed whatever the listing answers (ruling 109)", async () => {
    show({ over: { read: () => Promise.reject(new ApiError(502, "plugin_failed", null)) } });
    await ready();
    await userEvent.type(field(), "zz{Enter}");
    expect(await screen.findByText("Acme Prod's sites couldn't be read: Mist answered with an error. Try again, or type the site's ID.")).toBeTruthy();
    expect(field()).toHaveProperty("value", "zz");
  });

  it("drops its list when the form's scope changes (ruling 109)", async () => {
    const { rerender } = show();
    await ready();
    await userEvent.type(field(), "ly{Enter}");
    await screen.findByRole("listbox");
    rerender({ over: { scope: "v8" } });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(status()).toBe("One of Acme Prod's sites: type part of its name, then Show choices.");
  });

  it("says, under a simulated form's list only, that it's read from the connection now (the owner's answer 4)", async () => {
    show({ over: { simulated: true } });
    await ready();
    expect(screen.queryByText(/^Read from/)).toBeNull();
    await userEvent.type(field(), "ly{Enter}");
    await screen.findByRole("listbox");
    expect(screen.getByText("Read from Acme Prod now: listing changes nothing in Mist.")).toBeTruthy();
  });
});

describe("a picker field's words (the 4f-3 design §5.4)", () => {
  const W = { c: "Acme Prod", C: "Acme Prod", n: "sites", label: "site" };
  const done = (count: number, query = "") =>
    ({ status: "done", options: Array.from({ length: count }, (_, i) => ({ value: `s${i}`, label: `S${i}` })), query }) as const;

  it("says what a listing found", () => {
    expect(statusWords({ status: "idle" }, null, W)).toBe("One of Acme Prod's sites: type part of its name, then Show choices.");
    expect(statusWords({ status: "idle" }, { value: "s1", label: "Lyon DC" }, W)).toBe("Lyon DC, picked from Acme Prod's sites.");
    expect(statusWords({ status: "loading" }, null, W)).toBe("Reading Acme Prod's sites…");
    expect(statusWords(done(2, "ly"), null, W)).toBe("2 of Acme Prod's sites have “ly” in their name.");
    expect(statusWords(done(1, "ly"), null, W)).toBe("1 of Acme Prod's sites has “ly” in its name.");
    expect(statusWords(done(3), null, W)).toBe("3 of Acme Prod's sites.");
    expect(statusWords(done(3, "  "), null, W)).toBe("3 of Acme Prod's sites.");
    expect(statusWords(done(0, "zurich"), null, W)).toBe("None of Acme Prod's sites has “zurich” in its name. Type less, or type the site's ID.");
    expect(statusWords(done(0), null, W)).toBe("Acme Prod has no sites: type the site's ID.");
    expect(statusWords(done(1000, "a"), null, W)).toBe("The first 1,000 of Acme Prod's sites: type part of a name to narrow them.");
    expect(statusWords({ status: "failed", why: "Why." }, null, W)).toBe("Why.");
  });

  it("says why a listing failed, per answer", () => {
    const no = (status: number, code: string, body: unknown = null) => new ApiError(status, code, body);
    const changed = no(409, "version_changed", { error: "version_changed", active_version_id: "v8", active_version_number: 8 });
    expect(failedWords(changed, W, "form")).toBe("Version 8 was published after this form opened, and its choices may differ: close the form and start again.");
    expect(failedWords(no(409, "workflow_disabled"), W, "form")).toBe("The workflow is disabled, so its choices can't be listed: type the site's ID, or enable it first.");
    expect(failedWords(no(404, "unknown_node_type"), W, "form")).toBe("This list isn't offered any more: type the site's ID. An editor can choose another list in Triggers.");
    expect(failedWords(no(422, "connection_unavailable"), W, "form")).toBe("Acme Prod can't list choices now: an editor can check it on Connections. Type the site's ID meanwhile.");
    expect(failedWords(no(422, "connection_unavailable"), W, "draft")).toBe("The draft names a connection this tenant doesn't have: choose one in Triggers › Input, or type the site's ID.");
    expect(failedWords(no(503, "plugin_calls_busy"), W, "form")).toBe("Too many lists are being read right now: try again in a moment.");
    expect(failedWords(no(429, "too_many_plugin_calls"), W, "form")).toBe("Too many lists are being read right now: try again in a moment.");
    expect(failedWords(no(409, "connection_changed"), W, "form")).toBe("Acme Prod changed while its sites were read: Show choices again.");
    expect(failedWords(no(404, "not_published"), W, "form")).toBe("This field's choices can't be listed: type the site's ID.");
    expect(failedWords(no(422, "not_a_picker"), W, "form")).toBe("This field's choices can't be listed: type the site's ID.");
    expect(failedWords(no(502, "plugin_failed"), W, "form")).toBe("Acme Prod's sites couldn't be read: Mist answered with an error. Try again, or type the site's ID.");
    // F4's three lines (ruled): no answer, Mist too slow, a role that can't list.
    expect(failedWords(new TypeError("Failed to fetch"), W, "form")).toBe("Acme Prod's sites couldn't be read: the server didn't answer. Try again, or type the site's ID.");
    expect(failedWords(no(504, "plugin_call_timeout"), W, "draft")).toBe("Acme Prod's sites couldn't be read: Mist didn't answer in time. Try again, or type the site's ID.");
    expect(failedWords(no(403, "forbidden"), W, "form")).toBe("Your role can't list these choices: type the site's ID.");
    expect(failedWords(no(422, "not_an_options_field"), W, "draft")).toBe("This list isn't offered any more: type the site's ID. An editor can choose another list in Triggers.");
    const unnamed = { c: "the connection", C: "The connection", n: "choices", label: "site" };
    expect(failedWords(no(422, "connection_unavailable"), unnamed, "form")).toBe("The connection can't list choices now: an editor can check it on Connections. Type the site's ID meanwhile.");
  });

  it("says why the list tried in the field's editor failed, in the editor's own words (F4, ruled)", () => {
    const no = (status: number, code: string) => new ApiError(status, code, null);
    expect(failedWords(no(502, "plugin_failed"), W, "editor")).toBe("Acme Prod's sites couldn't be read: Mist answered with an error. Try again.");
    expect(failedWords(new TypeError("Failed to fetch"), W, "editor")).toBe("Acme Prod's sites couldn't be read: the server didn't answer. Try again.");
    expect(failedWords(no(504, "plugin_call_timeout"), W, "editor")).toBe("Acme Prod's sites couldn't be read: Mist didn't answer in time. Try again.");
    expect(failedWords(no(422, "connection_unavailable"), W, "editor")).toBe("This tenant doesn't have the chosen connection now: choose another.");
    for (const e of [no(404, "unknown_node_type"), no(422, "not_an_options_field")])
      expect(failedWords(e, W, "editor")).toBe("This list isn't offered any more: choose another in Its choices.");
    expect(failedWords(no(403, "forbidden"), W, "editor")).toBe("Your role can't try this list.");
    expect(failedWords(no(503, "plugin_calls_busy"), W, "editor")).toBe("Too many lists are being read right now: try again in a moment.");
    expect(failedWords(no(409, "connection_changed"), W, "editor")).toBe("Acme Prod changed while its sites were read: Show choices again.");
  });

  it("calls a field by its label without “ID”, its first word lower-cased unless it's an acronym", () => {
    expect(labelWord("Site ID")).toBe("site");
    expect(labelWord("Site")).toBe("site");
    expect(labelWord("WLAN ID")).toBe("WLAN");
    expect(labelWord("Org site ID")).toBe("org site");
    expect(labelWord("site_id")).toBe("site_id");
    expect(labelWord("ID")).toBe("ID");
  });
});
