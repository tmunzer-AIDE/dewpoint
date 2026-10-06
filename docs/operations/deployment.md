# Deploying builds: Temporal and the engine worker

Specs: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7, and `2026-09-29-engine-2b-design.md` §2–§6
(the environment, the production gate, claims, taint, sizes, encrypted payloads, worker health).

A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
breaking the runs already going. Runs of a build from before versioning aren't pinned: see
[the first versioned build](#upgrading-from-a-build-without-versioning).

## Builds and versions

- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi6`. The
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
current: dewpoint-0.1.0+abi6
dewpoint-0.1.0+abi5  draining
dewpoint-0.1.0+abi6  current
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

A build ID ends with its engine ABI (`+abi6`), which changes whenever a build could execute a workflow differently. A
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

### ABI 6: what publishing again may refuse

ABI 6 (sub-project 2b-1b) keeps sensitive and large values out of runs as claims, and publish checks where sensitive
data flows. A workflow that published under ABI 5 may be refused, or run differently, when it's published again. Each
change, with its fix:

- **A position a schema doesn't declare is sensitive**: an object's `additionalProperties`, its pattern properties, a
  key one branch of a union declares and another leaves open, a list whose elements aren't described. CEL over it runs
  in the evaluator, and its value is claimed. Fix: declare the data (closed objects, declared element types) where it
  isn't secret.
- **A computed key or index into trigger or step data** (`trigger.rows[i]`, `m[k]` with `k` computed) runs in the
  evaluator. Fix: read static paths where the expression should stay in the workflow.
- **A literal or a default at a sensitive position** is refused, null and `""` included: a node's config, a reference's
  or a template's default, an assignment to a sensitive variable, a sub-flow's sensitive input field
  (`sensitive.literal`), and a `default` at a sensitive position of the input or variables schema
  (`sensitive.default`). Fix: pass the secret in the run's input, in a field marked `x-sensitive`.
- **Sensitive data that would leave a run in plain text** is refused: a timer computed from it (`taint.timer`), a
  `fail` node's message built from it (`taint.fail_message`), or a sub-flow input field the child doesn't mark
  sensitive (`taint.subflow_input`). Fix: compute timers and messages from plain data; mark the child's field
  `x-sensitive`.
- **A decision over sensitive data must be listed** in `graph.settings.declassify`: a `flow.if` condition, a switch
  case's `when`, a loop's items, a filter's items or predicate (`taint.undeclassified`; an entry that declassifies
  nothing is `taint.stale_declassify`). Publishing a workflow with entries needs the `workflow.declassify` permission
  (tenant admins and owners, `declassify.forbidden` otherwise), and the audit log lists what each site reveals. Fix:
  list the site, or decide on plain data.
- **A sensitive variable has no default** and is null until a step sets it: a read before a step sure to have set it
  is refused (`vars.unassigned`) unless the variable's type allows null. Fix: allow null, or set it first.
- **The key `$claim` is Dewpoint's**: an authored value, output or schema that holds it is refused
  (`value.reserved_key`).
- **A version whose state can't be bounded** is refused (`version.unbounded`): publish computes each version's limit
  on open loop iterations so that a run's carried state fits 1.5 MiB; a graph none fits can't run. No graph within
  the editor's limits is known to hit it: the largest shapes tested all get the full limit, 100.

What a run does differently on ABI 6:

- A sensitive value, a value over 64 KiB, and anything at a position its schema doesn't declare is a handle
  (`{"$claim": ...}`) in a run's outputs, its rows and its sub-runs: a client that read those values from a run's
  outputs reads handles instead ([`runs.md`](runs.md#sensitive-and-large-values-claims)).
- A run's input is checked against its input schema when it's admitted: a trigger that doesn't match is refused
  before any run exists.
- A loop's `failures` list in index order, not in the order the iterations failed.
- A plugin's failure shows its message only when it's text written in the plugin's code, and its code only when that's
  a constant identifier of its code (`node_failed` otherwise): a message a plugin computed is replaced by a generic
  one ([`runs.md`](runs.md#what-the-workers-log-shows)).
- A loop that collects more than 64 KiB, or more than the run's live state holds, outputs one claim:
  `steps.<loop>.output.items` is a handle, read by position as before.

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
- Every process that talks to Temporal — the worker, the dispatcher and the CLI's Temporal commands — compares its
  configured namespace with the record before it connects, and exits 2 when there's no record or it doesn't match. So a
  development database can't drive a namespace it wasn't set up for, and a production database can't either. The
  label proves nothing about the data: keep development's database and namespace apart from production's, with
  synthetic data only.
- In `production`, no run starts until the production gate is lifted (sub-project 2b-4, after its readiness checks):
  the run API answers 503 `production_runs_disabled` and `dewpoint dev run` exits 2, with "Production runs are off in
  this deployment"; the dispatcher starts nothing, and queued requests wait. In `development`, runs start freely.

### Turning production runs off

```bash
dewpoint platform disable-production-runs --wait 10
```

As `dewpoint_admin`, it turns the gate off at once, audited (`platform.production_runs.disable`): queued requests wait
and started runs continue. It waits for any starting transaction to finish first, so no request becomes `starting`
after it. Then it waits up to `--wait` seconds (the dispatcher's start deadline by default) for the starts already made
to settle, and exits 3 with the ids of any still unresolved: the gate stays off, and the reconciler settles and audits
them. No role turns the gate on outside 2b-4's command.

## Encrypted payloads

Every payload Dewpoint's workflows exchange with Temporal — a run's input and result, each step's input and output,
children's starts and results, failures' messages — is encrypted with its tenant's data key
([`key-rotation.md`](key-rotation.md)). The tenant is the one the workflow id names: `t:<tenant>:run:<run id>` for
every run, a sub-flow and a failure handler included, and `t:<tenant>:run:<run id>/<step>/<iteration>/batch:<start>`
for a loop's batch. Temporal's Web UI shows ciphertext; what stays readable there is the ids, workflow and activity
types, task queues, timestamps, and a local activity's own bookkeeping (its type and times).

- The worker, the dispatcher, the API and `dewpoint dev run` need the KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`) and
  read tenants' data keys through their database roles; they cache them for at most 5 minutes, and never longer, so a rotation reaches every
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
- **Claims** (from ABI 6) are stored in the database, encrypted with the same data keys and bound to their id and
  tenant: `run_inputs` and `step_outputs` hold sensitive and large values, `claim_grants` which run may read which, and
  `run_secret_index` each run tree's known secrets, used to mask messages and rows. The worker's role reads and writes
  them; admission (the dispatch role) writes a run's input claims and seeds its index. No role updates or deletes a
  claim; tenant retention will (sub-project 2b-4).
