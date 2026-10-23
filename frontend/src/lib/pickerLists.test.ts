// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { LISTING } from "../test/nodeTypes";
import { listOf, pickerLists } from "./pickerLists";

describe("the lists a start-form picker can name (the 4f-3 design §5.7)", () => {
  it("offers one list per options field of the active types, in its plugin's words, by label", () => {
    expect(pickerLists(LISTING).map((l) => [l.field, l.label, l.noun])).toEqual([
      ["psk_id", "Acme · Org PSKs", "PSKs"],
      ["site_id", "Acme · Org sites", "sites"],
      ["wlan_id", "Acme · Org WLANs", "WLANs"],
    ]);
  });

  it("names a read-only .get taking only the connection and the field, the first by ref; else the first read-only one", () => {
    const sites = listOf(pickerLists(LISTING), "site_id")!;
    expect(sites).toEqual({ field: "site_id", label: "Acme · Org sites", plugin: "Acme", noun: "sites", node: "acme.site_zones.get@1", credentials: ["acme"] });
    expect(listOf(pickerLists(LISTING), "psk_id")!.node).toBe("acme.org_psks.list@1"); // no such .get: the first read-only one
    expect(listOf(pickerLists(LISTING), "map_id")).toBeUndefined(); // only a deprecated type lists it
    expect(listOf(pickerLists(LISTING), "device_id")).toBeUndefined(); // its list has no words
  });
});
