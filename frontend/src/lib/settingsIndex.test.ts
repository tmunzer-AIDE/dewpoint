// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { UPDATE } from "../test/nodeTypes";
import { fieldsOf } from "./schemaForm";
import { findSettings, findWords, settingsOf, type Setting } from "./settingsIndex";

const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
const all = settingsOf(body);
const raws = (list: Setting[]) => list.map((s) => s.raw);

describe("settingsOf", () => {
  it("lists every setting a body offers, through its objects, a map's entries and a list's items", () => {
    const listed = raws(all);
    expect(listed).toEqual(expect.arrayContaining(["name", "rogue", "rogue.min_rogue_rssi", "auto_upgrade.custom.ap41", "port_usages.*.mode", "networks[].name", "radius.secret"]));
    expect(listed).not.toContain("id"); // Mist sets it
    expect(all.find((s) => s.raw === "port_usages.*.mode")!.titles).toEqual(["Port usages", "an entry", "Mode"]);
    expect(all.find((s) => s.raw === "networks[].name")!.titles).toEqual(["Networks", "an item", "Name"]);
  });
  it("is built once per body", () => {
    expect(settingsOf(body)).toBe(all);
  });
});

describe("findSettings", () => {
  it("finds by every word typed, a title or name before a description, top-level first", () => {
    expect(raws(findSettings(all, "rogue").shown)).toEqual(["rogue", "rogue.enabled", "rogue.min_rogue_rssi", "rogue.whitelisted_ssids"]);
    expect(raws(findSettings(all, "rogue  SSID").shown)).toEqual(["rogue.whitelisted_ssids"]);
    expect(raws(findSettings(all, "threat").shown)).toEqual(["rogue"]); // in its description only
    expect(raws(findSettings(all, "port_usages").shown)).toEqual(["port_usages", "port_usages.*.mode", "port_usages.*.port_vlan"]);
  });
  it("lists the top-level settings by title when nothing is typed", () => {
    expect(findSettings(all, " ").shown.map((s) => s.titles[0])).toEqual(["API secret", "Auto upgrade", "Enabled", "Name", "Networks", "Port usages", "RADIUS", "Rogue", "Tags", "VLAN ID"]);
  });
  it("shows at most 50, and says how many it left out", () => {
    const many = Array.from({ length: 60 }, (_, i): Setting => ({ steps: [{ kind: "setting", name: `s${i}` }], spec: body, titles: [`Item ${i}`], raw: `s${i}`, description: "" }));
    const { shown, total } = findSettings(many, "item");
    expect([shown.length, total]).toEqual([50, 60]);
    expect(findWords("item", 50, 60)).toBe("50 of 60 shown: type more to narrow.");
    expect(findWords("firewall", 0, 0)).toBe('No setting matches "firewall", by name or description.');
    expect(findWords("", 10, 10)).toBe("10 settings; the list scrolls.");
  });
});
