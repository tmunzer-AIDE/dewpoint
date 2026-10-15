// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { skeletonOf } from "./skeleton";

describe("a skeleton of an input (§7.1; the InputJson board)", () => {
  it("fills every field the input declares with an empty value of its type, optional ones too", () => {
    expect(
      skeletonOf({
        type: "object",
        properties: { topic: { type: "string" }, n: { type: "integer" }, x: { type: "number" }, on: { type: "boolean" }, gone: { type: "null" } },
        required: ["topic"],
      }),
    ).toEqual({ topic: "", n: 0, x: 0, on: false, gone: null });
  });

  it("gives a list one item, so its shape shows, and follows references", () => {
    const schema = {
      type: "object",
      properties: { events: { type: "array", items: { $ref: "#/$defs/event" } } },
      $defs: { event: { type: "object", properties: { mac: { type: "string" }, timestamp: { type: "integer" } } } },
    };
    expect(skeletonOf(schema)).toEqual({ events: [{ mac: "", timestamp: 0 }] });
  });

  it("takes a choice's first branch, a nullable type's other type, and an enum's first value", () => {
    expect(skeletonOf({ anyOf: [{ type: "string" }, { type: "integer" }] })).toBe("");
    expect(skeletonOf({ type: ["null", "integer"] })).toBe(0);
    expect(skeletonOf({ type: "string", enum: ["up", "down"] })).toBe("up");
  });

  it("stops where it would go on forever: a schema that refers to itself", () => {
    const schema = { $defs: { node: { type: "object", properties: { next: { $ref: "#/$defs/node" } } } }, $ref: "#/$defs/node" };
    expect(JSON.stringify(skeletonOf(schema)).length).toBeLessThan(400);
  });

  it("leaves what it can't tell as null", () => {
    expect(skeletonOf({})).toBeNull();
    expect(skeletonOf({ $ref: "#/$defs/missing" })).toBeNull();
  });
});
