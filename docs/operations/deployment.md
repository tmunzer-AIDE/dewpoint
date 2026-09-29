# Deploying builds: Temporal and the engine worker

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7.

A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
breaking the runs already going.

## Builds and versions

- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi3`. The
  engine ABI changes whenever a build could execute a workflow differently, so such a build always has a new ID.
- Every engine worker joins one Temporal **Worker Deployment**, `dewpoint-engine`, as its build's version.
- New runs start on the deployment's **current** version. Nothing becomes current by itself: making a build current
  is the step that switches new runs to it.
- The `cel.evaluate` queues (`dewpoint-cel.<profile>`) are outside the deployment: an expression goes to an evaluator
  serving its version's CEL profile, whatever the build ([`cel-evaluator.md`](cel-evaluator.md)).

`dewpoint deployment status` shows the current build and every version Temporal knows:

```text
current: dewpoint-0.1.0+abi3
dewpoint-0.1.0+abi2  draining
dewpoint-0.1.0+abi3  current
```

A `draining` version still has runs pinned to it. A `drained` one has none left.

## Rolling out a new build

1. Run `dewpoint plugins sync` with the new build, as on every deploy
   ([`plugin-lifecycle.md`](plugin-lifecycle.md)).
2. Start the new build's workers **next to** the old ones.
3. From the new build, run `dewpoint deployment set-current`. It waits (up to `--wait` seconds, default 60) until one
   of the new build's workers has polled, then makes that build current. `--build-id` names another build.
4. Watch `dewpoint deployment status`. Stop the old build's workers only once its version reports `drained`.

Stopping them earlier doesn't lose runs, but it stalls them: a pinned run waits, durably, until a worker of its own
build polls again. Temporal's Web UI lists the runs still pinned to a version.

To roll back, make the old build current again while its workers still run: `dewpoint deployment set-current
--build-id <old build ID>`. Runs that started on the new build stay on it.

A node type the new build no longer ships must be retired first ([`plugin-lifecycle.md`](plugin-lifecycle.md)). The
old build's runs that still use it finish on the old build's workers, which still have it.

## Docker Compose (evaluation)

Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
UI at <http://127.0.0.1:8233>) and one `worker`. Production uses a Temporal cluster instead.

Compose runs one build at a time, so its worker makes its own build current as it starts
(`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. Leave the setting
off wherever builds overlap.

The worker and `dewpoint dev run` log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
database predates them creates them once, as the database owner:

```sql
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
```
