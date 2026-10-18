// SPDX-License-Identifier: Apache-2.0
// A page's code, loaded when the page is opened (the owner's ruling on milestone 3 of 4b): the editor's, the Runs
// page's and a run's page's stay out of the list's and sign-in's first load. While it loads the page says so; if it
// can't be loaded the page says that, with Try again (a new load: React keeps a failed one).
import { Component, Suspense, lazy, useState, type ComponentType, type ReactNode } from "react";
import { Button } from "./Button";

/** A failure to fetch a page's code, told apart from an error inside the page (the router's to show). */
class PageLoadError extends Error {}

function lazyPage<P extends object>(load: () => Promise<ComponentType<P>>) {
  return lazy(() =>
    load().then(
      (Page) => ({ default: Page }),
      (e: unknown) => {
        throw new PageLoadError(e instanceof Error ? e.message : "the page couldn't be loaded");
      },
    ),
  );
}

class LoadBoundary extends Component<{ what: string; onRetry: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(error: unknown): { failed: boolean } | null {
    if (error instanceof PageLoadError) return { failed: true };
    throw error; // the page's own error: the router's boundary shows it
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const what = this.props.what;
    return (
      <section className="p-6">
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger bg-danger-bg px-3 py-2 text-body text-ink">
          <span>{`${what.charAt(0).toUpperCase()}${what.slice(1)} couldn't be loaded. Check your connection, then try again.`}</span>
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

/** `what`: the page's code as a person reads it ("the editor", "the runs"). */
export function LazyPage<P extends object>({ load, what, props }: { load: () => Promise<ComponentType<P>>; what: string; props: P }) {
  const [Page, setPage] = useState(() => lazyPage(load));
  return (
    <LoadBoundary what={what} onRetry={() => setPage(() => lazyPage(load))}>
      <Suspense fallback={<p role="status" className="p-6 text-body text-muted">{`Loading ${what}…`}</p>}>
        <Page {...props} />
      </Suspense>
    </LoadBoundary>
  );
}
