// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c): the draft, on a canvas, by pointer or keyboard alone (D16), saved as it changes (D17). Task 14
// adds problems, Task 15 publishing and versions.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker, useMatch, useRouter } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LoadError } from "../../components/LoadError";
import { announce } from "../../lib/announce";
import { ApiError, client, ok } from "../../lib/client";
import { admission, setConfig, setOptions, valueAt, type Changed } from "../../lib/config";
import { downloadJson, fileName } from "../../lib/download";
import { ConflictError, DraftSync, type SyncState } from "../../lib/draftSync";
import {
  START, addAfter, asGraph, connect, deleteEdge, deleteNode, edgesOf, findNode, idKey, insertBeforeEntry, insertOnEdge,
  moveNodes, nodesOf, portOf, portsOf, sameId, type PortRef,
} from "../../lib/graph";  // prettier-ignore
import { begin, record, redo, undo, type History } from "../../lib/history";
import { CARD, layout } from "../../lib/layout";
import { guardLeaving } from "../../lib/leaving";
import type { Path } from "../../lib/schemaForm";
import { useDocumentTitle } from "../../lib/title";
import {
  STALE, applyAll, applyUnapplied, baseOf, droppedWhy, isStale, lineageOf, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "../../lib/unapplied";  // prettier-ignore
import {
  canEdit, canPublish, nodeTypesQuery, notPortable, tenantQuery, versionsQuery, workflowQuery, type Diagnostic,
  type GraphDoc, type GraphEdge, type GraphNode, type NodeType, type PortableProblem, type VersionDetail, type VersionRow,
  type WorkflowDetail,
} from "../../lib/workflows";  // prettier-ignore
import { Canvas } from "./Canvas";
import { NAV_KEYS, isPath, navModel, pathTo, step, type NavKey } from "./canvasNav";
import { checkLabel, checkState, lastOf, type Check } from "./check";
import { ConnectDialog } from "./ConnectDialog";
import type { DrawerActions } from "./drawer/context";
import { StepDrawer } from "./drawer/StepDrawer";
import { addsOf, item, type ItemAction } from "./items";
import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
import { SaveState } from "./SaveState";
import { type Problems } from "./StepCard";
import { StepPicker, type PickMode } from "./StepPicker";
import { UnappliedPanel } from "./UnappliedPanel";
import { VersionsPanel } from "./VersionsPanel";
import { Toolbar } from "./Toolbar";

type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null };

/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds

/** Whether a request's outcome is unknown: no answer reached the editor (the network), or a 5xx came in the API's
 * place or after its commit. Such an outcome is read back, never assumed (4b ruling 25). */
const uncertain = (e: unknown) => !(e instanceof ApiError) || e.status >= 500;

type Notice = { tone: "danger" | "info"; text: string; action?: { label: string; run: () => void } };
type Confirm = { kind: "publish"; expected: number; elsewhere?: boolean } | { kind: "activate"; version: VersionRow };

/** What the editor asks before doing: deleting a step or an edge, or a settings change that takes ports away, with the
 * document it makes and the unapplied edits it applies (rulings 9 and 18). */
type Asking =
  | { kind: "node"; id: string }
  | { kind: "edge"; edge: GraphEdge }
  | { kind: "ports"; next: GraphDoc; dropped: GraphEdge[]; release: string[] }
  // edits that can't be applied, before what needs the draft settled: an export, a publication, a version view
  | { kind: "unapplied"; action: string; left: Unapplied[]; then: () => void };

/** Which ports a change takes away, and where their edges led (ruling 9). */
function portsQuestion(dropped: GraphEdge[], keyOf: (id: string) => string): string {
  const ports = [...new Set(dropped.map(portOf))];
  const targets = [...new Set(dropped.map((e) => keyOf(e.to.node)))];
  const one = ports.length === 1;
  return `${one ? "The port" : "The ports"} ${ports.join(", ")} ${one ? "goes" : "go"} with this change, and ${
    dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")} ${dropped.length === 1 ? "is" : "are"} deleted.`;
}

const CANT = "Not written: the draft can't be changed now."; // a conflict, an exit agreed to, a version view

/** A version's drawer: read only, and blind to the draft's edits not applied, which are never a version's (the review
 * of milestone 2). */
