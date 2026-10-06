// SPDX-License-Identifier: Apache-2.0
// Saving the draft (D17). At most one save in flight; edits made meanwhile coalesce into the next save, sent a
// second after the last change, with `If-Match` the revision the previous save returned, so the editor never
// conflicts with itself. A 409 means someone else saved: every save stops and the document stays with the person
// (read-only, downloadable), never sent over theirs. A failed save keeps the document for the next try. Each change
// is counted (`generation`) and the state says which one the server holds (`savedGeneration`): what leaving would
// lose (4b ruling 22), and whether a check of the saved draft is a check of what's on the screen (ruling 24). Once
// disposed (the editor closed), nothing more is sent or said, even when a save in flight answers.
import type { GraphDoc } from "./workflows";

export type SyncStatus = "saved" | "pending" | "saving" | "conflict" | "error";
export interface SyncState {
  status: SyncStatus;
  revision: number; // the revision the server holds of what was last saved
  unpublished: boolean | null; // that draft differs from the active version (the server's word); null: not known
  generation: number; // the editor's changes so far
  savedGeneration: number; // the change `revision` holds: `generation` when nothing is unsaved
  savedHash: string | null; // the server's graph hash of the draft at `revision` (what a version holding it records)
  activeNumber: number | null | "unknown"; // the active version, from the same answer as `unpublished`; null: none
}
export type Saved = {
  draft_revision: number;
  unpublished_changes: boolean;
  graph_hash: string | null;
  active_version_id: string | null;
  active_version_number: number | null;
};

export class ConflictError extends Error {
  constructor() {
    super("the draft changed elsewhere");
  }
}

export class SaveError extends Error {
  constructor() {
    super("the draft isn't saved");
  }
}

export class DraftSync {
  private state: SyncState;
  private latest: { doc: GraphDoc; generation: number } | null = null; // the newest change not yet sent
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inflight: Promise<void> | null = null;
  private disposed = false;

  constructor(
    private readonly opts: {
      revision: number;
      unpublished: boolean | null;
      savedHash: string | null;
      activeNumber: number | null;
      save: (doc: GraphDoc, revision: number) => Promise<Saved>;
      onChange: (state: SyncState) => void;
      onSettled?: (revision: number, generation: number) => void;
      delayMs?: number;
    },
  ) {
    this.state = {
      status: "saved",
      revision: opts.revision,
      unpublished: opts.unpublished,
      generation: 0,
      savedGeneration: 0,
      savedHash: opts.savedHash,
      activeNumber: opts.activeNumber,
    };
  }

  get current(): SyncState {
    return this.state;
  }

  /** Whether a change isn't on the server: what leaving now would lose. */
  get unsaved(): boolean {
    return this.state.generation !== this.state.savedGeneration;
  }

  private set(patch: Partial<SyncState>) {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.opts.onChange(this.state);
  }

  private stopTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(ms = this.opts.delayMs ?? 1000) {
    if (this.disposed) return;
    this.stopTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, ms);
  }

  change(doc: GraphDoc): void {
    if (this.disposed || this.state.status === "conflict") return;
    const generation = this.state.generation + 1;
    this.latest = { doc, generation };
    this.set(this.inflight ? { generation } : { generation, status: "pending" });
    this.schedule();
  }

  /** Try again now after a failed save. */
  retry(): void {
    if (this.state.status === "error" && this.latest) this.schedule(0);
  }

  /** Someone else saved (a publish's 409 says so too): stop saving. */
  conflict(): void {
    this.stopTimer();
    this.set({ status: "conflict" });
  }

  private run(): Promise<void> {
    if (this.disposed || this.inflight || this.latest === null || this.state.status === "conflict") {
      return this.inflight ?? Promise.resolve();
    }
    const sent = this.latest;
    this.latest = null;
    this.set({ status: "saving" });
    this.inflight = (async () => {
      try {
        const saved = await this.opts.save(sent.doc, this.state.revision);
        // One answer, one identity: the comparison and the version it was made against (Task 3) travel together.
        this.state = {
          ...this.state,
          revision: saved.draft_revision,
          unpublished: saved.unpublished_changes,
          savedGeneration: sent.generation,
          savedHash: saved.graph_hash,
          activeNumber: saved.active_version_number,
        };
      } catch (e) {
        if (e instanceof ConflictError) {
          this.set({ status: "conflict" });
        } else {
          this.latest ??= sent;
          this.set({ status: "error" });
        }
        return;
      } finally {
        this.inflight = null;
      }
      // Closed: no further save and no news. Declared a conflict meanwhile: it stays one.
      if (this.disposed || this.state.status === "conflict") return;
      if (this.latest !== null) {
        this.set({ status: "pending" });
        this.schedule();
      } else {
        this.set({ status: "saved" });
        this.opts.onSettled?.(this.state.revision, this.state.savedGeneration);
      }
    })();
    return this.inflight;
  }

  /** Save now whatever is pending; answer the revision saved (publish's `If-Match`). Rejects with ConflictError on a
   * conflict, and SaveError on a failed save or a closed editor: nothing is published, exported or left behind
   * over what isn't saved. */
  async flush(): Promise<number> {
    for (;;) {
      if (this.disposed) throw new SaveError();
      if (this.state.status === "conflict") throw new ConflictError();
      this.stopTimer();
      if (this.inflight) await this.inflight;
      else if (this.latest !== null) await this.run();
      else break;
      if (this.state.status === "error") throw new SaveError();
    }
    return this.state.revision;
  }

  /** The editor closed: stop, and drop whatever wasn't sent. */
  dispose(): void {
    this.disposed = true;
    this.stopTimer();
    this.latest = null;
  }
}
