# Deploying builds: Temporal and the engine worker

Specs: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7, and `2026-09-29-engine-2b-design.md` §2–§6
(the environment, the production gate, claims, taint, sizes, encrypted payloads, worker health).

A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
breaking the runs already going. Runs of a build from before versioning aren't pinned: see
[the first versioned build](#upgrading-from-a-build-without-versioning).

## Builds and versions

- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi7`. The
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
current: dewpoint-0.1.0+abi7
dewpoint-0.1.0+abi6  draining
dewpoint-0.1.0+abi7  current
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

## Upgrading the database while the old build runs (migrations 0035 to 0044)

Migrations 0035 to 0044 upgrade a database in use: each commits in short steps (`backend/migrations/online.py`), so
normal reads and writes wait behind the upgrade for a step's bounds and its local WAL flush (below), and an upgrade
interrupted anywhere is run again with `alembic upgrade head`. The waits measured (none over five seconds, under load,
up to 100,000 root runs) are those configurations' results, not a guarantee: no timeout bounds the local WAL flush, so
a stalled disk holds a step's locks as it holds every writer's commit. Two of the database's settings matter:

- A step's statements run within its budget: 60% of the shortest `deadlock_timeout` the server, the database or any
  role has (`ALTER ROLE … SET deadlock_timeout`), and 1 second at most (each statement a 5% margin more). Its commit
  then flushes locally, which no timeout bounds. A very short budget makes steps too short to finish: the upgrade then
  stops, naming the step.
- **Run it as a role whose `deadlock_timeout` is the server's:** with no role setting of its own (`ALTER ROLE … SET`),
  unless the database has one (`ALTER DATABASE … SET`). The upgrade refuses otherwise: a role's setting hides the
  server's, and a value given on the server's command line shows in no catalogue.
- **With the application connected, recycle its connections first.** Each session keeps the `deadlock_timeout` it had
  when it connected, which no catalogue shows. After any change to it, restart the application's processes (or
  recycle their connection pools), keep it unchanged until the upgrade ends, and attest that to the upgrade:
  `DEWPOINT_UPGRADE_SETTINGS_ATTESTED=1` in the migrating process's environment. While any application session is
  connected to the database being upgraded, the upgrade refuses without it; with none connected (a fresh
  installation, or the application stopped), it needs none. Sessions of the cluster's other databases don't count.
  The attestation is your assertion: nothing in the upgrade can read a live session's setting, so it can't check it.
- **A step's commit waits for no synchronous standby** (`synchronous_commit = local`): a standby that stops answering
  can't hold a step's locks. Each step is idempotent, and run again if a failover loses it.
- **A stalled migrating client is cut off.** A step's session left idle in its transaction longer than its budget (a
  paused machine, a lost network) is ended by the server, its locks with it: what waits behind it waits about two
  budgets (2.2 seconds with the 1-second budget) and the local WAL flush, which no timeout bounds. The upgrade stops
  there; run it again.
- No session may set its own `deadlock_timeout` lower than the catalogue shows. The upgrade refuses to start while a
  role other than the migrating one is granted `SET` on it, or while a superuser is one of the application's roles
  (`dewpoint_*`) or a member of one. Keep `deadlock_timeout` and those grants unchanged until the upgrade ends: each
  step reads them again and stops the upgrade if they changed. Run it again once they're settled.
- When the migrating role may set `deadlock_timeout` (a superuser, or one granted `SET ON PARAMETER
  deadlock_timeout`), a step waiting for an autovacuum has the server cancel that one; otherwise the step gives way
  and tries again until the autovacuum ends, and the upgrade stops after its attempts if it never does.

Then, once every process of the build from before migration 0040 (its API and its dispatcher) has stopped and can't be
deployed again, record the schedule inventory's cutover, as the key admin:

```sh
dewpoint schedules inventory-cutover --attest            # a dry run: the admission queue's pollers
dewpoint schedules inventory-cutover --attest --confirm  # records it, once
```

Until then the old dispatcher may sync any schedule under the schedule's own Temporal id, so the database records each
schedule added as one the inventory can't account for, and the new dispatcher's schedule passes and an erasure's
schedule stages wait (`schedule_inventory_not_cut_over`, alerted on). The command refuses while Temporal shows a
dispatcher from before 0040 polling the admission queue. Temporal keeps listing a stopped dispatcher's poller for a
while after its last poll (about four minutes in a local Compose upgrade): once the old dispatcher is stopped, run the
dry run again until it no longer refuses. It then works in two parts:

- **A catch-up, in batches of 1,000 schedules,** each committed on its own and holding no lock a schedule's writer
  waits for. It gives any schedule the database didn't record its incarnation 0. It also gives each schedule from
  before 0040 the missed count the old dispatcher last recorded, so the new dispatcher never counts those firings
  again. If it's interrupted, run the command again: the batches done stay done.
- **A short final step** that records the cutover. Schedule writes (inserts, updates, deletes) wait while it runs, but
  it reads no schedule, so its time doesn't grow with them. It waits at most 200 ms for its lock each attempt, each
  of its statements runs at most 500 ms, and its session left idle 500 ms in its transaction (a stalled client) is
  ended, nothing recorded: run it again. Its commit waits for no synchronous standby (`synchronous_commit = local`),
  so its hold is those bounds and the local WAL flush. If a failover loses it, its audit entry goes with it, the
  dispatcher's schedule passes wait again (`schedule_inventory_not_cut_over`), and you run it again. The audit anchor
  signs no entry before the configured synchronous standbys acknowledge it, so a failover to one of them never leaves
  `audit verify` naming a lost entry. That covers the standbys Postgres waits for (`synchronous_standby_names`), not
  every server that could be promoted: a failover to an asynchronous replica, or to one outside that set, can still
  lose an entry already anchored.

It refuses, records nothing and exits 1, saying why, when:
- **Another cutover is running.** A second one refuses while the first runs: wait for it to end, then run the
  command again.
- **The capture trigger (`schedules_inventoried`) is off,** or changed while the catch-up ran (turned off and on again,
  or replaced: a schedule added meanwhile could have escaped it). Turn it on, leave it, and run the command again.
- **Schedules stay busy through its attempts** (about a minute): a long transaction writing schedules, or an
  autovacuum of `schedules`, which a 200 ms wait never makes the server cancel. Wait for it to end (an autovacuum
  shows in `pg_stat_progress_vacuum`), or cancel that autovacuum (`pg_cancel_backend`), then run the command again.
  Retrying is safe: the catch-up's batches stay done, and nothing else was written.

**Every installation records it, fresh ones included,** whether Compose runs it or not: until it's recorded, the API
creates no schedule (`503 schedule_inventory_not_cut_over`), since a schedule created then would be counted as one from
before 0040, its accounting incomplete for good. On a fresh installation no writer from before 0040 exists: run the
command, with `--attest --confirm`, once Temporal is reachable and before the API serves schedule creates.

**Until the cutover is recorded, no session may set `session_replication_role = replica`** on this database (a
superuser's setting): such a session's inserts skip the capture trigger unseen, which nothing here can detect.

## Migration 0053: name the database, one per cluster

Migration 0053 tightens the database's privileges for operator recovery. It runs in one transaction: its checks, its
changes and its recorded revision commit together or not at all. It locks no application table, and waits at most
5 seconds for each lock. When it refuses or fails, nothing changed: fix the cause, then run the upgrade again.

- **Name the database you migrate,** apart from its URL: `DEWPOINT_EXPECTED_DATABASE=<name>` in the migrating
  process's environment, or `alembic -x expected_database=<name> upgrade head`. Compose's `migrate` service sets
  `DEWPOINT_EXPECTED_DATABASE: dewpoint`. The upgrade refuses when:
  - no name is given;
  - the name isn't the database it's connected to;
  - that database isn't Dewpoint's (no `alembic_version` or `platform_settings` table);
  - it's at another revision.
- **Run one Dewpoint database per PostgreSQL cluster.** 0053 makes a cluster-wide group role, `dewpoint_recovery`
  (`NOLOGIN`), for the recovery functions to come. It refuses when that role already exists, whoever made it, so a
  second Dewpoint database in the same cluster can't migrate past 0052. Other applications' databases may share the
  cluster: that role is 0053's only change outside the database it migrates.
- **The database's privileges must be the reviewed reference's.** Before changing anything, 0053 compares every object,
  owner and grant of the database with the reference it carries. It refuses on any difference, listing up to 20
  (a grant added by hand, say).
  - The reference expects the migrating role to own the database, its objects and its languages, as Compose's
    bootstrap superuser does.
  - A deployment where another role owns them (a managed PostgreSQL, say) needs a reviewed reference of its own first.
- **What PUBLIC loses:**
  - EXECUTE on the application's functions;
  - USAGE on schema `public`;
  - USAGE on the languages `plpgsql` and `sql`;
  - TEMPORARY on the database.

  Each service role keeps what it uses through explicit grants. A role of your own that reads the application's
  tables, a reporting login say, needs `GRANT USAGE ON SCHEMA public` after 0053, and its table grants as before.
- **Downgrading** to 0052 refuses while `dewpoint_recovery` has a member (a provisioned recovery login): remove the
  member first.

## A build with a new engine ABI

A build ID ends with its engine ABI (`+abi7`), which changes whenever a build could execute a workflow differently. A
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

### ABI 7: what changes

ABI 7 (2b-4b's engine blockers, #18 and #26) changes how a run binds and sends CEL, not what publishing accepts: a
workflow published under ABI 6 publishes again unchanged, as every workflow must once the ABI 7 build is current
(above). Its CEL queue is `dewpoint-cel.abi7.<profile>`: deploy the new build's evaluator workers with it, while the old
build's runs keep `abi6`'s until they end. What a run does differently:

- Binding many views of one large value yields by the bytes measured as well as the values bound: a filter whose every
  item reads a large value takes more workflow tasks, never one that outlasts the SDK's deadlock timeout.
- A value several of a step's binding sets share goes to the CEL evaluator once, as a claim each set carries the
  handle of: a filter over a large plain string no longer sends a copy with each item.
- A step whose CEL requests would take the run's history past 32 MiB fails with `history_too_large`, rather than
  Temporal terminating the run at its own limit.
- An execution continues as new once it has added 8 MiB of history, whatever Temporal suggests.

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

### The ingress capacity

```bash
dewpoint platform set-ingress-capacity --api https://dewpoint.example.com --email ops@example.com \
  --starts-per-s 8 --headroom 0.5 --queue-wait-s 300 --attestation "Measured on this deployment's Temporal, 2026-10-09"
```

A platform admin's change, through the API (D11): the command signs in as that admin, asking for the password and the
authenticator's code, and calls `PATCH /api/v1/admin/platform/ingress-capacity`, which needs the second factor proven
within the reauthentication window and audits the change in its transaction (`platform.ingress_capacity.set`) with the
admin's id, the attestation, what it was and what it is, and which values are still unset. No database login changes
it directly. The values: the sustained starts a second measured on this deployment's own Temporal, the share of them
ingress may use, and the wait its operators agree the outstanding webhook work may stand for. From them come an
endpoint's event rates and the deployment's outstanding-work limit ([ingress](ingress.md#the-ingress-capacity)); none
is set by default, and until they are, the rates and the limit are development-only. The values above are an example, not a
recommendation. A value left out keeps what it was; `--unset` unsets all three, which a production deployment whose
runs are on refuses (409 `ingress_capacity_required`): its capacity stays whole. A change that would take the limit
below the webhook work already outstanding is refused too (409 `ingress_capacity_below_outstanding`), until enough has
drained. `GET` on the same path shows it, the limit it makes, what's outstanding and what's unset; production readiness (M6's enable command, D14's ingress switch) refuses while any value is.

## Connecting to Temporal

Every process that talks to Temporal (the worker, the dispatcher, the retention process and the CLI's Temporal
commands) connects with one set of settings (engine 2b spec §10.4):

| Setting | What it is |
|---|---|
| `DEWPOINT_TEMPORAL_TLS_CA` | the CA the server's certificate is verified against; the system roots when unset |
| `DEWPOINT_TEMPORAL_TLS_SERVER_NAME` | the name verified, when it isn't the address's host |
| `DEWPOINT_TEMPORAL_TLS_CERT`, `DEWPOINT_TEMPORAL_TLS_KEY` | mutual TLS: production's target |
| `DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE` | a file holding a JWT bearer token, read at connection and every minute |
| `DEWPOINT_TEMPORAL_INSECURE_DEV` | plaintext: a recorded `development` environment only |

- Set exactly one of mutual TLS or the token file. Both, neither, a certificate without its key, or a file that can't
  be read stops the process at startup (exit 2 for a CLI command), the setting named, never its value.
- The token isn't a Temporal Cloud API key: the server's JWT claim mapper checks it against its key set and audience.
  A token replaced in its file is picked up within a minute by a running process, once that is proven on the D12
  server (2b-4b's DW.3); until then, restart the processes after replacing it.
- Production's Temporal is a self-hosted server with Dewpoint's authorizer (`deploy/temporal`), which keeps the
  namespace's retention at most 30 days and its archival disabled, and records each namespace change in the audit
  bucket. Temporal Cloud doesn't qualify.

Check what the deployment reaches, read-only:

```bash
dewpoint temporal check
```

It reports the address, the namespace, its retention and its archival, and exits 1 on plaintext, a retention above
30 days, archival enabled, or a Temporal it can't ask; 2 when the settings are refused or the namespace isn't the
recorded one.

### The namespace boundary

Tenant erasure completes only on a verified namespace-change boundary (D3g). Once D12's proof passes against the
server this deployment uses, a platform admin records it, tied to that proof:

```bash
dewpoint platform record-namespace-boundary --api https://dewpoint.example.com --email ops@example.com \
  --proof d12-proof.jsonl --name d12-local --attestation "D12 passed on <where>, configurations A and B, <date>"
```

The command refuses a proof record with a failed case, or whose two inventories name different server builds; asks
Temporal for the namespace's id under the same rules as `dewpoint temporal check`; then signs you in (password, then
your authenticator's code) and asks the API, which audits the row (`platform.namespace_boundary.record`) with your id.
Only the deployment's recorded namespace, and only a `development` deployment's for now: a production deployment's
boundary waits for real-target qualification. Keep the name when you record again after rebuilding the server: an
erasure relying on the boundary holds if the newest one's name changes.

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
  them; admission (the dispatch role) writes a run's input claims and seeds its index. No role updates a claim; only
  the retention job deletes them, with their run tree ([retention](retention.md)).
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

A worker process opens at most 23 database connections: a pool of 5 with an overflow of 10 for its activities, its
health check, the plugin calls' `LISTEN` and each call's own short transactions (its claim, its key lookup and
sealing, its answer), and a pool of 8 for the plugin calls' guards, one per call in flight, each held across the whole
call so that erasure can't start beneath it. A call never holds an activity's connection across its hook, but its
short transactions share the activities' pool. Measured (`tests/probes/test_plugin_calls_pool.py`, a development
machine, 2026-10-08): 30 activities projecting steps at once fill that pool alone (1,023 projections a second, 25 ms at
the median, 67 at the 95th percentile); beside 8 plugin calls in flight they did 14% fewer (881 a second, 27 and 87
ms). Every other process opens at most 15
(a pool of 5 with an overflow of 10): each API process, each dispatcher, each ingress process, the retention process,
and each CLI command while it runs. Size PostgreSQL's `max_connections` for their sum, plus headroom for migrations and
operators: two workers, two API processes, a dispatcher, an ingress process and the retention process need at most
2 × 23 + 5 × 15 = 121.

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

Compose's services set `DEWPOINT_TEMPORAL_INSECURE_DEV=true` to reach the dev server in plaintext, which only a
recorded `development` environment accepts: a Compose deployment recorded as `production` needs an external Temporal
and the settings above.

Compose's `migrate` service upgrades the schema (naming its database for migration 0053, above), records the
environment (`DEWPOINT_ENVIRONMENT`, `production` unless set) with the Temporal namespace
(`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data key as `dewpoint_admin_login`. Set
the namespace in `.env`: every service takes it from there, and the worker exits 2 unless its own matches the record.
Ordinary Compose is `production`, so no run starts; CI and local development use the development override, on a
database of their own (a project's own volume), with synthetic data only:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**Schedules need the inventory's cutover recorded** (above): until then the API creates none. On a fresh Compose
deployment, once `up` is done and Temporal answers, record it as the key admin (CI does the same):

```bash
docker compose run --rm -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_admin_login:<its password>@postgres/dewpoint" -e DEWPOINT_TEMPORAL_ADDRESS=temporal:7233 api dewpoint schedules inventory-cutover --attest --confirm
```

**Upgrading Compose in place,** `migrate` runs while the old build's services are still connected. Either stop them
first (`docker compose stop api worker dispatcher retention`), or, once their connections were recycled after any
`deadlock_timeout` change (above), set `DEWPOINT_UPGRADE_SETTINGS_ATTESTED=1` in `.env` for the upgrade, and remove it
after.

**Migrations run as a role that bypasses row-level security:** the database's superuser (as Compose's `POSTGRES_USER`
is) or a role with `BYPASSRLS`. Migrations 0035 and 0037 read every tenant's rows (0035 checks that no row names
another tenant's workflow, version or run; 0037 records each run's tree), and under any other role they stop with an
error naming row-level security rather than check nothing. Migration 0035 replaces its keys online, as the section
above describes: each in a short step of its own, added unchecked as the old one goes, then validated without blocking
reads or writes.

**That role keeps bypassing row-level security for as long as the deployment runs,** not only while it migrates: it
owns the database functions that read across tenants (the erasure's insert fence and stage gate, a workflow version's
immutability, a tenant's status, and the candidate lists of the dispatcher, the reconciler and the retention process),
and they read through it. Without it, the insert fence refuses every insert of a tenant's data (an error, migration
0043, never an insert let through), the stage gate, the immutability and the status refuse what they check, and the
candidate lists read nothing, so runs, events, erasures and sweeps wait without an error of their own.

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
(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`), webhook ingress as `dewpoint_ingress_login`
(`DEWPOINT_INGRESS_DB_PASSWORD`), whose role holds no table, only its three functions, and the retention job (Compose's
`retention` service) as `dewpoint_retention_login` (`DEWPOINT_RETENTION_DB_PASSWORD`), the only login that deletes
retained data ([retention](retention.md)). A fresh install creates them. An install whose database predates them
creates them once, as the database owner, after upgrading (the migrations make the group roles):

```sql
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD '<ingress password>' IN ROLE dewpoint_ingress;
CREATE ROLE dewpoint_retention_login LOGIN PASSWORD '<retention password>' IN ROLE dewpoint_retention;
```
