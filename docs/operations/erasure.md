# Tenant erasure

Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §6.5 (with §6.4, §10); the 2b-4 outline's "Tenant
erasure" (D3).

A platform admin erases a tenant: its data, its keys, and everything Dewpoint started for it in Temporal. **It can't be
undone.** Once started, an erasure can be stopped and retried, never reversed; the tenant is refused everything from
the first moment, and its rows, its keys and its Temporal executions go in the stages below.

> **No erasure completes today.** Completion needs proof that nothing of the tenant fires after its schedules were
> verified paused, and that proof doesn't hold yet: a Temporal schedule deleted and recreated counts its conflict
> token from 1 again, so an unpause sent before the deletion can land on a late create, and schedule ticks have no
> execution timeout. An erasure that reaches its bound holds there (`firing_bound_unproven`), its data, keys and
> executions already gone, until a design that proves it is ruled on; one stopped, or failing, stays at an earlier
> stage.

## Starting, stopping, retrying

As a platform admin, on an active session whose second factor was proven within the reauthentication window
(`DEWPOINT_REAUTH_MINUTES`):

| | |
|---|---|
| `POST /api/v1/admin/tenants/{tenant}/erasure` | `{"confirm": "<the tenant's slug>"}`: starts it (202). 422 `confirmation_mismatch`, 409 `not_erasable` (already under way or done), 403 `reauth_required`, 404 |
| `POST /api/v1/admin/tenants/{tenant}/erasure/stop` | the retention process leaves it where it is; the tenant stays `erasing` |
| `POST /api/v1/admin/tenants/{tenant}/erasure/retry` | clears a stop and the backoff: it's carried on at its recorded stage |
| `GET /api/v1/admin/tenants/{tenant}/erasure` | its record: stage, attempts and last failure or hold, its times, its counts, its items by stage and state |

Each is audited with the admin's user id (`tenant.erasure.start`, `.stop`, `.retry`), as is every move from stage to
stage (`tenant.erasure.step`, counts only), every incident and the completion.

## From the first moment

Starting marks the tenant `erasing` under its lifecycle lock, taken exclusively: every writer of tenant data takes that
lock shared and checks the tenant is active in the same transaction as its write, so a write in flight either commits
first (and the erasure removes it) or is refused. From then on: no run is admitted, dispatched or matched; a schedule's
tick is a skip; ingress refuses its endpoints (the same bodiless 401); every write through the API answers 409
`tenant_erasing` (reads still answer); a run's cancel is refused (the erasure cancels what's left); no key command
makes a key for it; the schedule sync only pauses or deletes its schedules.

A plugin call (a node's options, a connection's verification) is fenced the same way, by a lock of its own: the API's
ask checks the tenant is active in its insert's transaction, and a worker holds the tenant's plugin-call lock shared
from that check through the claim, the hook's requests and the answer. Starting takes it exclusively, before the
lifecycle lock, so it waits for a call in flight: its hook has a 10-second deadline, but its claim, key lookup and
sealing, and answer have none of their own, so the wait has no fixed bound. A call it finds queued is never run, nor
offered to a worker again (workers take only an active tenant's calls, so such calls can't hold an active tenant's
back), its row left to be deleted. A hook's own writes, on other connections, take the lifecycle lock in the fence's
trigger: holding that lock instead would leave them queued behind the start, which waits for the hook.

From stage 60 a database fence refuses any insert of a row of the tenant into any table holding tenant data (SQLSTATE
`DPE01`), whatever the writer, a straggling worker's included. It's never lifted, not even when an erasure reopens.

## The stages

The retention process carries every erasure on, every `DEWPOINT_ERASURE_INTERVAL_S` (60 s by default): each from its
recorded stage, each stage until one isn't done yet. What a stage does outside PostgreSQL goes through items (a request,
a schedule, a run, an execution), each found, requested, then verified by reading Temporal back.

