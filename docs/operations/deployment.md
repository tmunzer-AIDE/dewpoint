# Deploying builds: Temporal and the engine worker

Specs: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7, and `2026-09-29-engine-2b-design.md` §2 and §6
(the environment, the production gate, encrypted payloads, worker health).

A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
breaking the runs already going. Runs of a build from before versioning aren't pinned: see
[the first versioned build](#upgrading-from-a-build-without-versioning).

## Builds and versions

- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi5`. The
  engine ABI changes whenever a build could execute a workflow differently, so such a build always has a new ID.
- Every engine worker joins one Temporal **Worker Deployment**, `dewpoint-engine`, as its build's version.
- New runs start on the deployment's **current** version. Nothing becomes current by itself: making a build current
  is the step that switches new runs to it.
- The `cel.evaluate` queues are outside the deployment: an expression goes to an evaluator serving its version's CEL
  profile ([`cel-evaluator.md`](cel-evaluator.md)), on a worker of its build's engine ABI. A queue names both,
  `dewpoint-cel.abi<engine ABI>.<profile>` (builds before ABI 5: `dewpoint-cel.<profile>`), since each ABI's requests
  are written for it: from ABI 5 on they're encrypted, which an older build can't read.

`dewpoint deployment status` shows the current build and every version Temporal knows:

```text
current: dewpoint-0.1.0+abi5
dewpoint-0.1.0+abi4  draining
dewpoint-0.1.0+abi5  current
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

## A build with a new engine ABI

A build ID ends with its engine ABI (`+abi5`), which changes whenever a build could execute a workflow differently. A
version runs only on a build of the ABI it was published for. So when a new build changes it:

- Runs already started on the old build finish there, pinned to it, with their sub-flows and failure handlers. (A
  build from before versioning doesn't pin them: see below.)
- A new run starts on the deployment's current build, so that's the build admission compares versions with. The
  process that starts it must be a build of the same ABI, since a start is written for its own: until the promotion,
  start runs with the old build's `dewpoint`, and after it with the new build's. The new build's refuses to start any
  run while the old build is current ("start runs from a process of the current build"). A build of ABI 4 or older
  doesn't check this: once a newer ABI is current, don't start runs with it, or they never begin.
- Once the new build is current, the old build's versions are refused ("publish the workflow again"), and `dewpoint
  dev run` prints which ones. A sub-flow or failure handler of the other ABI refuses its parent's runs the same way.
- Publish each workflow again with the new build once it's current. Start with the workflows that others run as
  sub-flows or failure handlers, then publish those that run them. Publishing refuses a workflow that would run a
  version of another ABI (`subflow.engine_abi`).
- A promotion that happens between a run's admission and its start is caught when the run loads its version: it fails
  with `version_unusable` before any step runs, with the same explanation. Start it again.

Rolling back across an ABI change means publishing again with the old build, too.

## Upgrading from a build without versioning

A build from before Worker Versioning doesn't join the `dewpoint-engine` deployment: `dewpoint deployment status`
lists no version for it. Its runs aren't pinned. Once a versioned build is current, Temporal moves each of them to that
build at its next workflow task. The new build can't replay what the old one recorded, so the task fails as
nondeterministic and is retried forever, and the run stays `running`.

So for the first versioned build:
1. Stop starting runs with the old build, and let every run it started end, or cancel it. Temporal's Web UI lists the
   running workflows.
2. Start the new build's workers, make it current, and publish every workflow again with it (above).

Until a versioned build is current, the new build admits nothing: no build is current. The old build's processes
don't check the ABI when they admit a run, but a run they start after the promotion starts on the new build, whose
loader refuses a version of another ABI.

## The deployment's environment and the production gate

A deployment is `production` or `development`, recorded once with the Temporal namespace it uses:

```bash
dewpoint platform init-environment --environment production --temporal-namespace dewpoint
```

- The defaults are `DEWPOINT_ENVIRONMENT` (else `production`) and `DEWPOINT_TEMPORAL_NAMESPACE` (else `default`).
  Running it again with the same values changes nothing; with other values it refuses: neither can change.
- Every process that talks to Temporal — the worker and the CLI's Temporal commands — compares its configured
  namespace with the record before it connects, and exits 2 when there's no record or it doesn't match. So a
  development database can't drive a namespace it wasn't set up for, and a production database can't either. The
  label proves nothing about the data: keep development's database and namespace apart from production's, with
  synthetic data only.
- In `production`, no run starts until the production gate is lifted (sub-project 2b-4, after its readiness checks):
  `dewpoint dev run` is refused, exit 2, with "Production runs are off in this deployment". In `development`, runs
  start freely.

## Encrypted payloads

Every payload Dewpoint's workflows exchange with Temporal — a run's input and result, each step's input and output,
children's starts and results, failures' messages — is encrypted with its tenant's data key
([`key-rotation.md`](key-rotation.md)). The tenant is the one the workflow id names: `t:<tenant>:run:<run id>` for
every run, a sub-flow and a failure handler included, and `t:<tenant>:run:<run id>/<step>/<iteration>/batch:<start>`
for a loop's batch. Temporal's Web UI shows ciphertext; what stays readable there is the ids, workflow and activity
types, task queues, timestamps, and a local activity's own bookkeeping (its type and times).

- The worker and `dewpoint dev run` need the KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`) and read tenants' data keys
  through their database roles; they cache them for at most 5 minutes, and never longer, so a rotation reaches every
  process within 5 minutes ([`key-rotation.md`](key-rotation.md)).
- **Runs don't ride out a long database outage.** A key whose 5 minutes are up is read again, and while the database
  doesn't answer, it can't be: that tenant's payloads stop. An activity that starts or finishes then fails its
  attempt, like any failure the activity didn't describe itself ([`runs.md`](runs.md#attempts-and-retries)). A plugin
  step uses up its attempts, or records `outcome_unknown` if its node is `ambiguous`, and a `cel.evaluate` fails its
  step with `cel_profile_unavailable` after 3 attempts. Workflow tasks fail and are retried until the database
  answers. Expect failed steps after an outage longer than 5 minutes, and rerun their runs.
- A tenant gets its data key when it's created. `dewpoint keys ensure-tenants`, run as a `dewpoint_admin` login, gives
  one to every tenant that has none (tenants created before this build); Compose's migrate step runs it. It lists the
  tenants under row-level security, as the key admin, so it needs no role that bypasses it, and refuses (exit 2) a
  role that isn't the key admin, which would see none of them.
- A run of an older build (ABI 4 and before) keeps its plain-text payloads and its old workflow id; it finishes on its
  own build, as any pinned run does.

## Worker health

Each engine worker instance records itself in `worker_instances`: its build, its capabilities (`payload_codec`,
`cel_request_size_guard`), and whether its self-check passed — at startup, before it polls, and every 30 seconds. The
check proves what `payload_codec` needs of the instance: its KEK wraps and unwraps a key, and its database role may
read data keys. An instance that fails it stops polling (running attempts get the shutdown grace) and exits with code
3; its process manager should restart it. A database that doesn't answer proves nothing either way: during an outage
the worker keeps running, records nothing, and its row goes stale. Sub-project 2b-2's dispatcher starts runs only
while every live instance of the current build is healthy and holds every capability.

The check is deliberately light: it proves a grant and a fresh key's round trip, not that stored keys unwrap. A wrong
KEK configured under the right id passes it, and passes `dewpoint keys status`, which compares KEK ids
([`key-rotation.md`](key-rotation.md)). Lifting the production gate (sub-project 2b-4) unwraps every stored data key
and reads each tenant's key the way the workers do, first.

## Docker Compose (evaluation)

Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
UI at <http://127.0.0.1:8233>) and one `worker`. Production uses a Temporal cluster instead.

Its `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless set)
with the Temporal namespace (`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data key as
`dewpoint_admin_login`. Set the namespace in `.env`: every service takes it from there, and the worker exits 2 unless
its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development set
`DEWPOINT_ENVIRONMENT=development` through their own override, on a database of their own.

Compose runs one build at a time, so its worker makes its own build current as it starts
(`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. When the new
image has a new engine ABI, publish every workflow again after upgrading (above). Leave the setting off wherever builds
overlap.

The worker and `dewpoint dev run` log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
database predates them creates them once, as the database owner:

```sql
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
```
