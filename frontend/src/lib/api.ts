// SPDX-License-Identifier: Apache-2.0
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

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers = new Headers({ "X-Dewpoint-Client": "web", Accept: "application/json" });
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (UNSAFE.has(method) && csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const code = (data as { error?: string } | null)?.error ?? "http_error";
    throw new ApiError(res.status, code, data);
  }
  const token = (data as { csrf_token?: string } | null)?.csrf_token;
  if (token) setCsrf(token);
  return data as T;
}