| Stage | |
|---|---|
| 20 reconcile | waits until no request is `starting` (the dispatcher's reconciler resolves each) |
| 31 pause | every schedule of the tenant described paused, or absent |
| 32 inventory | before any schedule is deleted: every execution each schedule lists (recent and running), every firing its ticks recorded, and every execution visibility lists under its prefix |
| 33 unschedule | every schedule deleted, until a describe finds nothing |
| 40 cancel | queued requests and pending events cancelled (`tenant_erased`), their counters released |
| 50 end runs | every running run cancelled in Temporal, then waited for: ended in Dewpoint and closed in Temporal |
| 60 executions | the fence goes up; every execution enumerated from runs, started requests, the run evidence, the ticks' records and the inventory (visibility adding), each walked through its history (the run it continued from and as, every child it started), an open one terminated first, then deleted until describing that exact run answers not-found |
| 70 keys | every data-key version and event keypair deleted: no process can unwrap one again, so every ciphertext of the tenant is unreadable once the processes' key caches (at most 5 minutes) have expired |
| 80 sweep | every row of the tenant deleted in committed batches, counted (its own egress exceptions, quota budgets, scope key and plugin calls included; an egress exception for every tenant isn't the tenant's, and stays); the tenant renamed `Erased tenant`, its slug `erased-<id>` |
| 90 bound | the holds, then the final check (below) |
| 100 complete | the tenant is `erased` |

A stage that fails records a fixed code (`temporal_failed`, `database_failed`, `unreachable`, `stage_failed`), counts
the attempt, backs off (30 s, doubling, at most an hour) and alerts (`erasure_step_failed`, the error's type only). A
stage not done yet is tried again 30 s later; one still waiting an hour after it was entered (a run that ignores its
cancel, a request left `starting`) alerts on every pass (`erasure_stalled`). Temporal deletes a closed execution asynchronously (seconds to a minute on
the dev server): stage 60 waits for each.

## The bound and the final check

For executions it never found, an erasure relies on Temporal's own retention (D3d): a closed execution goes once the
namespace's retention has passed since it closed. So the final check may run only after the **bound**: stage 60's end
(every execution found closed and deleted by then) plus 30 days, the longest namespace retention the platform allows.
The bound is the earliest point, not a deadline. Stage 90 holds, with its reason in the record, while:

| Reason | |
|---|---|
| `firing_bound_unproven` | always, today (above): alerted |
| `boundary_unverified` | no verified namespace-change boundary is recorded (`namespace_boundaries`, written by 2b-4b's proof of the production Temporal, D3g): alerted |
| `boundary_lost` | the boundary it relied on was lost since: alerted |
| `bound_not_reached` | the bound hasn't passed: looked at again at the bound, no alert |
| `retention_unread`, `retention_above_bound` | Temporal's namespace retention can't be read, or is over 30 days: alerted |

Then the final check describes again every schedule and execution the erasure found or kept, and lists the tenant's
prefix in visibility. Anything found **reopens** the erasure (`tenant.erasure.incident`, alert `erasure_incident`): its
schedules from stage 31, its executions from stage 60, each with its own bound. Nothing found, and no row or key left:
it **completes** (`tenant.erasure.complete`, with its counts per table, the boundary it relied on, and the date backups
taken before completion expire), the tenant is `erased`, and its item rows go.

**After completion**, every Temporal id the erasure found stays listed (identifiers only), and the retention process
describes each, with a visibility listing, at every sweep, for good: anything found reopens the erasure, alerting. It
repairs a late Temporal write on its next pass; nothing keeps absence true between passes.

## What remains

- **Audit records**, under the platform's audit retention, not the tenant's. They never hold a run's inputs or
  outputs, an event's payload or a secret, but they keep identifiers and the names and labels the tenant gave (its slug
  at creation, its workflows', connections' and endpoints' names), until audit pruning removes them.
- **Backups** taken before completion, until they expire (keep them at most 35 days): they still hold the tenant's
  rows and its wrapped keys.
- **The tombstone**: the tenant's row, `erased`, anonymized, so its id is never reused and its audit chain resolves.
- **The erasure's record** and the Temporal ids it keeps for reconciliation: identifiers and counts only.
- **Logs**: identifiers and fixed codes, under the operator's log retention.
- **Late Temporal items** awaiting the reconciliation's next pass.

## Settings and alerts

The retention process needs `DEWPOINT_TEMPORAL_ADDRESS` (and `DEWPOINT_TEMPORAL_NAMESPACE`) to erase; it reaches
Temporal with a plain client and decodes nothing. Without it, every erasure under way is alerted on every interval
(`erasures_unattended`). Before it makes any Temporal call it checks that its namespace is the one the deployment
recorded: on a mismatch, or with none recorded, it erases nothing and alerts every interval
(`erasure_namespace_mismatch`, `erasure_environment_unrecorded`), and keeps sweeping. Alert on `erasure_step_failed`, `erasure_stalled`, `erasure_held` at error level, `erasure_incident`,
`erasures_unattended`, `erasure_namespace_mismatch`, `erasure_environment_unrecorded`, `erasure_temporal_unreachable`,
`erasure_unreconciled`, `erasure_reconciliation_failed` and `erasure_pass_failed`.
