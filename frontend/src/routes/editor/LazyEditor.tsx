// SPDX-License-Identifier: Apache-2.0
// The editor's code, loaded when a workflow is opened (the owner's ruling on milestone 3): React Flow and dagre stay
// out of the list's and sign-in's first load. While it loads the page says so; if it can't be loaded the page says
// that, with Try again (a new load: React keeps a failed one).
import { Component, Suspense, lazy, useState, type ComponentType, type ReactNode } from "react";
import { Button } from "../../components/Button";

type Props = { tenantId: string; workflowId: string };
export type EditorModule = { EditorPage: ComponentType<Props> };

/** A failure to fetch the editor's code, told apart from an error inside the editor (the router's to show). */
class EditorLoadError extends Error {}

const loadEditor = (): Promise<EditorModule> => import("./Editor");

function lazyEditor(load: () => Promise<EditorModule>) {
  return lazy(() =>
    load().then(
      (m) => ({ default: m.EditorPage }),
      (e: unknown) => {
        throw new EditorLoadError(e instanceof Error ? e.message : "the editor couldn't be loaded");
      },
    ),
  );
}

class LoadBoundary extends Component<{ onRetry: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(error: unknown): { failed: boolean } | null {
    if (error instanceof EditorLoadError) return { failed: true };
    throw error; // the editor's own error: the router's boundary shows it
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="p-6">
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger bg-danger-bg px-3 py-2 text-body text-ink">
          <span>The editor couldn&apos;t be loaded. Check your connection, then try again.</span>
          <Button
            size="sm"
            onClick={() => {
              this.setState({ failed: false });
              this.props.onRetry();
            }}
          >
            Try again
          </Button>
        </div>
      </section>
    );
  }
}

export function LazyEditor({ load = loadEditor, ...props }: Props & { load?: () => Promise<EditorModule> }) {
  const [Page, setPage] = useState(() => lazyEditor(load));
  return (
    <LoadBoundary onRetry={() => setPage(() => lazyEditor(load))}>
      <Suspense fallback={<p role="status" className="p-6 text-body text-muted">Loading the editor…</p>}>
        <Page {...props} />
      </Suspense>
    </LoadBoundary>
  );
}
