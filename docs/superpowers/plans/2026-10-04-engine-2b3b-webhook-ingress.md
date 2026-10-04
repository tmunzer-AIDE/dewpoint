# Engine 2b-3b: Webhook Ingress Implementation Plan

> **Status: outline, for the owner's decisions.** As in 2b-1a, 2b-1b, 2b-2 and 2b-3a, each task will be built and
> tested on a prototype branch from `main` first, with the owner's checkpoint after each milestone; the plan is then
> written from the tested diffs, each replayed tests-first, with a revision of the 2b spec, for the owner's review
> before execution. Nothing is prototyped before the owner rules on the decisions below.

**Goal:** a webhook a sender posts to Dewpoint becomes runs: `dewpoint ingress` authenticates it, splits it into
events and records each sealed to its tenant, and the dispatcher matches each event to its bindings, admitting one
request per matching workflow through `admit_request`.

**Architecture:** two halves that share only the `inbound_events` table (§8.3).
- **Ingress** (a new process and login, `/hooks/<endpoint_id>`) never holds a tenant's data key. It resolves the
  endpoint through a SECURITY DEFINER function, checks size, address, rate and authentication, seals each event to the
  tenant's X25519 public key, and records it, pending, under the backlog's quotas, answering 2xx only once committed.
- **The dispatcher** matches only while the gate is on: it claims pending events, opens each with the tenant's private
  key (wrapped by the tenant's data key), and, in one transaction per event, admits a request for each binding whose
  filter matches, recording the event `matched` or `unmatched`.

**Tech stack:** Python 3.12, FastAPI (the ingress app), SQLAlchemy async with asyncpg, Alembic, PostgreSQL 16 (forced
row-level security, SECURITY DEFINER functions), `cryptography` (X25519, HKDF, AES-256-GCM, HMAC), Typer, Compose and
nginx. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 8 (merged with 2b-3a): §8.3, with §2.5,
§6.4, §6.5, §7.2, §9, §10.1, §12, §14 and §15; engine-core revision 5.11; the parent spec's §3.1, §4.4, §6.1 and
§12. This plan's revision 9 of the 2b spec lands with it.

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
- **Keys.** Tenant data keys (AES-256, versioned, wrapped by the KEK) seal values under a purpose and a context
  (`claim`, `secret_index`, `connection.secret`, `csv.upload`, `csv.mapping`, `schedule.input`); the only HKDF derives
  the request-digest key. There's no asymmetric encryption (only Ed25519 audit anchors), no `DEWPOINT_INGRESS_KEY`
  and no re-encryption command. `create_tenant` and `dewpoint keys ensure-tenants` are where a tenant's keys are made.
- **The dispatcher's cycle** observes, dispatches and reports, and its leader reconciles, sends cancels, syncs
  schedules and reads misses. A step is a function returning counts, reading across tenants through an ids-only
  SECURITY DEFINER candidates function, each item in its own tenant-scoped transaction; `SKIP LOCKED` is already used.
- **Rate limits.** Only a fixed-window `auth_throttle` table (login throttling). No token bucket, backlog counter or
  quota exists.
- **The API process** has no CLI command: the image's default command runs uvicorn on the API's app factory. The API's
  body limit buffers 1 MiB, and its `/api/`-only client-header check wouldn't touch `/hooks/`.
- **Compose and nginx.** nginx routes `/api/` and `/health/` to `api`, with a 6 MiB body cap; the e2e job runs a
  dispatched run and the schedule proof. Adding ingress touches nginx, a Compose service, the init script's logins,
  the env files, CI's env step, the Compose tests and the deployment guide.
- **Tenancy.** `tenants.status` is `active` or `erasing`; admission, dispatch and ticks check it. Nothing sets it
  (2b-4's erasure transition), and there's no retention job (2b-4).
- **The parent spec** (§3.1, §4.4, §6.1) has the shape: `POST /hooks/{endpoint_id}`, a resolver returning only the
  tenant, the verification mode and its material, 128-bit random endpoint ids, the tenant never taken from the payload,
  events unique on a dedupe key, 2xx after commit, the dispatcher claiming with `SKIP LOCKED`. §8.3 replaced its outbox
  and roles, and added sealing, the ingress key and the quotas.

## Milestones and tasks (first cut)

**M1. Keys, the event store and the resolver**
1. The ingress key: `DEWPOINT_INGRESS_KEY` (and its id), read by ingress and the API only; endpoint secrets sealed
   under it (HMAC secrets, each endpoint's dedupe-digest key); bearer tokens stored as SHA-256 digests.
2. The tenants' inbound keypairs: `tenant_event_keys` (tenant, version, public key, private key sealed with the
   tenant's data key, purpose `event.private`), made by `create_tenant` and `keys ensure-tenants`; the sealing
   primitive (an ephemeral X25519 key, HKDF-SHA256, AES-256-GCM; the tenant, endpoint, event id and key version as
   associated data), with known-answer, tamper and wrong-key tests.
3. The tables, forced row-level security and grants: `webhook_endpoints` (with their counters and token bucket),
   `trigger_bindings`, `inbound_events`, the tenant's event counters; `resolve_webhook_endpoint()` and the recording
   function (decision 3), executable by `dewpoint_ingress` only; the ingress login (Compose's init, env, CI) and its
   test sessionmaker. Migrations upgrade, downgrade and upgrade again over existing rows.

**M2. The ingress process**
4. `dewpoint ingress` (its own app, CLI command and `/health`), `POST /hooks/<endpoint_id>`: the body read as it
   arrives up to the endpoint's size limit; the client address (decision 11) against the allowlist; the token bucket;
   authentication in constant time (decision 2); one refusal for every failure that could tell an endpoint exists
   (decision 5). An import contract keeps it from the API's, the dispatcher's and Temporal's modules.
5. Events: split by the array pointer, each event's id by its pointer or header, the dedupe key (decision 4), sealed,
   recorded in one transaction under the endpoint's and the tenant's quotas (429 with `Retry-After` past either), an
   authenticated duplicate acknowledged even at quota, an `erasing` tenant refused with nothing recorded, 2xx only
   after the commit.

**M3. Matching and management**
6. The matcher (decision 9): `event_candidates()` (ids only), an event claimed with `SKIP LOCKED` while the gate is on,
   opened with the tenant's private key, matched against its endpoint's bindings (typed JSON-pointer equality, no CEL),
   one `admit_request` per matching binding in workflow-id order under `evt:<event id>:<workflow id>`, the event
   `matched` (with its request count) or `unmatched`, counters released, in one transaction; a crash before the commit
   leaves it pending.
7. Outcomes: `dead` only for a confirmed event-specific failure (its ciphertext doesn't authenticate while its key
   version is present and opens other events; its payload isn't JSON) or after 5 event-specific attempts backing off;
   a platform-wide failure waits with backoff and an alert, attempts untouched (§10.5); a periodic recount corrects the
   counters' drift.
8. The API (decision 10): endpoints (the secret shown once, at creation and rotation), bindings (their filters
   checked), events (metadata only, never a payload; cancel one or an endpoint's pending ones, audited, counters
   released; dead events listed), and the tenant's backlog.

**M4. Proofs, Compose and docs**
9. End to end with the keyring's real keys: canaries in an event's payload, in an HMAC secret and in a bearer token
   appear in no raw history, projection, stored row in plain, log line or audit entry; replay outside the tolerance
   refused; the quotas and the rate limit; a crash before matching commits; the gate off (recorded, not matched).
10. A local load probe (decision 12), its results recorded for revision 9.
11. Compose: the `ingress` service, nginx's `/hooks/` route, the login; one bounded CI step posting a signed event and
    waiting for its run (decision 12). `docs/operations/` (a guide for ingress: endpoints, signing, limits, events).

## Revision 9 of the 2b spec (lands with the plan)

§8.3 with the rulings below (the signing scheme, the responses, the recording function, the keys and their lifecycle,
the trigger input, the matcher's placement and limits); §9 (ingress's responses, event statuses and reasons); §14 and
§15 (tables, grants, functions, provisional values); §12 (the proofs, the load probe); §6.4 (the ingress key and the
keypairs in key retirement); §7.9 (what this leaves open before production); the parent spec's outbox and `app_*` roles
noted in §13.

## Decisions for the owner

1. **Scope.** *Recommended:* one sub-project, the four milestones above, prototype first, with checkpoints after M1,
   M2 and M3, then M4 and a whole-branch review, as in 2b-3a. Ingress without the matcher would record events nothing
   reads, so they aren't split.
2. **Signing.** HMAC-SHA256 over `<timestamp>.<raw body>`, the timestamp and signature in headers (names configurable
   per endpoint, with Dewpoint defaults), within a tolerance (5 minutes by default, 1 to 15); or a bearer token.
   *Recommended:* only these two in 2b-3b. Mist signs its webhooks over the body alone, without a timestamp, so a
   replay can't be refused by age, only deduplicated; supporting it belongs to sub-project 3's Mist trigger, as the
   2b-3 outline proposed. Until then a Mist sender would authenticate with a bearer token, if it can send one; the
   prototype checks what Mist can send before this is final.
3. **How ingress writes.** *Recommended:* ingress gets no table privilege at all: it calls `resolve_webhook_endpoint()`
   and one recording function (both SECURITY DEFINER), which, in one transaction under the endpoint's then the
   tenant's row locks, takes a token, checks the quotas, inserts the events (skipping duplicates), moves the counters
   and returns each event's outcome. The alternative, RLS-scoped inserts plus a function for counters and buckets,
   gives ingress a table grant and splits one decision across two writers.
4. **Dedupe and request keys.** *Recommended:* the dedupe key is always an HMAC under the endpoint's dedupe-digest key
   (of the sender's event id, or of the event's bytes when it has none), so a sender's id is never stored plain; the
   request key is `evt:<inbound event's own id>:<workflow id>`, never the sender's id, since idempotency keys are
   plain metadata. A replay within the tolerance is deduplicated, not refused.
5. **Responses.** *Recommended:* one 401, with no body detail, for an unknown or disabled endpoint, a disallowed
   address, a failed authentication and an `erasing` tenant, so none tells a sender the endpoint exists; 413 past the
   size limit; 429 with `Retry-After` past the rate limit or a quota; 400 for an authenticated body that isn't JSON or
   whose pointers don't resolve, with nothing recorded; 200 with the counts accepted and duplicated, once committed.
6. **The run's trigger.** *Recommended:* the event itself, as §8.3 says, validated against the bound workflow's input
   schema as any trigger is (a mismatch is a `refused` request, `input_invalid`); no headers, no envelope. The
   alternative wraps it (`{"event": …, "endpoint": …, "received_at": …}`), which every bound workflow's schema would
   then have to declare.
7. **Limits.** *Recommended*, provisional (§15): an endpoint's body 1 MiB by default, 5 MiB at most (nginx allows
   6 MiB); at most 500 events a request; a token bucket of 20 requests a second, bursts of 100, per endpoint; the
   quotas §15 already gives (10,000 events and 64 MiB per endpoint, 50,000 and 256 MiB per tenant).
8. **Key lifecycle.** *Recommended:* keypairs made with the tenant and by `keys ensure-tenants`, versioned from the
   start; rotating a keypair, rotating the ingress key, and re-wrapping private keys before a data key retires (§6.4)
   are 2b-4's, with key retirement. A data key's rotation needs nothing here: its older versions stay readable.
9. **The matcher.** *Recommended:* a step of every dispatcher's cycle (not the leader's), after dispatch, only while
   the gate is on and the dispatch-time checks hold; up to 50 events a cycle, oldest first within a tenant; an
   `erasing` tenant's events left pending, for erasure to cancel (2b-4). Gate off: events wait, attempts untouched.
10. **Management and permissions.** *Recommended:* endpoints and bindings written with `trigger.manage` (editors and
    up) and read with `workflow.view`; events read with `workflow.view`, metadata only; cancelling events with
    `trigger.manage`. §8.3 says admins see dead events and cancel them: with `trigger.manage` that's editors and up;
    `tenant.manage` would keep it to admins.
11. **The client's address.** *Recommended:* ingress trusts `X-Forwarded-For` only from configured proxy networks
    (`DEWPOINT_INGRESS_TRUSTED_PROXIES`; in Compose, nginx's), and checks the allowlist against the address that
    gives; without a trusted proxy, the connection's address.
12. **Proofs.** *Recommended:* the load test (§12, parent §12) as a local probe whose results go into revision 9, not
    a CI job; one bounded CI step in the e2e job (an endpoint and a binding made through the API, a signed event
    posted through nginx, its run waited for), about 1 more minute of the runner per e2e run.
13. **Erasure and retention.** *Recommended:* ingress and the matcher refuse an `erasing` tenant now; cancelling its
    pending events belongs to 2b-4's erasure transition, with the schedules' pause (§7.9); deleting terminal events
    is 2b-4's retention. Until then terminal events stay, and the quotas count only pending ones.

**Open and separate:** issues #16, #18 and #26; §7.9's production items; 2b-3a's deferred minors; 2b-4 (retention,
the erasure transition, key rotation and retirement, lifting the gate).
