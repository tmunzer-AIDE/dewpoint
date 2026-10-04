# Engine 2b-3b: Webhook Ingress Implementation Plan

> **Status: outline revised with the owner's rulings (2026-10-04), for the owner's look at its dedupe, function and
> lock-order, work-limit and retained-storage sections before M1.** As in 2b-1a through 2b-3a, each task will be built
> and tested on a prototype branch from `main` first, with the owner's checkpoint after each milestone; the plan is
> then written from the tested diffs, each replayed tests-first, with a revision of the 2b spec, for the owner's review
> before execution. **Ingress stays a gated prototype**: it isn't exposed in production until 2b-4 supplies rotation,
> key retirement, retention and erasure (rulings 8 and 13).

**Goal:** a webhook a sender posts to Dewpoint becomes runs: `dewpoint ingress` authenticates it, splits it into
events and records each sealed to its tenant, and the dispatcher matches each event to its bindings, admitting one
request per matching workflow through `admit_request`.

**Architecture:** two halves that share only the event tables (§8.3).
- **Ingress** (a new process and login, `/hooks/<endpoint_id>`) never holds a tenant's data key and has no table
  privilege. It resolves the endpoint through one SECURITY DEFINER function, authenticates, seals each event to the
  tenant's X25519 public key, and records the batch through another, which applies the rate limits, the deduplication
  and the quotas under one lock order; it answers 200 only once committed.
- **The dispatcher** matches only while the gate is on, fairly across tenants: it claims a pending event, rechecks the
  gate and the tenant, opens the event with the tenant's private key (sealed with the tenant's data key), admits one
  request per matching binding, and records the event `matched` or `unmatched`, in one transaction.

**Tech stack:** Python 3.12, FastAPI (the ingress app), SQLAlchemy async with asyncpg, Alembic, PostgreSQL 16 (forced
row-level security, SECURITY DEFINER functions), `cryptography` (X25519, HKDF, AES-256-GCM, HMAC), Typer, Compose and
nginx. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 8 (merged with 2b-3a): §8.3, with §2.5,
§6.4, §6.5, §7.2, §9, §10.1, §10.5, §12, §14 and §15; engine-core revision 5.11; the parent spec's §3.1, §4.4, §6.1
and §12. This plan's revision 9 of the 2b spec lands with it.

## What exists today (main 9fb4ee5)

