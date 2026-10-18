// SPDX-License-Identifier: Apache-2.0
// The Runs page's code and a run's page's, each loaded when it's opened, in its own chunk (the runs design §5.1).
import type { ComponentType } from "react";
import { LazyPage } from "../../components/LazyPage";
import type { RunFilters } from "../../lib/runs";

type RunsProps = { tenantId: string; filters: RunFilters };
type RunProps = { tenantId: string; runId: string };

export function LazyRunsPage(props: RunsProps) {
  return <LazyPage what="the runs" load={(): Promise<ComponentType<RunsProps>> => import("./RunsPage").then((m) => m.RunsPage)} props={props} />;
}

export function LazyRunPage(props: RunProps) {
  return <LazyPage what="the run" load={(): Promise<ComponentType<RunProps>> => import("./RunPage").then((m) => m.RunPage)} props={props} />;
}
