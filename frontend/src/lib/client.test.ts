// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, client, ok, setCsrf } from "./client";

afterEach(() => vi.restoreAllMocks());

/** openapi-fetch hands fetch a Request. */
function sent(call: number): Request {
  return vi.mocked(globalThis.fetch).mock.calls[call]![0] as Request;
}

describe("the generated client", () => {
  it("sends the client header always, and the CSRF token on unsafe methods only", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response("[]", { status: 200 })));
    setCsrf("tok123");
    await ok(client.GET("/api/v1/tenants"));
    await ok(client.POST("/api/v1/tenants", { body: { name: "A", slug: "a-1" } }));
    expect(sent(0).headers.get("X-CSRF-Token")).toBeNull();
    expect(sent(1).headers.get("X-CSRF-Token")).toBe("tok123");
    expect(sent(1).headers.get("X-Dewpoint-Client")).toBe("web");
    expect(sent(1).credentials).toBe("same-origin");
    expect(new URL(sent(1).url).pathname).toBe("/api/v1/tenants");
  });

  it("turns an error answer into an ApiError with the API's code, and learns the CSRF token answers carry", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "active", csrf_token: "new" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "new" }), { status: 200 }));
    await expect(ok(client.POST("/api/v1/auth/login", { body: { email: "a@corp.test", password: "x" } }))).rejects
      .toMatchObject({ status: 401, code: "invalid_credentials" });
    await ok(client.POST("/api/v1/auth/mfa/totp", { body: { code: "123456" } }));
    await ok(client.POST("/api/v1/auth/password", { body: { current_password: "a", new_password: "b" } }));
    expect(sent(2).headers.get("X-CSRF-Token")).toBe("new");
    expect(new ApiError(500, "x", null)).toBeInstanceOf(Error);
  });

  it("names a body-less error by its status family", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("upstream down", { status: 502 }));
    await expect(ok(client.GET("/api/v1/tenants"))).rejects.toMatchObject({ status: 502, code: "http_error" });
  });
});
