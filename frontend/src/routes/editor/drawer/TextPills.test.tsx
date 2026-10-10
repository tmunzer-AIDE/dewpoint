// SPDX-License-Identifier: Apache-2.0
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const NOTE = typeWith(
  { type: "object", properties: { message: { type: "string", title: "Message" } }, required: ["message"] },
  { ref: "acme.note@1", type: "acme.note", title: "Post a note" },
);
const SITE = "00000000-0000-4000-8000-000000000002";
const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });

const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: null, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore

const ENTRIES: ScopeEntry[] = [
  entry("steps.get_site.output", { name: "output", types: ["object"], children: true }),
  entry("steps.get_site.output.name", { parent: "steps.get_site.output" }),
  entry("steps.get_site.output.timezone", { parent: "steps.get_site.output", missing: true }),
  entry("run.now", { root: "run", step: null, name: "now", format: "date-time" }),
];

const scope = (q: URLSearchParams) => {
  const at = q.get("at");
  const answer = (entries: ScopeEntry[]) =>
    json({ draft_revision: 1, node: NODE_ID, field: q.get("field"), state: "ok", reason: null, entries, more: false, problem: null });
  if (at !== null) return answer(ENTRIES.filter((e) => e.path === at));
  const under = q.get("under");
  if (under !== null) return answer(ENTRIES.filter((e) => e.parent === under));
  return answer(ENTRIES);
};

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/workflows/w1/draft/scope": scope });
});
afterEach(() => vi.restoreAllMocks());

const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "get_site", title: "Get a site" },
];

