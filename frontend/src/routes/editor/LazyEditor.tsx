// SPDX-License-Identifier: Apache-2.0
// The editor's code, loaded when a workflow is opened (the owner's ruling on milestone 3): React Flow and dagre stay
// out of the list's and sign-in's first load.
import type { ComponentType } from "react";
import { LazyPage } from "../../components/LazyPage";

type Props = { tenantId: string; workflowId: string; openTriggers?: boolean };
export type EditorModule = { EditorPage: ComponentType<Props> };

const loadEditor = (): Promise<EditorModule> => import("./Editor");

export function LazyEditor({ load = loadEditor, ...props }: Props & { load?: () => Promise<EditorModule> }) {
  return <LazyPage what="the editor" load={() => load().then((m) => m.EditorPage)} props={props} />;
}
