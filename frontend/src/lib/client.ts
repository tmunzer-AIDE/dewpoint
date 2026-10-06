// SPDX-License-Identifier: Apache-2.0
// The API client, typed by the schema the API serves (D15, B1): `pnpm gen:api` writes src/api/schema.d.ts from
// src/api/openapi.json, which `dewpoint api openapi` prints and CI holds to the backend. Paths, bodies and answers are
// all checked by TypeScript; a call that drifts from the API fails the build.
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "../api/schema";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(public status: number, public code: string, public body: unknown) {
    super(`${status} ${code}`);
  }
}

let csrf: string | null = null;
export function setCsrf(token: string | null): void {
  csrf = token;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const headers: Middleware = {
  onRequest({ request }) {
    request.headers.set("X-Dewpoint-Client", "web");
    request.headers.set("Accept", "application/json");
    if (UNSAFE.has(request.method) && csrf) request.headers.set("X-CSRF-Token", csrf);
    return request;
  },
};

// An absolute base: the browser resolves a relative one, a test runtime's Request doesn't. fetch is looked up at each
// call, not captured when the module loads.
export const client = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "same-origin",
  fetch: (request) => globalThis.fetch(request),
});
client.use(headers);

/** The answer's data, or an ApiError carrying the API's code (`{"error": code}`); a CSRF token an answer carries is
 * kept for the next unsafe call. */
export async function ok<D>(call: Promise<{ data?: D; error?: unknown; response: Response }>): Promise<D> {
  const { data, error, response } = await call;
  if (!response.ok) {
    const code = (error as { error?: unknown } | undefined)?.error;
    throw new ApiError(response.status, typeof code === "string" ? code : "http_error", error ?? null);
  }
  const token = (data as { csrf_token?: unknown } | undefined)?.csrf_token;
  if (typeof token === "string") setCsrf(token);
  return data as D;
}
