// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { SeedContract, SeedEntry } from "../../../lib/simulations";
import type { GraphDoc, NodeType } from "../../../lib/workflows";
import { choicesOf, collect, hintOf, initialOf, titleOf, typeWords } from "./seeds";

const entry = (pointer: string, over: Partial<SeedEntry> = {}): SeedEntry => ({
  pointer, types: ["string"], required: true, nullable: false, sensitive: false, prefill: { state: "typed", reason: "no_sample", value: null }, ...over,
});  // prettier-ignore
const contract = (...entries: SeedEntry[]): SeedContract => ({ draft_revision: 14, step_id: "id-notify", refused: null, entries });

describe("a step test's values (§7.6; the TestTab and TestOther boards)", () => {
  it("offers what the step's read allows: a value, null where it's nullable, absent where it's optional", () => {
    expect(choicesOf(entry("/a"))).toEqual(["value"]);
    expect(choicesOf(entry("/a", { nullable: true }))).toEqual(["value", "null"]);
    expect(choicesOf(entry("/a", { required: false }))).toEqual(["value", "absent"]);
    expect(choicesOf(entry("/a", { required: false, nullable: true }))).toEqual(["value", "null", "absent"]);
  });

  it("names a value's types in words", () => {
    expect(typeWords(["string"])).toBe("text");
    expect(typeWords(["array"])).toBe("list");
    expect(typeWords(["object", "null"])).toBe("object");
    expect(typeWords(["integer", "boolean"])).toBe("whole number or true or false");
    expect(typeWords([])).toBe("any value");
  });

  it("starts from a step's own sample where it fits, else from nothing, a single choice made", () => {
    const sampled = entry("/steps/get_site/output/name", { prefill: { state: "prefilled", reason: null, value: "HQ Paris" } });
    expect(initialOf(sampled)).toEqual({ choice: "value", text: "HQ Paris" });
    expect(initialOf(entry("/steps/list_aps/output/results", { types: ["array"], prefill: { state: "prefilled", reason: null, value: [{ mac: "5c" }] } }))).toEqual({ choice: "value", text: '[\n  {\n    "mac": "5c"\n  }\n]' });
    expect(initialOf(entry("/vars/channel", { required: false }))).toEqual({ choice: null, text: "" });
    expect(initialOf(entry("/vars/channel"))).toEqual({ choice: "value", text: "" });
  });

  it("says where a value comes from, or why it's typed", () => {
    const at = (over: Partial<SeedEntry>, pointer = "/steps/get_site/output/name") => hintOf(entry(pointer, over));
    expect(at({ prefill: { state: "prefilled", reason: null, value: "HQ" } })).toBe("From get_site's sample.");
    expect(at({ nullable: true, prefill: { state: "prefilled", reason: null, value: "UTC" } })).toBe("From get_site's sample. It can be null, but it can't be left out.");
    expect(at({ sensitive: true, prefill: { state: "typed", reason: "sensitive", value: null } })).toBe("Sensitive: typed, never prefilled. Kept as a protected value.");
    expect(at({ prefill: { state: "typed", reason: "no_sample", value: null } })).toBe("Typed: get_site has no sample yet.");
    expect(at({ prefill: { state: "typed", reason: "not_faithful", value: null } }, "/steps/list_aps/output/results")).toBe("Typed: list_aps's sample was cut or redacted, so it isn't used.");
    expect(at({ prefill: { state: "typed", reason: "not_in_sample", value: null } })).toBe("Typed: get_site's sample doesn't hold this value.");
    expect(at({ prefill: { state: "typed", reason: "doesnt_fit", value: null } })).toBe("Typed: get_site's sample doesn't fit what this step reads.");
    expect(at({ prefill: { state: "typed", reason: "not_step_output", value: null } }, "/item")).toBe("Typed: a loop's item has no sample.");
    expect(at({ required: false, nullable: true, prefill: { state: "typed", reason: "not_step_output", value: null } }, "/vars/channel")).toBe(
      "Typed: variables have no sample. Null and absent differ: a default replaces both, but has() is true for null.",
    );
    expect(at({ prefill: { state: "typed", reason: "not_step_output", value: null } }, "/trigger/site")).toBe("Typed: the workflow's input has no sample.");
  });

  it("sends each value as chosen: typed, null, or absent", () => {
    const c = contract(
      entry("/steps/get_site/output/name"),
      entry("/steps/list_aps/output/results", { types: ["array"] }),
      entry("/vars/channel", { required: false, nullable: true }),
      entry("/vars/region", { required: false }),
    );
    const sent = collect(c, {
      "/steps/get_site/output/name": { choice: "value", text: "HQ Paris" },
      "/steps/list_aps/output/results": { choice: "value", text: "[]" },
      "/vars/channel": { choice: "null", text: "" },
      "/vars/region": { choice: "absent", text: "" },
    }, "notify");  // prettier-ignore
    expect(sent).toEqual({ values: { "/steps/get_site/output/name": "HQ Paris", "/steps/list_aps/output/results": [], "/vars/channel": null }, absent: ["/vars/region"] });
  });

  it("says what's missing on each value, and what isn't JSON, sending nothing", () => {
    const c = contract(entry("/steps/get_site/output/name"), entry("/vars/channel", { required: false }), entry("/vars/tz", { nullable: true }), entry("/steps/list_aps/output/results", { types: ["array"] }));
    const out = collect(c, { "/steps/list_aps/output/results": { choice: "value", text: "[1," } }, "notify");
    expect(out).toEqual({
      missing: ["/steps/get_site/output/name", "/vars/channel", "/vars/tz"],
      problems: {
        "/steps/get_site/output/name": "Give a value: notify reads it without a default.",
        "/vars/channel": "Give a value, or choose Absent.",
        "/vars/tz": "Give a value, or choose Null.",
        "/steps/list_aps/output/results": "This isn't valid JSON, so it isn't sent.",
      },
    });
  });

  it("titles a value by its schema where it has one, else by its name", () => {
    const doc = {
      graph_format: 1,
      nodes: [{ id: "id-get_site", key: "get_site", type: "mist.sites.get@1" }, { id: "id-each_ap", key: "each_ap", type: "flow.loop@1" }, { id: "id-notify", key: "notify", type: "slack.post@1" }],
      edges: [{ from: { node: "id-each_ap", port: "body" }, to: { node: "id-notify" } }],
      settings: { input_schema: { type: "object", properties: { api_token: { type: "string", title: "API token" } } } },
    } as unknown as GraphDoc;  // prettier-ignore
    const types = new Map([["mist.sites.get@1", { output_schema: { type: "object", properties: { name: { type: "string", title: "The site's name" } } } } as unknown as NodeType]]);
    const title = (p: string) => titleOf(p, doc, types, "id-notify");
    expect(title("/steps/get_site/output/name")).toBe("The site's name");
    expect(title("/steps/get_site/output/timezone")).toBe("timezone");
    expect(title("/trigger/api_token")).toBe("API token");
    expect(title("/vars/channel")).toBe("channel");
    expect(title("/item")).toBe("each_ap's item");
    expect(title("/item/mac")).toBe("mac");
  });
});
