// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import cases from "../test/messageCases.json";
import { cut, googleChat, slack, teams, type Message, type Rendered } from "./messages";

interface Case {
  name: string;
  message: Message;
  slack: Rendered;
  teams: Rendered;
  google_chat: Rendered;
}

// The plugins' own renderers wrote these (backend/tests/plugins/test_message_cases.py holds the file to them).
const CASES = cases.cases as unknown as Case[];

const sent = ({ body, truncated }: Rendered): Rendered => ({ body, truncated });

describe.each(CASES)("$name", (c) => {
  it("is laid out as Slack's renderer lays it out", () => expect(sent(slack(c.message))).toEqual(c.slack));
  it("is laid out as Teams' renderer lays it out", () => expect(sent(teams(c.message))).toEqual(c.teams));
  it("is laid out as Google Chat's renderer lays it out", () => expect(sent(googleChat(c.message))).toEqual(c.google_chat));
});

describe("cut", () => {
  it("counts characters as Python does, a character outside the BMP as one", () => {
    expect(cut("𝄞".repeat(3), 3)).toEqual(["𝄞𝄞𝄞", false]);
    expect(cut("𝄞".repeat(4), 3)).toEqual(["𝄞𝄞…", true]);
  });

  it("counts UTF-8 bytes, never cutting through a character", () => {
    expect(cut("ééé", 6, "bytes")).toEqual(["ééé", false]);
    expect(cut("éééé", 6, "bytes")).toEqual(["é…", true]);
  });
});

describe("the body's size before it's shortened", () => {
  it("is the uncut body's UTF-8 bytes, as Teams and Google Chat are sent", () => {
    const message: Message = { text: "é".repeat(20_000) };
    expect(teams(message).size).toBeGreaterThan(40_000);
    expect(teams(message).truncated).toEqual(["text"]);
    expect(googleChat(message).size).toBe(new TextEncoder().encode(JSON.stringify({ text: `${"é".repeat(20_000)}\n\nSeverity: info` })).length);
  });
});
