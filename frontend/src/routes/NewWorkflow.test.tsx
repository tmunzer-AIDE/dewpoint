// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { onAnnounce } from "../lib/announce";
import { NewWorkflow, parseDocument } from "./NewWorkflow";

const DOC = {
  format: "dewpoint.workflow", format_version: 1, name: "Nightly report", graph: { graph_format: 1, nodes: [], edges: [] },
  bindings: [{ id: "b1", kind: "connection", type: "mist", label: "Acme Prod", sites: [{ node: "n1", field: "/connection" }] }],
};  // prettier-ignore
const CONNECTIONS = [
  { id: "c1", type: "mist", name: "Lab Mist", revision: 1, config: {}, secret_set: true, status: "ok", status_detail: "", privilege: null, last_verified_at: null },
  { id: "c2", type: "slack", name: "NOC Slack", revision: 1, config: {}, secret_set: true, status: "ok", status_detail: "", privilege: null, last_verified_at: null },
];  // prettier-ignore

let sent: { method: string; path: string; body: unknown }[];
let answer: { status: number; body: unknown };
let connectionsAnswer: () => Response;
let client: QueryClient;

beforeEach(() => {
  sent = [];
  answer = { status: 201, body: { id: "w9", name: "Nightly report" } };
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "POST") return new Response(JSON.stringify(answer.body), { status: answer.status });
    if (path.endsWith("/connections")) return connectionsAnswer();
    return new Response("[]");
  });
});

async function show(onClose = vi.fn()) {
  const root = createRootRoute({ component: () => <NewWorkflow tenantId="t1" onClose={onClose} /> });
  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: () => <p>editor</p> });
  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("dialog", { name: "New workflow" });
  return router;
}

it("starts blank from a name, and opens the editor", async () => {
  const router = await show();
  expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
  expect(sent.find((r) => r.method === "POST")).toEqual({ method: "POST", path: "/api/v1/t/t1/workflows", body: { name: "Nightly report" } });
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
});

it("says plainly when the name is taken", async () => {
  answer = { status: 409, body: { error: "name_taken" } };
  await show();
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
  expect((await screen.findByRole("alert")).textContent).toContain("A workflow with this name exists");
});

it("imports a file, binding each placeholder to one of this tenant's of its type", async () => {
  const router = await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const file = new File([JSON.stringify(DOC)], "nightly.dewpoint.json", { type: "application/json" });
  await userEvent.upload(screen.getByLabelText("Workflow file"), file);
  expect(await screen.findByDisplayValue("Nightly report")).toBeTruthy(); // the file's name, editable
  const binding = await screen.findByLabelText("Acme Prod (mist connection)");
  expect([...(binding as HTMLSelectElement).options].map((o) => o.text)).toEqual(["Choose…", "Leave unbound", "Lab Mist"]);
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true); // nothing chosen
  await userEvent.selectOptions(binding, "c1");
  await userEvent.click(screen.getByRole("button", { name: "Import and open" }));
  expect(sent.find((r) => r.method === "POST")).toEqual({
    method: "POST", path: "/api/v1/t/t1/workflows/import",
    body: { name: "Nightly report", document: DOC, bind: { b1: "c1" } },
  });  // prettier-ignore
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
});