- **The role, without a login.** `dewpoint_ingress` is a NOLOGIN group role (migration 0001) whose only grant is
  `EXECUTE` on `audit_append` (0005); a test asserts it has no `data_keys` grant. Logins are made by Compose's first
  database init (`deploy/compose/initdb/10-roles.sh`), one per role with a `DEWPOINT_*_DB_PASSWORD`; there's no ingress
  login or password anywhere (Compose, `.env.example`, CI's env, the Compose tests). The tests' `t_dewpoint_ingress`
  login already exists.
- **Admission takes the source.** `webhook` is a durable source: admission skips the gate and the environment checks
  for it, refuses an `erasing` tenant, keeps a refusal as a `refused` request, and merges `details` into the
  `run.request` audit entry. Idempotency keys are 255 characters, unique per tenant. No `evt:` key, no event, endpoint
  or binding exists. **The matcher must check the gate itself**: admission doesn't, for a durable source.
- **Keys.** Tenant data keys (AES-256, versioned, wrapped by the KEK) seal values under a purpose and a context; the
  only HKDF derives the request-digest key. There's no asymmetric encryption (only Ed25519 audit anchors), no
  `DEWPOINT_INGRESS_KEY` and no re-encryption command. `create_tenant` and `dewpoint keys ensure-tenants` are where a
  tenant's keys are made.
- **SECURITY DEFINER functions** (the candidates functions) pin `SET search_path = public, pg_temp`, return ids only,
  and are executable by one role.
- **The dispatcher's cycle** observes, dispatches and reports, and its leader reconciles, sends cancels, syncs
  schedules and reads misses. Its starting transaction takes `dewpoint:production-gate` and the tenant's lock shared.
- **Rate limits.** Only a fixed-window `auth_throttle` table (login throttling). No token bucket, counter or quota.
- **The API process** has no CLI command: the image's default command runs uvicorn on the API's app factory. nginx
  routes `/api/` and `/health/` to `api`, with a 6 MiB body cap.
- **Tenancy.** `tenants.status` is `active` or `erasing`, checked by admission, dispatch and ticks; nothing sets it
  (2b-4's erasure transition), and there's no retention job (2b-4).
- **The parent spec** (§3.1, §4.4, §6.1): `POST /hooks/{endpoint_id}`, a resolver returning only what verification
  needs, 128-bit random endpoint ids, the tenant never taken from the payload, 2xx after commit, the dispatcher
  claiming with `SKIP LOCKED`. §8.3 replaced its outbox and `app_*` roles and added sealing, the ingress key and the
  quotas.

## Deduplication (ruling 4)

Each endpoint declares where its events' ids are, `id_source`:
- **`pointer`:** each event carries its own id at a JSON pointer. An event without a string or integer there is a 400
  for the whole request.
- **`header`:** one id for the request, in a named header (required: a request without it is a 400); event *i* of the
  batch is identified by that id and its index *i*.
- **`none`:** events carry no id. Each accepted event is distinct: **nothing is deduplicated**, and two identical
  events are two events. The effect is at-least-once: a sender that retries after losing a 200 records its events
  twice. The guide says so, and an endpoint that can't accept that sets `pointer` or `header`.

There is no deduplication by body bytes: two legitimate events may be identical.

- **The dedupe key** is `HMAC-SHA256(endpoint dedupe key, "event:" ‖ id)` for `pointer`, and `HMAC-SHA256(endpoint
  dedupe key, "batch:" ‖ id ‖ ":" ‖ i)` for `header`; null for `none`. The id is taken only from an authenticated
  request, and never stored plain. `inbound_events` is unique on `(tenant_id, endpoint_id, dedupe_key)`, nulls distinct.
- **The content digest** is `HMAC-SHA256(endpoint dedupe key, "content:" ‖ canonical JSON of the event)`, stored beside
  the dedupe key (null for `none`).
- **A repeated id:** with the same content digest, the event is an acknowledged duplicate (nothing recorded); with a
  different one, the **whole request is refused**, 409 `event_id_reused`, nothing recorded: an id reused for other
  content is a sender's error, never silently a duplicate.
- **Deduplication lasts as long as the event's row.** Until 2b-4's retention, rows are kept (bounded, below); once
  retention deletes one, a replay of its id is a new event.
- **The request key** stays `evt:<inbound event's own id>:<workflow id>`. **One binding per endpoint and workflow**
  (unique on `(tenant_id, endpoint_id, workflow_id)`), so an event's key names one request per matching workflow.
- **The endpoint's dedupe key** is made with the endpoint, sealed under the ingress key, and never changes with its
  signing secret: rotating the secret keeps deduplication.

## Functions and lock order (rulings 3 and 9)

Ingress has **no table privilege**: only `EXECUTE` on two functions, both SECURITY DEFINER, with `search_path` pinned
(`public, pg_temp`, `pg_temp` last), every object schema-qualified, `EXECUTE` revoked from `PUBLIC` and granted to
`dewpoint_ingress` alone.

- **`resolve_webhook_endpoint(endpoint_id)`** returns, for an existing endpoint, only what ingress needs to decide:
  the endpoint's tenant, whether the endpoint is enabled and its tenant `active`, the authentication kind and its
  material (a bearer token's SHA-256 digest; the sealed HMAC secret, header names and tolerance), the sealed dedupe
  key, the address allowlist, the body limit, the id source, the events pointer, and the tenant's current public key
  and its version. Nothing for an unknown id. (Parent §4.4 named fewer fields; §13 notes it.)
- **`record_inbound_events(endpoint_id, batch)`** takes the endpoint's id and the sealed batch (each event's internal
  id, sealed payload, key version, size, dedupe key and content digest) and returns the outcome. **The tenant comes
  from the endpoint's row**, read inside the function; every statement filters or writes by it, and it's never a
  parameter. In one transaction (the caller's):
  1. lock the endpoint's row; refuse (`unknown`, answered as the uniform 401) if it's gone or disabled, or its tenant
     isn't `active`, by the tenant's row read under that lock;
  2. lock the tenant's event row (`tenant_event_counters`);
  3. take the rate limits' tokens (below): a request, its events and its bytes, from the endpoint's and the tenant's
     buckets; short of any, `rate_limited` with the wait;
  4. compare each keyed event with an existing row (a plain read, no lock): a duplicate, or `event_id_reused`;
  5. check the new events against the quotas: pending and retained, endpoint and tenant (below); past any,
     `quota_exceeded`;
  6. insert the new events, `pending`, and move the counters;
  7. return the counts accepted and duplicated.
  Steps 3–6 decide the whole batch: one refusal records nothing.
- **One lock order, for every writer of the counters:** the **endpoint's row, then the tenant's event row**. Ingress
  takes them as above, and never locks an existing event row (it reads; its inserts wait only on a concurrent insert
  of the same key). The matcher, a cancel and the recount lock an **event row first** (the matcher `SKIP LOCKED`),
  then the endpoint's row, then the tenant's; ingress holds no event row, so no cycle can form. A test races a
  duplicate's insertion against the matching of the same event, both ways, and two endpoints of one tenant against a
  match.
- **The matcher's transaction** (one per event): claim the event row (`FOR UPDATE SKIP LOCKED`); take the gate's lock
  and the tenant's lock shared, as dispatch does, and recheck the gate, the dispatch-time checks and `tenants.status`;
  if any fails, roll back, the event still pending and its attempts untouched; open the event; admit one request per
  matching binding, in workflow-id order (§7.2); record `matched` (with its request count) or `unmatched`; lock the
  endpoint's row, then the tenant's, and release the pending counters.
- **Fairness:** `event_candidates(n)` (ids only) ranks each tenant's pending events by age and returns them by rank,
  then age: every tenant with pending events gets its oldest event in before any tenant gets its second. FIFO within a
  tenant; at most 50 events a cycle; an event's fan-out is capped by its endpoint's bindings, at most 20 (refused at
  binding creation, rechecked at matching).

## Work limits (rulings 5 and 7)

Before authentication, only **global** limits, which tell nothing about any endpoint:
- **Concurrency:** at most 32 requests in flight per ingress process; past it, 503 with `Retry-After`, before the body
  is read.
- **The global body cap,** 5 MiB (the largest an endpoint may set; nginx allows 6 MiB): the body is read as it arrives
  and refused one byte past it, 413.

Then the endpoint is resolved, the address checked and the request authenticated: any failure is the **uniform
bodiless 401** (an unknown or disabled endpoint, a disallowed address, a failed authentication, an `erasing` tenant).
Only after a successful authentication:
- **the endpoint's body limit** (1 MiB by default, up to 5 MiB): 413;
- **parsing:** a body that isn't JSON, an events pointer that doesn't resolve to an array, an item that isn't a JSON
  object, more than 500 events, or a missing or invalid id (`pointer`, `header`): 400, nothing recorded (ruling 6);
- **the rate limits,** in the recording function: three token buckets per endpoint (requests, events, bytes) and two
  per tenant (events, bytes), each refilled continuously; short of any token, 429 with `Retry-After` (the wait for the
  scarcest bucket), nothing recorded. **Duplicates consume rate tokens** like any event; they bypass only the quotas;
- **an id reused for other content:** 409;
- **the quotas:** 429 with `Retry-After`, nothing recorded;
- **200**, once committed, with the counts accepted and duplicated. A batch is all or nothing.

**Provisional values** (§15), to be justified by the load probe (ruling 12), which measures each separately:

| Limit | Start |
|---|---|
| In-flight requests per ingress process | 32 |
| Global body cap; endpoint body limit | 5 MiB; 1 MiB by default |
| Events per request | 500 |
| Per endpoint: requests | 20/s, burst 100 |
| Per endpoint: events | measured first (the prototype starts at 200/s, burst 1,000) |
| Per endpoint: bytes | 2 MiB/s, burst 10 MiB |
| Per tenant: events; bytes | 1,000/s, burst 5,000; 10 MiB/s, burst 50 MiB |
| Matcher | 50 events a cycle; at most 20 bindings per endpoint |

## Retained storage (ruling 13)

Pending-only quotas don't bound storage while terminal events are kept, and until 2b-4's retention nothing deletes
them. So the recording function checks **two kinds of quota**, each on the endpoint and on the tenant:
- **Pending** (§8.3, §15): 10,000 events and 64 MiB per endpoint, 50,000 events and 256 MiB per tenant. Matching,
  cancelling and dead-lettering release them.
- **Retained, all rows whatever their status** (new): provisionally 100,000 events and 512 MiB per endpoint, 250,000
  events and 1 GiB per tenant, counted in sealed bytes. Only deleting a row releases them, which nothing does before
  2b-4: once full, ingress answers **429, failing closed**, until retention exists.

Both are counters on the endpoint's row and the tenant's event row, moved under the lock order above, with a periodic
recount (the dispatcher's leader, reading without locks, then taking the endpoint's and tenant's rows in order) that
corrects drift. **Production ingress stays unexposed** until 2b-4: `dewpoint ingress` refuses to start unless the
recorded environment is `development`, and 2b-4 lifts that with retention, erasure and key rotation.

## The event schema (M1's migrations)

- `tenant_event_keys` (`tenant_id`, `version`, `public_key`, `private_sealed`, `created_at`): the private key sealed
  with the tenant's data key (purpose `event.private`, the version as context). A missing required version fails
  closed (ruling 8).
- `webhook_endpoints`: a random id (UUIDv4, 122 random bits; the parent's 128 noted), `tenant_id`, a name, `enabled`,
  the authentication (`bearer` with a SHA-256 digest, or `hmac` with its secret sealed under the ingress key, header
  names and tolerance), the allowlist (CIDRs), the body limit, `id_source` and its pointer or header, the events
  pointer, the sealed dedupe key, the rate settings and bucket state, the pending and retained counters, `created_by`
  and times.
- `tenant_event_counters` (`tenant_id`): the tenant's buckets, pending and retained counters.
- `trigger_bindings`: `tenant_id`, `endpoint_id`, `workflow_id` (unique together), a filter (at most 8 typed
  JSON-pointer equalities, all of which must hold), `enabled`.
- `inbound_events`: the internal id, `tenant_id`, `endpoint_id`, `dedupe_key` and `content_digest` (null for
  `none`), `key_version`, `sealed`, `size_bytes`, `status` (`pending`, `matched`, `unmatched`, `cancelled`, `dead`),
  `reason`, `attempts`, `next_attempt_at`, `request_count`, `received_at`, `ended_at`; unique on `(tenant_id,
  endpoint_id, dedupe_key)`.
- Forced row-level security on each; the API's, the dispatcher's and (none) ingress's grants; the two ingress
  functions and the dispatcher's `event_candidates()`; migrations upgrade, downgrade and upgrade again over rows.

## Milestones and tasks (first cut)

**M1. Keys, the event store and the functions**
1. The ingress key, `DEWPOINT_INGRESS_KEY` with its id, for ingress and the API only: endpoint secrets and dedupe keys
   sealed under it; bearer tokens as SHA-256 digests (high-entropy, generated by Dewpoint).
2. The tenants' keypairs: made by `create_tenant` and `keys ensure-tenants`, versioned; the sealing primitive (an
   ephemeral X25519 key, HKDF-SHA256, AES-256-GCM; the tenant, endpoint, event id and key version as associated data),
   with known-answer, tamper, wrong-key and missing-version tests.
3. The schema above, the two ingress functions (their grants, pinned paths, the tenant from the endpoint's row, the
   lock order, all-or-nothing batches), the ingress login (Compose's init, env, CI, the Compose tests), the ingress
   test sessionmaker; proofs that ingress can't read or write any table directly.

**M2. The ingress process**
4. `dewpoint ingress` (its own app, CLI command and `/health`; refusing to start unless the environment is
   `development`), `POST /hooks/<endpoint_id>`, in the order of "Work limits": concurrency, the global cap, the
   resolver, the address (ruling 11: `X-Forwarded-For` trusted only from configured proxies, none by default, read from
   the trusted end of the chain; spoofed headers tested directly and through nginx), authentication in constant time
   (ruling 2: HMAC over the exact raw bytes, or a bearer token), the uniform 401. An import contract keeps it from the
   API's, the dispatcher's and Temporal's modules.
5. After authentication: the endpoint's limit, parsing and splitting (objects only), ids and deduplication, sealing,
   the recording function's outcome mapped to 200, 409 or 429, 200 only after the commit. Checked against Mist's own
   documentation: whether a Mist webhook can send a bearer token (ruling 2); the guide documents that path only if so.

**M3. Matching and management**
6. The matcher, as "Functions and lock order" says: every dispatcher, only while the gate is on, fair across tenants,
   its rechecks inside the transaction, the fan-out cap, the races tested.
7. Outcomes: `dead` only for a confirmed event-specific failure (its ciphertext doesn't authenticate while its key
   version is present and opens other events; its payload isn't a JSON object) or after 5 event-specific attempts
   backing off; a platform-wide failure waits with backoff and an alert, attempts untouched (§10.5); the recount.
8. The API (ruling 10): endpoints and bindings written with `trigger.manage` and read with `workflow.view` (the secret
   shown once, at creation and rotation; filters and the binding cap checked); events' metadata read with
   `workflow.view`, never a payload; **dead events listed, and pending or dead events cancelled, with `tenant.manage`**
   (admins), audited, counters released; the tenant's backlog and retained usage.

**M4. Proofs, Compose and docs**
9. End to end with the keyring's real keys: canaries in an event, an HMAC secret and a bearer token appear in no raw
   history, projection, stored row in plain, log line or audit entry; replay outside the tolerance refused; the
   limits, quotas and the retained cap; a crash before matching commits; the gate off (recorded, not matched).
10. The local load probe (ruling 12), not in CI: latency, memory, rate and quota behavior, matcher throughput, each
    limit measured separately; its results recorded for revision 9 and the provisional values revisited with the owner.
11. Compose: the `ingress` service, nginx's `/hooks/` route, the login; one bounded CI step posting a signed event
    through nginx and waiting for its run (about 1 more minute of the runner per e2e run); a guide for ingress
    (endpoints, signing, ids and their at-least-once effect, limits, events, the production gate).

## Revision 9 of the 2b spec (lands with the plan)

§8.3 with the sections above (deduplication, the functions and lock order, the work limits, retained storage, the
event schema, the trigger as the event object, the matcher's fairness and fan-out, the responses and their order, the
production gate on ingress); §9 (ingress's responses, event statuses and reasons); §14 and §15 (tables, grants,
functions, provisional values); §12 (the proofs, the load probe); §6.4 (the ingress key and the keypairs in key
retirement); §7.9 (what stays open before production: rotation, retirement, retention, erasure, the probe's values);
the parent spec's outbox, `app_*` roles and resolver noted in §13.

## The owner's rulings (2026-10-04)

1. One 2b-3b sub-project; checkpoints after M1, M2 and M3, then M4 and a whole-branch review.
2. Timestamped HMAC over the exact raw body, or a high-entropy bearer token. No claim of direct Mist HMAC
   compatibility in 2b-3b; confirm whether Mist can send a bearer token before documenting that path.
3. The resolver and recording functions, no ingress table grants: pinned `search_path`, public execution revoked, the
   tenant derived from the endpoint's row, one lock order across ingress and matcher counter updates.
4. Dedupe on a verified sender id (with the item's index for a batch-level header id); never by identical bytes;
   id-less events accepted as distinct (at-least-once, documented) or an id required per endpoint; an id reused with
   other content refused; the internal-event-id request key; one binding per endpoint and workflow.
5. The uniform bodiless 401; only a global body cap before authentication; endpoint-specific 413 and 429 and the JSON
   and pointer 400 after it; a batch all or nothing; duplicates bypass the quotas, not the rate limits.
6. The unwrapped event as the trigger, each split event a JSON object; malformed structure a 400 before recording; an
   object a workflow's schema refuses is its durable `input_invalid` refusal.
7. Limits provisional: event and byte work bounded too, and ingress concurrency; the event budget measured separately;
   the probe justifies final defaults.
8. Keys versioned now, failing closed when a version is missing; no production ingress until 2b-4 supplies rotation,
   key retirement and erasure handling.
9. Matching on every dispatcher only while the gate is on; fair across tenants, FIFO within one; fan-out capped as well
   as the batch; the gate and the tenant rechecked in the matching transaction; duplicate insertion raced against
   matching for deadlocks.
10. Admin-only recovery: `trigger.manage` writes endpoints and bindings, `workflow.view` reads event metadata,
    `tenant.manage` lists dead events and cancels pending or dead ones.
11. Trusted proxies, none by default; forwarded addresses resolved from the trusted end of the chain; spoofed headers
    tested through nginx and directly.
12. A bounded local load probe, not in CI, recording latency, memory, rate and quota behavior and matcher throughput;
    one signed-event Compose CI step.
13. A cap on all retained event rows and bytes until 2b-4's deletion, failing closed with 429; production ingress
    unexposed until retention and erasure exist.

**Open and separate:** issues #16, #18 and #26; §7.9's production items; 2b-3a's deferred minors; 2b-4 (retention,
the erasure transition, key rotation and retirement, lifting the gate on ingress and on runs).