describe("text with data pills", () => {
  it("writes typed text as text, and the field's mode is Text", async () => {
    const f = showFields(NOTE, { steps });
    expect(screen.getByRole("button", { name: "Text" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.type(screen.getByLabelText("Message"), "AP down");
    expect(f.config()).toEqual({ message: "AP down" });
  });

  it("inserts a pill from the tree at the caret, and writes a template", async () => {
    const f = showFields(NOTE, { steps, config: { message: "AP  went offline" } });
    const text = screen.getByLabelText("Message");
    await userEvent.click(text);
    (text as HTMLInputElement).setSelectionRange(3, 3);
    fireEvent.select(text);
    await userEvent.click(screen.getByRole("button", { name: "＋ Data" }));
    const tree = await screen.findByRole("tree", { name: "Data available here" });
    await userEvent.click(within(tree).getByText("name"));
    expect(f.config()).toEqual({ message: template({ text: "AP " }, { ref: "steps.get_site.output.name" }, { text: " went offline" }) });
    expect(screen.queryByRole("tree")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Message, text after get_site › name" })));
  });

  it("opens the tree with / at a text's start or after a space, never inside a word or a URL", async () => {
    showFields(NOTE, { steps, config: { message: "https:" } });
    const text = screen.getByLabelText("Message");
    await userEvent.type(text, "/");
    expect(screen.queryByRole("dialog", { name: "Insert data" })).toBeNull();
    await userEvent.type(text, " /");
    expect(await screen.findByRole("dialog", { name: "Insert data" })).toBeTruthy();
  });

  it("replaces the / typed to ask for data with the pill picked", async () => {
    const f = showFields(NOTE, { steps });
    await userEvent.type(screen.getByLabelText("Message"), "at /");
    const tree = await screen.findByRole("tree");
    await userEvent.click(within(tree).getByText("now"));
    expect(f.config()).toEqual({ message: template({ text: "at " }, { ref: "run.now" }) });
  });

  it("keeps the / when the tree is closed with Escape, and puts focus back after it", async () => {
    const f = showFields(NOTE, { steps });
    await userEvent.type(screen.getByLabelText("Message"), "a /");
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tree")).toBeNull();
    expect(f.config()).toEqual({ message: "a /" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Message")));
  });

  it("moves past a pill with the arrows, and removes it with Backspace, joining the texts either side", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }, { text: " down" }) } });
    const after = screen.getByRole("textbox", { name: "Message, text after run › now" });
    await userEvent.click(after);
    (after as HTMLInputElement).setSelectionRange(0, 0);
    await userEvent.keyboard("{ArrowLeft}");
    const pill = screen.getByRole("button", { name: /^run › now, run\.now/ });
    expect(document.activeElement).toBe(pill);
    await userEvent.keyboard("{Backspace}");
    expect(f.config()).toEqual({ message: "AP  down" });
    await waitFor(() => expect((document.activeElement as HTMLInputElement).selectionStart).toBe(3));
  });

  it("types where the caret is after ← from a pill, as after → (the review of milestone 2)", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }) } });
    screen.getByRole("button", { name: /^run › now, run\.now/ }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    await userEvent.keyboard("abc");
    expect(f.config()).toEqual({ message: template({ text: "AP abc" }, { ref: "run.now" }) });
  });

  it("draws a pill whose value may be missing dashed, and says so in its name", async () => {
    showFields(NOTE, { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) } });
    const pill = await screen.findByRole("button", { name: /^get_site › timezone \?, steps\.get_site\.output\.timezone, may be missing, no default$/ });
    expect(pill.className).toContain("border-dashed");
  });

  it("opens a pill's details with Enter, and writes the default typed there into its part", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) } });
    const pill = await screen.findByRole("button", { name: /^get_site › timezone/ });
    pill.focus();
    await userEvent.keyboard("{Enter}");
    const details = await screen.findByRole("dialog", { name: "steps.get_site.output.timezone" });
    await userEvent.click(within(details).getByRole("button", { name: "Add a default…" }));
    await userEvent.type(within(details).getByLabelText("If it's missing or null"), "UTC");
    expect(f.config()).toEqual({ message: template({ ref: "steps.get_site.output.timezone", default: "UTC" }) });
  });

  it("gives focus back to the text when the tree ＋ Data opened closes, the text never focused before (the final review)", async () => {
    showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }, { text: " down" }) } });
    await userEvent.click(screen.getByRole("button", { name: "＋ Data" }));
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Message, text after run › now" })));
  });

  it("puts focus on the default once added, and on Add a default… once it's removed (the final review)", async () => {
    showFields(NOTE, { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) } });
    const pill = await screen.findByRole("button", { name: /^get_site › timezone \?/ });
    pill.focus();
    await userEvent.keyboard("{Enter}");
    const details = await screen.findByRole("dialog", { name: "steps.get_site.output.timezone" });
    await userEvent.click(within(details).getByRole("button", { name: "Add a default…" }));
    await waitFor(() => expect(document.activeElement).toBe(within(details).getByLabelText("If it's missing or null")));
    await userEvent.click(within(details).getByRole("button", { name: "Remove the default" }));
    await waitFor(() => expect(document.activeElement).toBe(within(details).getByRole("button", { name: "Add a default…" })));
  });

  it("keeps a pill dashed while the next saved revision's answer comes (the final review)", async () => {
    let revision = 1;
    let pending = false;
    let release = () => {};
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const answer = json({ draft_revision: revision, node: NODE_ID, field: q.get("field"), state: "ok", reason: null, entries: ENTRIES.filter((e) => e.path === q.get("at")), more: false, problem: null });
        if (revision === 1) return answer;
        pending = true;
        return new Promise<Response>((done) => (release = () => done(answer)));
      },
    });
    const options = { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) }, revision: 1 };
    const f = showFields(NOTE, options);
    const dashed = () => screen.getByRole("button", { name: /^get_site › timezone \?, steps\.get_site\.output\.timezone, may be missing/ });
    await waitFor(() => expect(dashed().className).toContain("border-dashed"));
    revision = 2;
    options.revision = 2; // saved again: the next revision asks again
    f.replace(options.config);
    await waitFor(() => expect(pending).toBe(true));
    expect(dashed().className).toContain("border-dashed"); // the previous answer stands in, never "always there"
    release();
    await waitFor(() => expect(dashed().className).toContain("border-dashed"));
  });

  it("holds text and pills a write refused, whole, said in braces, and shows them still", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }) } });
    f.refuse("Not written: the draft can't be changed now.");
    await userEvent.type(screen.getByRole("textbox", { name: "Message, text after run › now" }), "!");
    expect(f.held()).toMatchObject([{ kind: "template", text: "AP {run.now}!", why: "Not written: the draft can't be changed now." }]);
    act(() => f.remount());
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Message, text after run › now" }).value).toBe("!");
  });

  it("holds text where the field takes no fixed value as it would write it: a template (the review of revision 1)", async () => {
    const TEMPLATED = typeWith(
      { type: "object", properties: { message: { type: "string", title: "Message", "x-dewpoint-kinds": ["template", "cel"] } } },
      { ref: "acme.note@1", type: "acme.note", title: "Post a note" },
    );
    const f = showFields(TEMPLATED, { steps });
    await userEvent.click(screen.getByRole("button", { name: "Text" })); // it opens as a formula: it takes no fixed value
    f.refuse("Not written: the draft can't be changed now.");
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "hi");
    expect(f.held()).toMatchObject([{ kind: "template", text: "hi", literalOk: false }]);
  });

  it("shows pills in a version's view without asking for data, and offers no ＋ Data", () => {
    showFields(NOTE, { steps, revision: null, editable: false, config: { message: template({ ref: "run.now" }) } });
    expect(screen.getByRole("button", { name: /^run › now/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "＋ Data" })).toBeNull();
  });
});