const VERSION_ACTIONS: DrawerActions = {
  set: () => CANT,
  options: () => CANT,
  held: () => undefined,
  hold: () => undefined,
  release: () => undefined,
  discard: () => undefined,
  apply: () => CANT,
  stale: () => false,
  rebase: () => undefined,
  restructure: () => CANT,
};

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const qc = useQueryClient();
  // A draft cached from an earlier visit would conflict on the first edit (4b ruling 23): the editor waits for the read
  // made after this page mounted. Once open it owns its document and keeps what it opened with: a later read, a
  // failed refresh or a cleared cache neither replaces nor closes it.
  const workflow = useQuery({
    ...workflowQuery(tenantId, workflowId),
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const types = useQuery(nodeTypesQuery);
  const tenant = useQuery(tenantQuery(tenantId));
  const [opened, setOpened] = useState<Opened | null>(null);
  const [loads, setLoads] = useState(0);
  useEffect(() => {
    if (opened !== null || !workflow.isFetchedAfterMount || !workflow.isSuccess || !types.data || !tenant.data) return;
    setOpened({ workflow: workflow.data, types: types.data, role: tenant.data.role ?? null });
  }, [opened, workflow.isFetchedAfterMount, workflow.isSuccess, workflow.data, types.data, tenant.data]);
  useDocumentTitle(opened?.workflow.name ?? "Workflow");

  /** After a conflict: the saved draft, read afresh, in a new editor. */
  const reload = async () => {
    await qc.invalidateQueries({ queryKey: ["workflow", tenantId, workflowId] });
    setOpened(null);
    setLoads((n) => n + 1);
  };

  if (opened === null) {
    if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
    if (types.isError && !types.data) return <section className="p-6"><LoadError what="The step types" /></section>;
    if (tenant.isError && !tenant.data) return <section className="p-6"><LoadError what="This tenant" /></section>;
    return <p className="p-6 text-body text-muted">Loading…</p>;
  }
  const trouble = types.isError ? "The step types couldn't be refreshed: the editor keeps the ones it opened with." : null;
  return (
    <Editor
      key={loads}
      tenantId={tenantId}
      workflow={opened.workflow}
      types={types.data ?? opened.types}
      role={opened.role}
      trouble={trouble}
      onReload={() => void reload()}
    />
  );
}

function Editor({
  tenantId, workflow, types, role, trouble, onReload,
}: {
  tenantId: string; workflow: WorkflowDetail; types: NodeType[]; role: string | null; trouble: string | null;
  onReload: () => void;
}) {  // prettier-ignore
  const typeMap = useMemo(() => new Map(types.map((t) => [t.ref, t])), [types]);
  const [history, setHistory] = useState<History<GraphDoc>>(() => begin(asGraph(workflow.draft)));
  const doc = history.present;
  // The history as of now, written at once (the review of revision 3): a decision made between renders (an exit
  // awaiting a save) settles against the document that save made, never one captured before it waited. `change` and
  // undo/redo go through `commitHistory`; the drawer's writes read `draftNow()`.
  const historyNow = useRef(history);
  const commitHistory = (next: History<GraphDoc>) => {
    historyNow.current = next;
    setHistory(next);
  };
  const draftNow = () => historyNow.current.present;
  const [sync, setSyncState] = useState<SyncState>({
    status: "saved", revision: workflow.draft_revision, unpublished: workflow.unpublished_changes, generation: 0,
    savedGeneration: 0, savedHash: workflow.draft_graph_hash, activeNumber: workflow.active_version_number,
  });  // prettier-ignore
  const saver = useRef<DraftSync | null>(null);
  // A save that failed is said, not only shown (WCAG 4.1.3): the edits made after it would otherwise go on unsaved
  // unnoticed. A conflict has its own alert.
  useEffect(() => {
    if (sync.status === "error") announce("Your latest edits aren't saved. Retry is in the toolbar.");
  }, [sync.status]);
  // Made in an effect, so StrictMode's second mount (main.tsx) gets a live saver: its cleanup disposes the first.
  useEffect(() => {
    const s = new DraftSync({
      revision: workflow.draft_revision,
      unpublished: workflow.unpublished_changes,
      savedHash: workflow.draft_graph_hash,
      activeNumber: workflow.active_version_number,
      onChange: setSyncState,
      onSettled: () => void validate.current(),
      save: async (next, revision) => {
        try {
          return await ok(
            client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", {
              params: { path: { tenant_id: tenantId, workflow_id: workflow.id }, header: { "If-Match": String(revision) } },
              body: next,
            }),
          );
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) throw new ConflictError();
          throw e;
        }
      },
    });
    saver.current = s;
    return () => s.dispose();
  }, [tenantId, workflow]);
  const [held, setHeld] = useState(false); // an exit was agreed to: no edit until it completes or is withdrawn
  const [viewing, setViewing] = useState<VersionDetail | null>(null); // a version on the canvas, read only
  const [busy, setBusy] = useState<"publishing" | "activating" | null>(null);
  // Nothing changes under a version view, a publication, an activation or an exit.
  const editable = canEdit(role) && sync.status !== "conflict" && !held && viewing === null && busy === null;
  // Every change asks at the moment it would land, not only when its control opened (the owner's review of 6d7766e):
  // `editable` as last drawn, an exit agreed to, and the saver's own state, which knows of a conflict before the
  // screen does.
  const editing = useRef(editable);
  editing.current = editable;
  const mayEdit = () => editing.current && !agreed.current && saver.current?.current.status !== "conflict";
  const shownDoc = viewing ? asGraph(viewing.graph) : doc;
  const downloadMine = () => downloadJson(fileName(workflow.name, ".draft.json"), doc);

  // Leaving is one transaction (4b ruling 22; the owner's review of revision 3). Its one decision: save what's
  // pending; when that can't be done (a failed save, a conflict), ask the person. The router's blocker awaits it for
  // every navigation (the breadcrumb, the rail, the palette, the tenant switcher); sign-out and an ended session ask
  // it through `leaving`. Exits that overlap share the decision in flight, so one answer settles every one of them.
  // Once an exit is agreed to, the document is held (`agreed`, `held`) until the exit completes (the editor unmounts)
  // or is withdrawn (`stayed`: a sign-out that failed): no edit can land after the consent and be discarded under it,
  // and the navigation that follows sign-out doesn't ask again. Every exit that joins a decision holds the document
  // in its own right (`holders`): one withdrawn gives it back only when no other still holds it (the owner's review of
  // 315e19f: a router exit sent back here must not release a sign-out that joined it).
  const [leaveQuestion, setLeaveQuestion] = useState<((leave: boolean) => void) | null>(null);
  const deciding = useRef<Promise<boolean> | null>(null);
  const agreed = useRef(false);
  const holders = useRef(new Set<"router" | "guard">()); // the exits the consent stands for
  const joined = useRef(new Set<"router" | "guard">()); // the exits waiting on the decision in flight
  const decide = useRef<(by: "router" | "guard") => Promise<boolean>>(() => Promise.resolve(true));
  decide.current = (by) => {
    joined.current.add(by); // recorded before it shares the decision, whichever exit came first
    if (deciding.current) return deciding.current;
    const ask = () => new Promise<boolean>((resolve) => setLeaveQuestion(() => resolve));
    const run = (async () => {
      // Settling and saving are one transaction (ruling 18; the review of revision 2): what's typed but not applied
      // goes in where it can, then the save is awaited; anything typed meanwhile goes round again. The person is asked
      // when an edit can't be applied or the save fails. Nothing is left unasked when this answers "leave".
      for (;;) {
        if (agreed.current) return true;
        if (settleAll().length > 0) return ask();
        const s = saver.current;
        if (!s?.unsaved) return true; // settled just now, synchronously: nothing typed since
        if (!(await s.flush().then(() => true, () => false))) return ask();
      }
    })().then((leave) => {
      deciding.current = null;
      const exits = [...joined.current];
      joined.current = new Set();
      if (leave) {
        for (const exit of exits) holders.current.add(exit);
        agreed.current = true;
        setHeld(true);
      }
      return leave;
    });
    deciding.current = run;
    return run;
  };
  /** An exit that didn't happen gives up its own hold; the document is the person's again once none holds it. */
  function withdraw(exit: "router" | "guard") {
    holders.current.delete(exit);
    if (holders.current.size > 0) return;
    agreed.current = false;
    setHeld(false);
  }
  useEffect(
    () =>
      guardLeaving({
        unsaved: () => (saver.current?.unsaved ?? false) || unappliedRef.current.size > 0,
        decide: () => decide.current("guard"),
        stayed: () => withdraw("guard"), // the sign-out it agreed to failed
      }),
    [],
  );
  // Only a navigation away from this editor is an exit: one that keeps it (a hash, a query) asks nothing and holds
  // nothing (the owner's review of 6d7766e). A router exit agreed to that never completes (its destination sends the
  // person back here) gives the document back once the router settles here again; a sign-out's hold is released only
  // by its own `stayed`.
  // "This editor" is its route and its params, never the path's spelling (a trailing slash, an encoding: the final
  // checkpoint's second review).
  const own = useMatch({ strict: false });
  const home = useRef({ routeId: own.routeId, params: own.params });
  const isHome = (routeId: string, params: Record<string, unknown>) =>
    routeId === home.current.routeId && Object.entries(home.current.params).every(([k, v]) => params[k] === v);
  const router = useRouter();
  useBlocker({
    shouldBlockFn: async ({ next }) => !isHome(next.routeId, next.params as Record<string, unknown>) && !(await decide.current("router")),
    enableBeforeUnload: () => (saver.current?.unsaved ?? false) || unappliedRef.current.size > 0,
  });
  useEffect(
    () =>
      router.subscribe("onResolved", () => {
        const at = router.state.matches.at(-1);
        if (!holders.current.has("router") || !at || !isHome(at.routeId, at.params)) return;
        withdraw("router");
      }),
    [router],
  );
  const answer = (leave: boolean) => {
    leaveQuestion?.(leave);
    setLeaveQuestion(null);
  };
  const [reloading, setReloading] = useState(false);
  const [focusId, setFocusId] = useState<string>(START);
  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item
  const [picker, setPicker] = useState<PickMode | null>(null);
  // Steps by identity (`idKey`, `findNode`): an item names a step's canonical id, the document its authored one.
  const keyOf = (id: string) => findNode(doc, id)?.key ?? "a step";

  const portMap = useMemo(
    () => new Map(nodesOf(shownDoc).map((n) => [idKey(n.id), portsOf(n, typeMap.get(n.type))])),
    [shownDoc, typeMap],
  );
  const nav = useMemo(
    () => navModel(shownDoc, (id) => portMap.get(idKey(id)) ?? [], editable),
    [shownDoc, portMap, editable],
  );
  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card
  const [connecting, setConnecting] = useState<PortRef | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  // What's typed in the drawer but not in the draft (ruling 18): the editor's, never a control's, so a tab, a toggle
  // or a closed drawer keeps it. The ref is the record, written at once, so a decision made between renders (an exit
  // awaiting a save, Task 8) reads every keystroke; the state draws it.
  const unappliedRef = useRef<ReadonlyMap<string, Unapplied>>(new Map());
  const [unapplied, setUnapplied] = useState(unappliedRef.current);
  const setRecord = (next: ReadonlyMap<string, Unapplied>) => {
    unappliedRef.current = next;
    setUnapplied(next);
  };
  const keep = (u: Unapplied) => setRecord(new Map(unappliedRef.current).set(u.id, u));
  const drop = (ids: string[]) => {
    if (!ids.some((id) => unappliedRef.current.has(id))) return;
    const next = new Map(unappliedRef.current);
    for (const id of ids) next.delete(id);
    setRecord(next);
  };
  // A rename's word on formulas, in its step's drawer while the draft is the one it made (ruling 11; the review of
  // 66fc658: kept when the rename is applied with the rest, and said in no other step's drawer).
  const [renamed, setRenamed] = useState<{ doc: GraphDoc; node: string; text: string } | null>(null);
  const typeOf = (n: GraphNode) => typeMap.get(n.type);
  const [side, setSide] = useState<Side>(null); // the right column's one panel
  // Where focus lands when what held it goes: a panel's Close, or a confirmation whose button an action removed or
  // disabled (the final checkpoint's review, WCAG 2.4.3). A native dialog returns focus to its opener only while that
  // opener can take it, and a modal one keeps it from anything else until it closes: the editor places it, after.
  const problemsButton = useRef<HTMLButtonElement>(null);
  const versionsButton = useRef<HTMLButtonElement>(null);
  const publishButton = useRef<HTMLButtonElement>(null);
  const unappliedButton = useRef<HTMLButtonElement>(null);
  const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
  const [landing, setLanding] = useState<{
    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel";
    n: number;
  } | null>(null);
  const land = (on: NonNullable<typeof landing>["on"]) => setLanding((l) => ({ on, n: (l?.n ?? 0) + 1 }));
  useEffect(() => {
    if (!landing) return;
    const frame = requestAnimationFrame(() => {
      const usable = (el: HTMLElement | null | undefined) => (el && !(el as HTMLButtonElement).disabled ? el : null);
      const target = {
        problems: () => usable(problemsButton.current),
        versions: () => usable(versionsButton.current),
        publish: () => usable(publishButton.current) ?? usable(versionsButton.current),
        "problems-panel": () => document.getElementById("problems-title") ?? usable(problemsButton.current),
        "versions-panel": () => document.getElementById("versions-title") ?? usable(versionsButton.current),
        unapplied: () => usable(unappliedButton.current),
        "unapplied-panel": () => document.getElementById("unapplied-title") ?? usable(unappliedButton.current),
      }[landing.on]();
      target?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [landing]);
  const panel = side?.kind === "step" ? side.node : null; // the step whose panel is open
  // An editor checks on opening: its first frame already says so, never "Not checked" for an instant.
  const [check, setCheck] = useState<Check>(() => (canEdit(role) ? { status: "checking", last: null } : { status: "unchecked" }));
  const [publishProblems, setPublishProblems] = useState<PublishProblems | null>(null);
  const asked = useRef(0); // the newest check asked for: an older one's answer or failure says nothing

  /** Check the saved draft (validate needs workflow.edit). Its answer names the revision it checked. */
  const validate = useRef(async () => {});
  validate.current = async () => {
    if (!canEdit(role)) return;
    const n = ++asked.current;
    setCheck((c) => ({ status: "checking", last: lastOf(c) }));
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/validate", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
        }),
      );
      if (n === asked.current) setCheck({ status: "done", last: answer });
    } catch {
      if (n === asked.current) setCheck((c) => ({ status: "failed", last: lastOf(c) }));
    }
  };
  useEffect(() => void validate.current(), []);

  const checked = checkState(check, sync);
  const last = lastOf(check);
  const trusted = checked === "current" ? last : null; // badges and the step panel's problems: current only
  // What only publish found is current only for the snapshot it was found in: the same saved revision, and no edit
  // since (a pending edit leaves the revision as it was, never the generation).
  const publishCurrent =
    publishProblems !== null && publishProblems.revision === sync.revision &&
    publishProblems.generation === sync.generation && sync.generation === sync.savedGeneration;  // prettier-ignore
  const published = publishCurrent && publishProblems ? publishProblems.diagnostics : NO_DIAGNOSTICS;
  // Keyed by the step's identity (`idKey`): the server names steps by their canonical ids, the draft as authored.
  const problems = useMemo(() => {
    const counts = new Map<string, Problems>();
    for (const d of [...(trusted?.diagnostics ?? []), ...published]) {
      if (!d.node) continue;
      const c = counts.get(idKey(d.node)) ?? { errors: 0, warnings: 0 };
      counts.set(idKey(d.node), d.severity === "error" ? { ...c, errors: c.errors + 1 } : { ...c, warnings: c.warnings + 1 });
    }
    return counts;
  }, [trusted, published]);
  const separate = useMemo(() => {
    const counts = new Map<string, number>();
    for (const x of trusted?.expressions ?? []) {
      if (x.node && x.mode === "activity") counts.set(idKey(x.node), (counts.get(idKey(x.node)) ?? 0) + 1);
    }
    return counts;
  }, [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
  const [placing, setPlacing] = useState<string | null>(null); // the step the next click on the canvas puts there
  const qc = useQueryClient();
  const versions = useQuery(versionsQuery(tenantId, workflow.id));
  // The newest version's number: what a publish expects (4b ruling 17). Unknown while the list loads or refreshes.
  const latest = versions.isSuccess && !versions.isFetching ? (versions.data[0]?.number ?? 0) : null; // newest first
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const viewAsked = useRef(0); // the newest version view asked for
  const publisher = canPublish(role) && sync.status !== "conflict";
  // When editing stops (a conflict, an exit, a publication), what only editing offers stops with it: an open dialog
  // closes, placing ends (a click on a read-only canvas places nothing) and says so. Focus held by what's gone (the
  // dialog, a "+", Auto layout, Add step, a panel's buttons) goes to what's drawn: a panel's heading when it was in
  // the panel, else the canvas item it was on, or, for a "+", its step (the final checkpoint's second review).
  const root = useRef<HTMLDivElement>(null);
  const lastFocus = useRef<{ inPanel: boolean } | null>(null);
  const wasEditable = useRef(editable);
  useEffect(() => {
    if (wasEditable.current === editable) return;
    wasEditable.current = editable;
    if (editable) return;
    const dialog = picker !== null || connecting !== null || asking !== null;
    setPicker(null);
    setConnecting(null);
    setAsking(null);
    if (placing !== null) {
      setPlacing(null);
      announce("Not placed: the draft can't be changed now");
    }
    const back = nearestDrawn(focusId);
    if (dialog) return focus(back);
    requestAnimationFrame(() => {
      const active = document.activeElement;
      if (lastFocus.current === null || (active && active !== document.body && root.current?.contains(active))) return;
      const heading = lastFocus.current.inPanel ? root.current?.querySelector<HTMLElement>("aside h2[tabindex='-1']") : null;
      if (heading) heading.focus();
      else focus(back);
    });
  }, [editable]); // once, as editing stops: the state of the render it stopped in
  const path = { params: { path: { tenant_id: tenantId, workflow_id: workflow.id } } };
  const readWorkflow = () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}", path));
  const readVersions = () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions", path));

  /** The lists that show versions: refreshed after a change, their failure changing no outcome. */
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
    return qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] }).catch(() => undefined);
  };

  function publishedAs(number: number, revision: number) {
    saver.current?.published(revision, number);
    setPublishProblems(null);
    announce(`Published version ${number}`);
    return refresh();
  }

  async function publish(expected: number) {
    setBusy("publishing");
    setNotice(null);
    let revision: number;
    let hash: string | null; // the server's hash of the draft submitted: how a version is known to hold it
    let generation: number;
    try {
      revision = await saver.current!.flush();
      ({ savedHash: hash, savedGeneration: generation } = saver.current!.current);
    } catch (e) {
      setBusy(null);
      setConfirm(null);
      if (!(e instanceof ConflictError)) setNotice({ tone: "danger", text: "Not published: your latest edits aren't saved. Retry the save, then publish." });
      return; // a conflict has its own banner
    }
    let next: Confirm | null = null;
    let landOn: "publish" | "problems-panel" = "publish";
    try {
      const done = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id }, header: { "If-Match": String(revision) } },
          body: { expected_latest_version: expected },
        }),
      );
      await publishedAs(done.number, revision); // the dialog holds until Publish names the next number again
    } catch (e) {
      if (e instanceof ApiError && e.code === "version_changed") {
        // Someone (or an attempt whose answer was lost) published meanwhile: ask again, naming the new number.
        await qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] });
        const latestNow = (e.body as { latest_version: number }).latest_version;
        next = { kind: "publish", expected: latestNow, elsewhere: true };
        announce(`Version ${latestNow} was published meanwhile. Confirm to publish version ${latestNow + 1}`);
      } else if (e instanceof ApiError && e.code === "draft_conflict") {
        saver.current?.conflict();
      } else if (e instanceof ApiError && e.code === "invalid") {
        const diagnostics = (e.body as { diagnostics: Diagnostic[] }).diagnostics;
        setPublishProblems({ revision, generation, diagnostics }); // the snapshot they were found in
        setSide({ kind: "problems" });
        landOn = "problems-panel";
        announce(`Not published: ${diagnostics.filter((d) => d.severity === "error").length} problems`);
      } else if (uncertain(e)) {
        await reconcilePublish(expected + 1, hash);
      } else {
        setNotice({ tone: "danger", text: "Not published: the server refused it. Try again." });
      }
    } finally {
      setBusy(null);
      setConfirm(next);
      if (next === null) land(landOn);
    }
  }

  /** A publish without an answer (4b ruling 25, its proof amended by the owner's review of revision 2). Only a
   * publish expecting the version before could have made version `number`, and a version records its graph's hash:
   * it holds this draft only if that hash is the one the server gave for the draft submitted. The active version and
   * the draft's comparison come from the read, never from the number hoped for. */
  async function reconcilePublish(number: number, hash: string | null) {
    // Each read stands on its own: the workflow's says which version is active, the versions' what this publish did.
    const [listedRead, nowRead] = await Promise.allSettled([readVersions(), readWorkflow()]);
    if (nowRead.status === "fulfilled") saver.current?.compared(nowRead.value);
    else saver.current?.lostTrack();
    if (listedRead.status === "rejected") {
      setNotice({ tone: "danger", text: `It isn't known whether version ${number} was published: its answer was lost. Open Versions to see before publishing again.` });
    } else {
      const made = listedRead.value.find((v) => v.number === number);
      if (made && hash !== null && made.graph_hash === hash) {
        setPublishProblems(null);
        // A matching hash says the version holds the graph submitted, never which request made it (the owner's review
        // of milestone 1).
        setNotice({ tone: "info", text: `Version ${number} holds the submitted graph. Your publish request's outcome wasn't received.` });
      } else if (made && hash !== null) {
        // Someone else's publication made version `number`: this one, expecting the one before, was refused.
        setNotice({ tone: "danger", text: `Version ${number} holds another draft: yours wasn't published. Open Versions before publishing again.` });
      } else if (made) {
        // No hash for the draft submitted (one that doesn't parse): nothing proves either way (the owner's review).
        setNotice({ tone: "danger", text: `Version ${number} exists, and it isn't known whether it holds your draft. Open Versions to see before publishing again.` });
      } else {
        setNotice({
          tone: "danger",
          text: `Version ${number} isn't published, as far as the server can tell now. If the first attempt is still finishing it may appear: open Versions before publishing again.`,
        });
      }
    }
    void refresh();
  }

  /** Made active: so it stays, whatever a read after it fails to say. The draft's comparison with it is the server's,
   * from `now` when a read already has it, else read here, and not claimed until then. */
  async function activatedAs(version: VersionRow, now?: WorkflowDetail) {
    saver.current?.activated(version.number);
    announce(`Version ${version.number} is active`);
    void refresh();
    try {
      saver.current?.compared(now ?? (await readWorkflow()));
    } catch {
      setNotice({ tone: "info", text: `Version ${version.number} is active. Whether your draft differs from it couldn't be checked: reload the page to see.` });
    }
  }

  async function activate(version: VersionRow) {
    setBusy("activating");
    setNotice(null);
    // No save may answer after the activation with the version it compared against before it (the revision's review):
    // what's pending or in flight settles first. A save that fails keeps its own state; the activation doesn't need it.
    await saver.current?.flush().catch(() => undefined);
    try {
      await ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/activate", { ...path, body: { version_id: version.id } }));
      await activatedAs(version);
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_activatable") {
        const first = (e.body as { diagnostics?: Diagnostic[] }).diagnostics?.[0]?.message;
        setNotice({ tone: "danger", text: `Version ${version.number} can't be made active${first ? `: ${first}` : "."}` });
      } else if (uncertain(e)) {
        await reconcileActivate(version);
      } else {
        setNotice({ tone: "danger", text: `Version ${version.number} wasn't made active: the server refused it.` });
      }
    } finally {
      setBusy(null);
      setConfirm(null);
      land("versions-panel"); // its Make active is gone: the version is active, or the panel held it while it ran
    }
  }

  async function reconcileActivate(version: VersionRow) {
    try {
      const now = await readWorkflow();
      if (now.active_version_id === version.id) return await activatedAs(version, now);
      saver.current?.compared(now);
      setNotice({ tone: "danger", text: `Version ${version.number} isn't active, as far as the server can tell now. Open Versions before trying again.` });
    } catch {
      saver.current?.lostTrack();
      setNotice({ tone: "danger", text: `It isn't known whether version ${version.number} was made active: its answer was lost. Open Versions to see.` });
    }
    void refresh();
  }

  async function view(version: VersionRow) {
    const asked = ++viewAsked.current;
    try {
      const opened = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id, version_id: version.id } },
        }),
      );
      if (asked !== viewAsked.current) return; // a newer view, or Back to the draft, came since
      // What was typed while the version was read is applied now, or asked about: a version view never carries the
      // draft's edits not applied, and never drops them unasked (the review of milestone 2).
      whenSettled("view the version", () => {
        if (asked !== viewAsked.current) return; // Back to the draft, or a newer view, while the person decided
        setViewing(opened);
        setSide(null);
        setPlacing(null);
        focus(START);
        announce(`Viewing version ${opened.number}, read only`);
      });
    } catch {
      if (asked === viewAsked.current) setNotice({ tone: "danger", text: `Version ${version.number} couldn't be opened. Try again.` });
    }
  }

  function backToDraft() {
    viewAsked.current++;
    setViewing(null);
    focus(START);
  }

  /** The saved draft as a file (B12; 4b ruling 18). Unsaved edits stop it: the file would miss them. Settling and
   * saving are one transaction, as leaving's are: what's typed while the save is awaited is applied too, or asked about,
   * before the file is asked for (the review of milestone 2). */
  async function exportFile(savedOnly = false) {
    setNotice(null);
    while (!savedOnly) {
      const left = settleAll();
      if (left.length > 0) {
        setAsking({ kind: "unapplied", action: "export", left, then: () => void exportFile() });
        return;
      }
      const s = saver.current!;
      if (!s.unsaved) break; // settled just now, synchronously: nothing typed since
      try {
        await s.flush();
      } catch {
        setNotice({
          tone: "danger",
          text: "Not exported: your latest edits aren't saved, so the file would miss them.",
          action: { label: "Export the last saved draft", run: () => void exportFile(true) },
        });
        return;
      }
    }
    try {
      downloadJson(fileName(workflow.name, ".dewpoint.json"), await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/export", path)));
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_portable") {
        setNotice({
          tone: "danger",
          text: `Not exported: ${notPortable((e.body as { problems: PortableProblem[] }).problems, keyOf)}, so it can't be exported as a portable file.`,
          action: { label: "Download this draft as it is (not portable)", run: () => downloadJson(fileName(workflow.name, ".draft.json"), doc) },
        });
        return;
      }
      setNotice({ tone: "danger", text: "The workflow couldn't be exported. Try again." });
    }
  }

  /** Where `id` falls back to when it isn't drawn (a "+" on a read-only canvas): the step it belongs to (an edge's or a
   * port's source, the step an entry "+" stands before), else the start card. */
  function nearestDrawn(id: string): string {
    if (nav.order.includes(id)) return id;
    const at = id.indexOf(":");
    const kind = id.slice(0, at);
    const node = kind === "edge" || kind === "port" ? id.slice(at + 1).split(":")[0] : kind === "entry" ? id.slice(at + 1) : null;
    const step = node ? item.node(node) : null;
    return step !== null && nav.order.includes(step) ? step : START;
  }

  function focus(id: string, path: string[] | null = null) {
    setFocusId(id);
    setTrail(path);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }

  /** One edit: recorded (edits sharing a field's mark are one undo step, ruling 8), saved, and said, unless `message`
   * is null: a field's edits aren't announced, its control says what it holds. Whether it landed. */
  function change(next: GraphDoc, message: string | null, then?: string, mark?: string): boolean {
    if (!mayEdit()) return false; // read only now: a conflict, an exit agreed to, a version view, a publication
    commitHistory(record(historyNow.current, next, mark));
    saver.current?.change(next);
    if (message !== null) announce(message);
    if (then) focus(then);
    return true;
  }

  /** A drawer's change to the draft. Refused when the graph's format would refuse it (ruling 7); asked first when it
   * takes ports away (ruling 9); else recorded, and the unapplied edits it carries released. Why it wasn't made, or
   * null (made, or asked). */
  function writeDraft(changed: Changed, how: { mark?: string; release?: string[]; said?: string | null } = {}): string | null {
    const refused = admission(changed.doc);
    if (refused !== null) return refused;
    if (changed.dropped.length > 0) {
      setAsking({ kind: "ports", next: changed.doc, dropped: changed.dropped, release: how.release ?? [] });
      return null;
    }
    if (!change(changed.doc, how.said ?? null, undefined, how.mark)) return CANT;
    drop(how.release ?? []);
    return null;
  }

  /** One unapplied edit applied now (focus left its control, Enter): why it stays unapplied, or null. A name moves its
   * entry, so what's typed inside the entry is applied with it, first, or the name waits (the review of revision 2). */
  function applyEdit(id: string): string | null {
    const u = unappliedRef.current.get(id);
    if (!u) return null;
    if (u.kind === "name") return restructureStep(u.node, u.pointer);
    const now = draftNow();
    const node = findNode(now, u.node);
    const result = applyUnapplied(now, u, node ? typeOf(node) : undefined);
    // Asked before it takes ports away: until the answer, and after a Cancel, its control says why (ruling 9).
    const why =
      "problem" in result ? result.problem
      : result.dropped.length > 0 ? (writeDraft(result, { release: [id] }) ?? droppedWhy(result.dropped, result.doc))
      : writeDraft(result, { release: [id], said: result.said });  // prettier-ignore
    if (why !== null) keep({ ...u, why });
    else if (!("problem" in result) && result.note !== null) setRenamed({ doc: result.doc, node: u.node, text: result.note });
    return why;
  }

  /** The unapplied edits at `pointer` and below in a step applied; then, with `then`, what `make` makes of the value
   * at `path` written: one undo step (ruling 18). An edit that can't be applied stops it, said at its control. */
  function restructureStep(nodeId: string, pointer: string, then?: { path: Path; make: (current: unknown) => unknown }): string | null {
    const now = draftNow();
    const { doc: settled, applied, left } = applyAll(now, unappliedRef.current.values(), typeOf, within(nodeId, pointer));
    for (const u of left) keep(u);
    if (left.length > 0) return left[0]!.why;
    let changed: Changed = { doc: settled, dropped: [] };
    const node = findNode(settled, nodeId);
    if (then && node) {
      const current = valueAt(node.config ?? {}, then.path);
      const made = then.make(current);
      if (made !== current) changed = setConfig(settled, nodeId, then.path, made, typeOf(node));
    }
    if (changed.doc === now) return null;
    return writeDraft(changed, { release: applied.map((u) => u.id) });
  }

  /** What the open step's drawer may do. Every write goes through `change`, so through 4b's guards (`mayEdit`). */
  function actionsFor(nodeId: string): DrawerActions {
    const id = (kind: UnappliedKind, pointer: string) => unappliedId(nodeId, kind, pointer);
    const stepType = () => {
      const node = findNode(draftNow(), nodeId);
      return node ? typeOf(node) : undefined;
    };
    return {
      set: (path, value, mark) => writeDraft(setConfig(draftNow(), nodeId, path, value, stepType()), { mark }),
      options: (options, mark) => writeDraft(setOptions(draftNow(), nodeId, options, stepType()), { mark }),
      held: (kind, pointer) => unapplied.get(id(kind, pointer)),
      hold: (kind, pointer, holding) => {
        // What it's typed over is recorded when the edit begins, and kept while it's typed (ruling 18).
        const was = unappliedRef.current.get(id(kind, pointer));
        const u: Unapplied = { ...holding, id: id(kind, pointer), node: nodeId, kind, pointer, base: "", lineage: [] };
        keep({ ...u, base: was?.base ?? baseOf(draftNow(), u), lineage: was?.lineage ?? lineageOf(draftNow(), u) });
      },
      release: (kind, pointer) => drop([id(kind, pointer)]),
      discard: (pointer) => drop([...unappliedRef.current.values()].filter(within(nodeId, pointer)).map((u) => u.id)),
      apply: (kind, pointer) => applyEdit(id(kind, pointer)),
      stale: (kind, pointer) => {
        const u = unappliedRef.current.get(id(kind, pointer));
        return u !== undefined && isStale(draftNow(), u);
      },
      rebase: (kind, pointer) => {
        const u = unappliedRef.current.get(id(kind, pointer));
        if (u) keep({ ...u, base: baseOf(draftNow(), u), lineage: lineageOf(draftNow(), u), why: null });
      },
      restructure: (pointer, then) => restructureStep(nodeId, pointer, then),
    };
  }

  /** Every unapplied edit that can be applied, applied as one undo step; those that can't, returned with their reasons
   * (ruling 18). */
  function settleAll(): Unapplied[] {
    const all = [...unappliedRef.current.values()];
    // The latest document, not the render's: after a save was awaited, this render's `doc` is older (the review of
    // revision 3).
    const { doc: next, applied, left, note } = applyAll(draftNow(), all, typeOf, () => true);
    for (const u of left) keep(u);
    if (applied.length === 0) return left;
    if (!change(next, applied.length === 1 ? "Applied an edit" : `Applied ${applied.length} edits`)) return all;
    drop(applied.map((u) => u.id));
    if (note !== null) setRenamed({ doc: next, ...note });
    return left;
  }

  /** `then`, once every unapplied edit is in the draft; when one can't be, the person decides first (ruling 18). */
  function whenSettled(action: string, then: () => void) {
    const left = settleAll();
    if (left.length === 0) then();
    else setAsking({ kind: "unapplied", action, left, then });
  }

  /** Back to the edits not applied: their list, where each can be read, gone to or discarded, its field gone or not. */
  function goBack() {
    setSide({ kind: "unapplied" });
  }

  const describe = (u: Unapplied) => `${keyOf(u.node)} · ${u.label}: ${u.why ?? "still being typed"}`;

  /** The edits not applied, as a file of their own: never written into the graph to keep them, as the graph is what
   * runs (ruling 18; the review of revision 2). */
  const downloadUnapplied = () =>
    downloadJson(fileName(workflow.name, ".unapplied.json"), unappliedFile([...unappliedRef.current.values()], keyOf));
  /** Said beside every "Download my version": that file is the draft, and the edits not applied aren't in it. */
  const notInMine = (n: number) =>
    n === 0 ? "" : `Your version's file doesn't hold the ${n === 1 ? "1 edit" : `${n} edits`} not applied: download ${n === 1 ? "it" : "them"} separately.`;
  const downloadLabel = (n: number) => (n === 1 ? "Download the edit not applied" : "Download the edits not applied");

  const firstPort = (nodeId: string): PortRef | null => {
    const port = portMap.get(idKey(nodeId))?.[0];
    return port ? { node: nodeId, port } : null;
  };

  /** `A`, the toolbar's Add step, and Enter on a "+": the picker for the focused item. */
  function addFrom(id: string) {
    if (id === START || id === item.port(START, "out")) return setPicker({ kind: "after", from: null });
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setPicker({ kind: "after", from });
      else announce(`${keyOf(id.slice(5))} ends its branch: there's no port to add after`);
      return;
    }
    if (id.startsWith("entry:")) return setPicker({ kind: "before", entry: id.slice(6) });
    if (id.startsWith("edge:")) return setPicker({ kind: "insert", edge: nav.edges.get(id)! });
    if (id.startsWith("port:")) {
      const [, node, port] = id.split(":");
      setPicker({ kind: "after", from: { node: node!, port: port! } });
    }
  }

  function connectFrom(id: string) {
    if (id.startsWith("port:") && !id.startsWith(`port:${START}:`)) {
      const [, node, port] = id.split(":");
      return setConnecting({ node: node!, port: port! });
    }
    if (id.startsWith("edge:")) return setConnecting(nav.edges.get(id)!.from as PortRef);
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setConnecting(from);
    }
  }

  function askDelete(id: string) {
    if (id.startsWith("node:")) setAsking({ kind: "node", id: id.slice(5) });
    if (id.startsWith("edge:")) setAsking({ kind: "edge", edge: nav.edges.get(id)! });
  }

  function confirmDelete() {
    if (!asking) return;
    if (asking.kind === "unapplied") {
      drop(asking.left.map((u) => u.id)); // discarded, on purpose
      setAsking(null);
      asking.then();
      return;
    }
    if (asking.kind === "ports") {
      const ports = [...new Set(asking.dropped.map(portOf))].join(", ");
      const edges = asking.dropped.length === 1 ? "its edge" : `${asking.dropped.length} edges`;
      if (change(asking.next, `Removed ${ports} and ${edges}`)) drop(asking.release);
      setAsking(null);
      // What asked is gone with its port (a Remove, a JSON edit): focus lands on the drawer, after the dialog has
      // given it back (WCAG 2.4.3).
      requestAnimationFrame(() => document.getElementById("step-drawer-title")?.focus());
      return;
    }
    if (asking.kind === "node") {
      const { doc: next, healed } = deleteNode(doc, asking.id);
      // Focus goes to the step it came after (its own items are gone with it), or to the start card.
      const inbound = edgesOf(doc).find((e) => sameId(e.to.node, asking.id));
      const back = inbound ? item.node(inbound.from.node) : START;
      if (panel !== null && sameId(panel, asking.id)) setSide(null);
      drop([...unappliedRef.current.values()].filter(within(asking.id, "")).map((u) => u.id));
      change(next, `Deleted ${keyOf(asking.id)}${healed ? `; ${keyOf(healed.from.node)} now leads to ${keyOf(healed.to.node)}` : ""}`, back);
    } else {
      change(deleteEdge(doc, asking.edge), `Deleted the edge from ${keyOf(asking.edge.from.node)} to ${keyOf(asking.edge.to.node)}`, item.node(asking.edge.from.node));
    }
    setAsking(null);
  }

  function nudge(nodeId: string, key: NavKey) {
    const n = findNode(doc, nodeId);
    if (!n) return;
    const d = { ArrowUp: [0, -20], ArrowDown: [0, 20], ArrowLeft: [-20, 0], ArrowRight: [20, 0], Home: [0, 0] }[key];
    change(moveNodes(doc, new Map([[nodeId, { x: (n.position?.x ?? 0) + d[0]!, y: (n.position?.y ?? 0) + d[1]! }]])), `Moved ${n.key}`);
  }

  /** The click that ends "Place on the canvas…": the step, centred on it (WCAG 2.5.7). Never on a read-only canvas. */
  function place(at: { x: number; y: number }) {
    if (!placing || !editable) return;
    const id = placing;
    setPlacing(null);
    change(moveNodes(doc, new Map([[id, { x: at.x - CARD.width / 2, y: at.y - CARD.height / 2 }]])), `Placed ${keyOf(id)}`, item.node(id));
  }

  /** Escape stops placing first, before it closes a panel or a picker. */
  function onEditorKeyCapture(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Escape" || !placing) return;
    e.stopPropagation();
    e.preventDefault();
    setPlacing(null);
    announce("Not placed");
  }

  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.target as HTMLElement).dataset.item || e.altKey) return;
    // From the item focus is meant to be on: a key moves focus a frame later (the canvas draws it first), and a key
    // pressed before then (auto-repeat, a quick hand) starts where the last one left it, not where the browser's
    // focus still is.
    const id = shown;
    const plain = !e.ctrlKey && !e.metaKey;
    if (NAV_KEYS.includes(e.key) && plain) {
      e.preventDefault();
      if (e.shiftKey && editable && id.startsWith("node:")) return nudge(id.slice(5), e.key as NavKey);
      // The path the keys came by while it still holds (at a join, the branch taken); else the walk's own path.
      const path = trail && trail.at(-1) === id && isPath(nav, trail) ? trail : pathTo(nav, id);
      const next = step(nav, path, e.key as NavKey);
      if (next.at(-1) !== id) focus(next.at(-1)!, next);
      return;
    }
    if (!editable || !plain) return;
    if (e.key === "a" || e.key === "A") {
      e.preventDefault();
      addFrom(id);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      askDelete(id);
    } else if (e.key === "c" || e.key === "C") {
      e.preventDefault();
      connectFrom(id);
    }
  }

  /** Ctrl or Cmd+Z undoes, with Shift redoes (D17: local). Not while typing, nor behind a dialog. Focus stays in the
   * editor: on the focused item while it survives, else on its nearest surviving item back along the path the keys
   * would take to it, else on the start card (the owner's review of M3). */
  function onEditorKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || !editable) return;
    const t = e.target as HTMLElement;
    if (t.closest("input, textarea, select, dialog")) return;
    e.preventDefault();
    if (!mayEdit()) return;
    const next = e.shiftKey ? redo(historyNow.current) : undo(historyNow.current);
    if (next === historyNow.current) return;
    commitHistory(next);
    saver.current?.change(next.present);
    announce(e.shiftKey ? "Redone" : "Undone");
    const after = next.present;
    const nextNav = navModel(after, (id) => {
      const n = findNode(after, id);
      return n ? portsOf(n, typeMap.get(n.type)) : [];
    }, editable);  // prettier-ignore
    const panelGone = panel !== null && !findNode(after, panel);
    if (panelGone) setSide(null);
    // What had focus: a canvas item; the open panel (left there while its step survives); or something else in the
    // editor (left where it is).
    const inPanel = panel !== null && !t.dataset.item && t.closest("aside") !== null;
    if (inPanel && !panelGone) return;
    const held = inPanel ? item.node(panel) : (t.dataset.item ?? null);
    if (held === null) return;
    // A surviving item keeps its element and its focus: asking again would steal it back a frame later from
    // wherever the person has since moved it.
    if (nextNav.order.includes(held)) return;
    const back = (trail && trail.at(-1) === held ? trail : pathTo(nav, held)).slice(0, -1).reverse();
    focus(back.find((id) => nextNav.order.includes(id)) ?? START);
  }

  function onItem(action: ItemAction) {
    if (action.kind === "open") return setSide({ kind: "step", node: action.node });
    if (!editable) return;
    if (action.kind === "after") setPicker({ kind: "after", from: action.from });
    if (action.kind === "insert") setPicker({ kind: "insert", edge: action.edge });
    if (action.kind === "before") setPicker({ kind: "before", entry: action.entry });
  }

  function onPick(type: NodeType) {
    if (!picker) return;
    const made =
      picker.kind === "after" ? addAfter(doc, picker.from, type)
      : picker.kind === "insert" ? insertOnEdge(doc, picker.edge, type)
      : insertBeforeEntry(doc, picker.entry, type);  // prettier-ignore
    if (!made) return;
    const where =
      picker.kind === "after" ? (picker.from ? `after ${keyOf(picker.from.node)}` : "at the start")
      : picker.kind === "insert" ? `between ${keyOf(picker.edge.from.node)} and ${keyOf(picker.edge.to.node)}`
      : `before ${keyOf(picker.entry)}`;  // prettier-ignore
    change(made.doc, `Added ${made.node.key} ${where}`, item.node(made.node.id));
  }

  function onConnect(from: PortRef, to: string) {
    const next = connect(doc, from, to);
    if (next) change(next, `Connected ${keyOf(from.node)} to ${keyOf(to)}`, item.edge({ from, to: { node: to } }));
    else announce(`${keyOf(from.node)} can't lead to ${keyOf(to)}: that would repeat an edge or close a loop`);
  }

  const healed = asking?.kind === "node" ? deleteNode(doc, asking.id).healed : null;
  const open = panel ? findNode(shownDoc, panel) : undefined; // the step of what's on the screen

  return (
    <div
      ref={root}
      className="@container flex min-h-0 flex-1 flex-col"
      onKeyDown={onEditorKey}
      onKeyDownCapture={onEditorKeyCapture}
      onFocus={(e) => (lastFocus.current = { inPanel: (e.target as HTMLElement).closest("aside") !== null })}
    >
      <Toolbar
        tenantId={tenantId}
        name={workflow.name}
        state={
          <>
            <SaveState state={sync} />
            {unapplied.size > 0 && (
              <Button ref={unappliedButton} size="md" aria-expanded={side?.kind === "unapplied"} onClick={() => setSide(side?.kind === "unapplied" ? null : { kind: "unapplied" })}>
                {unapplied.size === 1 ? "1 edit not applied" : `${unapplied.size} edits not applied`}
              </Button>
            )}
            {sync.status === "error" && (
              <Button size="md" onClick={() => saver.current?.retry()}>Retry</Button>
            )}
          </>
        }
      >
        {editable ? (
          <Button size="md" aria-keyshortcuts="A" onClick={() => addFrom(shown)}>
            ＋ Add step <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>
          </Button>
        ) : !canEdit(role) ? (
          <span className="text-small text-muted">Read only: your role can&apos;t edit workflows</span>
        ) : null}
        {canEdit(role) && viewing === null && (
          <Button
            ref={problemsButton}
            size="md"
            aria-expanded={side?.kind === "problems"}
            onClick={() => setSide(side?.kind === "problems" ? null : { kind: "problems" })}
          >
            {checkLabel(checked, count)}
          </Button>
        )}
        <Button ref={versionsButton} size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
          Versions
        </Button>
        <Button size="md" onClick={() => void exportFile()}>Export</Button>
        {publisher && viewing === null && (
          <Button
            ref={publishButton}
            variant="primary"
            size="md"
            disabled={busy !== null || latest === null}
            onClick={() => {
              if (latest !== null) whenSettled("publish", () => setConfirm({ kind: "publish", expected: latest }));
            }}
          >
            {latest === null ? "Publish" : `Publish v${latest + 1}`}
          </Button>
        )}
      </Toolbar>
      {viewing && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
          <span className="grow">Viewing version {viewing.number}, read only. The draft is unchanged.</span>
          <Button size="sm" onClick={backToDraft}>Back to the draft</Button>
        </div>
      )}
      {publisher && versions.isError && (
        <p className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-5 py-2.5 text-small text-danger">
          The versions couldn&apos;t be read, so publishing waits.
          <Button size="sm" onClick={() => void versions.refetch()}>Read them again</Button>
        </p>
      )}
      {/* A notice's live region is there before its text, so the text is said (WCAG 4.1.3); a refusal is an alert. */}
      <div
        role="status"
        aria-label="Notice"
        className={notice?.tone === "info" ? "flex flex-wrap items-center gap-3 border-b border-line bg-surface px-5 py-2.5 text-small text-ink" : undefined}
      >
        {notice?.tone === "info" && (
          <>
            <span className="grow">{notice.text}</span>
            {notice.action && <Button size="sm" onClick={notice.action.run}>{notice.action.label}</Button>}
          </>
        )}
      </div>
      {notice?.tone === "danger" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-5 py-2.5 text-small text-danger">
          <span className="grow">{notice.text}</span>
          {notice.action && <Button size="sm" onClick={notice.action.run}>{notice.action.label}</Button>}
        </div>
      )}
      <p role="status" className={trouble ? "border-b border-line bg-surface px-5 py-2.5 text-small text-muted" : undefined}>{trouble}</p>
      {sync.status === "conflict" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-danger bg-danger-bg px-5 py-2.5 text-small text-ink">
          <span className="grow">
            This draft was changed elsewhere, so your changes since then aren&apos;t saved. Reload to see the saved draft, or
            download your version to keep it.
          </span>
          {unapplied.size > 0 && (
            <>
              <span className="basis-full">{notInMine(unapplied.size)}</span>
              <Button size="sm" onClick={downloadUnapplied}>{downloadLabel(unapplied.size)}</Button>
            </>
          )}
          <Button size="sm" onClick={downloadMine}>Download my version</Button>
          <Button size="sm" variant="primary" onClick={() => setReloading(true)}>Reload</Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1 @max-3xl:flex-col">
        <div className="relative flex min-h-0 min-w-0 flex-1">
          {placing && editable && (
            // Over the canvas's top edge, never above it: the canvas doesn't move when placing starts or ends, so a
            // step placed with a click stays under the click (ledger M13).
            <div data-canvas-overlay className="absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
              <span className="grow">Click an empty place on the canvas to put {keyOf(placing)} there.</span>
              <Button size="sm" onClick={() => setPlacing(null)}>Cancel</Button>
            </div>
          )}
          <Canvas
          doc={shownDoc}
          types={typeMap}
          problems={viewing ? new Map() : problems}
          separate={viewing ? new Map() : separate}
          editable={editable}
          current={panel}
          focusId={shown}
          focusRequest={focusRequest}
          onFocusItem={(id) => {
            setFocusId(id);
            setTrail((t) => (t?.at(-1) === id ? t : null));
          }}
          onItem={onItem}
          onMove={(positions) => change(moveNodes(doc, positions), "Moved")}
          onConnect={onConnect}
          onLayout={() => change(moveNodes(doc, layout(doc)), "Laid out the steps")}
          onKeyDown={onCanvasKey}
          placing={editable && placing !== null}
          onPlace={place}
          overview={side === null}
          />
        </div>
        {open && (
          <StepDrawer
            key={idKey(open.id)}
            node={open}
            type={typeMap.get(open.type)}
            tenantId={tenantId}
            workflowId={workflow.id}
            ports={portMap.get(idKey(open.id)) ?? []}
            problems={
              viewing || !trusted ? null : [...trusted.diagnostics, ...published].filter((d) => d.node !== null && sameId(d.node, open.id))
            }
            expressions={(viewing ? viewing.expressions : (trusted?.expressions ?? [])).filter((x) => x.node !== null && sameId(x.node, open.id))}
            editable={editable}
            adds={editable ? addsOf(doc, open, portMap.get(idKey(open.id)) ?? []) : []}
            actions={viewing ? VERSION_ACTIONS : actionsFor(open.id)}
            note={renamed !== null && renamed.doc === doc && sameId(renamed.node, open.id) ? renamed.text : null}
            focusField={side?.kind === "step" ? (side.field ?? null) : null}
            onAdd={onItem}
            onDelete={() => setAsking({ kind: "node", id: open.id })}
            onConnectPort={(port) => setConnecting({ node: open.id, port })}
            onPlace={() => {
              setPlacing(open.id);
              announce(`Click an empty place on the canvas to put ${open.key} there`);
            }}
            onNudge={(key) => nudge(open.id, key)}
            onClose={() => {
              setSide(null);
              focus(item.node(open.id));
            }}
          />
        )}
        {side?.kind === "unapplied" && (
          <UnappliedPanel
            edits={[...unapplied.values()]}
            keyOf={(id) => findNode(doc, id)?.key ?? null}
            reason={(u) => (isStale(draftNow(), u) ? STALE : (u.why ?? "Still being typed."))}
            onGo={(u) => setSide({ kind: "step", node: u.node, field: { pointer: u.pointer, kind: u.kind, n: ++jumps.current } })}
            onDiscard={(u) => {
              drop([u.id]);
              land("unapplied-panel"); // its entry is gone, and with the last one the count: the list's heading takes focus
            }}
            onDownload={downloadUnapplied}
            onClose={() => {
              setSide(null);
              // Back to the count that opened it while there is one; with none left, to the canvas (WCAG 2.4.3).
              if (unappliedRef.current.size > 0) land("unapplied");
              else focus(shown);
            }}
          />
        )}
        {side?.kind === "versions" && (
          <VersionsPanel
            versions={versions.data ?? []}
            publisher={publisher && busy === null}
            onView={(v) => whenSettled("view the version", () => void view(v))}
            onActivate={(version) => setConfirm({ kind: "activate", version })}
            onClose={() => {
              setSide(null);
              land("versions");
            }}
          />
        )}
        {side?.kind === "problems" && (
          <ProblemsPanel
            state={checked}
            validation={last}
            publishProblems={publishProblems}
            publishCurrent={publishCurrent}
            keyOf={keyOf}
            onJump={(nodeId, field) => {
              // A field inside the step opens its drawer there (ruling 16); the step as a whole is focused, as in 4b.
              if (field === null || field === "") focus(item.node(nodeId));
              else setSide({ kind: "step", node: nodeId, field: { pointer: field, n: ++jumps.current } });
            }}
            onCheck={() => void validate.current()}
            onClose={() => {
              setSide(null);
              land("problems");
            }}
          />
        )}
      </div>
      {picker && (
        <StepPicker
          mode={picker}
          types={types}
          onPick={onPick}
          onConnect={picker.kind === "after" && picker.from ? () => setConnecting(picker.from) : undefined}
          onClose={() => setPicker(null)}
        />
      )}
      {connecting && (
        <ConnectDialog
          doc={doc}
          types={typeMap}
          from={connecting}
          onConnect={(to) => onConnect(connecting, to)}
          onClose={() => setConnecting(null)}
        />
      )}
      <ConfirmDialog
        open={asking !== null}
        title={
          asking?.kind === "unapplied" ? "Edits not applied"
          : asking?.kind === "edge" ? "Delete an edge" : asking?.kind === "ports" ? "Remove a port" : "Delete a step"
        }
        confirmLabel={asking?.kind === "unapplied" ? `Discard and ${asking.action}` : asking?.kind === "ports" ? "Remove" : "Delete"}
        cancelLabel={asking?.kind === "unapplied" ? "Go back to them" : "Cancel"}
        onConfirm={confirmDelete}
        onCancel={() => {
          if (asking?.kind === "unapplied") goBack();
          setAsking(null);
        }}
      >
        {asking?.kind === "node" && (
          <>
            {keyOf(asking.id)} and its edges are deleted.
            {healed && ` ${keyOf(healed.from.node)} will lead to ${keyOf(healed.to.node)}.`} Other steps that read its
            output will show a problem.
            {[...unapplied.values()].some(within(asking.id, "")) && " Its edits not applied yet are discarded too."}
          </>
        )}
        {asking?.kind === "edge" && `${keyOf(asking.edge.to.node)} will no longer follow ${keyOf(asking.edge.from.node)}.`}
        {asking?.kind === "ports" && portsQuestion(asking.dropped, keyOf)}
        {asking?.kind === "unapplied" &&
          `${asking.left.length === 1 ? "This edit isn't applied, so it would be left out" : "These edits aren't applied, so they would be left out"}: ${asking.left.map(describe).join("; ")}.`}
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm !== null}
        tone="primary"
        busy={busy !== null}
        title={confirm?.kind === "activate" ? `Make version ${confirm.version.number} active` : confirm ? `Publish version ${confirm.expected + 1}` : ""}
        confirmLabel={confirm?.kind === "activate" ? "Make active" : "Publish"}
        onConfirm={() => {
          if (confirm?.kind === "activate") void activate(confirm.version);
          else if (confirm) void publish(confirm.expected);
        }}
        onCancel={() => setConfirm(null)}
      >
        {confirm?.kind === "activate" && `Runs start on version ${confirm.version.number} from now on. The draft doesn't change.`}
        {confirm?.kind === "publish" && (
          <>
            {confirm.elsewhere &&
              `Version ${confirm.expected} was published since you opened this, by someone else or by an attempt whose answer was lost. `}
            {`Your latest edits are saved first. Version ${confirm.expected + 1} of ${workflow.name} becomes the active version${workflow.enabled ? ": its triggers start runs on it" : ""}.`}
          </>
        )}
      </ConfirmDialog>
      <ConfirmDialog
        open={leaveQuestion !== null}
        title="Your latest changes aren't saved"
        confirmLabel="Leave without saving"
        cancelLabel="Stay"
        onConfirm={() => answer(true)}
        onCancel={() => answer(false)}
      >
        {sync.status === "conflict"
          ? "This draft was changed elsewhere, so your changes since then can't be saved here. "
          : sync.status !== "saved" ? "They couldn't be saved. Stay to try again, or keep a copy before you leave. " : ""}
        {unapplied.size > 0 &&
          `${unapplied.size === 1 ? "An edit isn't applied" : "Some edits aren't applied"}: ${[...unapplied.values()].map(describe).join("; ")}. Stay to fix ${unapplied.size === 1 ? "it" : "them"}. `}
        {unapplied.size > 0 && (
          <>
            <span className="basis-full">{notInMine(unapplied.size)}</span>
            <Button size="sm" onClick={downloadUnapplied}>{downloadLabel(unapplied.size)}</Button>
          </>
        )}
        <Button size="sm" onClick={downloadMine}>Download my version</Button>
      </ConfirmDialog>
      <ConfirmDialog
        open={reloading}
        title="Reload the saved draft"
        confirmLabel="Discard my version and reload"
        onConfirm={() => {
          setReloading(false);
          onReload();
        }}
        onCancel={() => setReloading(false)}
      >
        Your version since the conflict is discarded. Download it first to keep it.
        {unapplied.size > 0 && ` The ${unapplied.size === 1 ? "edit" : "edits"} not applied ${unapplied.size === 1 ? "is" : "are"} discarded too: ${notInMine(unapplied.size)}`}
        {unapplied.size > 0 && <Button size="sm" onClick={downloadUnapplied}>{downloadLabel(unapplied.size)}</Button>}
      </ConfirmDialog>
    </div>
  );
}
