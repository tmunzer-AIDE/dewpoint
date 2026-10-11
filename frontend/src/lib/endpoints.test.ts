// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { ENDPOINT, MIST } from "../test/triggers";
import {
  allowlistOf, blankForm, endpointBody, endpointPatch, eventsWords, fixedWords, idsWords, secretWords, senderWords,
} from "./endpoints";  // prettier-ignore

describe("a new endpoint's form as the API takes it", () => {
  it("sends a trigger's endpoint its trigger, name and limits alone: the trigger decides the rest", () => {
    expect(endpointBody({ ...blankForm("mist.webhook"), name: " Mist prod ", allowlist: "203.0.113.0/24\n\n" })).toEqual({
      name: "Mist prod", allowlist: ["203.0.113.0/24"], body_limit: 1_048_576, trigger: "mist.webhook",
    });  // prettier-ignore
  });

  it("sends another sender's proof, events and ids", () => {
    const f = { ...blankForm(null), name: "Ticketing", auth: "hmac" as const, events: "at" as const, eventsAt: "/items", ids: "pointer" as const };
    expect(endpointBody(f)).toEqual({
      name: "Ticketing", allowlist: [], body_limit: 1_048_576, auth: "hmac", signature_header: "x-dewpoint-signature",
      timestamp_header: "x-dewpoint-timestamp", tolerance_s: 300, events_pointer: "/items", id_source: "pointer", id_pointer: "/id",
    });  // prettier-ignore
    expect(endpointBody({ ...blankForm(null), name: "A", events: "list", ids: "header", idHeader: "X-Request-Id" })).toMatchObject({
      auth: "bearer", events_pointer: "", id_source: "header", id_header: "x-request-id",
    });  // prettier-ignore
    expect(endpointBody({ ...blankForm(null), name: "A" })).toMatchObject({ events_pointer: null, id_source: "none" });
  });

  it("changes only what an edit may, and only what changed", () => {
    const f = { name: "Mist prod", signature: "", timestamp: "", tolerance: 300, allowlist: "", bodyLimit: 1_048_576 };
    expect(endpointPatch(ENDPOINT, f)).toEqual({});
    expect(endpointPatch(ENDPOINT, { ...f, name: "Mist", allowlist: "10.0.0.0/8", bodyLimit: 262_144, tolerance: 60 })).toEqual({
      name: "Mist", allowlist: ["10.0.0.0/8"], body_limit: 262_144,
    });  // prettier-ignore
    const hmac = { ...ENDPOINT, auth: "hmac" as const, signature_header: "x-sig", timestamp_header: "x-ts" };
    expect(endpointPatch(hmac, { ...f, signature: "x-sig", timestamp: "x-time", tolerance: 900 })).toEqual({ timestamp_header: "x-time", tolerance_s: 900 });
  });

  it("reads an allowlist one network a line", () => {
    expect(allowlistOf(" 10.0.0.0/8 \n\n2001:db8::/32\n")).toEqual(["10.0.0.0/8", "2001:db8::/32"]);
  });
});

describe("an endpoint in words", () => {
  it("names its sender, a trigger's or another's, and one no plugin declares any more", () => {
    expect(senderWords("mist.webhook", [MIST])).toBe("Mist");
    expect(senderWords(null, [MIST])).toBe("Another sender");
    expect(senderWords("old.hook", [MIST])).toBe("An unknown sender (old.hook)");
  });

  it("says where its events and their ids are", () => {
    expect(eventsWords(null)).toBe("The body is one event");
    expect(eventsWords("")).toBe("The body is a list of events");
    expect(eventsWords("/items")).toBe("The list at /items");
    expect(idsWords({ id_source: "pointer", id_pointer: "/id", id_header: null })).toBe("At /id in each event");
    expect(idsWords({ id_source: "header", id_pointer: null, id_header: "x-request-id" })).toBe("In the x-request-id header");
    expect(idsWords({ id_source: "none", id_pointer: null, id_header: null })).toBe("None");
  });

  it("says what's fixed once made, and what needs fixing first, as the EndpointOther board does", () => {
    const f = { ...blankForm(null), auth: "hmac" as const, events: "at" as const, eventsAt: "/items", ids: "pointer" as const, idPointer: "id" };
    expect(fixedWords(f)).toBe("Fixed once made: an HMAC signature; events in the list at /items; each event's id: its pointer needs fixing first.");
    expect(fixedWords(blankForm(null))).toBe("Fixed once made: a token; each delivery one event; no ids.");
  });

  it("says how a sender uses the secret shown once", () => {
    expect(secretWords({ ...ENDPOINT, auth: "hmac", signature_header: "x-dewpoint-signature", timestamp_header: "x-dewpoint-timestamp", tolerance_s: 300 }, "Another sender")).toBe(
      "The sender signs the Unix time in seconds, a dot, then the raw body, with HMAC-SHA256 under this secret. It sends the hex digest in x-dewpoint-signature (sha256= in front is fine) and the time in x-dewpoint-timestamp. A time more than 5 minutes off is refused.",
    );
    expect(secretWords(ENDPOINT, "Mist")).toBe(
      "In Mist's webhook, the sender sends it in a header: Authorization: Bearer and the token. Lost, it can't be shown again: rotate it for a new one.",
    );
  });
});
