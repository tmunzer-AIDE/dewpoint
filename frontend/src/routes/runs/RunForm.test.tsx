// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StartForm } from "../../lib/runForm";
import { local } from "../../test/runs";
import { RunForm } from "./RunForm";

const FORM: StartForm = {
  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 12, 0), published_by: "nadia@corp.test", csv: null,
  fields: [
    { name: "site", title: "Site", type: "string", required: true, sensitive: false },
    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
  ],
};  // prettier-ignore
const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8, published_by: null, fields: [FORM.fields[0]!, { ...FORM.fields[1]!, type: "string" }] };

let forms: StartForm[];
let answers: (() => Promise<Response>)[];
let posts: { key: string | null; body: unknown }[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  forms = [FORM];
  answers = [];
  posts = [];
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (url.pathname === "/api/v1/t/t1/workflows/w1/start-form") return json(forms.length > 1 ? forms.shift() : forms[0]);
    if (request.method === "POST" && url.pathname === "/api/v1/t/t1/workflows/w1/runs") {
      posts.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
      return (answers.shift() ?? (() => Promise.resolve(json({ id: "r1" }, 202))))();
    }
    return json({ error: "not_found" }, 404);
  });
});
afterEach(() => vi.restoreAllMocks());

function show(over: { draftDiffers?: boolean; cached?: StartForm } = {}) {
  const onStarted = vi.fn();
  const onClose = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (over.cached) qc.setQueryData(["start-form", "t1", "w1"], over.cached); // read when the form was open before
  render(
    <QueryClientProvider client={qc}>
      <RunForm tenantId="t1" workflow={{ id: "w1", name: "Site onboarding" }} draftDiffers={over.draftDiffers} onStarted={onStarted} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onStarted, onClose };
}
const dialog = () => screen.getByRole("dialog", { name: "Start a run" });
/** The version line, its time a <time> inside it. */
const versionLine = (text: string) => screen.findByText((_, el) => el?.tagName === "P" && el.textContent === text);

