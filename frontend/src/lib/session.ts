// SPDX-License-Identifier: Apache-2.0
import { useQuery } from "@tanstack/react-query";
import { ApiError, client, ok, type Schemas } from "./client";

export type SessionState = Schemas["SessionOut"]["state"];
export type Session = Schemas["SessionOut"];

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        return await ok(client.GET("/api/v1/auth/session"));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 30_000,
  });
}