- **No digest of a claim's value is kept** (migration 0018, issue #28). Before it, each claim row held an unkeyed
  SHA-256 of its plaintext, which let anyone who read the table test guesses for a short secret offline. The migration
  drops the column from the live database, and a rewrite of a claim's id is checked by decrypting the existing claim.
  A database backup taken before 0018 still holds those hashes: keep it under the same controls as a backup of the
  data itself, and let it expire on your backup schedule rather than restoring it into a new environment.

## Worker health

Each engine worker instance records itself in `worker_instances`: its build, its capabilities (`payload_codec`,
`cel_request_size_guard`, and from ABI 6 `claim_check`), and whether its self-check passed — at startup, before it
polls, and every 30 seconds. The check proves what `payload_codec` needs of the instance, that its KEK wraps and
unwraps a key and its database role may read data keys, and what `claim_check` needs, that its role may read and write
claims, grants and the secret index. An instance that fails it stops polling (running attempts get the shutdown grace)
and exits with code 3; its process manager should restart it. A database that doesn't answer proves nothing either
way: during an outage the worker keeps running, records nothing, and its row goes stale. Sub-project 2b-2's dispatcher
starts runs only while every live instance of the current build is healthy and holds every capability.

The check is deliberately light: it proves a grant and a fresh key's round trip, not that stored keys unwrap. A wrong
KEK configured under the right id passes it, and passes `dewpoint keys status`, which compares KEK ids
([`key-rotation.md`](key-rotation.md)). Lifting the production gate (sub-project 2b-4) unwraps every stored data key
and reads each tenant's key the way the workers do, first.

## Docker Compose (evaluation)

Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
UI at <http://127.0.0.1:8233>), one `worker` and one `dispatcher`, which Compose restarts unless it's stopped.
Production uses a Temporal cluster instead.

The dispatcher also runs schedules' ticks: its own Temporal worker, on the task queue `dewpoint-admission`, outside the
engine's Worker Deployment and unversioned, admits each firing as the dispatch login; its leader keeps the Temporal
Schedules in step with the `schedules` table. A schedule's time zone is checked against the image's IANA time zone
data, which the shipped image holds (CI schedules a run in `Europe/Paris` through Compose to prove it). Don't edit a
Dewpoint schedule in Temporal's UI: the dispatcher only tells its own updates apart, by the `dewpoint generation <n>`
note it writes.

Compose's `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless
set) with the Temporal namespace (`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data
key as `dewpoint_admin_login`. Set the namespace in `.env`: every service takes it from there, and the worker exits 2
unless its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development use the
development override, on a database of their own (a project's own volume), with synthetic data only:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**Migrations run as a role that bypasses row-level security:** the database's superuser (as Compose's `POSTGRES_USER`
is) or a role with `BYPASSRLS`. Migrations 0035 and 0037 read every tenant's rows (0035 checks that no row names
another tenant's workflow, version or run; 0037 records each run's tree), and under any other role they stop with an
error naming row-level security rather than check nothing. Migration 0035 also adds and checks its keys inside its own
transaction, which blocks writes to `runs`, `run_steps`, `run_requests` and the other tables it changes until it ends;
before migrating large populated tables, plan the downtime or split the check (a decision of its own).

It records `development` (`DEWPOINT_ENVIRONMENT`); CI sets `COMPOSE_FILE` to both files.

Webhook ingress, a development-only prototype until engine 2b-4, runs only with the `ingress` profile
(`COMPOSE_PROFILES=ingress`, as CI sets it) and the development override; it needs `DEWPOINT_INGRESS_KEY_B64` in
`.env`, which the API holds too ([webhook ingress](ingress.md)).

Compose runs one build at a time, so its worker makes its own build current as it starts
(`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. When the new
image has a new engine ABI, publish every workflow again after upgrading (above). Leave the setting off wherever builds
overlap.

The worker, and the dispatcher and `dewpoint dev run`, log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`), and webhook ingress as `dewpoint_ingress_login`
(`DEWPOINT_INGRESS_DB_PASSWORD`), whose role holds no table, only its three functions. A fresh install creates them. An
install whose database predates them creates them once, as the database owner:

```sql
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD '<ingress password>' IN ROLE dewpoint_ingress;
```
