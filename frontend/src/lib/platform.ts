// SPDX-License-Identifier: Apache-2.0
import { useQuery } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

export type PlatformStatus = Schemas["PlatformStatusOut"];

/** What this deployment is (engine 2b spec §2.1), for the development banner. It never changes while the app runs. */
export function usePlatformStatus() {
  return useQuery({
    queryKey: ["platform-status"],
    queryFn: () => ok(client.GET("/api/v1/platform/status")),
    staleTime: Infinity,
  });
}