it("refuses a file that isn't a workflow, and names a refused binding", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File(["{}"], "x.json", { type: "application/json" }));
  expect((await screen.findByText(/isn't a Dewpoint workflow/)).textContent).toBeTruthy();
  answer = { status: 422, body: { error: "bad_binding", binding: "b1", reason: "wrong_type" } };
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  await userEvent.selectOptions(await screen.findByLabelText("Acme Prod (mist connection)"), "c1");
  await userEvent.click(screen.getByRole("button", { name: "Import and open" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Acme Prod is of another type");
});

it("imports a binding left unbound only when the person chooses so", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  const binding = await screen.findByLabelText("Acme Prod (mist connection)");
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
  await userEvent.selectOptions(binding, "Leave unbound");
  await userEvent.click(screen.getByRole("button", { name: "Import and open" }));
  expect((sent.find((r) => r.method === "POST")!.body as { bind: object }).bind).toEqual({});
});

it("closes on Cancel", async () => {
  const onClose = vi.fn();
  await show(onClose);
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalled();
});

it("reads only a Dewpoint workflow file", () => {
  expect(parseDocument(JSON.stringify(DOC))?.name).toBe("Nightly report");
  expect(parseDocument("not json")).toBeNull();
  expect(parseDocument(JSON.stringify({ ...DOC, format_version: 2 }))).toBeNull();
});

const B = DOC.bindings[0]!;
it.each([
  ["a null graph", { ...DOC, graph: null }],
  ["a graph that's a list", { ...DOC, graph: [] }],
  ["a null binding", { ...DOC, bindings: [null] }],
  ["a binding without a site", { ...DOC, bindings: [{ ...B, sites: [] }] }],
  ["a binding id used twice", { ...DOC, bindings: [B, B] }],
  ["a binding id the API refuses", { ...DOC, bindings: [{ ...B, id: "B 1" }] }],
  ["a connection binding without a type", { ...DOC, bindings: [{ ...B, type: null }] }],
  ["a workflow binding with a type", { ...DOC, bindings: [{ ...B, kind: "workflow" }] }],
  ["a kind that isn't one", { ...DOC, bindings: [{ ...B, kind: "secret" }] }],
  ["a site without a field", { ...DOC, bindings: [{ ...B, sites: [{ node: "n1" }] }] }],
  ["a site's node that's a number", { ...DOC, bindings: [{ ...B, sites: [{ node: 7, field: "/connection" }] }] }],
  ["an extra key", { ...DOC, extra: 1 }],
  ["an extra key in a binding", { ...DOC, bindings: [{ ...B, secret: "x" }] }],
  ["a name longer than the API takes", { ...DOC, name: "n".repeat(101) }],
  ["a label longer than the API takes", { ...DOC, bindings: [{ ...B, label: "l".repeat(201) }] }],
  ["a field shorter than a pointer", { ...DOC, bindings: [{ ...B, sites: [{ node: "n1", field: "/" }] }] }],
])("refuses %s", (_, doc) => {
  expect(parseDocument(JSON.stringify(doc))).toBeNull();
});

async function importDoc(doc: object = DOC) {
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(doc)], "n.json", { type: "application/json" }));
}

it("offers no choice until this tenant's connections are read, and says when they can't be", async () => {
  connectionsAnswer = () => new Response(JSON.stringify({ error: "http_error" }), { status: 500 });
  await show();
  await importDoc();
  expect((await screen.findByRole("alert")).textContent).toContain("couldn't be read, so nothing can be bound yet");
  expect(screen.queryByLabelText("Acme Prod (mist connection)")).toBeNull(); // never "Leave unbound" by default
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS));
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await userEvent.selectOptions(await screen.findByLabelText("Acme Prod (mist connection)"), "c1");
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(false);
});

it("says when this tenant has no connection of a binding's type", async () => {
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS.filter((c) => c.type !== "mist")));
  await show();
  await importDoc();
  const binding = await screen.findByLabelText("Acme Prod (mist connection)");
  expect([...(binding as HTMLSelectElement).options].map((o) => o.text)).toEqual(["Choose…", "Leave unbound"]);
  expect(screen.getByText("No mist connection in this tenant: choose Leave unbound.")).toBeTruthy();
});

it("refuses a file with a null binding without breaking the dialog", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const bad = new File([JSON.stringify({ ...DOC, bindings: [null] })], "x.json", { type: "application/json" });
  await userEvent.upload(screen.getByLabelText("Workflow file"), bad);
  expect((await screen.findByRole("alert")).textContent).toContain("isn't a Dewpoint workflow"); // said, not only shown
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
});

