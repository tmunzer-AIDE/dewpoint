// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { GROUPED, IF, typeWith } from "../test/nodeTypes";
import { actionWords, groupMatches, groupOf, grouped, stepMatches, type StepGroup } from "./stepGroups";

const group = (title: string): StepGroup => grouped(GROUPED).plugins[0]!.groups.find((g) => g.title === title)!;

describe("groupOf", () => {
  it("reads the group at a config's root", () => {
    expect(groupOf(GROUPED[0]!)).toEqual({ plugin: "Acme", title: "Org WLANs" });
  });

  it("finds none without one, or without its words", () => {
    expect(groupOf(IF)).toBeNull();
    expect(groupOf(typeWith({ "x-group": "Org WLANs" }))).toBeNull();
    expect(groupOf(typeWith({ "x-group": { plugin: "Acme" } }))).toBeNull();
    expect(groupOf(typeWith({ "x-group": { plugin: "Acme", title: " " } }))).toBeNull();
  });
});

describe("grouped", () => {
  it("puts a plugin's steps in its groups, each by title, and leaves the others in their order", () => {
    const { plugins, loose } = grouped([IF, ...GROUPED]);
    expect(loose).toEqual([IF]);
    expect(plugins.map((p) => p.plugin)).toEqual(["Acme"]);
    expect(plugins[0]!.groups.map((g) => g.title)).toEqual(["Org WLANs", "Site settings", "Site WLANs"]);
    expect(plugins[0]!.groups[0]!.types.map((t) => t.title)).toEqual(["Create org WLAN", "Delete org WLAN", "List org WLANs", "Update org WLAN"]);
  });
});

describe("actionWords", () => {
  it("says what a group's steps do, by their titles' first words", () => {
    expect(actionWords(group("Org WLANs"))).toBe("Create, Delete, List, Update");
  });

  it("cuts after six", () => {
    const many = ["Arp", "Bounce", "Clear", "Get", "List", "Ping", "Restart"].map((w, i) => typeWith({}, { ref: `acme.d.${i}@1`, title: `${w} device` }));
    expect(actionWords({ plugin: "Acme", title: "Devices", types: many })).toBe("Arp, Bounce, Clear, Get, List, Ping…");
  });
});

describe("groupMatches", () => {
  it("finds a group by each word typed, in its title or a step's ref", () => {
    expect(groupMatches(group("Org WLANs"), "wlan")).toBe(true);
    expect(groupMatches(group("Site WLANs"), "WLAN")).toBe(true);
    expect(groupMatches(group("Site settings"), "wlan")).toBe(false);
    expect(groupMatches(group("Org WLANs"), "org  wlan")).toBe(true);
    expect(groupMatches(group("Site WLANs"), "org wlan")).toBe(false);
    expect(groupMatches(group("Site settings"), "site_settings")).toBe(true);
    expect(groupMatches(group("Org WLANs"), "  ")).toBe(false);
  });
});

describe("stepMatches", () => {
  const update = GROUPED[2]!;
  it("finds a step when its title starts with what's typed, or when its ref holds a ref typed", () => {
    expect(stepMatches(update, "update org wlan")).toBe(true);
    expect(stepMatches(update, "Update  org")).toBe(true);
    expect(stepMatches(update, "wlan")).toBe(false); // in its ref, but no ref was typed
    expect(stepMatches(update, "org_wlans")).toBe(false);
    expect(stepMatches(update, "acme.org_wlans.update")).toBe(true);
    expect(stepMatches(update, "")).toBe(false);
  });
});
