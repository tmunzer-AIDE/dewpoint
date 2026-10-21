// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { COMPUTED, cutName, cutWords, draftOf, slackCount, sourceText } from "./composer";

const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
const ref = (path: string) => ({ $value: { kind: "ref", path } });
const formula = (expr: string) => ({ $value: { kind: "cel", expr } });
/** A draft's text with each placeholder written as {what it says}. */
const said = (text: string, says: string[]) => [...text].map((c) => (c.codePointAt(0)! >= 0xf0000 ? `{${says[c.codePointAt(0)! - 0xf0000]}}` : c)).join("");

describe("where a value comes from, as a preview says it", () => {
  it("names a step's output by the step, and any other root by itself", () => {
    expect(sourceText("steps.check.output.site")).toBe("check.site");
    expect(sourceText("trigger.events[0].ap_name")).toBe("trigger.events[0].ap_name");
    expect(sourceText("steps.check.output[0].name")).toBe("check[0].name");
    expect(sourceText("run.now")).toBe("run.now");
    expect(sourceText("vars")).toBe("vars");
  });
});

describe("the message as a preview draws it", () => {
  it("puts a placeholder for each value, and leaves the values out of what the cut maths count", () => {
    const draft = draftOf({
      title: template({ text: "AP offline at " }, { ref: "steps.check.output.site" }),
      text: template({ text: "Access point " }, { ref: "steps.check.output.name" }, { text: " stopped." }),
      fields: [{ label: "Site", value: ref("steps.check.output.site") }],
      links: [{ label: "Open", url: template({ text: "https://manage.mist.test/?id=" }, { ref: "steps.check.output.id" }) }],
      severity: "warning",
    });
    expect(said(draft.shown.title!, draft.says)).toBe("AP offline at {check.site}");
    expect(said(draft.shown.text, draft.says)).toBe("Access point {check.name} stopped.");
    expect(said(draft.shown.fields![0]!.value, draft.says)).toBe("{check.site}");
    expect(said(draft.shown.links![0]!.url, draft.says)).toBe("https://manage.mist.test/?id={check.id}");
    expect(draft.shown.severity).toBe("warning");
    expect(draft.bare).toEqual({
      title: "AP offline at ", text: "Access point  stopped.", fields: [{ label: "Site", value: "" }],
      links: [{ label: "Open", url: "https://manage.mist.test/?id=" }], severity: "warning",
    });  // prettier-ignore
  });

  it("shows a part a formula computes as computed when the step runs, and counts none of it", () => {
    const draft = draftOf({ text: formula("trigger.text"), fields: formula("steps.a.output.fields"), links: ref("steps.a.output.links"), severity: formula("'critical'") });
    expect(said(draft.shown.text, draft.says)).toBe(`{${COMPUTED}}`);
    expect(said(draft.shown.fields![0]!.label, draft.says)).toBe(`{${COMPUTED}}`);
    expect(said(draft.shown.links![0]!.label, draft.says)).toBe(`{${COMPUTED}}`);
    expect(said(draft.shown.severity!, draft.says)).toBe(`{${COMPUTED}}`);
    expect(draft.bare).toEqual({ title: null, text: "", fields: [], links: [], severity: "info" });
    expect(draft.computed).toEqual(["text", "fields", "links", "severity"]);
  });

  it("reads a literal's text and list as written, and an empty message as one with nothing to show", () => {
    const draft = draftOf({ text: { $value: { kind: "literal", value: "a {b}" } }, fields: { $value: { kind: "literal", value: [{ label: "x", value: "y" }] } } });
    expect(draft.shown.text).toBe("a {b}");
    expect(draft.shown.fields).toEqual([{ label: "x", value: "y" }]);
    expect(draftOf({}).shown.text).toBe("");
  });
});

describe("what a target would cut, its values left out", () => {
  it("names each value as the composer says it", () => {
    expect(["title", "text", "fields[2].label", "fields[2].value", "links[1].label", "links[1]", "description", "odd"].map(cutName)).toEqual([
      "the title", "the text", "field 3's label", "field 3's value", "link 2's label", "link 2 (left out)", "the description", "odd",
    ]);  // prettier-ignore
  });

  it("says Slack's cuts with its limits, a field's value within what its label leaves", () => {
    const draft = draftOf({
      text: template({ text: "x".repeat(3214) }, { ref: "trigger.org" }),
      fields: [{ label: "Note", value: "v".repeat(2500) }],
      links: [{ label: "b".repeat(100), url: "https://a.test" }],
    });
    expect(cutWords("slack", draft)).toEqual([
      "Slack will cut the text at 3,000 characters.",
      "Slack will cut field 1's value at 1,993 characters.",
      "Slack will cut link 1's label at 75 characters.",
    ]);
    expect(slackCount(draft)).toBe('3,214 characters. Slack shows the first 3,000 and ends them with "…".');
    expect(cutWords("slack", draftOf({ text: "AP down" }))).toEqual([]);
  });

  it("counts Slack's text as its renderer does, escapes included, before its values", () => {
    expect(slackCount(draftOf({ text: template({ text: "a & b " }, { ref: "trigger.x" }) }))).toBe("10 characters, before its values. Slack shows up to 3,000.");
    expect(slackCount(draftOf({ text: "AP down" }))).toBe("7 characters. Slack shows up to 3,000.");
  });

  it("says Teams' and Google Chat's size against their budget, and what would be shortened first", () => {
    // The plugins' renderers make the uncut bodies 49,199 and 45,371 bytes.
    const big = draftOf({
      text: "é".repeat(10_000),
      fields: Array.from({ length: 25 }, (_, i) => ({ label: `Field ${i}`, value: "v".repeat(1000) })),
    });
    expect(cutWords("teams", big)).toEqual([
      "About 49,000 bytes before its values: Teams takes 24,000. The text would be shortened first, then the fields' values.",
    ]);
    expect(cutWords("google_chat", big)).toEqual([
      "About 45,000 bytes before its values: Google Chat takes 30,000. The text would be shortened first, then the fields' values.",
    ]);
    expect(cutWords("teams", draftOf({ text: "AP down" }))).toEqual([]);
    expect(cutWords("webhook", big)).toEqual([]);
  });
});
