# Retention: a tenant's cutoff and the retention job

Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §10.1–10.3 (with §2.3 and §14).

Each tenant keeps its runs, requests and events for its retention. Past the cutoff, that data leaves every
user-facing read at once, and the retention job deletes it within the next sweeps. Retention is described by its
cutoff, by what reads stop showing and by when deletion happens, never as "exactly N days": backups and Temporal keep
some of it longer (below).

## A tenant's retention

`runs_days`: 30 unless the tenant's admins set it, from 1 to 365 days.

| | |
|---|---|
| `GET /api/v1/t/{tenant}/retention` | `{"runs_days": n}`, with `tenant.view` |
| `PUT /api/v1/t/{tenant}/retention` | `{"runs_days": n}`, with `tenant.manage`; audited (`tenant.retention.update`) with what it was; 422 outside 1 to 365 |

**The cutoff**, on the database's clock:
- a run tree is past it `runs_days` after its root run ended; its sub-runs go with it;
- a request that ended without starting (cancelled, refused, dead), when it ended;
- an ended event (matched, unmatched, cancelled, dead), when it ended.

Nothing that hasn't ended is ever past it: a running tree, a queued or starting request, a pending event.

## What reads stop showing

At the cutoff, whatever is still stored, and the API's own reads only (the engine's own work is unaffected):
- the runs list leaves out runs and requests past it;
- a run's, a sub-run's or a request's detail, with its steps, sub-runs and CSV record, answers 404;
- a request's cancel answers 404: only an ended request can be past the cutoff, so there is nothing to cancel;
- a re-run with the original input answers 410 `input_not_retained`, even while its claims are still stored; a
  re-run with new input still works ([runs](runs.md));
- an endpoint's events, the dead events list and an event's cancel leave out, or answer 404 for, events past it.

A longer retention shows again whatever the job hasn't deleted yet.

**An idempotency key lives as long as its request is stored.** An exact retry of a start or a re-run under its key
admits nothing new while the request is stored, and shows it only within its cutoff: past it, 410
`request_not_retained`; `dewpoint dev run` refuses the same way (exit 2). Once the job deletes the request, the key is
free again, and a retry under it admits a new request: don't retry under a key past the tenant's retention.

## The retention job

`dewpoint retention` is its own process, with its own database login, `dewpoint_retention_login`, the only login that
deletes retained data ([deployment](deployment.md#docker-compose-evaluation)). It never decrypts anything, so it holds
no key; its settings come from its environment only:

| Setting | |
|---|---|
| `DEWPOINT_DATABASE_URL` | the retention login's |
| `DEWPOINT_RETENTION_INTERVAL_S` | between sweeps: 3600 by default, from 60 to 21,600 |
| `DEWPOINT_RETENTION_BATCH` | rows (or run trees) per transaction: 100 by default |

`dewpoint retention --once` sweeps once and exits 0 only if the sweep succeeded (1 if it failed, or if another
retention process is sweeping). Compose runs the `retention` service, restarting it if it ends.

One sweep runs at a time, under a lock its database connection holds: another retention process finds it held and
makes none, and a process that dies releases it. A sweep takes each active tenant in turn, under its scope and its
lifecycle lock, in batches that each commit, so a sweep that stops resumes where it left. It deletes:
- a run tree past the cutoff, whole: its runs and their steps, its claims, grants and secret index, and its request
  with its envelope, together;
- a request that ended without starting, with its inputs;
- an event that ended, freeing its endpoint's and its tenant's retained counters (so `retained_full` clears);
- an upload, an hour after it was made, whether a start consumed it or not;
- a schedule's tombstone, once the dispatcher's sync has recorded its Temporal schedule gone.

Each sweep is recorded in `retention_sweeps`: its start and end, whether every tenant was swept, and its **lag**, how
far past its cutoff the oldest data still stored is. A run tree held back past its cutoff (a sub-run that never ended)
counts. Each batch counts what it deleted, in its own transaction (`retention_sweep_tenants`), and every active tenant
gets one audit entry per sweep, `retention.sweep`, naming the sweep, with counts only, zero counts included. A sweep
that stops before its end is resumed by the next start, which audits what it had already deleted, once, a tenant's
no longer active (being erased) included, without deleting anything more of it. A tenant whose sweep fails is logged
by its error's type, its counts so far are still audited, and its failure is kept with them: the sweep, resumed or
not, is recorded as unsuccessful, so it never meets the SLO; the other tenants are still swept. Sweep records go after
30 days.

**The SLO:** a successful sweep within the last 24 hours, with a lag under 24 hours. In a `production` deployment, the
dispatcher checks it before every start: while it's breached, requests stay queued (`retention_unhealthy`, with a
warning), no attempt counted, until retention recovers; a new production deployment starts nothing until its first
successful sweep. A `development` deployment doesn't check it. Alert on a sweep
older than a few intervals, an unsuccessful one, or a lag approaching a day.

## What a tenant's retention can't reach

- **Temporal** keeps histories (their visible metadata and codec-encrypted payloads) for the namespace's retention: 7
  days by default, 30 at most. A tenant whose retention is shorter has histories that outlive its data.
- **Audit records** follow the platform's audit retention, not the tenant's.
- **Backups** keep deleted data until they expire: keep them at most 35 days.