it("says why the server refused the file", async () => {
  answer = { status: 422, body: { error: "bad_document", problems: [{ reason: "embedded_value", binding: null, node: "n1", field: "/connection" }] } };
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  await userEvent.selectOptions(await screen.findByLabelText("Acme Prod (mist connection)"), "Leave unbound");
  await userEvent.click(screen.getByRole("button", { name: "Import and open" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The file can't be imported: it holds a connection or workflow id where a binding goes. Export it again from Dewpoint.",
  );
});

it("never opens nor announces a workflow created after its dialog was dismissed; its tenant's list still learns of it", async () => {
  let release!: (r: Response) => void;
  const base = vi.mocked(globalThis.fetch).getMockImplementation()!;
  vi.mocked(globalThis.fetch).mockImplementation((input) =>
    (input as Request).method === "POST" ? new Promise<Response>((r) => (release = r)) : base(input));
  const heard: string[] = [];
  const stop = onAnnounce((m) => heard.push(m));
  const onClose = vi.fn();
  const router = await show(onClose);
  client.setQueryData(["workflows", "t1"], []);
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" })); // while the creation is on its way
  expect(onClose).toHaveBeenCalled();
  release(new Response(JSON.stringify({ id: "w9", name: "Nightly report" }), { status: 201 }));
  await vi.waitFor(() => expect(client.getQueryState(["workflows", "t1"])?.isInvalidated).toBe(true));
  expect(router.state.location.pathname).toBe("/");
  expect(heard).toEqual([]);
  stop();
});

/** A file whose read answers when the test says: with `content`, or failing when it's null. `settle` answers it,
 * then waits until the read has been heard. */
function slowFile(name: string, content: object | null) {
  let answer!: () => void;
  const read = new Promise<string>((resolve, reject) => {
    answer = () => (content === null ? reject(new Error("unreadable")) : resolve(JSON.stringify(content)));
  });
  const file = new File(["{}"], name, { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => read });
  const settle = () => {
    answer();
    return read.then(() => undefined, () => undefined);
  };
  return { file, settle };
}

it("keeps the latest file chosen when an earlier one finishes reading after it", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const a = slowFile("a.json", { ...DOC, name: "From A" });
  const b = slowFile("b.json", { ...DOC, name: "From B", bindings: [] });
  await userEvent.upload(screen.getByLabelText("Workflow file"), a.file);
  expect(screen.getByText("Reading the file…")).toBeTruthy();
  await userEvent.upload(screen.getByLabelText("Workflow file"), b.file);
  await act(() => b.settle());
  expect(await screen.findByDisplayValue("From B")).toBeTruthy();
  await act(() => a.settle()); // A answers last: it changes nothing
  expect(screen.getByDisplayValue("From B")).toBeTruthy();
  expect(screen.getByText("The file names no connection or workflow.")).toBeTruthy(); // B's bindings, not A's
  expect(screen.queryByText("Reading the file…")).toBeNull();
});

it("says when a file can't be read, and takes another", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const bad = slowFile("bad.json", null);
  await userEvent.upload(screen.getByLabelText("Workflow file"), bad.file);
  await act(() => bad.settle());
  expect((await screen.findByRole("alert")).textContent).toBe("That file couldn't be read. Choose it again, or another.");
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  expect(await screen.findByLabelText("Acme Prod (mist connection)")).toBeTruthy();
  expect(screen.queryByText(/couldn't be read/)).toBeNull();
});

it("never overwrites a name typed while the file was read", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const a = slowFile("a.json", DOC);
  await userEvent.upload(screen.getByLabelText("Workflow file"), a.file);
  await userEvent.type(screen.getByLabelText("Name"), "My own name");
  await act(() => a.settle());
  expect(await screen.findByLabelText("Acme Prod (mist connection)")).toBeTruthy();
  expect(screen.getByDisplayValue("My own name")).toBeTruthy();
});
