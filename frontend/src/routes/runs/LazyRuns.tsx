// SPDX-License-Identifier: Apache-2.0
// The Runs page's code and a run's page's, each loaded when it's opened, in its own chunk (the runs design §5.1). The
// run form's too, opened from the Workflows list (4e-2b): the list's first load doesn't carry it.
import type { ComponentProps, ComponentType } from "react";
import { LazyPage } from "../../components/LazyPage";
import type { RunFilters } from "../../lib/runs";
import type { RunForm } from "./RunForm";

type RunsProps = { tenantId: string; filters: RunFilters };
type RunProps = { tenantId: string; runId: string };

export function LazyRunsPage(props: RunsProps) {
  return <LazyPage what="the runs" load={(): Promise<ComponentType<RunsProps>> => import("./RunsPage").then((m) => m.RunsPage)} props={props} />;
}

export function LazyRunPage(props: RunProps) {
  return <LazyPage what="the run" load={(): Promise<ComponentType<RunProps>> => import("./RunPage").then((m) => m.RunPage)} props={props} />;
}

type RunFormProps = ComponentProps<typeof RunForm>;

export function LazyRunForm(props: RunFormProps) {
  return <LazyPage what="the run form" load={(): Promise<ComponentType<RunFormProps>> => import("./RunForm").then((m) => m.RunForm)} props={props} />;
}
