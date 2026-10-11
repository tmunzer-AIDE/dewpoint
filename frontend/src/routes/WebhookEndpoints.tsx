// SPDX-License-Identifier: Apache-2.0
// Settings → Webhook endpoints (D11; 4c-3b; the Endpoints, EndpointNew, EndpointOther, ReadOnly and NarrowForms
// boards): where other systems send events, each with its sender, how it proves itself, the workflows it starts, its
// waiting events and its path. Every member reads; editors and above make, change, turn off and rotate (trigger.manage),
// and the API decides every write. An endpoint is turned off, never deleted. A secret is shown once, when it's made or
// rotated, and never kept by the page.
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Fragment, useRef, useState } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError } from "../components/LoadError";
import { Switch } from "../components/Switch";
import { Table, Td, Th } from "../components/Table";
import { announce } from "../lib/announce";
import { proofWords, secretWords, senderWords } from "../lib/endpoints";
import { usePlatformStatus } from "../lib/platform";
import { useDocumentTitle } from "../lib/title";
import {
  endpointBindingsQuery, endpointsQuery, rotateSecret, topicOf, triggerTypesQuery, updateEndpoint, type Endpoint, type EndpointBinding,
} from "../lib/triggers";  // prettier-ignore
import { canEdit, tenantQuery, workflowsQuery } from "../lib/workflows";
import { EditEndpoint, NewEndpoint } from "./EndpointForm";

type Shown = { name: string; secret: string; endpoint: Endpoint; rotated: boolean };

const short = (path: string) => (path.length > 18 ? `${path.slice(0, 16)}…` : path);

/** Copies the path, and says so: a refused clipboard says where to read it instead. */
async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    announce("Copied the path");
  } catch {
    announce("The clipboard refused it: the path is in the details, to copy by hand");
  }
}

