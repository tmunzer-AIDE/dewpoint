// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./api";
import { signOut } from "./signOut";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

afterEach(() => vi.restoreAllMocks());

describe("signOut", () => {
  it("succeeds only when the server confirms", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    expect(await signOut()).toBe("signed_out");
  });

  it("does not treat any other 2xx as a completed sign-out", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { ok: true }));
    expect(await signOut()).toBe("failed");
  });

  it("treats an already-invalid session as signed out", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(401, { error: "unauthenticated" }));
    expect(await signOut()).toBe("signed_out");
  });

  it("fails when the network is down", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await signOut()).toBe("failed");
  });

  it("fails on a server error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(500, { error: "internal_error" }));
    expect(await signOut()).toBe("failed");
  });

  it("refreshes a stale CSRF token once, then retries", async () => {
    setCsrf("stale");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(403, { error: "csrf" }))
      .mockResolvedValueOnce(json(200, { state: "active", csrf_token: "fresh" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(await signOut()).toBe("signed_out");
    const retry = fetchMock.mock.calls[2]![1]!;
    expect(new Headers(retry.headers).get("X-CSRF-Token")).toBe("fresh");
  });

  it("fails if the retry after a CSRF refresh also fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(403, { error: "csrf" }))
      .mockResolvedValueOnce(json(200, { state: "active", csrf_token: "fresh" }))
      .mockResolvedValueOnce(json(403, { error: "csrf" }));
    expect(await signOut()).toBe("failed");
  });
});