describe("the run form (the run form design §5.2; the Main board)", () => {
  it("names the workflow, the version that will run and who published it", async () => {
    show();
    expect(await versionLine("Version 7 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
    expect(within(dialog()).getByText("Site onboarding")).toBeTruthy();
    expect(screen.queryByText(/The draft has changes/)).toBeNull();
  });

  it("shows the version published since the form was last read, never the one it read then (the final review)", async () => {
    forms = [NEWER];
    show({ cached: FORM });
    expect(await versionLine("Version 8 · published today 09:12:00")).toBeTruthy();
    expect(screen.queryByText(/^Version 7/)).toBeNull();
  });

  it("says when the draft differs from the published version, opened from the editor", async () => {
    show({ draftDiffers: true });
    expect(await screen.findByText("The draft has changes that aren't published. This run uses version 7, not the draft.")).toBeTruthy();
  });

  it("starts live by default, saying so; simulated says nothing is sent, and its button says so", async () => {
    show();
    const user = userEvent.setup();
    await screen.findByLabelText(/Site/);
    expect(screen.getByRole("radio", { name: "Live" })).toHaveProperty("checked", true);
    expect(screen.getByText(/It acts for real: its steps call their connections/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start the live run" })).toBeTruthy();
    await user.click(screen.getByRole("radio", { name: "Simulated" }));
    expect(screen.getByText(/Nothing is sent: actions return fixtures instead of calling out/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "◌ Start the simulation" })).toBeTruthy();
  });

  it("starts the version it names under one key, and hands over the new run", async () => {
    const { onStarted } = show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.type(screen.getByLabelText(/Floor/), "2");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(posts).toEqual([{ key: expect.any(String) as string, body: { input: { site: "HQ", floor: 2 }, mode: "live", expected_version_id: "v7" } }]);
    expect(onStarted).toHaveBeenCalledWith("r1");
  });

  it("says beside a required field left empty that it's required, and sends nothing", async () => {
    show();
    const user = userEvent.setup();
    await screen.findByLabelText(/Site/);
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(screen.getByText("Give a value: the input requires it.")).toBeTruthy();
    expect(posts).toEqual([]);
  });

  it("shows a version published meanwhile, keeping the values that still fit, and starts it once asked again", async () => {
    forms = [FORM, NEWER];
    answers = [() => Promise.resolve(json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409))];
    const { onStarted } = show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.type(screen.getByLabelText(/Floor/), "2");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringMatching(/^Version 8 was published while this was open\. Nothing started\./));
    expect(await versionLine("Version 8 · published today 09:12:00")).toBeTruthy(); // its publisher gone
    expect(screen.getByLabelText(/Site/)).toHaveProperty("value", "HQ");
    expect(screen.getByLabelText(/Floor/)).toHaveProperty("value", ""); // now text: not kept
    expect(onStarted).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(posts.map((p) => (p.body as { expected_version_id: string }).expected_version_id)).toEqual(["v7", "v8"]);
    expect(posts[1]!.key).not.toBe(posts[0]!.key);
    expect(onStarted).toHaveBeenCalledWith("r1");
  });

  it("sends the same form again under the same key after its answer was lost", async () => {
    answers = [() => Promise.reject(new TypeError("Failed to fetch"))];
    const { onStarted } = show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "The server didn't answer. Start again: the same form is never started twice.");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(posts).toHaveLength(2);
    expect(posts[1]!.key).toBe(posts[0]!.key);
    expect(onStarted).toHaveBeenCalledWith("r1");
  });

  it("says an input's refusal beside the field it names, and the rest above the buttons", async () => {
    answers = [() => Promise.resolve(json({ error: "input_invalid", messages: ["The run's input doesn't match the workflow's input schema at floor: it breaks `maximum`."] }, 422))];
    show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.type(screen.getByLabelText(/Floor/), "200");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(await screen.findByText("Doesn't fit the input: it breaks `maximum`.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("The input doesn't fit the workflow's input. Nothing started. input_invalid");
  });

  it("says a refusal's code beside its words", async () => {
    answers = [() => Promise.resolve(json({ error: "workflow_disabled", messages: ["The workflow is disabled."] }, 409))];
    show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The workflow is disabled. Nothing started. workflow_disabled");
  });

  it("starts once however often Start is pressed while the start is sent", async () => {
    let answer!: (r: Response) => void;
    answers = [() => new Promise((r) => (answer = r))];
    const { onStarted } = show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    answer(json({ id: "r1" }, 202));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("r1"));
    expect(posts).toHaveLength(1);
  });

  it("keeps the form when the version published meanwhile can't be read, saying why", async () => {
    answers = [() => Promise.resolve(json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409))];
    show();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Site/), "HQ");
    const served = vi.mocked(globalThis.fetch).getMockImplementation()!;
    vi.mocked(globalThis.fetch).mockImplementation(async (input) =>
      new URL((input as Request).url).pathname.endsWith("/start-form") ? json({ error: "internal_error", messages: ["The server failed."] }, 500) : served(input),
    );  // prettier-ignore
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The server failed. Nothing started. internal_error");
    expect(await versionLine("Version 7 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
    expect(screen.getByLabelText(/Site/)).toHaveProperty("value", "HQ");
  });

  it("takes the input as JSON too", async () => {
    show();
    const user = userEvent.setup();
    await screen.findByLabelText(/Site/);
    await user.click(screen.getByRole("button", { name: "Edit as JSON" }));
    const text = screen.getByLabelText("The input, as JSON");
    await user.clear(text);
    await user.type(text, '{{"site": "Lyon"}');
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    expect(posts[0]!.body).toEqual({ input: { site: "Lyon" }, mode: "live", expected_version_id: "v7" });
  });

  it("focuses its first field once the form is read", async () => {
    show();
    const site = await screen.findByLabelText(/Site/);
    await waitFor(() => expect(document.activeElement).toBe(site));
  });

  it("closes on Cancel, starting nothing", async () => {
    const { onClose } = show();
    const user = userEvent.setup();
    await screen.findByLabelText(/Site/);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(posts).toEqual([]);
  });
});

describe("below 640 px (the run form design §5.6; the Narrow320 boards)", () => {
  beforeEach(() => {
    const wide = window.matchMedia.bind(window);
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
  });

  it("fills the screen, with a Close button, its buttons stacked, Start first", async () => {
    const { onClose } = show();
    await screen.findByLabelText(/Site/);
    expect(dialog().className).toContain("h-dvh");
    const buttons = within(dialog()).getAllByRole("button").map((b) => b.textContent);
    expect(buttons.slice(-2)).toEqual(["Start the live run", "Cancel"]);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("makes every target 44 px: each kind of field, the mode's choices, Edit as JSON, Close, Start and Cancel (the 4f-3 design §5.6)", async () => {
    const more = [
      { name: "kind", title: "Kind", type: "string", enum: ["a", "b"], required: false, sensitive: false },
      { name: "on", title: "On", type: "boolean", required: false, sensitive: false },
      { name: "tags", title: "Tags", type: "array", required: false, sensitive: false },
    ];  // prettier-ignore
    forms = [{ ...FORM, fields: [...FORM.fields, ...more] }];
    show();
    await screen.findByLabelText(/^Site/);
    const tall = (el: Element) => expect(el.className).toContain("max-sm:min-h-[44px]");
    for (const label of [/^Site/, /^Floor/, /^Kind/, /^On/, /^Tags/]) tall(screen.getByLabelText(label));
    for (const name of ["Live", "Simulated"]) tall(screen.getByRole("radio", { name }).closest("label")!);
    for (const name of ["Edit as JSON", "Start the live run", "Cancel"]) tall(screen.getByRole("button", { name }));
    expect(screen.getByRole("button", { name: "Close" }).className).toContain("size-[44px]");
    await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
    tall(screen.getByLabelText("The input, as JSON"));
  });
});
