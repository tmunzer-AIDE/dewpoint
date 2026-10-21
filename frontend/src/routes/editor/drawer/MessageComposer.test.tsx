// SPDX-License-Identifier: Apache-2.0
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { messageStep, typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, showDrawer } from "./harness";

const SLACK = messageStep("slack.send_message");
const SERVICENOW = messageStep("servicenow.create_incident", { urgency: { type: "integer", title: "Urgency", enum: [1, 2, 3] } });
const EMAIL = messageStep("email.send_message", { to: { type: "array", title: "To", items: { type: "string" }, minItems: 1 } }, ["to"]);
const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
const formula = (expr: string) => ({ $value: { kind: "cel", expr } });
const fields = (n: number) => Array.from({ length: n }, (_, i) => ({ label: `Field ${i}`, value: `value ${i}` }));

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
});
afterEach(() => vi.restoreAllMocks());

const message = () => screen.getByRole("group", { name: "Message" });

describe("the message composer (4f-1, the message composer design §5)", () => {
  it("shows the message on Setup after the step's required fields: severity, title, text, fields, links", () => {
    showDrawer(EMAIL);
    expect(screen.getByRole("tab", { name: "Setup" }).getAttribute("aria-selected")).toBe("true");
    const panel = screen.getByRole("tabpanel");
    const labels = [...panel.querySelectorAll("label, legend")].map((l) => l.textContent);
    expect(labels.slice(0, 2)).toEqual(["Connection", "To"]);
    expect(labels.indexOf("Message")).toBe(2);
    const parts = [...message().querySelectorAll<HTMLElement>(":scope > [data-pointer]")].map((part) => part.dataset.pointer);
    expect(parts).toEqual(["/severity", "/title", "/text", "/fields", "/links"]);
    expect(within(panel).getAllByText("(required)")).toHaveLength(3); // Connection, To and the text say it themselves
    expect(within(message()).getByText("optional · the email's subject")).toBeTruthy();
  });

  it("keeps on Options what only the target takes, with a line saying where the message is", async () => {
    showDrawer(SERVICENOW);
    await userEvent.click(screen.getByRole("tab", { name: "Options" }));
    expect(screen.getByText("The message is on Setup; what only ServiceNow takes stays here.")).toBeTruthy();
    expect(screen.getByLabelText("Urgency")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Message" })).toBeNull();
  });

  it("says so on Options when nothing else is there", async () => {
    showDrawer(SLACK);
    await userEvent.click(screen.getByRole("tab", { name: "Options" }));
    expect(screen.getByText("The message is on Setup; what only Slack takes stays here.")).toBeTruthy();
    expect(screen.getByText("Nothing else to set.")).toBeTruthy();
  });

  it("leaves a config with the hint but no text to the generic form (ruling 100)", () => {
    showDrawer(typeWith({ type: "object", "x-widget": "message", properties: { title: { type: "string", title: "Title" } } }));
    expect(screen.queryByRole("group", { name: "Message" })).toBeNull();
  });

  it("sets the severity with four choices, Info by default, and keeps its Fixed and Formula switch", async () => {
    const f = showDrawer(SLACK);
    const severity = within(message()).getByRole("radiogroup", { name: "Severity" });
    expect(within(severity).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["Info", "Success", "Warning", "Critical"]);
    expect(within(severity).getByRole<HTMLInputElement>("radio", { name: "Info" }).checked).toBe(true);
    expect(f.config()).toEqual({}); // the default shown, nothing written
    await userEvent.click(within(severity).getByRole("radio", { name: "Warning" }));
    expect(f.config()).toEqual({ severity: "warning" });
    expect(within(within(message()).getByRole("group", { name: "How Severity is set" })).getByRole("button", { name: "Formula" })).toBeTruthy();
  });

  it("writes the text on several lines", async () => {
    const f = showDrawer(SLACK, { config: { text: "AP down" } });
    await userEvent.type(within(message()).getByLabelText("Text"), "{Enter}at HQ");
    expect(f.config()).toEqual({ text: "AP down\nat HQ" });
  });

  it("adds fields up to 25, each row named by its number, and says why another can't be added", async () => {
    // 25 rows are many: found by text and attributes, as role queries over them take seconds in jsdom.
    const f = showDrawer(SLACK, { config: { text: "x", fields: fields(24) } });
    const addButton = () => within(message()).getByText("＋ Add a field").closest("button")!;
    expect(within(message()).getByText("24 of 25")).toBeTruthy();
    expect(message().querySelector('[role="group"][aria-label="Field 24"]')).not.toBeNull();
    await userEvent.click(addButton());
    expect((f.config().fields as unknown[]).length).toBe(25);
    expect(within(message()).getByText("25 of 25")).toBeTruthy();
    expect(addButton().disabled).toBe(true);
    const cap = within(message()).getByText("A message takes up to 25 fields: remove one to add another.");
    expect(addButton().getAttribute("aria-describedby")).toBe(cap.id);
    expect(within(message()).getByLabelText("Field 25 label")).toBeTruthy();
    expect(within(message()).queryByText("Edit as JSON")).toBeNull();
  }, 15_000); // 1.1 s alone; 25 adds over a growing list took 5–7 s under the whole suite's parallel load (4f-2b, M114)

  it("moves a link's row and removes one, each control named by its row", async () => {
    const links = [{ label: "One", url: "https://a.test" }, { label: "Two", url: "https://b.test" }];
    const f = showDrawer(SLACK, { config: { text: "x", links } });
    expect(within(message()).getByText("2 of 10")).toBeTruthy();
    await userEvent.click(within(message()).getByRole("button", { name: "Move down: link 1" }));
    expect(f.config().links).toEqual([links[1], links[0]]);
    await userEvent.click(within(message()).getByRole("button", { name: "Remove link 2" }));
    expect(f.config().links).toEqual([links[1]]);
    await waitFor(() => expect(document.activeElement).toBe(within(message()).getByRole("button", { name: "＋ Add a link" })));
  });

  it("checks a link's address as it's typed, when it starts with written text", async () => {
    const f = showDrawer(SLACK, { config: { text: "x", links: [{ label: "Runbook", url: "" }] } });
    const address = within(message()).getByLabelText("Link 1 address");
    await userEvent.type(address, "ftp://x");
    const said = within(message()).getByText("A link's address starts with http:// or https://.");
    expect(address.getAttribute("aria-describedby")).toContain(said.id);
    expect(address.getAttribute("aria-invalid")).toBe("true");
    f.replace({ text: "x", links: [{ label: "Runbook", url: template({ ref: "steps.check.output.url" }, { text: "/runbook" }) }] });
    expect(within(message()).queryByText("A link's address starts with http:// or https://.")).toBeNull();
    f.replace({ text: "x", links: [{ label: "Runbook", url: "https://a.test" }] });
    expect(within(message()).queryByText("A link's address starts with http:// or https://.")).toBeNull();
  });

  it("asks for the text in the composer's words once it's left empty", async () => {
    showDrawer(SLACK, { config: { text: "x" } });
    await userEvent.clear(within(message()).getByLabelText("Text"));
    const said = within(message()).getByText("Give the text: a message needs it.");
    expect(within(message()).getByLabelText("Text").getAttribute("aria-describedby")).toContain(said.id);
  });

  it("shows a version or a viewer the message as written, the rest summed up, and its preview", () => {
    const config = {
      text: template({ text: "Access point " }, { ref: "steps.check.output.name" }),
      fields: [{ label: "Site", value: "HQ" }, { label: "Model", value: "AP45" }], links: [{ label: "Open", url: "https://a.test" }],
      severity: "warning",
    };  // prettier-ignore
    showDrawer(SLACK, { editable: false, config });
    expect(within(message()).getByText("Severity: warning · 2 fields · 1 link")).toBeTruthy();
    expect(within(message()).getByRole("button", { name: /^check › name/ })).toBeTruthy();
    expect(within(message()).queryByRole("radiogroup")).toBeNull();
    expect(within(message()).queryByText("2 of 25")).toBeNull();
    expect(screen.getByRole("region", { name: "Preview in Slack" })).toBeTruthy();
  });

  it("sums up a part a formula computes, and no fields or links", () => {
    showDrawer(SLACK, { editable: false, config: { text: "x", severity: formula("'critical'") } });
    expect(within(message()).getByText("Severity: computed when the step runs · no fields · no links")).toBeTruthy();
  });

  it("keeps a list a formula computes as a formula, and one it can't draw as today's control", () => {
    showDrawer(SLACK, { config: { text: "x", fields: formula("steps.check.output.fields"), links: { $value: { kind: "literal", value: [] } } } });
    expect(within(message()).getByRole("textbox", { name: "Fields" })).toBeTruthy();
    expect(within(message()).queryByRole("button", { name: "＋ Add a field" })).toBeNull();
    expect(within(message()).queryByRole("button", { name: "＋ Add a link" })).toBeNull();
  });
});
