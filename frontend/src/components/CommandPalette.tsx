// SPDX-License-Identifier: Apache-2.0
// The ⌘K palette (screen 1a's header search; the palette itself is undesigned, D8, built in the design's grammar).
// A native modal <dialog> holds cmdk's Command: focus moves in and back, Escape closes, the page behind is inert, and
// nothing injects a stylesheet (D23). Later slices add their pages and actions here.
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { Command } from "cmdk";
import { useEffect, useRef, useState } from "react";
import { client, ok } from "../lib/client";
import { canEdit, workflowsQuery } from "../lib/workflows";

// The selected option never takes focus (the search field keeps it), so it carries its own 3:1 outline (WCAG 1.4.11).
export const PALETTE_ITEM =
  "flex cursor-pointer items-center justify-between gap-4 rounded-md px-3 py-2 text-body " +
  "data-[selected=true]:bg-accent-soft data-[selected=true]:text-accent-ink " +
  "data-[selected=true]:outline-2 data-[selected=true]:-outline-offset-2 data-[selected=true]:outline-focus";
export const PALETTE_GROUP = "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 " +
  "[&_[cmdk-group-heading]]:text-small [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const navigate = useNavigate();
  const params = useParams({ strict: false });
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: () => ok(client.GET("/api/v1/tenants")) });
  const workflows = useQuery({ ...workflowsQuery(params.tenantId ?? ""), enabled: open && !!params.tenantId });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      // React's autoFocus runs while the dialog is still closed, where nothing can take focus; showModal() would
      // then focus the dialog itself, and keys would never reach the search field (the browser gate caught this).
      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
    }
    if (!open && d.open) d.close();
  }, [open]);

  function go(to: () => Promise<void>) {
    setOpen(false);
    void to();
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-keyshortcuts="Meta+K Control+K"
        className="inline-flex min-h-9 min-w-0 flex-1 basis-40 items-center gap-2.5 rounded-lg border border-line bg-surface-2 px-3 text-small text-muted hover:bg-surface-hover sm:w-80 sm:flex-none"
      >
        <span className="truncate">Search or jump to…</span>
        <kbd aria-hidden="true" className="ml-auto rounded-sm border border-line-strong px-1.5 font-mono text-meta">⌘K</kbd>
      </button>
      <dialog
        ref={dialog}
        aria-label="Search or jump to"
        onClose={() => setOpen(false)}
        className="mx-auto mt-20 w-[640px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
      >
        {open && (
          <Command label="Search or jump to" loop>
            <Command.Input
              placeholder="Type a page, a workflow or a tenant"
              className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
            />
            <Command.List className="max-h-80 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-2 text-body text-muted">Nothing matches.</Command.Empty>
              <Command.Group heading="Go to" className={PALETTE_GROUP}>
                {params.tenantId && (
                  <Command.Item
                    value="Workflows"
                    className={PALETTE_ITEM}
                    onSelect={() => go(() => navigate({ to: "/t/$tenantId/workflows", params: { tenantId: params.tenantId! } }))}
                  >
                    Workflows
                  </Command.Item>
                )}
                {/* Only for a role that can create one: the server would refuse anyone else (403). */}
                {params.tenantId && canEdit(tenants.data?.find((t) => t.id === params.tenantId)?.role) && (
                  <Command.Item
                    value="New workflow"
                    className={PALETTE_ITEM}
                    onSelect={() =>
                      go(() =>
                        navigate({ to: "/t/$tenantId/workflows", params: { tenantId: params.tenantId! }, search: { new: true } }),
                      )
                    }
                  >
                    New workflow
                  </Command.Item>
                )}
                {params.tenantId && (
                  <Command.Item
                    value="Connections"
                    className={PALETTE_ITEM}
                    onSelect={() => go(() => navigate({ to: "/t/$tenantId/connections", params: { tenantId: params.tenantId! } }))}
                  >
                    Connections
                  </Command.Item>
                )}
                {params.tenantId && (
                  <Command.Item
                    value="Members & roles"
                    className={PALETTE_ITEM}
                    onSelect={() =>
                      go(() => navigate({ to: "/t/$tenantId/settings/members", params: { tenantId: params.tenantId! } }))
                    }
                  >
                    Members &amp; roles
                  </Command.Item>
                )}
                <Command.Item value="Security" className={PALETTE_ITEM} onSelect={() => go(() => navigate({ to: "/account/security" }))}>
                  Security
                </Command.Item>
                <Command.Item value="All tenants" className={PALETTE_ITEM} onSelect={() => go(() => navigate({ to: "/tenants" }))}>
                  All tenants
                </Command.Item>
              </Command.Group>
              {params.tenantId && !!workflows.data?.length && (
                <Command.Group heading="Workflows" className={PALETTE_GROUP}>
                  {workflows.data.map((w) => (
                    <Command.Item
                      key={w.id}
                      value={w.name}
                      className={PALETTE_ITEM}
                      onSelect={() =>
                        go(() =>
                          navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId: params.tenantId!, workflowId: w.id } }),
                        )
                      }
                    >
                      {w.name}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {!!tenants.data?.length && (
                <Command.Group heading="Tenants" className={PALETTE_GROUP}>
                  {tenants.data.map((t) => (
                    <Command.Item
                      key={t.id}
                      value={`${t.name} ${t.slug}`}
                      className={PALETTE_ITEM}
                      onSelect={() => go(() => navigate({ to: "/t/$tenantId/workflows", params: { tenantId: t.id } }))}
                    >
                      <span>{t.name}</span>
                      <span className="text-small text-muted">{t.role}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
            </Command.List>
          </Command>
        )}
      </dialog>
    </>
  );
}
