// SPDX-License-Identifier: Apache-2.0
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./api";

export type SessionState = "mfa_pending" | "enroll_required" | "active";
export interface Session {
  user: { id: string; email: string; is_platform_admin: boolean };
  state: SessionState;
  auth_methods: string[];
  csrf_token: string;
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        return await api<Session>("GET", "/api/v1/auth/session");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 30_000,
  });
}
