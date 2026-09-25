// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setCsrf } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("api", () => {
  it("sends client header always and csrf on unsafe methods", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    setCsrf("tok123");
    await api("GET", "/api/v1/tenants");
    await api("POST", "/api/v1/tenants", { name: "A" });
    const [, getInit] = fetchMock.mock.calls[0]!;
    const [, postInit] = fetchMock.mock.calls[1]!;
    expect(new Headers(getInit!.headers).get("X-CSRF-Token")).toBeNull();
    expect(new Headers(postInit!.headers).get("X-CSRF-Token")).toBe("tok123");
    expect(new Headers(postInit!.headers).get("X-Dewpoint-Client")).toBe("web");
    expect(postInit!.credentials).toBe("same-origin");
  });

  it("maps error bodies to ApiError codes and learns csrf from responses", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "active", csrf_token: "new" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(api("POST", "/api/v1/auth/login", {})).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    await api("POST", "/api/v1/auth/mfa/totp", { code: "123456" });
    await api("POST", "/api/v1/auth/logout");
    const last = vi.mocked(globalThis.fetch).mock.calls[2]![1]!;
    expect(new Headers(last.headers).get("X-CSRF-Token")).toBe("new");
    expect(new ApiError(500, "x", null)).toBeInstanceOf(Error);
  });
});
