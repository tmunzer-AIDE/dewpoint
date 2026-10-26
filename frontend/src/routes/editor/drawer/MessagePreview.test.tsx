// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { messageStep } from "../../../test/nodeTypes";
import { fakeApi, json, showDrawer } from "./harness";

const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
const ref = (path: string) => ({ $value: { kind: "ref", path } });
const formula = (expr: string) => ({ $value: { kind: "cel", expr } });

const WHOLE = {
  title: template({ text: "AP offline at " }, { ref: "steps.check.output.site" }),
  text: template({ text: "Access point " }, { ref: "steps.check.output.name" }, { text: " stopped." }),
  fields: [{ label: "Site", value: ref("steps.check.output.site") }, { label: "Model", value: "AP45" }],
  links: [{ label: "Open in Mist", url: "https://manage.mist.test/admin" }],
  severity: "warning",
};

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
});
afterEach(() => vi.restoreAllMocks());

const preview = (name: string) => screen.getByRole("region", { name });

describe("a message's preview (4f-1, the message composer design §5.5)", () => {
  it("lays a Slack message out as Slack shows it, each value as where it comes from", () => {
    showDrawer(messageStep("slack.send_message"), { config: WHOLE });
    const region = preview("Preview in Slack");
    expect(region.getAttribute("aria-live")).toBeNull();
    expect(within(region).getByText("Laid out as Slack shows it. A value shows where it comes from until the step runs.")).toBeTruthy();
    const title = within(region).getByText("AP offline at", { exact: false });
    expect(title.className).toContain("font-semibold");
    const site = within(title).getByText("check.site");
    expect(site.className).toContain("font-mono");
    expect(site.className).toContain("decoration-dotted");
    expect(within(region).getByText("Site").tagName).toBe("DT");
    expect(within(region).getByText("AP45").tagName).toBe("DD");
    expect(within(region).getByText("Open in Mist")).toBeTruthy();
    expect(within(region).getByText("Severity: warning")).toBeTruthy();
    expect(within(region).queryByRole("link")).toBeNull(); // nothing in a preview goes anywhere
  });

  it("lays Teams' card out with each field as label: value", () => {
    showDrawer(messageStep("teams.send_message"), { config: WHOLE });
    const region = preview("Preview in Teams");
    expect(within(region).getByText("Laid out as a Teams card. A value shows where it comes from until the step runs.")).toBeTruthy();
    expect(within(region).getByText("Model").nextSibling!.textContent).toBe(": ");
    expect(within(region).getByText("Severity: warning")).toBeTruthy();
  });

  it("shows Google Chat's < and > as ＜ ＞, and links as linked words", () => {
    showDrawer(messageStep("google_chat.send_message"), { config: { ...WHOLE, text: "a <b> & c" } });
    const region = preview("Preview in Google Chat");
    expect(within(region).getByText("a ＜b＞ & c", { exact: false })).toBeTruthy();
    expect(within(region).getByText("Open in Mist").className).toContain("underline");
  });

  it("shows what the webhook posts as JSON, as written, a value in braces", () => {
    showDrawer(messageStep("webhook.send_message"), { config: { ...WHOLE, links: formula("steps.a.output.links") } });
    const region = preview("What it posts");
    expect(within(region).getByText("The message as JSON, as written: nothing is cut. A value shows where it comes from until the step runs.")).toBeTruthy();
    const posted = region.querySelector("pre")!.textContent;
    expect(posted).toContain('"title": "AP offline at {check.site}"');
    expect(posted).toContain('"links": Computed when the step runs');
    expect(posted).toContain('"severity": "warning"');
  });

  it("says how email and the others send it, with no preview", () => {
    showDrawer(messageStep("email.send_message"), { config: WHOLE });
    expect(screen.getByText("No preview: an email is plain text, its subject the title (or the text's first line), up to 200 characters.")).toBeTruthy();
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("says ServiceNow sends the message in its own form", () => {
    showDrawer(messageStep("servicenow.create_incident"), { config: WHOLE });
    expect(screen.getByText("No preview for ServiceNow: it sends the same message in its own form, and Simulate step says what it would cut.")).toBeTruthy();
  });

  it("gives a third party's message step the composer and no preview", () => {
    showDrawer(messageStep("acme.notify"), { config: WHOLE });
    expect(screen.getByRole("group", { name: "Message" })).toBeTruthy();
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByText(/^No preview/)).toBeNull();
  });

  it("shows a part a formula computes as computed when the step runs", () => {
    showDrawer(messageStep("slack.send_message"), { config: { ...WHOLE, fields: formula("steps.check.output.fields") } });
    expect(within(preview("Preview in Slack")).getByText("Computed when the step runs")).toBeTruthy();
  });

  it("has nothing to show without the text", () => {
    showDrawer(messageStep("slack.send_message"), { config: { title: "Hello" } });
    expect(within(preview("Preview in Slack")).getByText("Nothing to show yet: the message has no text.")).toBeTruthy();
  });

  it("counts Slack's text under it, and past Slack's limit warns there and under the preview", () => {
    const f = showDrawer(messageStep("slack.send_message"), { config: { text: template({ text: "Access point " }, { ref: "trigger.ap" }) } });
    const count = screen.getByText("13 characters, before its values. Slack shows up to 3,000.");
    // Every line of the text is described by it, the one after a value too (#136 item 2).
    const lines = [...document.querySelector('[data-pointer="/text"]')!.querySelectorAll("input")];
    expect(lines.length).toBeGreaterThan(1);
    for (const line of lines) expect(line.getAttribute("aria-describedby")?.split(" ")).toContain(count.id);
    f.replace({ text: template({ text: "x".repeat(3214) }, { ref: "trigger.org" }) });
    const warning = screen.getByText('3,214 characters. Slack shows the first 3,000 and ends them with "…".');
    expect(warning.className).toContain("text-warn-ink");
    expect(screen.getByLabelText("Text").getAttribute("aria-describedby")).toContain(warning.id);
    expect(within(preview("Preview in Slack")).getByText("Slack will cut the text at 3,000 characters.")).toBeTruthy();
  });

  it("warns of Teams' size under the text and the preview", () => {
    showDrawer(messageStep("teams.send_message"), { config: { text: "é".repeat(20_000) } });
    const words = "About 40,000 bytes before its values: Teams takes 24,000. The text would be shortened.";
    expect(screen.getAllByText(words)).toHaveLength(2);
  });
});