export function WebhookEndpointsPage({ tenantId }: { tenantId: string }) {
  useDocumentTitle("Webhook endpoints");
  const qc = useQueryClient();
  const tenant = useQuery(tenantQuery(tenantId));
  const manage = canEdit(tenant.data?.role);
  const endpoints = useQuery(endpointsQuery(tenantId));
  const types = useQuery(triggerTypesQuery);
  const platform = usePlatformStatus();
  const workflows = useQuery(workflowsQuery(tenantId));
  const list = endpoints.data?.endpoints ?? [];
  const bindings = useQueries({ queries: list.map((e) => endpointBindingsQuery(tenantId, e.id)) });
  const bound = new Map(list.map((e, i) => [e.id, bindings[i]?.data?.bindings ?? null]));
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const [rotating, setRotating] = useState<Endpoint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const shownHeading = useRef<HTMLHeadingElement>(null);
  /** Focus where a person carries on once a form closes (WCAG 2.4.3; the final review): a token shown once, or the
   * edited endpoint's Details, the one on screen (the table's, or its card's at narrow widths). */
  const toShown = () => requestAnimationFrame(() => shownHeading.current?.focus());
  const toDetails = (id: string) =>
    requestAnimationFrame(() => {
      const all = [...document.querySelectorAll<HTMLElement>("[data-back]")].filter((el) => el.dataset.back === `endpoint:${id}`);
      (all.find((el) => el.getClientRects().length > 0) ?? all[0])?.focus();
    });
  const refresh = () => qc.invalidateQueries({ queryKey: ["endpoints", tenantId] });
  const named = (id: string) => workflows.data?.find((w) => w.id === id)?.name ?? "a workflow";
  const typeOf = (e: Endpoint) => (types.data ?? []).find((t) => t.key === e.trigger);

  const toggle = useMutation({
    mutationFn: (e: { id: string; name: string; enabled: boolean }) => updateEndpoint(tenantId, e.id, { enabled: e.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, e) => announce(`${e.name} turned ${e.enabled ? "on" : "off: events sent to it are refused"}`),
    onError: (_, e) => setError(`${e.name} couldn't be turned ${e.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const rotate = useMutation({
    mutationFn: (e: Endpoint) => rotateSecret(tenantId, e.id),
    onSuccess: (out, e) => {
      setRotating(null);
      setShown({ name: e.name, secret: out.secret, endpoint: e, rotated: true });
      toShown();
    },
    onError: (_, e) => {
      setRotating(null);
      setError(`${e.name}'s ${e.auth === "hmac" ? "secret" : "token"} wasn't rotated. Try again.`);
    },
  });

  /** What the endpoint starts, as links to its workflows, with each one's topic where it has one. */
  function starts(e: Endpoint, rows: EndpointBinding[] | null) {
    if (rows === null) return <span className="text-muted">The workflows it starts couldn&apos;t be read.</span>;
    if (rows.length === 0) return <span className="text-muted">It starts no workflow yet: a workflow picks it in its Triggers.</span>;
    return (
      <span>
        Starts{" "}
        {rows.map((b, i) => {
          const topic = topicOf(b.filter, typeOf(e));
          return (
            <Fragment key={b.id}>
              {i > 0 && ", "}
              <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: b.workflow_id }} className="text-accent-ink underline">
                {named(b.workflow_id)}{topic ? ` · ${topic}` : ""}
              </Link>
              {!b.enabled && " (off)"}
            </Fragment>
          );
        })}
      </span>
    );  // prettier-ignore
  }

  function details(e: Endpoint) {
    const sender = senderWords(e.trigger, types.data);
    const rows = bound.get(e.id) ?? null;
    return (
      <div className="flex flex-col gap-2 text-small">
        <p>
          Path <code className="break-all font-mono">{e.path}</code>, on your Dewpoint webhook address.{" "}
          {e.auth === "hmac" ? "Each delivery is signed with its secret, and timed." : `${sender === "Another sender" ? "The sender" : sender} sends its token in an Authorization: Bearer header.`}
        </p>
        <p>{starts(e, rows)}</p>
        {e.pending_events > 0 && <p className="text-muted">{e.pending_events === 1 ? "1 event is" : `${e.pending_events} events are`} waiting to be matched.</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void copy(e.path)}>Copy the path</Button>
          {manage && <Button size="sm" onClick={() => setEditing(e.id)}>Edit</Button>}
          {manage && <Button size="sm" variant="danger-outline" onClick={() => setRotating(e)}>{e.auth === "hmac" ? "Rotate the secret…" : "Rotate the token…"}</Button>}
        </div>
      </div>
    );  // prettier-ignore
  }

  const onSwitch = (e: Endpoint) =>
    manage ? (
      <Switch checked={e.enabled} label={e.name} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: e.id, name: e.name, enabled })} />
    ) : (
      <span>{e.enabled ? "On" : "Off"}</span>
    );  // prettier-ignore
  /** How many workflows it starts: loading, or couldn't be read, said apart (4c-3b's final review). */
  const workflowsOf = (e: Endpoint) => {
    const read = bindings[list.indexOf(e)];
    if (!read || read.isPending) return <><span aria-hidden="true">…</span><span className="sr-only">Loading</span></>;
    if (read.isError) return <span className="font-sans text-muted">couldn&apos;t be read</span>;
    return read.data.bindings.length;
  };
  const detailsButton = (e: Endpoint) => (
    <Button size="sm" aria-label={`${e.name}, details`} aria-expanded={open === e.id} data-back={`endpoint:${e.id}`} onClick={() => setOpen(open === e.id ? null : e.id)}>Details</Button>
  );
  const editingOne = list.find((e) => e.id === editing);
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Webhook endpoints</h2>
        <p className="mt-0.5 text-small text-muted">
          Where other systems send events. {manage ? "A workflow picks an endpoint in its Triggers." : "Making and changing endpoints needs the editor role."}
        </p>
      </div>
      {platform.isSuccess && platform.data.environment !== "development" && (
        <p className="text-small text-warn-ink">This deployment doesn&apos;t receive webhooks yet: only development deployments do, for now.</p>
      )}
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      {shown && (
        <div role="status" className="flex max-w-2xl flex-col gap-2 rounded-lg border border-line-strong bg-surface p-4">
          <h3 ref={shownHeading} tabIndex={-1} className="text-body-lg font-semibold outline-none">{shown.rotated ? `${shown.name}'s new ${shown.endpoint.auth === "hmac" ? "secret" : "token"}` : `${shown.name} is ready`}</h3>
          <p className="text-small">{shown.endpoint.auth === "hmac" ? "Its signing secret" : "Its token"}, shown this once:</p>
          <code className="break-all rounded-lg border border-line px-3 py-2 font-mono text-small">{shown.secret}</code>
          <p className="text-small text-muted">{secretWords(shown.endpoint, senderWords(shown.endpoint.trigger, types.data))}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(shown.secret).then(() => announce("Copied"), () => announce("The clipboard refused it: select it to copy by hand"));
              }}
            >
              Copy
            </Button>
            <Button
              size="sm" variant="primary"
              onClick={() => {
                setShown(null);
                requestAnimationFrame(() => heading.current?.focus());
              }}
            >
              I&apos;ve copied it
            </Button>
          </div>
        </div>
      )}
      {manage && !adding && !editingOne && (
        <Button variant="primary" size="md" className="self-start" onClick={() => setAdding(true)}>＋ Endpoint</Button>
      )}
      {adding && (
        <NewEndpoint
          tenantId={tenantId} types={types.data ?? []}
          onCreated={(made) => {
            setAdding(false);
            setShown({ name: made.name, secret: made.secret, endpoint: made, rotated: false });
            announce(`Created ${made.name}`);
            toShown();
            void refresh();
          }}
          onCancel={() => {
            setAdding(false);
            requestAnimationFrame(() => heading.current?.focus());
          }}
        />
      )}
      {editingOne && (
        <EditEndpoint
          tenantId={tenantId} endpoint={editingOne} types={types.data}
          onSaved={() => {
            setEditing(null);
            announce(`Saved ${editingOne.name}`);
            toDetails(editingOne.id);
            void refresh();
          }}
          onCancel={() => {
            setEditing(null);
            toDetails(editingOne.id);
          }}
        />
      )}
      {endpoints.isError ? (
        <LoadError what="The webhook endpoints" />
      ) : endpoints.isSuccess && list.length === 0 ? (
        <p className="text-small text-muted">No endpoint yet.</p>
      ) : (
        <>
          <Table label="Webhook endpoints" className="hidden sm:block">
            <thead>
              <tr>
                <Th>Name</Th><Th>Sender</Th><Th>Signed with</Th><Th>Workflows</Th><Th>Waiting</Th><Th>On</Th><Th>Path</Th>
                <Th><span className="sr-only">Actions</span></Th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <Fragment key={e.id}>
                  <tr>
                    <Td className="font-medium">{e.name}</Td>
                    <Td>{senderWords(e.trigger, types.data)}</Td>
                    <Td>{proofWords(e.auth)}</Td>
                    <Td className="font-mono text-small">{workflowsOf(e)}</Td>
                    <Td className="font-mono text-small">{e.pending_events}</Td>
                    <Td>{onSwitch(e)}</Td>
                    <Td className="font-mono text-small">{short(e.path)}</Td>
                    <Td className="text-right">{detailsButton(e)}</Td>
                  </tr>
                  {open === e.id && (
                    <tr>
                      <Td colSpan={8}>{details(e)}</Td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </Table>
          <ul aria-label="Webhook endpoints" className="flex flex-col gap-3 sm:hidden">
            {list.map((e) => (
              <li key={e.id} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{e.name}</span>
                  {onSwitch(e)}
                </div>
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
                  <dt className="text-muted">Sender</dt><dd>{senderWords(e.trigger, types.data)}</dd>
                  <dt className="text-muted">Signed with</dt><dd>{proofWords(e.auth)}</dd>
                  <dt className="text-muted">Workflows</dt><dd className="font-mono">{workflowsOf(e)}</dd>
                  <dt className="text-muted">Waiting</dt><dd className="font-mono">{e.pending_events}</dd>
                  <dt className="text-muted">Path</dt><dd className="break-all font-mono">{e.path}</dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void copy(e.path)}>Copy the path</Button>
                  {detailsButton(e)}
                </div>
                {open === e.id && details(e)}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="text-small text-muted">An endpoint is turned off rather than deleted: events sent to it are refused, and its workflows keep their bindings.</p>
      <ConfirmDialog
        open={rotating !== null}
        title={rotating ? `Rotate ${rotating.name}'s ${rotating.auth === "hmac" ? "secret" : "token"}?` : ""}
        confirmLabel={rotating?.auth === "hmac" ? "Rotate the secret" : "Rotate the token"}
        busy={rotate.isPending}
        onConfirm={() => rotating && rotate.mutate(rotating)}
        onCancel={() => setRotating(null)}
      >
        {rotating &&
          `The old ${rotating.auth === "hmac" ? "secret" : "token"} stops working now: ${senderWords(rotating.trigger, types.data) === "Another sender" ? "the sender's" : `${senderWords(rotating.trigger, types.data)}'s`} events are refused until it sends the new one.`}
      </ConfirmDialog>
    </div>
  );  // prettier-ignore
}
