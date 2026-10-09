# Sub-project 3 — ledger

The outline (`docs/plugins-3-outline`, revision 5, 02b7e62) was approved as recommended by the owner on 2026-10-06
(D1–D28). This file records, per slice, the tasks, the mid-slice rulings ("Ruling: what - why - cost if wrong") the
owner rules on at the checkpoint, and open questions.

## Deferred: the API's preflight on creation and host-setting updates (D7, D8)

Recorded 2026-10-08 on the owner's word, from a check of `origin/main` f0e7bf55 and five review rounds. Nothing is
built; its owning slice, 4g in the editor UI 4 outline (`2026-10-05-editor-ui-4-outline.md`), is proposed, pending
approval.

**The gap.** The API's connection create and update (`core/connections/service.py`) run only the type's declared checks;
only the worker builds the guard (`apps/worker/main.py`). No 3a-1 or 3a-2 task or ruling planned or dropped vetting at
creation. An API client can create a connection to a destination the guard refuses (3c-1, unmerged, adds a generic
webhook whose pattern admits `localhost`, private and link-local addresses): it is saved and fails, fatally
(`EgressRefused`), at its first connect. Deferring is acceptable because the worker's check on every connect is
mandatory and authoritative, not because nobody can reach the gap. Migration 0041 already grants `dewpoint_api` a
tenant-scoped SELECT on `egress_allowlist`; it stays for the preflight.

**Scope.** Destinations a tenant chooses: a `url_field` config value and a secret URL (`secret_url`); host maps fixed by
the plugin (Mist) get no lookup. It runs on creation and on any update that supplies a host-setting value: a secret-only
update of a secret URL, a changed `url_field` with or without a new secret, on a type with or without secret fields. A
name-only edit does no lookup.

**Design.**
1. First transaction: authorization, the declaration and the body; the URL parsed and its host's shape checked (a
   malformed host is a 422, before any DNS); the declaration's hash kept; then committed, so no pooled connection,
   lifecycle lock or row lock is held during the lookup.
2. The lookup, outside any transaction (a literal address needs none): `socket.getaddrinfo` on a dedicated executor of N
   threads, never `loop.getaddrinfo`, which under uvloop (the API's loop) runs on libuv's shared pool, the one asyncpg's
   connects use. N permits, each released only when its lookup's thread finishes, not when the caller times out; with no
   free permit the lookup is skipped at once (`busy`), never queued. The request waits up to a timeout.
3. Write transaction, in a new session (a repeat query in the first session returns its loaded objects unrefreshed): the
   whole sign-in chain again from the request's cookie and CSRF header (session validity and revocation, the active
   state, the user's `is_active`), then `require()`'s checks (the lifecycle lock, membership, role, the passkey
   requirement, the tenant's status) and the tenant scope, through one function shared with the dependencies, which keep
   their order and errors; the connection locked and reloaded (404 when deleted); the declaration's hash compared (409
   when it changed); `secret_required` applied against the locked row; the tenant's and every tenant's allowlist entries
   read, and the already-resolved addresses checked with the worker's port (explicit, or the scheme's default) and
   plaintext rule (`http` needs an entry), through a verdict function split out of `Guard.vet` so the worker and the API
   share it; then the write and its audit entry.

**Outcomes.** A refusal is a 422 `destination_refused` naming the field only (never the host, an address or the reason),
with nothing written. `unresolved` (a DNS failure or no answer), `timeout` and `busy` save the connection with a "not
checked" warning, recorded in its audit entry: an advisory preflight, not a completed check. An allowlist read failure
or any other error is a server error, never an acceptance. The web form shows the warnings (4g); a response field alone
is not feedback.

**Tests** (a fake resolver, no real DNS; counted in work units, not time): secret-only updates; a `url_field` change on
a type without secret fields; name-only edits and Mist doing no lookup (resolver calls counted); `http` refused without
an entry and accepted with one; explicit and default ports against an entry's range; mixed public and private answers;
tenant and every-tenant entries, another tenant's not honoured; a refusal leaving the row unchanged with no audit entry;
`unresolved`, `timeout` and `busy` warned, a malformed host and an allowlist failure not; during a blocked lookup, the
pool's checked-out count at its baseline, an exclusive lifecycle lock takeable and the row lockable `NOWAIT`; an edit, a
deletion and a declaration change between the transactions; a logout, a token rotation, a disabled account and a rotated
CSRF token during the lookup; repeated timeouts while lookup threads are still blocked (the next request `busy` at once,
the permits back when the threads finish).

**Open for 4g's rulings:** N and the timeout (proposed: about 4 lookups and 2 s); the warnings' shape in the response.

## 3a-1 Egress and connections at run time

Branch `feat/plugins-3a1` from `origin/main` 6482c53.

**Checkpoint:** the owner approved every 3a-1 ruling below as recommended (at 33a29b4, 2026-10-06), including the
revised rulings on a failure after a send, quota identity across a key rotation, and missing connections in a
closure. Pushing, a PR, 3a-2 and the flaky-test issues are not yet approved.

Tasks (test-first, in order):
1. `core/egress`: address classification, the allowlist, the guard's vetting (D7, D8).
2. Migration 0041: `egress_allowlist`, `rate_buckets` (D25).
3. Guarded HTTP transport: resolve, vet, pin, TLS by hostname, no proxies, redirects, caps, outcome errors (D7).
4. Guarded TCP/TLS/UDP for `ctx.net` (D7).
5. Rate buckets: scopes, acquire, cooldown, `Retry-After` (D9, D10), and the connection's current cooldown.
6. Connection fields: the SDK marker, the engine's sites, publish checks and `connection_ids`, 409 on delete (D6).
7. `ctx.connection()` in the worker: allowed ids, tenant and type, per-call decryption, the secret index, auth applied
   by the runtime, simulate refused (D4, D5).
8. SDK 0.2.0 surface and the activity wrapper's mapping of transport errors; flow@1 hashes unchanged (D12).
9. `dewpoint platform egress add|list|remove`, audited (D8).
10. Proof: testkit nodes through RunGraph against local fakes.

Rulings:
- Ruling: the feature branch starts from `origin/main`, not from the docs branch - the outline is reviewed and merged
  on its own, as for 2b-3b - cost if wrong: one rebase onto the docs merge.
- Ruling: until 3a-2 moves connection types into manifests, `core` keeps the `mist` type and gains its declared auth
  (`header`: `Authorization: Token {api_token}`) and rate scopes - D11 lands in 3a-2 - cost if wrong: none; 3a-2
  replaces the declaration.
- Ruling: the SDK's transport errors (`EgressRefused`, `NotSent`, `MaybeSent`) are mapped by the activity wrapper with
  fixed codes: refused is fatal, not sent is retryable, maybe sent is `outcome_unknown` for an ambiguous node and
  retryable otherwise - D7's "the node's policy decides" made explicit, so a plugin that doesn't catch them is still
  classified safely - cost if wrong: a plugin wanting another mapping catches the error itself.
- Ruling (revised after the second review): a credential's quota scope is an HMAC under a per-tenant random scope key
  (`rate_scope_keys`, sealed under the tenant's data key, purpose `rate.scope`), made once by the worker and read by
  the API - workers may hold different data-key versions for 300 s, and a key derived from the active version split a
  token's budget and bypassed its cooldown - cost if wrong: one more sealed row per tenant, which 2b-4a's
  re-encryption and key retirement must cover (dependency, below).
- Ruling: the guard blocks multicast, reserved, IPv6 site-local and any non-global embedded IPv4 on top of
  `is_global` - Python 3.14 calls multicast, `fec0::/10`, `::127.0.0.1` and NAT64-wrapped loopback global - cost if
  wrong: a NAT64-only deployment needs allowlist entries for its translated destinations.
- Ruling: plain TCP and UDP (`ctx.net`) need an allowlist entry, as plain http does - D7 states it for http; the same
  exposure applies - cost if wrong: a public syslog/UDP target needs an entry.
- Ruling: a TLS verification failure is fatal, not retried - nothing was sent, but retrying can't fix a certificate
  - cost if wrong: a certificate fixed mid-run needs a new run.
- Ruling: `ResponseTooLarge` and `RedirectRefused` end an ambiguous node `outcome_unknown` and fail any other - the
  request was sent and answered, and a retry gets the same answer - cost if wrong: a flaky oversized answer fails.
- Ruling: an unknown `TransportError` subclass is treated as any unexpected exception (retryable, `outcome_unknown`
  for an ambiguous node), and only the SDK's own class constants are ever shown - a plugin can't widen what's shown
  - cost if wrong: none.
- Ruling: a plugin that sets its connection's credential header (`Authorization`) is refused (`invalid_request`), not
  silently overridden - fail closed - cost if wrong: a node needing a second Authorization-like header can't.
- Ruling: a `Retry-After` (429, or 503 with one) blocks the connection's scopes for every node, whatever its side
  effect, and a plain 503 is returned to the node - D10's block is about the provider, not the node - cost if wrong:
  none; the block is capped at an hour.
- Ruling: until 3a-2, only header auth (`HeaderAuth`) is implemented; `url`, `basic`, `body_field` and `smtp_login`
  land with the slices that need them (3c, 3d) - YAGNI - cost if wrong: none.
- Ruling: a connection's allowed ids are read by the worker from the run's version graph, intersected with the
  version's `connection_ids`, and the graph node's type must equal the step's node type - nothing from the workflow's
  input is trusted - cost if wrong: none.
- Ruling (revised after the second review): publish checks the connections its nodes name and every connection its
  closure's versions name (pinned sub-flows, failure handler), locked FOR SHARE; enabling and activating refuse a
  closure naming a connection that no longer exists (`connection.missing`) - fail closed, before anything runs - cost
  if wrong: none; a run still fails `connection_unavailable` before sending if one disappears another way.
- Ruling: the allowlist audit goes to the tenant's chain (an entry for every tenant to the platform's), actor NULL as
  for other CLI actions - cost if wrong: none.
- Ruling: the egress allowlist and rate buckets are read on every connect/request (no cache) - exactness over a query
  per request - cost if wrong: one small query per connect and per request.

- Ruling (revised after the second review): once a request of an attempt may have left, or is still under way, an
  ambiguous node's failure is never retried and its outcome is unknown, the node's own `FatalError` included - a later
  failure can't establish what an earlier request did - cost if wrong: a definite refusal after an earlier write shows
  as unknown, for a person to check.
- Ruling (checkpoint review): an allowlist entry is sensitive, and needs `--allow-sensitive`, when its prefix is
  shorter than /8 (IPv4 or IPv6) or it overlaps loopback, link-local (cloud metadata), unspecified or multicast - cost
  if wrong: an operator confirms a legitimate broad range explicitly.
- Ruling (checkpoint review): responses are asked `Accept-Encoding: identity`; a gzip or deflate answer is inflated
  within the cap; any other encoding fails `response_unreadable` (sent and answered) - cost if wrong: a provider that
  answers br regardless can't be read.
- Ruling (checkpoint review): `Retry-After` is read as ASCII delta-seconds or an HTTP date, clamped to an hour; inside
  an attempt a node resends at most 3 times, waiting at least 1 s each - cost if wrong: none.

Checkpoint review (fresh-context reviewer, 2026-10-06): no SSRF bypass, secret leak or cross-tenant path found. Eight
findings, all fixed test-first in edace9b: (1, High) an ambiguous node retried after an earlier send in its attempt;
(2) a reconcilable node resending inside its attempt; (3) `Retry-After: 0` looping; (4) strange `Retry-After` values
raising after a send; (5) a bucket's refill time moving back; (6) gzip inflating past the cap before the check;
(7) near-everything allowlist entries; (8) `ctx.net`'s TLS trust read from the environment, an unbounded `receive`,
uncapped redirect hops, framing headers set by a plugin. The self-review's own four (a database outage before a send,
best-effort blocks, and (2)) are in the same commit.

Second checkpoint review (2026-10-06, pasted by the owner): three findings, all fixed test-first in fd3105c: (1, High)
a request still under way when a concurrent call failed left the attempt retryable; (2) a truncated gzip stream was
accepted and only the first gzip member decoded; (3) publish didn't check connections named by the pinned closure. Its
recommendations on rulings 4, 7 and 8 (above, revised) were taken as the fail-closed options, for the owner's ruling.

Dependency for 2b-4a (data lifecycle): `rate_scope_keys.sealed` is sealed under a tenant's data key (purpose
`rate.scope`, the tenant id as context). Re-encryption must re-seal the same plaintext key under the new data key,
never generate a new one (a new key splits every credential's budget and cooldown again), and key retirement must
count it among the ciphertexts that still need a version; tenant erasure removes it by its foreign key (cascade).
The fix review (2026-10-06) also checked that workers on different data-key versions converge on one stored key on
first use, which the API opens.

CI on PR #40 (2026-10-06), two fixes:
- Ruling: the guard keeps its own table of IANA special-purpose ranges and reads an IPv4-mapped address as its IPv4;
  `ipaddress`'s flags can only add a refusal - CI's CPython 3.12.3 called `::ffff:8.8.8.8` reserved, and 3.12.4
  changed the stdlib's tables (CVE-2024-4032), so the verdict depended on the interpreter's patch level - cost if
  wrong: a few globally reachable special-purpose addresses (6to4, `192.0.0.9`, parts of `2001::/23`) need an
  allowlist entry.
- Ruling: a credential's scope is a CMAC-AES-256 of it under the tenant's scope key, not an HMAC-SHA256 - CodeQL's
  `py/weak-sensitive-data-hashing` fails the private-repository gate on any digest of a credential, though a keyed MAC
  under a random sealed key can't be guessed offline; CMAC (NIST SP 800-38B) is the equivalent keyed PRF - cost if
  wrong: none; nothing was stored under the old function (unmerged).

Local verification of these fixes at 48f427b (reported by the owner, 2026-10-06; GitHub Actions minutes are exhausted,
so CI didn't run):
- CPython 3.12.3: at 22d508b the mapped-address failure reproduced exactly (166 other targeted tests passed); at
  48f427b all 170 targeted tests passed.
- Isolated Compose proofs (2m48s): migration 0041, forced RLS on `rate_scope_keys`, worker startup, a published
  workflow's run, a non-UTC schedule, a signed webhook (duplicates handled; a trickled body answered 408 after 10.01 s).
- CodeQL (run locally with the owner's OK): CI's versions (CLI 2.27.1, `codeql/python-queries` 1.8.11), the same 45
  queries and query filter, over the whole tree. The baseline finding reproduced exactly at 22d508b
  (`py/weak-sensitive-data-hashing`, `scopes.py:48`) and is absent locally at 0714c2e, with no other finding. That is
  not a guarantee of zero in CI: the platform (macOS arm64 here, Linux x64 there) and extraction can differ. Whether
  CodeQL's licence covers this repository is unconfirmed (open questions).
- Not verified: the backend job under `act`, and the browser E2E tests (3a-1 changes no frontend file).

Open questions:
- CodeQL licensing (the owner's to confirm): the CLI's terms (`LICENSE.md` in 2.27.1) allow use with a codebase not
  released under an OSI-approved licence, the terms' example being code in a private GitHub repository, only under a
  paid GitHub Advanced Security licence. This repository is private (it has an Apache-2.0 `LICENSE`), and the CI
  CodeQL log says code scanning isn't enabled for it (which doesn't establish whether a licence exists). The
  entitlement is unconfirmed. Until it's confirmed, the hold covers local runs and CI execution (the owner,
  2026-10-06): a push to #40 would start the `codeql` workflow, so the question must be settled before a push is
  authorized. The workflow also starts on any push to a pull request (#39 too), on every push to `main` (a merge), and
  on its weekly schedule (Mondays 04:23 UTC: it last ran on 2026-10-05, so the next run is due on 2026-10-12 without
  any push). Disabling it or removing the schedule is a CI change: the owner's call.
  The owner disabled the `codeql` workflow on GitHub on 2026-10-06 (state `disabled_manually`, no repository file
  changed; no run queued or running). While disabled it starts on no push, pull request or schedule, and #40 keeps its
  failed `analyze (python)` check from 22d508b. Re-enabling it waits for the licence question.
- `tests/apps/dispatcher/test_triggers_end_to_end.py::test_a_short_outage_fires_each_missed_time_and_admits_each_once`
  failed once in the full parallel run under extra load (a 4 s tick gap on Temporal's dev server where 2 s was
  expected) and passes alone; this slice touches no schedule or dispatcher code. Load-sensitive, not a regression.
- An intermittent `PytestUnraisableExceptionWarning` (a `GeneratorExit` in RunGraph's `_drive` while Temporal tears down
  a terminated batch) comes from `tests/apps/worker/test_real_server.py::test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used`;
  3a-1 changes no engine code. Pre-existing, worth its own issue.

## 3a-2 Plugin calls and connection types

Branch `feat/plugins-3a2` from `origin/main` 15084df (3a-1's merge), started 2026-10-06 on the owner's word. Migration
0042 chains from 0041; 2b-4a holds 0035-0040 and the editor UI 0043-0046.

Tasks (test-first, in order):
1. SDK 0.3.0: `Option` and `Node.options(ctx, field, query)` for fields marked `options_field`; a node's `icon`;
   `ConnectionType` declared in a plugin (key, label, config and secret models, auth, host rule, rate scopes,
   `verify(ctx, config)`); the outside-run context (D3: read-only `http`, a connection's read-only `http`, no `net`).
   Manifest keys `connection_types` (plugin), `icon` (node, display) and `options` (node), each emitted only when set;
   flow@1's hashes unchanged (D12).
2. The catalog validates the new keys as data; `icon` joins `_DISPLAY`.
3. `mist` leaves `core` for `dewpoint.plugins.mist`, its shape unchanged: the same schemas, auth and scope keys (D11).
4. The API reads connection types from synced manifests: schema validation, the type list, cooldowns' scope keys.
5. Migration 0042: `plugin_calls`, its candidates and sweep functions, RLS and grants (D3, D25).
6. The worker serves plugin calls: candidates for its build's refs and types, claim (`SKIP LOCKED`, claim token,
   lease), the hook under the outside-run context, the fenced result write, encrypted; the sweep (D3).
7. The API: options for a node's config (`connection.use`), verify through a plugin call (compare-and-set on the
   revision kept), the start form's picker options; waits up to 10 s, then deletes the row (D3).
8. Publish checks `x-dewpoint-picker` in the input schema and records its connection in `connection_ids` (D19).
9. Flow completion (D19): icons for the 11 flow nodes, `x-widget` hints on CEL fields; flow@1's hashes unchanged.
10. Proof: a site picker end to end (API, `plugin_calls`, worker, a test node's `options()` through a Mist connection,
    a local Mist fake), and Mist verify end to end.

Rulings:
- Ruling: the branch starts from `origin/main` 15084df (3a-1 merged), not from the docs branch (#39 still open) - as
  for 3a-1 - cost if wrong: one rebase.
- Ruling: the SDK becomes 0.3.0 - 3a-1 shipped 0.2.0 with part of D12; a new surface under the same number would make
  "0.2.0" mean two things - cost if wrong: none (the catalog checks the major only).
- Ruling: no Mist node type ships in 3a-2; the proof's picker node is test-only - a registered node type version stays
  until retired (sync refuses a build without it), and 3b-1 generates the Mist nodes (D23) - cost if wrong: the site
  picker isn't usable in the product before 3b-1.
- Ruling: the `mist` plugin declares only its connection type, and a plugin may declare connection types without
  nodes - the type has to leave `core` now (D11) and has no node yet - cost if wrong: none.
- Ruling: a connection type's hosts and quota scopes are declared as data, not code - the API never runs plugin code
  (spec §3.3) yet shows each scope's cooldown (D10), so both sides compute the same keys from one declaration - cost
  if wrong: a scope that needs computing (3c's Slack workspace from a URL) needs a new declarative form.
- Ruling: a connection type's key is its plugin's name or starts with it and a dot - two plugins can't then declare the
  same key (plugin names have no dots) - cost if wrong: 3c's types are named `messaging.slack` and so on.
- Ruling: the config and secret models of a connection type forbid extra fields, its secret fields are `SecretStr`, and
  the fields its host, auth template and rate scopes read are required - the API validates and computes from the
  stored values as written, the worker from validated ones, so a default or an extra key would make them differ - cost
  if wrong: a provider field with a sensible default must still be written.
- Ruling: a plugin call waits at most 2 s for a quota token and never resends after a 429 or 503 - the API waits 10 s
  for the whole call, and nothing outside a run is retried - cost if wrong: a busy connection's picker fails `cooldown`
  sooner.
- Ruling: an answer holding any string of a secret the call opened is refused (`result_refused`), not masked - a hook
  outside a run has no secret index, and the person asking may not hold `connection.manage` - cost if wrong: an option
  that legitimately contains a token-like string can't be listed.
- Ruling: at most 1,000 options, a value of 1,000 characters and a label of 1-200, 256 KiB in all; option values are
  strings - cost if wrong: a long list needs the typed text to narrow it.
- Ruling: options calls check the connection's revision too, not only verify - fail closed - cost if wrong: an options
  list asked just before an edit fails `connection_changed` and is asked again.
- Ruling: a call's typed text (at most 200 characters) is stored as written, its answer sealed - the text is what the
  person typed, the answer is the provider's data - cost if wrong: none.
- Ruling: NOTIFY carries nothing (every role may listen on a channel); workers also poll every second - cost if wrong:
  one cheap query a second per worker.
- Ruling: a failure shows the SDK's own transport error codes, or a fixed code (`timeout`, `plugin_failed`,
  `connection_changed`, `invalid_field`, `invalid_result`, `result_refused`, `result_too_large`, `unavailable`) -
  as in runs - cost if wrong: none.

Dependency for 2b-4a (data lifecycle): `plugin_calls.result_ct` is sealed under a tenant's data key (purpose
`plugin.call`, the call's id as context). A call becomes deletable 90 s after it was asked (30 s to expiry, then a
minute) and is deleted by the API at once or by a worker's periodic sweep, but that is no bound: without a working
sweeper a row can survive indefinitely. Key retirement must check the `plugin_calls` rows that still hold a ciphertext
of the version (the owner's correction), never rely on the duration; tenant erasure removes calls by their foreign key
(cascade).
- Ruling: options for a node's field need `workflow.edit`, and `connection.use` when a connection is named, of a type the
  node declares - D3 names `connection.use`; options are an editing aid - cost if wrong: an operator can't list choices.
- Ruling: a verification no worker answered within 10 s records nothing (504), rather than marking the connection in
  error - the credentials may be fine - cost if wrong: a broken worker pool shows as timeouts, not statuses.
- Ruling: the API keeps decrypting a secret before asking for a verification, to record `secret_unreadable` without a
  call; it no longer holds an outbound HTTP client at all - verify was its last outbound request (D3) - cost if wrong:
  none.
- Ruling: a start-form picker is `x-dewpoint-picker: {node, field, connection}` on a top-level string field of the input
  schema, its connection written literally and recorded in `connection_ids` - the start form shows top-level fields,
  a picked value is text, and the connection can't then be deleted while the workflow is enabled - cost if wrong: a
  picker on a nested or non-string field needs a new form.
- Ruling: a start form's options need `run.start`, through the connection the publisher wrote, not `connection.use` -
  publishing the picker is the publisher's consent, and a run would use the connection with the same authority -
  cost if wrong: an operator sees option labels (site names) through a connection they couldn't name themselves.
- Ruling: a picker's node isn't part of the version's closure: retiring it stops the start form listing choices (the
  field stays typeable), never a run - the node isn't run - cost if wrong: none.
- Ruling: flow completion names icons (`branch`, `switch`, `repeat`, `filter`, `variable`, `timer`, `calendar-clock`,
  `stop`, `alert`, `workflow`, `transform`) and marks `if.condition`, a switch case's `when` and `filter.predicate`
  `x-widget: cel`; no `x-group` (the flow nodes have one to three fields) - both are display metadata, so the editor
  (sub-project 4, slice 4f) can rename them without a new version - cost if wrong: none.
- 3a-2's first full run (2026-10-06, 11 min on a machine another session was loading): 2802 passed, 3 failed. Two were
  2b-2's start-form tests, whose fixture used a placeholder picker (`{"kind": "site"}`) that 3a-2's validation now
  refuses: the fixture now uses a real picker. The third, `tests/engine/cel/test_gate_cost.py::
  test_local_latency_and_the_cpu_between_two_yield_points` (0.90 s against a 0.2 s budget), passes alone: a timing
  gate CI runs in its own container; 3a-2 changes no CEL code.

Checkpoint review (fresh-context reviewer, 2026-10-06): no High fail-open; tenant isolation, claim fencing and the
hook's reach held. Two Medium and ten Low findings, all fixed test-first (each fix also mutation-checked), plus a
merge prerequisite:
- (1, Medium) a config-only edit moved a connection's host and kept its secret, so the stored secret could reach a
  host its writer never chose: `a5d8df4`.
- (2, Medium) the API held its request's pooled connection (and a session row lock) while waiting up to 10 s and needed
  a second one, so about 15 concurrent waits stalled every tenant: `eefd445`.
- (3) auth templates accepted format specs and conversions (an error quoting the secret, a 1 GB header): `85549f8`.
- (4) a verification's detail and privilege allowed 64 characters, their columns 40 (a failed write kept an older
  status); type keys could exceed `connections.type`: `efabe54`.
- (5) the start form listed options for a disabled workflow, and through a picker connection its version didn't
  record: `af91c3f`, test corrected in `15fb162`.
- (6) a connection's cooldowns failed with the decrypted secret in scope on a config its declaration refuses:
  `f352fda`.
- (7) the branch predated #41 (no frame locals in logs): rebased onto `origin/main` 717f420 before the fixes.
- (8) a worker of another build served calls with its own declaration of a connection type: calls carry the synced
  declaration's hash and only a worker with the same one claims them; (9) the queue now takes turns across tenants;
  (10) a call's connection key is the tenant's: `e39ffc1` (migration 0042 edited in place, unmerged; round trip
  checked).
- (11) read-only only restricted the method: no body, no method-override header now: `10737ba`.
- (12) the API re-checks the ruled option limits and shows only fixed failure codes; answers are exact strings; the
  worker logs proven class names: `863e0a4`.
- (13) reading declared types loaded whole manifests: only the declarations now: `9616fb3`.

Rulings taken with the fixes:
- Ruling: changing the field a connection type's host comes from (Mist's `cloud`, a URL field) needs the secret in the
  same edit (422 `secret_required`) - the secret never follows a host its writer didn't choose - cost if wrong: moving
  a Mist connection to another cloud means pasting its token again.
- Ruling: one API process waits for at most 16 plugin calls (503 `plugin_calls_busy`) and a tenant may have 8
  outstanding (429 `too_many_plugin_calls`); a waiting request holds no pooled connection; reads back off from 50 ms
  to 500 ms - cost if wrong: a burst of pickers gets 503/429 and retries.
- Ruling: a call through a connection records the synced declaration's hash of its type, and only a worker whose own
  declaration hashes the same claims it; without one the call times out - fail closed across a rollout - cost if
  wrong: while builds disagree on a type, its pickers and verifications time out until the new workers are up.
- Ruling: a start form lists options only for an enabled workflow, through a connection its active version recorded -
  no wider than a run - cost if wrong: a disabled workflow's form shows no choices.

Open question for 3b: a start form passes the operator's typed text to `options()`, through the publisher's connection.
A hook that put that text into a URL path (relative URLs may hold `../` within the origin) would let an operator reach
any GET the publisher's token can. 3b's Mist nodes must encode path parameters (the SDK should offer a helper) before
any picker uses typed text in a path.

Checkpoint full runs (2026-10-06, after the review's fixes): one run errored on the test database's container start
under another session's load (no code involved); the next showed 4 failures in #41's lifespan logging tests, which
closed the API's outbound HTTP client 3a-2 removed: they now fail the engine's disposal instead (`27e6585`). Final run
at `27e6585`: 2876 passed, 8 skipped, in 4 min 52 s; ruff, format, mypy, import contracts, licences and the replay gate
pass at `211ef73`. Not run: the Compose proof. (Correction from the owner: its web image's bases,
`node:22-bookworm-slim` and `nginxinc/nginx-unprivileged:1.30-alpine`, were approved for #40's proof; that doesn't
authorize a new Compose run, which still needs the owner's say.)

Owner's review of the checkpoint (`6167ed1`, 2026-10-06, pasted): three Medium and two Low findings, reproduced against
an isolated database and local fakes, all fixed test-first:
- (1, Medium) the host rule compared with an unlocked, possibly stale copy: an edit restoring the old host while
  another moved it with a new token kept the new token. The edit now locks the connection first: `64dfc8e`.
- (2, Medium) the tenant cap counted then inserted without serializing: two asks at seven both got in. Admission takes
  a per-tenant advisory lock: `609b437`.
- (3, Medium) options were accepted after an edit landed while the provider answered. The answer write is fenced on
  the connection's revision (`connection_changed` otherwise), and the API checks it again before returning:
  `4286729`. D3 asked a final compare-and-set for verification only; this is the stricter ruling.
- (4) secrets shorter than four characters escaped the answer's secret check (the run index's minimum): a call's
  answer is checked against every non-empty string: `7354193`.
- (5) a notification arriving during a round was cleared without another query: the event is cleared before the
  query: `2e81380`.

Each of the five failed its new test before its fix. Full run after them, at `b5e076c`: 2882 passed, 8 skipped, in
4 min 14 s; ruff, format, mypy, import contracts, licences and the replay gate pass.

The owner closed the technical review at `01cdcdc` (2026-10-06): no remaining blockers, both ledger corrections
accurate; an independent run of 130 targeted tests replayed the original races, and late revision changes and deletions
return 409 for both editor and start-form options while a rename still lets the answer through. This closes the
technical review only.

The owner then asked for the push and PR (2026-10-06). Before it, the branch was rebased onto `origin/main` ff1536e
(#42, editor UI 4a): one conflict, `/connection-types` keeping #42's response model with 3a-2's declared types; the
options routes answer a named `OptionsOut`, and the web client's `openapi.json` and `schema.d.ts` were regenerated
(`pnpm check:api`, lint, typecheck, 292 tests and build pass). Full run at `6f5fdce`: 2921 passed, 8 skipped, in
3 min 50 s; ruff, format, mypy, import contracts, licences, the replay gate and the schema drift check pass. Pushed
with `[skip ci]` (Actions minutes are exhausted).

**Checkpoint:** the owner approved every 3a-2 ruling above as recommended (2026-10-06), including the stricter
revision fencing of options (the owner's finding 3). The owner also decided to make the repository public (which
settles the CodeQL licence question once done), authorized a new Compose proof, and merged the outline (#39).

Compose proof (2026-10-06, at `47632f7`, on the owner's word): CI's e2e steps against an isolated project
(`dewpoint-p3a2`, its own ports, image tags and generated secrets), with the approved images: the stack up and
healthy, admin init, the worker's build current, `plugins sync` (flow and mist), migration 0042's table (forced RLS),
functions and the tenant-scoped connection key, the `mist` connection type registered, no plugin-call errors in the
worker's log; a run, a schedule and a signed webhook (a duplicate acknowledged once, a trickled body answered 408
after 10.09 s) through the Compose dispatcher; the 8 browser tests. All passed in 1 min 35 s. A first attempt's
passkey test failed only because the browser used 127.0.0.1 while the stack's origin was localhost (WebAuthn binds
the origin); with `DEWPOINT_PUBLIC_ORIGIN` matching, it passed. The stack, its volumes, images and secrets were
removed afterwards.

The owner made the repository public (2026-10-06), after a pre-flight (no secret patterns in the full history of every
branch; `.env.example` held placeholders in all its revisions); this settles the CodeQL licence question. CodeQL
then ran locally at `0812e14` with CI's versions (CLI 2.27.1, `python-queries` 1.8.11, `javascript-queries` 2.4.6) and
query filter, over the whole tree: no findings in Python (45 queries) or JavaScript/TypeScript (89 queries). The
`codeql` workflow is still disabled on GitHub.

## 3b-1 Mist REST

Branch `feat/plugins-3b1` from `origin/main` f65c6f9 (3a-2's merge), started 2026-10-06 on the owner's word. No
migration expected: connection types, nodes and triggers all live in synced manifests.

Tasks (test-first, in order):
1. The OAS as data (D2): `mist.openapi.json` at 0613a22 vendored gzipped, its SHA-256 checked when it's read, a
   `NOTICE` entry; a test pins each curated operation's method and path.
2. The operation-policy map (D28, D24, D14): one generated data file with an entry per OAS operation (state, the nodes
   that may reach it, capability, scope class, side effect and its evidence), made by a script from the OAS and the
   reviewed table; a test regenerates it and refuses drift, and checks the invariants (deprecated and always-refused
   routes denied, held operations reach nothing).
3. SDK 0.4.0: models declared by a JSON Schema (validated by it, reporting it as their schema), for nodes generated
   from data; a plugin's `triggers` (D12, D17), emitted only when set; the catalog checks both as data.
4. The Mist client (D1, D16): requests through the connection's HTTP, path values checked and encoded, the org forced
   to the connection's, a site checked to belong to it; status codes mapped; lists paged by `X-Page-*` headers,
   searches by the body's `next` kept on the connection's host and path, under a page cap.
5. One node type per curated operation (D23, D16, D15): config (connection, path values, query, body, a page cap,
   an update's mode) and output (the 2xx answer) schemas from the OAS; side effects from the map; nested update
   (merge by default, replace); delete's 404 on a retry. The manifest's size measured.
6. Simulate (D13): the OAS's 2xx example when it validates, else a value made from the schema; every node checked.
7. Options: the site picker and the org-scope resources' pickers.
8. Any endpoint (D14): `mist.api.read` and `mist.api.write`, only what the map allows them, inside the connection's
   scope, always-refused routes refused whatever the map says.
9. The Mist webhook trigger (D17): the plugin declares its 30 topics' envelope schemas; the API lists trigger types;
   an endpoint records the whole envelope (no events pointer, `id_source: none`); bindings filter on `/topic`.
10. Proof: a curated read and a merge update through RunGraph against a local Mist fake, and a webhook delivery
    through ingress into a run whose trigger is typed by its topic.

Rulings:
- Ruling: the branch starts from `origin/main` f65c6f9 (3a-2 merged) - as for 3a-2 - cost if wrong: one rebase.
- Ruling: the OAS is taken from a local clone of `mistsys/mist_openapi` with `git show 0613a22:mist.openapi.json`
  (the commit the appendix was generated from; that clone's working tree has local edits, which are not used), so
  nothing is downloaded; SHA-256 of the file `22f55432535ab38f6c0539392a729b8fd515a9ccae9df693fbd4ff23d40b8fac`,
  3,630,900 bytes; its `LICENSE` (MIT) comes from the same commit - cost if wrong: none (the hash pins the content).
- Ruling: the SDK becomes 0.4.0 - 3b-1 adds schema-declared models and triggers - cost if wrong: none (the catalog
  checks the major only).
- Ruling (D23 measurement, before generation): the 262 curated operations' schemas, each with its own `$defs`, come to
  6.5 MB of JSON (1.1 MB gzipped), 3.0 MB (0.3 MB gzipped) without `description` and `examples`; one schema reaches
  341 KB (site settings), and device schemas about 300 KB. The palette (`GET /node-types`) returns every type's
  schemas in one answer. Measured again on the generated manifests (task 5) before ruling on a split.
- Ruling: every allowed operation is reachable by its curated node and by the any-endpoint node of its method
  (`mist.api.read` for a GET, `mist.api.write` otherwise, always `ambiguous`) - D14 lets the generic nodes reach only
  what the map allows, and an idempotent operation through `mist.api.write` is only retried less - cost if wrong:
  none for safety; such a write never retries.
- Ruling: the always-refused routes (D14) are read broadly: the roots `msps`, `self`, `login`, `logout`, `register`,
  `recover`, `invite`, `installer`, `mobile` and `utils` (credential tests); any path with a segment `admins`,
  `apitokens`, `invites`, `sdkinvites`, `marvisinvites`, `ssos`, `ssoroles`, `cert`, `crl`, `ssl_proxy_cert`,
  `link_accounts`, `unlink_account`, `mist_scep`, `mist_nac_crls`, `export_idtokens`, `register_cmd` or
  `request_ztp_password`; anything outside `/api/v1/`, or with an empty or dot segment: 173 operations - certificates,
  CRLs, SCEP, OAuth links, registration commands and the ZTP password are authentication material - cost if wrong: a
  reviewed certificate read can't be allowed without changing the rule.
- Ruling: `listOrgAuditLogsLegacy` is denied as deprecated rather than held - D28 denies every deprecated operation,
  stricter than D24's hold - cost if wrong: none.
- Ruling: a side effect follows the method once evidence covers that kind: GET `none`, PUT and DELETE `idempotent`,
  POST `ambiguous` (the creates and the two actions, alarm ack and device restart: ack's repeat behaviour isn't
  documented, so D16's "else ambiguous") - cost if wrong: an ack that fails after sending needs a person.
- Ruling: the approved metadata outside an org or site is `/api/v1/const/webhook_topics` alone, the one curated
  constant - fail closed - cost if wrong: another constant needs a review.
- The map (`backend/src/dewpoint/plugins/mist/data/policy.json`, made by `python -m dewpoint.plugins.mist.reviews`):
  1,072 operations: 262 allowed (146 reads, 78 idempotent writes, 38 ambiguous; 173 org, 88 site, 1 metadata), 632
  held (620 unreviewed, 12 the owner's), 178 denied (173 always refused, 5 deprecated).
- Ruling: a declared model (`declared_model(name, schema)`) is the SDK's: it reports its schema in every mode, validates
  with it (Draft 2020-12 and the formats a step's output is checked for: date, uuid, email, ipv4, ipv6, regex) and
  names each failing place and the schema keyword, never the value; its output schema is shown exactly as declared,
  not closed as a pydantic model's is - a generated node's schema is the provider's, and closing it would fail every
  answer carrying a field the description doesn't list - cost if wrong: an undeclared output field is tainted, never
  refused.
- Ruling: a trigger declares only `id_source: none` and bearer or HMAC endpoints - ingress offers those, and D17 needs no
  more - cost if wrong: a provider with event ids needs the declaration widened.
- Ruling: a path value must be one segment of unreserved characters (letters, digits, `_ . ~ -`), neither `.` nor `..`,
  then percent-encoded; anything else fails `mist.invalid_path_value` before sending - every curated parameter is a
  UUID, a MAC or a name of that shape, and the open question of 3a-2 (typed text in a path) closes with it - cost if
  wrong: a parameter with other characters needs the rule widened.
- Ruling: a site is the connection's org's only when Mist's `GET /sites/{id}` answers that org's id exactly (one GET a
  site per attempt), for curated site-scope nodes too, not only D14's any-endpoint nodes - a token can reach other
  orgs' sites (an MSP's, an admin of several orgs) - cost if wrong: one more request per site-scope step.
- Ruling: a search's `next` is followed only on the connection's host and exactly the search's own path (no fragment);
  else the step fails `mist.invalid_next` - D14 - cost if wrong: a search Mist pages through another path stops
  failing instead of truncating.
- Ruling: a list without page headers whose page came back full is reported `truncated` - it may have more - cost if
  wrong: a list of exactly a page's size says it might be truncated.
- Ruling: the curated nodes are built when the plugin loads, from the map and the OAS, not written out as source -
  those two files are the reviewed source, and a test checks the whole manifest as the catalog does - cost if wrong:
  none (0.9 s at import).
- Ruling: the generated models skip the metaschema check at import (`declared_model(..., checked=False)`): 524 checks
  took 6 s; `plugins sync` checks every schema before registering it (11.6 s for Mist's manifest), and so does a test
  - cost if wrong: a malformed schema shows at sync rather than at import.
- Ruling: an output keeps the OAS's shape (types, properties, required fields, items) and drops value constraints
  (formats, enums, patterns, bounds) and closed objects; `oneOf` becomes `anyOf` (without their enums, branches
  overlap) - the OAS is documentation (D2) and Mist adds fields and values; what it doesn't describe is tainted, never
  refused - cost if wrong: a pill loses an enum's list of values; an out-of-range value passes.
- Ruling: a field is a secret, `x-sensitive` in config and output, when its name's last word is `psk`, `passphrase`,
  `secret`, `password`, `token`, `community`, `key`, `keys`, `apitoken`, `keypair`, `kek` or `mack`, or it's named
  `community_name`; a version can't then write it as a literal (engine 2b §3.8) - D16's list read by word - cost if
  wrong: a few non-secrets are tainted (BGP communities, SSH public keys, `cleanup_psk`), or a secret named otherwise
  isn't claimed.
- Ruling: a config is checked by the OAS's constraints but not its formats - publish validates literals without
  formats, so the run does the same and a version that publishes runs; path values are checked by the client - cost
  if wrong: a malformed address reaches Mist, which refuses it (`mist.bad_request`).
- Ruling: the four array query parameters (`labels`, `usermac_label` twice, `resp_attrs`) are left out - the OAS gives
  no style, so whether Mist wants them repeated or comma-joined is unverified - cost if wrong: those filters wait for
  a verification.
- Ruling: an update's body requires nothing; `mode` is `merge` (the default, when a GET of the same path is allowed)
  or `replace`; `clear` names top-level fields sent as null; a field both set and cleared, or nothing to change, fails
  before anything is sent - D15's Keep / Set / Null as absent / set / cleared - cost if wrong: clearing a nested field
  means setting its parent structure.
- Ruling: a list answers `{results, total, truncated}`, a search Mist's answer with every page's results, without
  `next`, and `truncated`; a page cap of 1-10 (default 1), a list's or search's timeout 5 minutes - the cap bounds a
  step's memory (an output over 64 KB is already a size claim) - cost if wrong: a list past 10 pages of 1,000 is cut.
- Ruling: a create's body is required, an action's (ack, restart) optional; an action answers `{}` and a delete
  `{already_absent}`, whatever Mist's body says - the OAS describes no answer for them - cost if wrong: none.
- Ruling: titles are the operationId in words ("List org sites"), normalized through reviewed Mist terminology
  ("List org PSKs", "Create org wxtag"; amended 2026-10-09, awaiting the owner's sign-off: see "Mist titles" at the
  end), descriptions the OAS's first paragraph cut at 300 characters, no icon - display metadata, changeable without a
  version - cost if wrong: none.
- D23 measured on the generated manifest: 262 nodes, 8.0 MB (1.34 MB gzipped), 3.3 MB without `description`s; the
  median node 5.6 KB; the largest site settings' update (634 KB: config 327 KB, output 307 KB), a device's update
  (560 KB) and device profiles' create and update (500 KB). A schema's descriptions sit outside contract hashes, so
  trimming them later makes no new versions. Splitting Mist into per-scope plugins changes no total, so it isn't
  done. **For the owner:** `GET /node-types` answers every schema at once, 8 MB uncompressed (neither the API nor
  nginx compresses); options are trimming descriptions, compressing, or a palette without schemas plus one type's
  schemas on demand (an editor change).
- Ruling: a simulated Mist step answers its operation's fixture without opening the connection: the OAS's first 2xx
  example shaped as the output (a list's as `{results, total, truncated: false}`, a search's without `next`) when the
  output schema accepts it, else the smallest value the schema accepts; a delete `{already_absent: false}`, an action
  `{}`. The map and an update's config are checked as in a run. The step's `simulated` outcome is the fixture's label
  - an output must match its schema, so it can't carry one - cost if wrong: none. Counts: 182 from examples (every
  example present fits), 39 made from the schema (the OAS has no example), 41 fixed.
- Ruling: pickers list a site-scope node's `site_id` (the org's sites) and an org resource's id or MAC where the map
  allows a list at its collection's path (27 fields, 169 nodes); a site's resources (devices, maps…) get none - a hook
  sees the typed text and the connection, never the rest of the config, so it can't know the site - cost if wrong: a
  device id is typed or referenced, not picked.
- Ruling: a picker reads one page of 1,000 (`limit=1000`) and filters it by the typed text locally; the text never
  enters a path or a query (3a-2's open question); labels are `name`, else `ssid`, else the value; the node's own
  operation and the list's must both be allowed - cost if wrong: an org with more than 1,000 sites shows its first
  1,000, by Mist's order.
- Ruling: `mist.api.read` and `mist.api.write` take a concrete path whose org is written as the connection's id or as
  `{org_id}` (another org fails `mist.org_mismatch`); the config's `path` is an `anyOf` of one pattern per path the
  map allows the node, so a version's reach is pinned in its contract (a later map that allows more makes a new
  version; one that allows less refuses at run time) and publish refuses a literal path outside it - D28's check at
  publish and at run time - cost if wrong: every map review that widens the generic nodes ships them as a new version.
- Ruling: a generic request matches the most specific allowed template (most literal segments; a tie is refused), its
  method must be the operation's, each path value must pass its parameter's schema (UUIDs and MAC patterns checked),
  the query may name only the operation's (non-array) parameters, each value checked, and the body must pass the
  operation's request body (an update's without required fields), or no body at all; everything is checked before
  the connection is opened - D14 - cost if wrong: a parameter the OAS describes wrongly can't be sent until the map
  overrides it.
- Ruling: a generic node answers `{status, body}`, the body undeclared and so tainted; its simulation answers the
  matched operation's OAS example with status 200 - D14, D13 - cost if wrong: none.
- Open question (from the owner's remark, 2026-10-06: the OAS's examples are incomplete and may be outdated; the
  schemas are the complete payloads): node schemas come only from the OAS's `schema` objects; examples are used only
  as simulate fixtures (D13, recommended there). A fixture taken from an incomplete example can lack fields a real
  answer has, so a later step referencing them could fail only in simulation. Alternative: build every fixture from
  the schema (each declared property filled, to a bounded depth), with the example's values laid over where they
  fit. Recommendation: switch to schema-built fixtures with example values laid over - the schema is the complete
  shape - for the owner's ruling at the checkpoint.
- Ruling: the Mist webhook trigger (`mist.webhook`) declares a bearer endpoint, no events pointer and no event ids, its
  topic at `/topic`, and each of the OAS's 30 topics' envelope schema, relaxed as an output is (93 KB in all), its
  `topic` fixed to the topic's name; every one passes publish's checks as a workflow's input schema. Its production
  support still waits for a real delivery (D17, 2b-4 D13) - cost if wrong: none until then.
- Ruling: `GET /api/v1/trigger-types` (any active session) lists the synced plugins' triggers, with each topic's
  schema; nothing creates the endpoint or the binding for the editor yet (the existing webhook routes do, with the
  declared settings) - D17 asks the editor to type pills per topic, which needs the schemas - cost if wrong: none.
- Proof (`backend/tests/apps/worker/test_run_graph_mist.py`, task 10): a workflow of two generated nodes published,
  admitted, dispatched and run through RunGraph against a local fake standing in for `api.eu.mist.com` (vetted,
  pinned, TLS-checked; its port 443 redirected in the test's socket layer): the site checked, its devices listed, the
  WLAN read and merge-updated (`auth` sent whole: its type and PSK kept, `pairwise` changed), every request with the
  runtime's `Token` header, neither the token nor the PSK in any preview, the token in the run's secret index. The
  same workflow simulated sends nothing. A Mist `alarms` envelope recorded by ingress's own function is matched by a
  `/topic` binding and runs a workflow typed by the topic's schema; a `device-updowns` envelope matches nothing; an
  `alarms` envelope whose events aren't a list is refused by admission (`input_invalid`).

Runs at `7e81c7d` (tasks 1-10 done), 2026-10-06: the full backend suite, 3145 passed, 8 skipped, in 6 min 12 s
(`-n auto`, with the reviewer's targeted runs alongside); ruff, format, mypy, import contracts and the OpenAPI drift
check pass; the web client's `check:api`, lint, typecheck, 292 tests and build pass. CodeQL locally with CI's CLI
(2.27.1) and query filter over the whole tree: no findings in Python (45 queries) or JavaScript/TypeScript (89).

Checkpoint review (fresh-context reviewer, 2026-10-06, at `7e81c7d`): one High, three Medium and eleven Low findings,
each fixed test-first and mutation-checked:
- (H1, High) a curated node's id took any plain segment, so a sibling route's literal reached another operation:
  `DELETE …/alarmtemplates/suppress` is `unsuppressOrgSuppressedAlarms` (held), and 17 such values reached held
  operations (32 shadowings counting ties). Each path value's config pattern is now its parameter's (UUID, MAC, one
  segment), so publish refuses it; every run and simulation checks each value against its parameter, and the concrete
  path must resolve, among every OAS operation, to the node's own (the most literal template wins, a tie is refused),
  for the generic nodes too: `373b731`, `75db8f8` (a test of the generic nodes' route check that the parameter
  check masked).
- (M1, Medium) the site check counted as a send, so an ambiguous site-scope write that never left (a restart whose
  site check met a 503, a site of another org) ended `outcome_unknown`; (M2, Medium) a site delete's retry after the
  delete applied found the site gone and failed `mist.not_found`.
- Ruling (M1): a node may mark a GET or HEAD without a body as a **probe**, a read before its effect: the runtime
  doesn't count it as a send (an ambiguous node's later failure that sent nothing stays retryable), may resend it
  within the attempt after a short `Retry-After`, and refuses a probe of any other method or with a body before
  sending. Mist's site check is a probe; one that may have reached Mist and failed is `mist.site_check_failed`,
  retryable - the check D14 requires changes nothing - cost if wrong: a plugin marking a request that has an effect
  as a probe has an ambiguous node retried after it (first-party code's declaration: the SDK is an API, not a sandbox).
- Ruling (M2): a delete's retry whose site check finds the site gone answers `already_absent` - the object can't
  outlive its site (D16) - cost if wrong: none.
- (M3, Medium) `mist.api.write`'s body declared nothing, so a PSK written there as a literal published (the curated
  node refuses it) and showed in previews. Fixed with the Ruling below; (L1) `magic`, a device's claim code, is now a
  secret name.
- Ruling (M3): the generic write's body marks, at any depth, every property name the OAS uses that the curated rule
  calls a secret (76 names), as exact names: the engine never runs a pattern on workflow data (a sensitive
  `patternProperties` marks its whole object), and the body's operation is known only at run time - the same reach as
  the curated nodes' marking - cost if wrong: a secret under a name the OAS doesn't use isn't claimed, as with a
  curated node.
- Low findings, fixed together: (L2) simulate didn't check path values: it does now, with H1's checks; (L3) a list
  reported a full page without headers as cut only when `limit` was asked: Mist's documented default page (100,
  `guides/api-requests/pagination`) counts too, and the one unpaged list that takes `limit`
  (`mist.site_wireless_client_stats.list`) says when it may be cut; (L4) a merge update's description warns of the
  race D15 can't prevent; (L5) a declared model's error text quoted the value, and the step's message showed
  `custom_error`: the input is hidden, and the message names the schema keyword (`schema_maxLength`); (L6) an output
  check failing after the node ran recorded no outcome: it records `applied` (or `simulated`), as a claim failing then
  does; (L7) a partial update of a typed union (a device: AP, switch or gateway) failed `oneOf` without `type`: a
  partial body's `oneOf` is `anyOf`; (L8) a search at its cap judged a next page it would never follow; (L9) a
  trailing newline passed the path-value check (`$`): `fullmatch`; (L10) a picker's list was checked by state only:
  by `allowed()`, as any node's operation; (L11) four tests that couldn't fail were rewritten or removed (the most
  specific route now has two candidates; the manifest-size bound is gone, the size being the ledger's), and a test
  for a generic site path of another org added.
- Ruling (L4): the exact merged body isn't previewed - it depends on the object read at run time, and a simulation
  sends nothing, so it would need a new output field or a step-level preview contract; the description carries D15's
  race warning instead - cost if wrong: an editor showing the body must wait for that contract.
- Ruling (L6): outputs keep the OAS's `required` fields (pills need them unguarded); a Mist answer lacking one fails
  `output_schema_violation`, now with `applied` recorded, so nobody takes a created object for one never made; the
  read-only smoke test at the checkpoint is where a wrong `required` shows - cost if wrong: such a step fails after
  its effect until the map overrides that schema.

Runs after the review's fixes, at `5edee45` (2026-10-06): a first full run gave 3212 passed and 6 setup errors in
`tests/sdk/test_manifest.py`, while another session's 14-worker suite loaded the machine (load average 36; the file
passes alone, serial and parallel); the rerun: 3212 passed, 8 skipped, in 10 min 13 s, with that session's next run
alongside. Ruff, format, mypy, import contracts and the OpenAPI drift check pass. CodeQL locally (CI's CLI 2.27.1 and
query filter): no findings in Python or JavaScript/TypeScript.

**Checkpoint (3b-1), for the owner:** every ruling above; the open question on simulate fixtures (the owner's remark on
examples); the palette's 8 MB (D23); the `probe` the SDK gained for M1, a runtime change (`apps/worker/network.py`);
an output check failing after a node ran now records `applied` for every node (L6, `apps/worker/activities.py`);
`plugins sync` checks Mist's manifest in about 12 s. Not run: the Compose proof (needs the owner's say), the
read-only Mist smoke test against a test org (D23's measure and L6's `required` fields; needs the owner's say).

The owner's review of the checkpoint (`2c94e1e`, 2026-10-06, pasted): the review isn't closed; two earlier findings
remain and `probe` adds one; the generic-secret leak, the picker refusal, the default page, the route shadowing and the
output outcome are closed. Fixed test-first:
- (O1, Medium) a probe accepted method-override headers (`X-HTTP-Method-Override: DELETE`): a GET the runtime took for
  a read could apply an effect on a server honouring them. A probe now passes exactly the read-only channel's check
  (GET or HEAD, no body, none of the three override headers), refused before sending otherwise.
- (O2, Medium) the site check's `GET /sites/{id}` bypassed the map: with `getSiteInfo` held, a site-scope node still
  sent it, then its own request; picker lists were checked, merge reads by state only.
- Ruling (O2): every request a node makes for an operation other than its own is an auxiliary read the map lists for
  that operation (`reads`: the site check's `getSiteInfo`, the same-path GET an update merges into, the lists its
  pickers read) and allows, checked before anything is sent, in a run, a simulation and an options call; a site-scope
  operation can't be allowed unless its site check is (the map's build fails); a merge read the map doesn't list or
  allow leaves `replace` available - the map stays the single source (D28), its diff showing every read - cost if
  wrong: holding `getSiteInfo` makes every site-scope node unavailable, as intended.
- (O3, Low) a generic simulation answered `body: null` where the OAS has no example (`getOrgPsk`): it now answers the
  example when the answer's schema (relaxed as an output's) accepts it, else the smallest value that schema accepts,
  and null only for an operation that answers nothing - as the curated nodes do today. The fixture redesign the owner
  recommends (bounded schema-built fixtures with validated example overlays, generic nodes included) is still the
  open ruling above; it would replace both.

Runs after the owner's three findings, at `839d733` (2026-10-06): the full backend suite, 3222 passed, 8 skipped, in
6 min 33 s; ruff, format, mypy, import contracts and the OpenAPI drift check pass; CodeQL locally: no findings in
Python or JavaScript/TypeScript. Still open for the owner: the rulings, the fixture redesign and the catalog's size (the
owner recommends bounded schema-built fixtures with validated example overlays, generic nodes included, and catalog
compression before a schema-on-demand redesign), the Compose proof, the read-only Mist smoke test, push and PR.

The owner's second review of the checkpoint (`6c7e2bc`, 2026-10-07, pasted): O1-O3 closed (override-bearing probes
refused on both channels; holding `getSiteInfo` stops curated and generic nodes; generic fixtures validate against every
allowed operation's answer schema). One Low remained: (O4) with an update's merge read held, a merge simulated
successfully (by default or asked), its authorization living only in the run's merge. The mode-aware check now sits in
the preflight a run and a simulation share; `replace` reads nothing and stays available.

The owner closed the 3b-1 technical review at `461a926` (2026-10-07): default and explicit merges are refused when their
auxiliary read is held, denied or not delegated, in a run and a simulation alike, before the connection opens; replace
stays available; the earlier findings stay resolved. This closes the technical review only: the rulings above, the
fixture redesign, catalog compression, the Compose proof, the read-only Mist smoke test, and push and PR remain the
owner's.

The owner chose to have the fixture redesign and catalog compression built in this slice (2026-10-07, "approve 2
and 3, build them"); both were built test-first. The two rulings below record how; like every 3b-1 ruling, they
await the owner's sign-off, and the later technical clearance of R1 and R2 is not acceptance (corrected at the
owner's review, 2026-10-07; an earlier wording read "approved"):
- Ruling (fixtures): a fixture is built from the schema, every declared property filled to 6 levels (only the required
  ones past them, so recursive schemas end), within 64 KB (the engine's inline limit; shallower past it): a given
  default, an array of one element, a union's first branch, else the type's empty value. The OAS example, shaped as
  the output, is laid over it: objects key by key, each array element over the built element; each part of the example
  that the schema refuses is put back to the built one. Curated and generic nodes alike (a generic node over its
  operation's answer schema, relaxed as an output's; null only when the operation answers nothing) - the OAS's examples
  are incomplete (the owner's remark), so the schema gives the shape and the example values - cost if wrong: a fixture
  fills optional properties a real answer may lack, so a simulation takes the "present" branch of a reference to one;
  publish requires such a reference to carry a default, which prevents a missing-reference error, but the absent
  (default) branch goes untested, and a failure there stays hidden until a real answer lacks the field (wording
  corrected on the owner's review). Measured: all 262
  curated fixtures in 0.2 s, the largest 30 KB (site settings), none past the budget; 182 take example values, 39 have
  none, 41 are a delete's or an action's fixed answer.
- Ruling (catalog): `GET /api/v1/node-types` and `GET /api/v1/trigger-types` answer gzipped (level 5) to a client that
  accepts it (`Vary: Accept-Encoding`; a `q` of 0 refuses), rendered and compressed in a worker thread; no other route
  is compressed - the catalog is the plugins' public metadata, while compressing an answer that holds a secret beside
  what the client sent would let its length reveal the secret (BREACH); the documented response models are unchanged
  (no OpenAPI drift) - cost if wrong: none; the schema-on-demand palette stays the editor's later redesign. Measured on
  the installed plugins' 273 node types: 8.08 MB of JSON rendered in 26 ms, gzipped to 1.40 MB in 72 ms (level 6:
  1.36 MB in 102 ms); returning the bytes also skips FastAPI's per-value encoding of the 8 MB.

Runs after both, at `d09db0c` (2026-10-07): the full backend suite, 3235 passed, 8 skipped, in 9 min 7 s; ruff (one
test line, fixed after), format, mypy, import contracts and the OpenAPI drift check pass; the web client's
`check:api`, typecheck and 292 tests pass; CodeQL locally: no findings in Python or JavaScript/TypeScript.

The owner's review of the redesign (`45d2245`, 2026-10-07, pasted): two Low findings and a wording correction.
- (R1, Low) a fixture could be returned invalid or over budget: a merged `allOf` breaking one of its parts, or a default
  too large to shrink. Every fixture returned is now one the schema accepts within the budget: shallower, then
  without defaults, and when none is, the operation has no fixture and its simulation fails `simulation_unavailable`.
- The ruling's wording claimed no failure hides behind a "present" fixture; corrected above: the default prevents a
  missing-reference error, but the absent branch goes untested.
- (R2, Low) the catalog's encoding was chosen loosely: `Q=0` or a wildcard went unread, identity couldn't be refused.
  It's negotiated as RFC 9110 12.5.3 says: `q` in any case and a malformed one refusing its coding, `x-gzip` as
  gzip, `*` for whatever isn't named, identity acceptable unless refused by name or by `*` (then, unnamed, yielding to
  any coding accepted), the higher weight chosen (gzip on a tie), and 406 `not_acceptable` when neither gzip nor
  identity is acceptable.
Targeted runs at `3beacb5` (2026-10-07): the API tests (276), the plugin, SDK and end-to-end Mist proof tests (385),
ruff, format, mypy, import contracts and the OpenAPI drift check pass; each of R1's and R2's fixes was also checked by
disabling it (the tests fail). The last full run is `d09db0c`'s (3235 passed).

The owner closed R1 and R2 at `5699914` (2026-10-07): fixture returns enforce the schema and the size cap, and when
none fits, curated and generic simulations fail `simulation_unavailable` alike; the encoding cases negotiate correctly,
406 included; the optional-field wording is corrected. The fixture and compression additions are technically cleared.
This is technical closure only: the rulings, the Compose proof, the read-only Mist smoke test, and push and PR remain
the owner's.

The owner asked for the push and PR (2026-10-07). The branch was rebased onto `origin/main` 69944d0 (#46, #47: 2b-4a)
without conflicts; the OpenAPI document and the web client's types still match (no drift, `check:api` passes). Full
run at the rebased head: 3621 passed, 8 skipped, in 12 min 7 s; ruff, format, mypy and import contracts pass.

**Status at the merge** (#49, `bc4c840`, 2026-10-07; all 15 checks passed): the technical review is closed; no 3b-1
ruling has the owner's sign-off yet; the read-only Mist smoke test against a test org is pending. #49's e2e jobs ran
the packaged Compose proof and the browser tests, so no separate local Compose run was made.

Read-only Mist smoke run (2026-10-07): the owner ran `backend/tests/probes/mist_smoke.py` (local `test/mist-smoke`
3dd2ebb) against the test org `9777c1a0-6ef6-11e6-8bbf-02e208b2d34f`, site `978c48e6-…`, on `api.mist.com`; GET only,
the report holding names and schema rules, never a value. 146 curated reads in 108.6 s: 64 matched their output
schema, 68 didn't, 1 failed, 13 were skipped (9 with nothing in this org to read their id from, 4 needing a query).
- 53 of the 68 only because Mist answers null where the OAS types a value (79 places: ids such as `map_id` and
  `template_id`, flags, lists), or a fractional number where it says integer (68 places: the `start` and `end` of
  search and count answers, map origins).
- 15 with real disagreements: fields typed otherwise (`lease_time`, `last_vlan` and `mfg_company_id` strings,
  `random_mac` a boolean, a client's `model` an array, site settings' `flags` integers); unions no branch fits
  (devices, device profiles, a port usage's `reauth_interval`); required fields absent (site stats' `country_code`
  and `latlng`, discovered assets' `name`, WxRule usage's `client_mac`, `name`, `usage`, `dst_allow_wxtags`,
  `dst_deny_wxtags`).
- The failure: `searchOrgUserMacs` answered in a shape the search node doesn't read (`mist.invalid_answer`).
- Sizes: wired-client searches about 434 KB a page; 2.25 MB across all answers.
As shipped, those 69 operations fail their runs (`output_schema_violation` after the request, or `invalid_answer`).

The OAS overlay (2026-10-07, the owner's request after the smoke run, while the upstream description is fixed):
`backend/src/dewpoint/plugins/mist/data/oas-overlay.json`, 87 patches laid over the vendored file when it's read
(`oas.document()`), each citing the smoke run and the definition it expects to replace: 43 fields nullable, 39 types
widened (`start` and `end` of 14 search and count answers and map origins to numbers; `lease_time`, `last_vlan`,
`mfg_company_id`, `random_mac`, a client's `model`, site settings' `flags` and an AP search result's bandwidths to
both types seen), required fields dropped from site stats, assets, WxRule usage and AP search results, and
`searchOrgUserMacs`'s answer an object with `results` and `total` (Mist's shape; the OAS says an array). A second probe
run with per-branch union detail (`c8c59d8`) pinned the unions: the AP branch's `esl_config` and `usb_config` channels
and band-6 `standard_power` null; an AP search result without `type`, `mxtunnel_status` or `wlans`, its bandwidths
integers; a port usage's `reauth_interval` null.
- Ruling: patches only what the smoke run showed, not every field made nullable - a nullable field makes every
  reference to it need a default at publish (`ref.conditional`), so blanket nullability would weigh on every workflow
  reading a Mist output - cost if wrong: a field null in another org's answers still fails its step until patched.
- Ruling: the patched schemas are the components themselves, so they relax requests too (a PSK's `admin_sso_id` may be
  sent null, an asset created without `name`, which Mist then refuses) - one description, read the same way in both
  directions - cost if wrong: a config Mist refuses is caught by Mist (`mist.bad_request`) rather than at publish.
- Ruling: the vendored file stays pinned; a patch whose target no longer reads as it expects fails the build, so
  re-vendoring a fixed description retires its patches by test - cost if wrong: none.
- Ruling: the changed output schemas change the contracts of the registered `@1` node types; they're amended in place,
  not shipped as `@2`, since no environment runs workflows on Mist nodes yet - a database that already synced them
  needs its Mist node-type rows reset before the next sync - cost if wrong: such a sync is refused (`contract changed`)
  until reset. The owner confirmed (2026-10-07): no environment uses the Mist nodes yet, so amending `@1` is fine.
- The user-MAC search now answers one page as Mist sends it (an object, `page` and `limit` in its query) instead of
  paging headers it never sent; fixture counts move to 181 from examples and 40 from schemas.
- The owner's third probe run (with the overlay): 127 matched, 6 mismatched, 0 failed, 13 skipped. The 6: two fields
  missed (`alarm_search_result`'s `start` and `end`; `asset.map_id`), and two retyped fields that were references
  (`client_nac.last_vlan`, `random_mac`) whose new type was added beside the reference, which JSON Schema applies too.
  A retyped field's reference is now replaced by its new type, and a test checks the observed values validate, not
  only the patched keyword. The overlay holds 90 patches: 44 nullable, 41 types widened (15 search and count answers'
  `start` and `end`), 4 `required` lists trimmed, 1 answer reshaped.
- The owner's fourth probe run (2026-10-07, at `a9c8610`): 133 matched their output schema, 0 mismatched, 0 failed;
  13 skipped as before (9 with nothing in the test org to read their id from, 4 insight reads needing a `metrics`
  query). Every curated read the probe could reach runs as shipped against this org.

## 3b-2 Mist device utilities

Branch `feat/plugins-3b2` from `origin/main` 5e79a10 (#51, after 3b-1's #49 and its follow-up #50), started 2026-10-07:
I named 3b-2 as next and the owner said "let's continue". That is the go to build 3b-2; this section's rulings await
the owner's sign-off. No migration expected. No real Mist call: the proof runs against local fakes (REST and stream).

Facts checked before the tasks (never from memory):
- `websockets` 17.1 as installed (`websockets/asyncio/client.py`): `connect(uri, sock=..., ssl=..., server_hostname=...,
  proxy=..., additional_headers=..., open_timeout=..., ping_interval=..., ping_timeout=..., max_size=...)`; with `sock`
  given it sets no proxy and refuses every redirect ("cannot follow redirect ... with a preexisting socket"); `max_size`
  bounds a message.
- Mist's stream (docs clone `mistapi-portal` 919c9b47, `guides/websocket/`): hosts `api-ws.<cloud>` beside each REST
  `api.<cloud>` (`1_hosts`); `wss://api-ws.mist.com/api-ws/v1/stream` with `Authorization: Token` (`2_best_practices`);
  `{"subscribe": channel}` answered `channel_subscribed` or `subscribe_failed` with a `detail` (sample: "Server error,
  please try again later"); 2,000 connections an hour and 2,000 channels a connection per token, 429 past them
  (`3_rate_limit`); device command output on `/sites/{site_id}/devices/{device_id}/cmd`, `data.session` matching the
  POST answer's `session`, `data.raw` the text; `"finished": true` in table output (`samples/site_device_command_output`:
  show ARP, show service path, show session); a release-DHCP sample whose `data` is a JSON string holding another
  envelope (the OAS). Unsubscribing is mentioned but its message isn't documented.
- The 30 utilities in the vendored OAS (0613a22): all exist, none deprecated; 25 answer `websocket_session`
  (`{session}`, required), 5 an empty 200 (`bounce_port`, `clear_macs`, `clear_bpdu_error`, `release_dhcp_leases`,
  `clear_session`); `resolve_dns` takes no body; five table commands take a refresh `interval` (at most 10 s) and
  `duration` (at most 300 s); devices are typed `ap`, `switch` or `gateway`. In 3b-1's map each is `held`
  (`unreviewed`). (An earlier line said 24 and 6, counting `resolve_dns` as empty: corrected when the reviews were
  generated from the OAS.)

Tasks (test-first, in order):
1. `websockets` 17.1 becomes a direct dependency (D26; approved with the outline's rev 5).
2. The guarded websocket in `core` (D26): wss only; the name vetted and the socket connected by the guard to a vetted
   address, then handed to `websockets` (`sock`, `server_hostname`, `proxy=None`); opening 5 s, 1 MiB a message, 10 MiB
   an attempt, pings every 60 s with a 45 s timeout; text messages only; failures as core errors.
3. SDK 0.5.0: a connection's `ws.connect()` (its type's stream endpoint) and the `WebSocket` it gives (`send`, with
   `probe` for a message that changes nothing; `receive` with a timeout; `close`); a connection type's
   `StreamEndpoint` (host map, path, stream quota scopes) as data; `HandshakeRejected` (its status) and `StreamLost`.
4. The runtime's connection stream (D4, D9, D10): the declared URL only, the credentials the runtime's, a token from
   each stream scope per connection (`Cooldown` otherwise), a 429's `Retry-After` blocking those scopes; refused in a
   simulation and on a plugin call's read-only channel; a counted send marks the attempt, a probe doesn't; closed with
   the attempt. The API's cooldowns list the stream scopes.
5. Mist's stream endpoint: each cloud's `api-ws` host, `/api-ws/v1/stream`, a stream scope per token.
6. The utilities' reviews (D27, D28): each with its contract, stream mode, device types, permitted parameters,
   execution bounds, repeat behaviour and evidence; allowed to its own node only; the map's version 2.
7. The stream reader (D27): subscribe, acknowledgement (10 s), POST, the session's messages kept (at most 256 and 1 MiB
   before the session is known), strict and bounded decoding, ANSI stripped; idle (10 s), first message (30 s),
   maximum duration, terminal evidence; heartbeats; closed in `finally`; every failure classified.
8. One node type per utility: config (connection, site, device, permitted parameters, maximum duration), output by
   contract, the site and device-type checks, simulate, pickers.
9. Proof: a ping streamed from a local stream fake and a bounce-port accepted by a local REST fake, through RunGraph;
   the same run simulated sends nothing.

Rulings:
- Ruling: the branch starts from `origin/main` 5e79a10 - #50's overlay and #51's log fields included - cost if wrong:
  one rebase.
- Ruling: D26's `ctx.ws` is exposed as `connection.ws` only: the connection type's stream endpoint, its credentials
  applied by the runtime, its stream scopes charged. A websocket without credentials waits for a node that needs one -
  every node 3b-2 adds streams through its connection, and each surface is one more to guard - cost if wrong: adding
  `ctx.ws` later is additive (an SDK minor).
- Ruling: a node can't name the stream URL: it's the type's declared host (from a config field's host map) and path -
  as the REST base is - cost if wrong: a provider whose stream URL varies per call needs the declaration widened.
- Ruling: opening a stream sends nothing a node is accountable for (as a TCP connect isn't); a message sent counts as a
  send unless the node marks it `probe` (a message that changes nothing, as Mist's subscribe) - fail closed for a
  stream API whose messages act - cost if wrong: a node that mis-marks an acting message as a probe gets a retry it
  shouldn't (first-party nodes only today).
- Ruling: no unsubscribe message is sent: its format isn't documented; closing the connection ends its subscriptions -
  cost if wrong: none (one connection a call, never shared).
- Ruling: `subscribe_failed` is retryable only with the documented `detail` "Server error, please try again later",
  fatal with any other - nothing was sent before the POST, so a retry is safe, but a refused channel or forbidden site
  would only burn stream connections - cost if wrong: a transient failure worded otherwise fails the step.
- Ruling: every disruptive utility is acceptance only (`{accepted: true, completion_known: false}`), none subscribes:
  no completion, final message or readback is documented for any of the 11 (an empty 200 isn't documented as
  completion; bounce port's docs sample streams "Port bounce complete." while its OAS answer is empty, unverified) -
  cost if wrong: no output from the cable test (TDR) and the clears until a device run verifies a contract to promote.
- Ruling: three diagnostics have stream terminal evidence (show ARP, show service path, show session: the docs samples'
  `"finished": true` with `"status": "SUCCESS"`); the 16 others are bounded collections, and one that sees that evidence
  ends early with `completion_known: true` - cost if wrong: a table command that never finishes fails its three nodes
  `mist.completion_unknown` (retried, being repeatable diagnostics).
- Ruling: a finished table whose `status` isn't `SUCCESS` fails `mist.command_failed` (fatal) - the device answered;
  repeating a diagnostic the device refused won't change it - cost if wrong: a transient device failure isn't retried.
- Ruling: the refresh parameters (`interval`, `duration`) aren't permitted: they repeat the output for up to 300 s, which
  no contract bounds yet - cost if wrong: a repeated table needs a workflow loop.
- Ruling: the device type is checked before anything else is sent: a probe read of the device (`getSiteDevice`, in the
  map's reads), its `type` among the review's - D28's device types checked at run time, not only recorded - cost if
  wrong: one more read a utility step.
- Ruling: utilities are reachable by their own node only, never by `mist.api.write` - the generic node would bypass the
  permitted parameters and the contract - cost if wrong: none for safety.
- Ruling: the map's version is 2: an allowed utility's entry carries its review (`utility`: contract, stream, device
  types, parameters, bounds, repeat); a map of version 1 is refused, as one of another description is - cost if wrong:
  none (generated, and checked against the reviews by a test).
- Ruling: a utility's contract is one its node implements: bounded collection, stream terminal evidence or acceptance
  only; D28's documented REST completion and verified readback have no node yet, so a map naming them is refused -
  cost if wrong: none until a utility needs one.
- Ruling: a utility's device types are its OAS tag's (Utilities Common: AP, switch and gateway; LAN: switch; WAN:
  gateway), narrowed or widened by its description's own list ("Ping from AP, Switch and SSR"; "BGP Summary from SSR,
  SRX and Switch"; "Clear ARP cache for SSR, SRX and Switch"; port bounce "from Switch/Gateway"; TDR "from the
  Switch"; show ARP's `node` "required for Gateways") - the documentation is the only evidence short of a device run -
  cost if wrong: a supported type is refused `mist.device_type_unsupported`, or an unsupported one reaches Mist, which
  refuses it.
- Ruling: maxima on top of the OAS's: a ping's or a service ping's `count` at most 100, a traceroute's `timeout` at most
  120 s, a streaming utility's own `max_duration_s` at most 240 - bounded collection needs a bounded command - cost if
  wrong: a longer ping takes several steps.
- Ruling: a device id has no picker: 3b-1's pickers are a site's and an org resource's, and a site resource's list
  needs the chosen site, which an options query doesn't carry - cost if wrong: the device id is typed or referenced.
- Ruling: the twelve utilities D27 holds back are `held` with their reason (shell, CLI config, support upload, FIPS
  zeroize, reprovision, re-adoption, firmware rollback, VC switchover, packet capture, and the three JWT-URL streams);
  `getSiteDeviceZtpPassword` stays denied as always refused, which is stricter - cost if wrong: none.
- The map at task 6 (measured): 1,072 operations, 292 allowed (262 curated, 30 utilities: 19 diagnostics, 11
  disruptive), 602 held (578 unreviewed, 24 the owner's or D27's), 178 denied.
- Ruling (task 7, the stream reader): a finished table counts as evidence only with `"status": "SUCCESS"`; with another
  status it's the device's refusal (`mist.command_failed`); without a status it's no evidence (`completion_unknown`) -
  the docs show only `SUCCESS` - cost if wrong: a status-less finished table is retried instead of accepted.
- Ruling: a table's evidence is the JSON object at the start of `raw`, whatever text follows it - the docs' show ARP
  sample ends its table with `\n"}}` where show service path's and show session's end in a newline - cost if wrong:
  trailing text that should have voided the table doesn't.
- Ruling: a data envelope's channel must be the device's (compared in lower case), a nested envelope's too, at most one
  level deep; `data` an object or a JSON string of one, never a string encoded twice; `session` a non-empty string and
  `raw` a string; anything else is discarded, never accepted - cost if wrong: a reshaped Mist message reads as no
  output (retried for diagnostics).
- Ruling: while the POST is under way the reader buffers the channel's data (at most 256 messages and 1 MiB); a lost
  stream or an overflow then lets the POST finish, since it's the command, and fails after it (`mist.stream_lost`,
  `mist.output_unreadable`, `mist.output_overflow`) - cost if wrong: none.
- Ruling: the kept output is at most 5,000 lines and 512 KiB (`truncated` past either; reading goes on to the end),
  well under a step output's 1.75 MiB - cost if wrong: a long table is cut.
- Ruling: a `HandshakeRejected` the node doesn't catch is retried by the runtime only for a 429 or a 5xx; a
  `StreamLost` is handled as `MaybeSent` (8ac5b1f) - cost if wrong: none for safety.
- Ruling (task 8, the utility nodes): a utility node is a curated operation (`MistUtility` extends `MistOperation`): the
  same map, site and path checks and the same site picker, then the device check - one code path for what 3b-1's
  review hardened - cost if wrong: none.
- Ruling: a device whose answer names no `type` is refused `mist.device_type_unsupported` (the OAS's
  `device_type_default_ap` suggests an unnamed type is an AP, but that's a default for writing) - fail closed - cost
  if wrong: a utility on such a device fails until a device run shows what Mist answers.
- Ruling: a utility whose OAS takes a body sends the permitted parameters given, `{}` when none are; `resolve_dns`,
  which takes none, sends no body - cost if wrong: Mist refuses an empty body (`mist.bad_request`).
- Ruling: an acceptance-only utility whose OAS answer holds a `session` reports it, and an answer without one is
  `mist.invalid_answer` (after the send: outcome unknown, the node being ambiguous); the five answering nothing report
  `{accepted, completion_known}` only - cost if wrong: none.
- Ruling: a streaming utility's maximum duration defaults to 60 s (bounded collection) or 120 s (terminal evidence),
  at most 240 s, within a 5-minute step timeout that also covers the 10 s acknowledgement, the POST and the 30 s first
  message; an acceptance-only utility's timeout is a minute - cost if wrong: a slow table needs a longer maximum.
- Ruling: a simulated utility answers its contract's shape (one line saying no command was sent; the session a fixed
  placeholder), never an example of real output: the OAS has none to validate - cost if wrong: none.

Fresh-context review of 3b-2 (at 40e800c, 2026-10-07): no High, 2 Medium, 7 Low and a parity note. Each finding is
fixed test-first, and each fix's protection checked by disabling it.
- M1 (disruptive utilities accepted their whole-device forms: an omitted, empty or `all` port list, an unfiltered MAC
  table or ARP cache, an unscoped session clear, a BGP clear of `all` neighbors): each disruptive review names its
  selectors (`ports`, `port`, `port_id`, `session_ids`, `neighbor`), required, a list of at least one, never `all` in
  any case. Ruling: a whole-device form isn't permitted until the owner reviews it - D24 holds bulk forms where empty
  means all - cost if wrong: clearing a whole table takes a loop over its ports.
- M2 (`count` and `timeout` could be 0 or negative, which some pings read as unlimited): a bounded integer is at least
  1. Ruling: every free-text string a utility sends (no enum) is one word of letters, digits and `. _ : / @ -` (host
  names, addresses, interfaces, prefixes, names), at most 253 characters - such text reaches a device's command line
  through Mist - cost if wrong: a name with another character is refused at publish.
- L4 (show route's `node` is an object in the OAS, open to any keys): a permitted parameter can't be an object; show
  route's `node` isn't permitted (the string form every other utility takes is refused by the OAS's object type).
- L5 (the map's loader trusted a utility entry's consistency): where the map is read, a utility's entry must name its
  own node alone (never `mist.api.read`/`write`), be a site's, pair `mist.diagnose` with idempotent and `mist.write`
  with ambiguous, acceptance only and selectors, keep acceptance only ambiguous, and bound only its parameters and,
  streaming, its duration; `api.routes` skips utilities whatever a map says; a stream on an answer without a session
  fails the build where the OAS is read.
- L1 (JSON nested past the decoder's limit raised `RecursionError`, which no phase caught, and the POST wait's `finally`
  left the POST and the receive running): the three decoders read it as unreadable, so the message is discarded; the
  wait cancels and awaits whatever is still running, the POST and the receive alike, whatever ended it.
- L2 (a redirect whose Location isn't a websocket URL escaped as the library's own exception, retried or of unknown
  outcome though nothing was sent; a malformed one read as not sent): every library exception is read for the refused
  handshake behind it, so any redirect is `HandshakeRejected` with its status, anything else `NotSent`.
- L3 (the library writes each handshake header at DEBUG, the token included): its logger is Dewpoint's own, pinned at
  WARNING, so no level of the root logger lets such a line out.
- The parity note (an attempt's websockets opened after `aclose()`): refused (`InvalidRequest`).
- L6 (the checks before a collection could take longer than the reviewer's 75 s: three REST requests of up to 60 s
  each, token waits, opening, the acknowledgement and in-attempt `Retry-After` waits; with a 240 s maximum the attempt
  could pass its 5-minute timeout, losing its output and repeating the command): the collection ends 30 s before the
  node's step timeout, counted from when it started running, as `max_duration` would. Ruling: the node's own timeout
  is the reference; a graph that sets a shorter one cuts the collection by Temporal's timeout instead - cost if wrong:
  such a step is retried as a timeout (the diagnostics are repeatable).
- L7 (the runtime's receive waited up to an hour without a heartbeat, delaying a cancel): it waits in slices of 10 s,
  heartbeating between them, the timeout checked first.

### 3b-2 checkpoint (2026-10-07, at 8e96fda, local, not pushed)

- Built (tasks 1-9, test-first): `websockets` 17.1 direct (983bb24); the guarded websocket (09c328d); SDK 0.5.0 with a
  connection's stream (285694d); the runtime's connection stream (ae70993); Mist's stream endpoint and stream scope
  (bc2e2a8); the 30 utility reviews in map version 2 (eaa614a); stream failures' classification (8ac5b1f); the stream
  reader (9c0b952); a node per utility (ebd556f); the RunGraph proof (200e7ab); operator docs (7bc611a, 40e800c).
- The map: 1,072 operations, 292 allowed (262 curated, 30 utilities: 19 diagnostics, 11 disruptive), 602 held, 178
  denied. Mist declares 294 node types; its manifest is 8.25 MB.
- Fresh-context review: no High; M1, M2, L1-L7 and the parity note fixed test-first, each protection checked by
  disabling it (abfb1c3, 7b1aa66, 30401b3, 4ddd44d, 727db46, 8e96fda).
- Verified locally: 1,843 tests (plugins, SDK, core, catalog, API, the worker's network, plugin calls and both Mist
  RunGraph proofs), ruff, format, mypy, import contracts; CodeQL's python analysis (CI's CLI 2.27.1 and query filter)
  0 findings at 8e96fda. Not run: the full backend suite (about 12 minutes: on the owner's word), a Compose proof, and
  any real Mist call.
- Unverified until a device run (each recorded above as a ruling): bounce port's streamed output; whether Mist sends
  show ARP's table with text after it; `subscribe_failed` details other than the documented one; a device answer
  without `type`; whether an empty body is what Mist expects where no parameter is given. Every utility is a POST to a
  device, so a run against the test org needs the owner's go, and a device it may act on.
- Awaiting the owner: sign-off on this section's rulings; the full suite; push and PR.

The owner's technical review of 4d6c627 (2026-10-07): no High or Medium; four Low (R1-R4), each fixed test-first and
its protection checked by disabling it. A technical review; the rulings above still await the owner's sign-off.
- R1 (an opening under way when the attempt closed returned a live stream): the attempt's close fences openings under
  way; a socket dialed or a handshake completed after it is closed and the opening refused (`InvalidRequest`).
- R2 (vetting ran outside the 5 s opening bound): the guard's resolution and allowlist read count in it too.
- R3 (Python's `$` matches before a final newline, so `"8.8.8.8\n"` passed the one-word pattern and reached the POST):
  the one-word and `all` patterns end with `(?![\s\S])`, the text's very end in Python and JavaScript alike; the
  stream path and host checks (SDK and catalog, the host check shared with 3a-2's host map) and the utility path
  check use `fullmatch`. The same `.match` with `$` remains in older manifest validators (plugin names, type keys,
  ports, icons, topics, header names, scope kinds, a verify's detail): flagged as its own task.
- R4 (a JSON escape decoded to a lone surrogate, which then failed the byte counting): a session or a raw text that
  isn't UTF-8 is unreadable, so the message is discarded in either phase, never counted or kept.
- At eadff20 (local, not pushed): 1,857 tests in the affected areas, ruff, format, mypy, import contracts; CodeQL's
  python analysis 0 findings. Still not run: the full suite, a Compose proof, any real Mist call.
- The owner's review of the fixes (2026-10-07): R1-R4 technically closed at 12cd76b, no new findings. Technical closure
  only: the rulings still await the owner's sign-off, and the full suite, any real Mist call, push and PR each wait for
  the owner's word.
- The owner signed off this section's rulings as written (2026-10-07, "go", confirmed in chat as covering the
  rulings, push and PR after the full suite, and a real run against the test org).
- Rebased onto `origin/main` af8b808 (#52, #53, #54; no conflicts; local backup branch
  `backup/plugins-3b2-pre-rebase`). The full backend suite at the rebased head 80348ca: 3,929 passed, 8 skipped, in 8
  minutes (`-n 10`).
- The device-utility probe (`backend/tests/probes/mist_utilities.py`, bd03de3): `list` sends GETs only; `run` sends a
  POST only to a diagnostic utility of a chosen device, any other request refused before sending. The owner chose
  diagnostics only, on one device of each kind in the test org: a switch (EX4100-48MP), an SRX340, an SSR130 and an
  AP47.
- R3's class in the guarded websocket (flagged by the `fix/validator-fullmatch` work and named a follow-up in the
  owner's review of it): `HEADER_NAME.match` let a header name ending in "\n" through, and `websockets` checks only a
  header's value, so the line break would have gone into the handshake. `fullmatch` refuses it as an invalid header
  before anything is resolved or dialed (4cee8c8, its test failing first). No other `.match` on a `$` pattern is new
  on this branch: the utility path check and the SDK's stream path check already use `fullmatch`. The utility nodes'
  path value patterns still end in `$`, like main's Mist path patterns (left as they are by the owner): a config may
  hold "x\n", and the run refuses it before the connection opens (`mist.invalid_path_value`, `client.path`'s
  `fullmatch`). At 4cee8c8: 245 tests (core egress, the worker's network, streams, plugin calls and the utilities'
  RunGraph proof), ruff, format, mypy, import contracts. Not rerun: the full suite, CodeQL.

The device runs (2026-10-07, diagnostics only, on the owner's go; the probe ran in this session; reports in the owner's
home, mode 600, holding outcomes, counts and message shapes, never a value):
- Run 1 (bd03de3): every streaming diagnostic on the four devices ended `mist.no_output`; the subscription was
  acknowledged and each POST answered a `session`. Traced by shape: each output is a JSON string holding an envelope
  whose channel names the device by its MAC, `/sites/<site>/devices/<mac>/cmd`, the MAC its id
  `00000000-0000-0000-1000-<mac>` ends with, the session ours. Fixed (f4aebdf): that name is the device's command
  channel too, at either level; another device's MAC, another site or another channel is still discarded.
- Run 2 (f0806ea): 24 ok, 26 failed, 6 skipped (service ping and DHCP leases need a name of the org's).
  - Every SRX and SSR table (OSPF database, interfaces, neighbors and summary, routes, BGP summary, forwarding table,
    sessions, service path, ARP) ended on `"finished": true` with `"status": "SUCCESS"` within seconds, so the bounded
    collections among them reported their completion; no table had text after it.
  - Pings ended on idle, traceroutes at the 30 s maximum, the switch's MAC table on idle (73 messages).
  - Show ARP on the switch and the SRX sent text (19 or more messages), no finished table: its terminal-evidence
    contract failed every time (`mist.completion_unknown`).
  - Commands to which a device sent nothing ended `mist.no_output` with only the acknowledgement seen: ARP, BGP
    summary, 802.1X, EVPN and forwarding table on the switch; ARP, 802.1X, EVPN, MAC table, sessions and service path
    on the SRX; ARP, 802.1X, EVPN, MAC table and DNS on the SSR; most of the AP's.
  - The AP's output came after 30 s that time: another session's output (its earlier command's) reached the next
    command's window, where it was discarded. Run 3 measured the AP alone: ping and ARP answered within 1 to 2 s and
    succeeded. The 30 s first-message wait stays; a late answer fails `mist.no_output` and is retried.
  - `mist.bad_request`: DNS resolution on the SRX (an SSR command; the review's device types are coarse, `gateway`);
    the forwarding table on the SSR.
- Ruling (changed after run 2, awaiting the owner's sign-off): show ARP is a bounded collection, no longer stream
  terminal evidence - the docs' finished-table sample doesn't hold for a switch or an SRX; it still ends early, with
  its completion known, when a finished table comes - cost if wrong: none for safety; a run that ends on idle doesn't
  claim the table was complete. Show service path and show session keep their terminal evidence, which the SSR sent.
  Run 4 (show ARP on the switch and the SRX): both ok, ended on idle (39 and 71 messages).
- Still unverified: bounce port's answer and stream (no disruptive utility ran); a `subscribe_failed` detail (none
  came); a device answer without `type` (every device had one).

After the PR (2026-10-08):
- The owner's technical review of 59111815: no new findings (the MAC channel keeps the site, device and exact-session
  checks, nested envelopes and messages before the POST's answer included; show ARP reports `completion_known: false`
  on idle and `true` on a finished table; the header-name fix holds). CI on #56 at 59111815: all nine checks passed
  (the backend suite, the CEL gates, both CodeQL analyses, the Compose and browser e2e job). That run is 59111815's
  only; the merge below needs its own.
- `origin/main` moved to 4977bfe (#55, the Python validators' `fullmatch`), conflicting with #56 in the catalog's
  `_host_problems`. The session "Fix websocket header-name check on plugins-3b2", at the owner's request, merged it
  into this branch (c7e793f, a merge commit, no rebase), keeping 3b-2's labelled messages with #55's `fullmatch`. That
  session ran the full backend suite at c7e793f: 3,977 passed, 8 skipped, in 10 minutes 36 seconds; this session ran
  495 tests in the catalog, SDK, egress and Mist stream and utility areas; the owner's review found the resolution
  correct (113 catalog and SDK tests). Not pushed: on the owner's word.
- The show ARP ruling change (a bounded collection, above) still awaits the owner's sign-off.
- The owner signed off the show ARP ruling change (a bounded collection) and the push of the merge (2026-10-08).

## 3c-1 Messaging: chat and webhooks

Branch `feat/plugins-3c1` from `origin/main` f0e7bf5 (#56), started 2026-10-08 on the owner's "let's go" after 3b-2
merged; the outline's order puts 3c before 3d. A go to build; this section's rulings await the owner's sign-off. No
migration expected. No real Slack, Teams or Google Chat call: tests and the proof run against local fakes.

Facts checked (official documentation, read 2026-10-08; never from memory):
- Slack incoming webhooks (docs.slack.dev `messaging/sending-messages-using-incoming-webhooks`, `apis/web-api/rate-limits`,
  `reference/block-kit/*`, `messaging/formatting-message-text`, `changelog/2016-05-17-changes-to-errors-for-incoming-webhooks`):
  - the URL's only documented form is `https://hooks.slack.com/services/T…/B…/…` (the `B` segment named the service
    id; the `T` segment not named); the URL is a secret; channel, user name and icon can't be overridden;
  - POST JSON with `text` (the `no_text` error says it's needed), optional `blocks`; success is 200 with body `ok`;
    errors are 4xx with a reason string (400 `invalid_payload`, 403 `action_prohibited`, 404 `channel_not_found`, 410
    `channel_is_archived`; 500 `rollup_error` in the 2016 mapping); "any other response code as a failure";
  - rate: incoming webhooks 1 a second, short bursts allowed; about one message a second a channel; past it, 429 with
    `Retry-After` in seconds;
  - Block Kit: 50 blocks a message; section text 1 to 3,000 characters; up to 10 fields of 2,000; context up to 10
    elements; actions up to 25 elements; a button's text 75 (plain text), its url 3,000; a message `text` past 40,000
    characters is truncated (documented for chat.postMessage);
  - escaping: `&`, `<` and `>` become `&amp;`, `&lt;` and `&gt;` when not used for formatting; `<!here>` is a special
    mention; `verbatim: true` turns off automatic parsing (bare links, `@here`, channels).
- Microsoft Teams through Workflows (learn.microsoft.com `connectors/teams` "When a Teams webhook request is received",
  `power-automate/ip-address-configuration`, `troubleshoot/.../triggers-troubleshoot`; devblogs on the connectors'
  retirement):
  - Office 365 connectors stopped working by 2026-05-22; Workflows replace them;
  - body `{"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
    "contentUrl": null, "content": <Adaptive Card>}]}`; POST only; samples at card version 1.2; Teams supports cards
    up to 1.6 for bots; about 28 KB a message;
  - the trigger's "Anyone" setting takes no authentication header (one sent fails it); the other settings need a
    token;
  - hosts: `*.logic.azure.com` (moved since 2025-11-30) and `*.api.powerplatform.com` for the public cloud (the
    allowlist page; sovereign clouds have their own); the `sig` query value is the secret;
  - the success status isn't documented for this trigger (Logic Apps' request trigger answers 202 without a Response
    action), nor 429; throttling: 25 non-GET flow-bot posts a connection per 300 s; a flow throttled for 14 days is
    turned off;
  - cards (`task-modules-and-cards/cards/cards-format`, `cards-reference`, and the card schema
    adaptivecards.microsoft.com `schemas/adaptive-card.json`, read 2026-10-08): markdown renders in a `TextBlock` and
    in a fact's title and value, `[Title](url)` links included; a `TextRun`'s text: "Markdown is not supported";
    `RichTextBlock` is 1.2, its inlines `TextRun`s only, no `wrap`; incoming-webhook cards support every native
    element but `Action.Submit`, up to 1.6; a mention needs an `msteams` entity with the user's id;
  - httpx 0.28.1 (the lock's) sends a `json=` body compact and UTF-8 (`httpx._content.encode_json`).
- Google Chat incoming webhooks (developers.google.com `workspace/chat/quickstart/webhooks`, `spaces.messages/create`,
  `format-messages`, `limits`):
  - URL `https://chat.googleapis.com/v1/spaces/SPACE_ID/messages?key=KEY&token=TOKEN`; a webhook works only in its
    space;
  - POST JSON `{"text": …}`; cards over webhooks not documented; a message is at most 32,000 bytes;
  - 1 request a second a space, shared by all its webhooks; 429 past a quota (no `Retry-After` documented); errors
    are `google.rpc.Status` with 4xx or 5xx; the answer holds the message's `name` and `thread.name`;
  - `<users/all>` mentions everyone in a text message; no escape is documented; `<url|text>` is a link.
  - text syntax (`format-messages`, read again 2026-10-08): Chat's own by default - bold `*x*`, links
    `<url|text>`, mentions `<users/{user}>`; Markdown (`[text](url)`, `<chat-user …>`) only when the request sets
    `markupSyntax` to Markdown; bare URLs are linked; no escape is documented.

Tasks (test-first, in order):
1. SDK 0.6.0: a connection type whose base URL is a secret field (`SecretUrl`), the URL's shape the secret field's own
   pattern; a rate scope keyed by a part of a secret field (`secret_pattern`); the message model (title, text, label
   and value fields, link buttons, severity); the catalog checks the new declarations as data.
2. The runtime and the API for a secret-URL connection: the request goes to that exact URL only, with no credentials
   added; its parts join the secret index (as today); its quota scopes from URL parts; a URL of another shape is
   refused when the connection is created.
3. Slack: a connection type and `slack.send_message` (Block Kit, the documented escaping, every limit cut and marked;
   200 `ok` sent, 4xx fatal, anything else after sending unknown).
4. Teams: a connection type and `teams.send_message` (an Adaptive Card through a Workflows webhook; a 2xx is the flow's
   acceptance, any other answer unknown).
5. Google Chat: a connection type and `google_chat.send_message` (text, a scope per space).
6. Webhook: a connection type, `webhook.send_message` (the message as JSON) and `webhook.send_json` (a body of the
   workflow's).
7. Simulate: each node renders and reports what would be cut, sending nothing.
8. Proof: a workflow posting to Slack, Google Chat, Teams and a webhook through RunGraph against local fakes; simulated,
   nothing is sent.
9. Docs: the operator guide's connection types, their URLs and quotas.

Rulings:
- Ruling: 3c splits in two: 3c-1, the message model and its chat and webhook targets; 3c-2, SMTP (D20) and syslog
  (D21) - HTTP and socket transports share little, and 3b split the same way - cost if wrong: one more PR.
- Ruling: one plugin a target (`slack`, `teams`, `google_chat`, `webhook`), each with its connection type and node (the
  webhook two: task 6, below); the
  message model is the SDK's (`dewpoint.sdk.messages`), so any plugin can render it - a type key starts with its
  plugin's name - cost if wrong: none.
- Ruling: a secret-URL connection sends to its URL exactly, with no path, query or header of the node's; the URL's
  shape is its secret field's pattern, checked at creation and again where it's read; no verify hook (verifying
  would post to the channel; the pattern is the host and syntax check D3 names) - cost if wrong: a wrong URL fails at
  its first send (`connection_unavailable` or the provider's 404).
- Ruling: Slack's URL is its documented form only (`https://hooks.slack.com/services/T…/B…/…`, each segment letters
  and digits): GovSlack's host isn't documented, so it's refused - cost if wrong: a GovSlack workspace waits for a
  documented host.
- Ruling: Slack's quota scope is one a tenant (D9's fallback: the `T` segment isn't documented as the workspace), 1 a
  second with bursts of 3 - under-using the quota, never exceeding it - cost if wrong: a tenant's Slack messages queue
  behind one another at 1 a second.
- Ruling: a 429 or a 5xx after sending is `outcome_unknown` for every target (D10, D20): Slack and Google document a 429
  past their rate, not that the message wasn't posted - cost if wrong: such a send needs a person; the buckets keep it
  rare.
- Ruling: Slack text is escaped (`&`, `<`, `>`) and sent in `mrkdwn` objects with `verbatim: true`; the title is a bold
  line, not a `header` block, whose `plain_text` isn't documented to ignore mentions; button labels are `plain_text`
  (Slack's only kind for them) - a value from run data never mentions `@here` or a channel, nor makes a link - cost if
  wrong: a title loses the header's size. (Narrowed after the review of 1e71079, R4: no link labelled other than its URL;
  a bare URL may link to itself.)
- Ruling: Google Chat text replaces `<` and `>` with their full-width forms: no escape is documented, and `<users/all>`
  would notify the whole space - cost if wrong: a `<` in a message shows as `＜`.
- Ruling: Teams cards are version 1.2 (the documented samples'), rich text only (was "text blocks only": changed in
  task 4, below) and `Action.OpenUrl` buttons; hosts
  `*.logic.azure.com` and `*.api.powerplatform.com` only (the public cloud); no authentication header (the "Anyone"
  trigger) - cost if wrong: a sovereign-cloud or a tenant-only trigger isn't reachable yet.
- Ruling: a Teams 2xx is reported `{accepted: true}`, never `delivered`: the trigger's success status isn't documented,
  and a flow accepting a request doesn't prove the post - cost if wrong: none.
- Ruling: Teams's quota scope is per URL, 25 posts in 300 s (the flow-bot limit), bursts of 5 - cost if wrong: a fast
  workflow waits. (Changed after the review: one a tenant, below.)
- Ruling: Google Chat's scope is per space (D9: the URL's `spaces/{space}`), 1 a second, no burst - cost if wrong: none.
- Ruling: a generic webhook's URL is any https URL the guard allows (http only to allowlisted addresses, D7: dropped
  in task 6, below), the answer's status its only output (a receiver's body could quote anything) - cost if wrong: a receiver's answer isn't
  readable.
- Ruling (task 1): a secret URL's pattern is declared on the type (`SecretUrl(field, pattern)`), matched whole
  (`re.fullmatch`) wherever the secret is read, not put on the secret field: pydantic's default regex engine has no
  look-around, and with Python's it can't apply a pattern to a `SecretStr`, while a `$` in JSON Schema's Python check
  would accept a final newline - cost if wrong: none.
- Ruling (task 2): a secret-URL connection's request carries nothing of the node's - no path, query, parameters,
  headers or redirects - the provider's URL is the whole request target, and a header of the node's could add
  credentials the type doesn't declare - cost if wrong: a provider option set by query (Google Chat's threads) needs
  the type to declare it.
- Ruling (task 3, Slack): a 4xx is Slack's refusal (`slack.invalid_payload`, `slack.action_prohibited`,
  `slack.channel_not_found`, `slack.channel_is_archived`, else `slack.refused`), never retried; the runtime marks an
  ambiguous step's failure after a send `outcome_unknown` with that code kept (2b's rule: a later failure can't
  establish what an earlier request did) - cost if wrong: the step reads unknown where Slack said no.
- Ruling: a simulated send renders the message and reports what it would cut, `sent: true` like the real output's
  shape, opening no connection - cost if wrong: none.
- Ruling (task 4, Teams): run data goes in rich text blocks of text runs, never a `TextBlock` or a fact set: those
  render markdown, so a `[label](url)` from run data would be a link with a label of its choosing, while a text run's
  text isn't markdown; no `msteams` entity is ever sent, so `<at>` mentions no one - cost if wrong: fields lose the
  fact set's columns, and markdown a workflow meant shows as typed.
- Ruling (task 4, Teams): the body is kept within 24,000 bytes, measured as httpx sends it (compact UTF-8), under the
  documented ~28 KB; it's fitted in levels - nothing cut, then the text, field values, labels, and last links - and
  every cut or dropped value is named in `truncated` - cost if wrong: a message near the limit loses detail it could
  have kept.
- Ruling (task 4, Teams): every non-2xx answer is `teams.outcome_unknown`, a 4xx included (unlike Slack): the
  trigger's error answers aren't documented, so none can be read as a refusal - cost if wrong: a refused send reads
  unknown and needs a person.
- Ruling (task 4, Teams): the severity is a subtle line, as in Slack, not a container style: the styles' rendering in
  Teams isn't documented on the pages read - cost if wrong: the severity isn't coloured.
- Ruling (task 5, Google Chat): the URL is the documented form exactly - `spaces/{space}/messages?key=…&token=…`, in
  that order, no port nor other parameter; the space letters, digits, `-` and `_`; the key and token, whose
  characters aren't documented, the URL's unreserved ones, `%` and `=` - cost if wrong: a URL Google issues with
  another character is refused at creation until the class widens.
- Ruling (task 5, Google Chat): text in Chat's own syntax (no `markupSyntax`, so Markdown never applies), the title
  and labels bold; a link's `|` is percent-encoded so a URL never ends its link early - cost if wrong: a title's own
  `*` or `_` may format it.
- Ruling (task 5, Google Chat): the body is kept within 30,000 bytes as sent, under the documented 32,000, fitted in
  Teams' levels, every cut or dropped value named - cost if wrong: a message near the limit loses detail.
- Ruling (task 5, Google Chat): only a 200 is sent (Google answers the created message); a 4xx but 429 is
  `google_chat.refused`, naming the status only, never the answer's message (it could quote anything); any other
  answer is unknown - cost if wrong: as Slack's.
- Ruling (task 6, webhook): two nodes, `webhook.send_message` (the message model as JSON, the chat targets'
  configuration, so a workflow changes target without reshaping it) and `webhook.send_json` (D18's template body: a
  JSON value of the workflow's), not one node with a union, whose configuration would take two shapes - cost if
  wrong: one more node type.
- Ruling (task 6, webhook): https only: a secret URL's pattern starts with https (task 1), so D7's http to an
  allowlisted address isn't offered - cost if wrong: a plain-http receiver waits for a type that declares it.
- Ruling (task 6, webhook): the URL is a lowercase host name or IPv4 address (no IPv6 literal, no trailing dot), a
  port 1 to 65535, a path of RFC 3986's characters with its query; no user, no fragment - so the host the scope is
  keyed by is the host connected to - cost if wrong: an IPv6-literal or an uppercase URL is refused at creation. (The
  review added: not a chat target's own webhook host, below.)
- Ruling (task 6, webhook): one quota scope a host (`secret_pattern` on the URL's host), 1 a second with bursts of 5:
  a receiver's limit isn't known, and URLs to one receiver share its budget - cost if wrong: a fast workflow waits.
- Ruling (task 6, webhook): no header of the node's (task 2), so a receiver that needs an authentication header
  isn't reachable yet; the URL's own token is the credential - cost if wrong: such a receiver waits for a type that
  declares the header as a secret.
- Ruling (task 6, webhook): a 2xx is sent, its status the output; a 4xx but 429 is `webhook.refused`, naming the
  status only; a 3xx (no redirect is followed), a 429, a 5xx or anything else is unknown; simulated, the status is
  none - cost if wrong: as Slack's.
- Ruling (task 6, webhook): a workflow's body is at most 1 MiB as sent and never NaN, checked when the configuration
  is validated, before anything is sent; the message's size is its model's bound - cost if wrong: a larger body
  needs a larger bound.
- Ruling (task 6, webhook): its URL's path segments and query values of 8 characters or more join the secret index
  like any secret URL's (task 2), so an output naming one (a path word such as `incoming`) is redacted - cost if
  wrong: over-redaction of such words.

Fresh-context review of 3c-1 (at e62f132, 2026-10-08): no High, no Medium, six Low and two notes. Each finding is
fixed test-first, its protection checked by removing it (mutants named in each commit):
- L1 (`c82364d`): a secret URL's pattern was checked as text only, so `https://x|http://.*` started with https yet
  admitted plain http. Ruling: the runtime holds the rule - `secret()` takes a secret URL only if it starts with
  `https://`, and `base_url()` reads none that doesn't - since a pattern's text can't prove what it matches - cost if
  wrong: none.
- L2 (`c82364d`): a `secret_pattern` whose group is optional or empty keyed a scope by nothing. A scope's part must
  take part in the match and not be empty, where the secret is accepted and where scopes are keyed; else the secret
  is refused before any request.
- L3, a ruling challenge (`f6e6d4d`): Teams limits a flow bot's posts per Teams connection ("Non-Get requests per
  connection", `connectors/teams`, read again 2026-10-08), which no Workflows URL names; keyed by URL, flows sharing
  one connection each got a budget, as did one flow's URL spelt two ways. Ruling: Teams' scope is one a tenant
  (`teams.tenant`), D9's fallback as Slack's - under-using the quota, never exceeding it - cost if wrong: a tenant's
  Teams messages, every flow's together, queue at 25 in 300 s.
- L4 (`7719a88`): the generic webhook accepted Slack's, Google Chat's and Teams' webhook URLs, and
  `webhook.send_message` posts run data as it is, so a `<!channel>` would have reached Slack unescaped and the send
  charged `webhook.host`. Ruling: the generic type refuses `hooks.slack.com`, `chat.googleapis.com` and any host
  under `logic.azure.com`, `api.powerplatform.com` or `webhook.office.com`; those take their own type - cost if
  wrong: a workflow that wanted the raw JSON shape on such a host can't have it.
- L5 (`9c3728f`): the secret index held a URL's parts decoded only (a Chat token written `…%3D` was indexed as
  `…=`). The raw path, raw segments and raw query values of 8 characters or more join it too.
- L6 (`c48eec0`): httpx logs each request's whole URL at INFO; only the root's WARNING level kept it out. Configuring
  the process sets `httpx` and `httpcore` to WARNING.
- Note (docs): the webhook's docstring claimed a guard check at creation; the API's create path runs the type's
  checks only, and the guard vets on every connect. Docstring corrected (`7719a88`). The gap against D7's and D8's
  wording ("the API at connection creation") predates 3c-1; it's flagged for the owner as a separate task, not fixed
  here.
- Note (over-redaction): every secret-URL type's path segments and query values of 8 characters or more join the
  index (task 2), so a provider's constant words (`services`, `messages`, `workflows`, `triggers`, `2016-06-01`,
  `/triggers/manual/run`) are masked in every output of a run tree that uses such a connection, Mist's included.
  Ruling: kept, fail-closed - cost if wrong: such words read redacted in those outputs. Recommendation for the owner,
  not built: a type declares its URL's secret parts (named groups in its pattern: Teams' `sig`, Chat's `token`, a
  Slack URL's last segment), the rest indexed only within the whole URL; it needs each provider's secret parts
  verified first.

### 3c-1 checkpoint (2026-10-08, at c48eec0, local, not pushed)

- Built (tasks 1-9, test-first): SDK 0.6.0 with `SecretUrl`, `RateScope.secret_pattern` and the message model
  (32b2d31); secret-URL connections at run time and at creation, exact URL only (616391e); Slack (5d56645); Teams
  (4e34072); Google Chat (d34dd85); the generic webhook (684022d); simulate in each node; the RunGraph proof against
  local fakes (fa26d8f); the operator guides (e62f132).
- Fresh-context review: no High or Medium; L1-L6 fixed test-first, each protection checked by removing it; two notes
  recorded above.
- Verified at c48eec0: 1,656 tests across the SDK, the catalog, connections, egress, logs, the worker, the API's
  connections and uvicorn logging, every plugin and the CLI; ruff, format, mypy and import contracts; CodeQL's
  python analysis finds nothing locally, with CI's CLI and query filter.
- Not run: the full suite (about 10 minutes, asked first); a Compose proof; any real Slack, Teams, Google Chat or
  receiver call (each needs the owner's say and a test channel).
- Awaiting the owner: sign-off of this section's rulings (amended in tasks 4 and 6 and after the review, as marked);
  the full suite; push and PR.

A technical review of 1e71079 (pasted by the owner, 2026-10-08): the six fixes above check out; four Low (R1-R4), no
High or Medium. Each fixed test-first, its protection checked by removing it. A technical review: it grants no ruling
acceptance or push permission.
- R1 (`434db38`): `webhook.send_json` with a null body posted an empty request (httpx sends `json=None` as no body)
  and reported it sent. Ruling: a workflow's body is never null - refused when validated and by the published schema
  (`not: null`) - since sending `null` as content would need a content type a secret-URL request can't carry (task
  2) - cost if wrong: a receiver that wants a bare `null` can't have it. A wire-level regression sends every falsy
  body through the guarded transport to a local server: each arrives as its JSON with a JSON content type.
- R2 (`61ef7ee`): Teams' bucket of 5 refilled at 25 per 300 s granted 30 posts in 300 s (29 in 288 s, measured on
  the database bucket). Ruling (amends L3's): bursts of 5, then 20 in 300 s, so never more than 25 in any 300 s - a
  work-unit test counts it exactly - cost if wrong: a tenant's Teams posts stay a little under the quota.
- R3 (`4879091`): any Slack 200 was reported sent. Ruling: only a 200 whose body is exactly `ok` (the documented
  acknowledgement) is sent; any other 200 is `slack.outcome_unknown`, never retried - cost if wrong: such a send
  needs a person.
- R4 (`86c9d9c`): Slack's top-level `text` (the escaped fallback) still turns "Regular URLs" into links unless `parse`
  is `none` (`messaging/formatting-message-text`). Ruling (narrows Slack's and Google Chat's): run data never mentions
  anyone nor makes a link labelled other than its own URL; a bare URL may become a link to itself. `parse: none`
  isn't sent: it isn't documented for incoming webhooks, and an unknown field could make Slack refuse every send -
  cost if wrong: a bare URL from run data is clickable, showing where it goes. Option for the owner: try `parse:
  none` against a test channel (a real Slack call, on the owner's say). Docstrings and tests narrowed; a test pins
  the fallback against a labelled link.
- The creation-time vetting gap and the over-redaction note stand as separate owner decisions.

### 3c-1 checkpoint, after the review of 1e71079 (2026-10-08, at 86c9d9c, local, not pushed)

- Verified at 86c9d9c: 1,675 tests across the affected areas (as at c48eec0, plus the webhook's wire test); ruff,
  format, mypy and import contracts; CodeQL's python analysis finds nothing locally.
- Not run: the full suite (about 10 minutes, asked first); a Compose proof; any real provider call.
- Awaiting the owner: technical closure of R1-R4; sign-off of this section's rulings (amended as marked); the full
  suite; push and PR.
- The review of the fixes (pasted by the owner, 2026-10-08): R1-R4 technically closed at 2ee0d8c, against the amended
  contracts, no new findings (264 existing tests and 52 closure checks run independently; no real provider call). R1
  and R4 change the promised behaviour rather than preserve it. A technical closure only: the revised null-body and
  link rulings, and every other 3c-1 ruling, still await the owner's sign-off; the creation-time vetting gap and the
  over-redaction note stay separate decisions.
- The owner signed off this section's rulings, as amended and marked (2026-10-08), and authorized the full suite, the
  push and the PR.
- The full backend suite at 9e9881b (2026-10-08), as CI runs it: 3,834 passed with `-n auto`, then the CEL gate tests
  on their own, 398 passed and 8 skipped.

- The first push was declined by GitHub's push protection (2026-10-08): `test_slack.py` held Slack's documented
  example webhook URL as one literal (since 5d56645), and gitleaks (the repository's config) also found the
  secret-URL tests' fake key `k3y…` (since 616391e). On the owner's choice, the branch was rewritten from f0e7bf5
  (`git filter-branch --tree-filter`, one idempotent text substitution in every commit): Slack's URL is assembled from
  parts, the fake key is a run of `k` of the same length. Code is identical; the three test files alone differ, and
  gitleaks finds nothing in the range. The pre-rewrite branch is kept as `backup/plugins-3c1-pre-rewrite` (c2a3127).
  Every SHA this section names is a pre-rewrite one; the map, in order: ebf932b -> b71326b, 32b2d31 -> dd4bc7b, 616391e -> 7bd65f3, 5d56645 -> 0bde4a3, 4e34072 -> dd7b68b, d34dd85 -> 4914391, 684022d -> f985277, fa26d8f -> 8545b6e, e62f132 -> c63ac2d, c82364d -> eaf909f, f6e6d4d -> ae87c81, 7719a88 -> 548d5d4, 9c3728f -> 78fc369, c48eec0 -> 1efdda9, 1e71079 -> 3f74d5d, 434db38 -> 06ad7fb, 61ef7ee -> de3e9a8, 4879091 -> 8201fab, 86c9d9c -> a505157, 2ee0d8c -> 48069a7, cf69a8d -> b8fc955, be0e579 -> cba7847, 9e9881b -> e7efe68, c2a3127 -> 5eccfed.
- 3c-1 MERGED by the owner (#58, merge 6e092b5, 2026-10-08), CI green.

## 3c-2 Messaging: SMTP and syslog

Branch `feat/plugins-3c2` from `origin/main` 6e092b5 (#58), started 2026-10-08 on the owner's "3c-2". A go to build;
this section's rulings await the owner's sign-off. No migration expected. No real mail or syslog server is contacted:
tests and the proof run against local fakes.

Facts checked (official sources, read 2026-10-08 by a research subagent, the key ones spot-checked; the stdlib read
from the installed CPython 3.12.3; never from memory):
- `smtplib` (CPython 3.12.3 source, docs.python.org/3.12): `SMTP.connect()` calls `_get_socket(host, port, timeout)`,
  which a subclass may replace; `_host`, the name `starttls()` and `SMTP_SSL` check the certificate against
  (`server_hostname=self._host`), is set only in `__init__`; `starttls()` raises `SMTPNotSupportedError` when the
  server doesn't advertise it and discards the extensions after the handshake; `login()` tries CRAM-MD5, PLAIN, LOGIN
  in that order; `sendmail()` returns the refused recipients when at least one is accepted, raises
  `SMTPRecipientsRefused` when all are, `SMTPSenderRefused` on MAIL, `SMTPDataError` on DATA or after the payload;
  `data()` dot-stuffs and writes the payload, then reads the final reply; `timeout` bounds each blocking operation.
- `email` (CPython 3.12.3, tried; docs `email.policy`): `EmailMessage` refuses a header value holding CR or LF
  (`ValueError`), To included; `email.policy.SMTP` writes CRLF and folds lines to 78; `make_msgid()` defaults to the
  local host name (`socket.getfqdn()`), so a domain must be passed; `headerregistry.Address` refuses spaces, CR/LF and
  angle brackets in an addr-spec.
- RFC 5321: end of data "tells the SMTP server to now process the stored recipients" (§3.3); a 250 to it hands over
  responsibility (§2.1, §4.1.1.4); after a 4yz or 5yz to it the server "MUST NOT make a subsequent attempt to deliver"
  and the client retains responsibility (§4.2.5); a connection failure is treated "as if a 451 response had been
  received" (§3.8), while a spurious timeout after the data "would typically result in delivery of multiple copies"
  (§4.5.3.2.6); 4yz transient, 5yz permanent (§4.2.1); 421 may answer any command (§4.2.2); text lines at most 1000
  octets with CRLF (§4.5.3.1.6); at least 100 recipients must be buffered (§4.5.3.1.8); dot-stuffing (§4.5.2). No
  sentence says outright that a message goes to the accepted recipients only; it follows from the buffer model
  (§3.3, §4.1.1.3).
- RFC 3207: after the TLS handshake the client MUST discard prior knowledge and SHOULD re-issue EHLO (§4.2); 454 is a
  temporary failure (§4); deleting "250 STARTTLS" is a man-in-the-middle attack (§6), and TLS can be required for
  selected hosts (§6). RFC 8314: implicit TLS on 465 (§3.3), preferred to STARTTLS (§1); MUAs MUST validate the server
  certificate per RFC 7817 (§5.3). RFC 8997: TLS 1.2 minimum. RFC 6409: submission on 587 (§3.1). RFC 4954: 235
  success, 535 invalid credentials, 534 too weak, 454 temporary, 530 required (§6); PLAIN over TLS (§4), and no PLAIN
  after a failed certificate check (§14). RFC 5322: Date and From required, Message-ID SHOULD (§3.6); lines at most
  998 characters (§2.1.1). RFC 3834: `Auto-Submitted: auto-generated` SHOULD mark mail from automatic processes, and
  responders SHOULD NOT answer it (§2, §5.2).
- RFC 5424: `<PRI>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID SD MSG`; PRI = facility × 8 + severity, no leading zero
  (§6.2.1); facilities 0-23, severities 0 Emergency to 7 Debug (Tables 1, 2); HOSTNAME 255, APP-NAME 48, PROCID 128,
  MSGID 32 characters of `%d33-126`, `-` for none; TIMESTAMP RFC 3339 with upper-case T and Z, at most 6 fraction
  digits (§6.2.3); in an SD-PARAM value `"`, `\` and `]` MUST be escaped (§6.3.3); a UTF-8 MSG MUST start with the BOM
  (§6.4); receivers MUST accept 480 octets and SHOULD accept 2048 (§6.1).
- RFC 5425 (updated by RFC 9662): TLS on 6514, `MSG-LEN SP SYSLOG-MSG` framing (§4.3), receivers SHOULD handle 8192
  octets (§4.3.1), the sender sends close_notify (§4.4), the host name matched against the certificate (§5.2); RFC
  9662: TLS 1.2 mandatory, TLS 1.3 preferred if implemented, ECDHE-GCM preferred. RFC 5426: one message per datagram
  (§3.1), no acknowledgement (§3.2), port 514 (§3.3), receivers SHOULD accept 2048 octets (§3.2), TLS outside managed
  networks (§4.3); 65,507 is derived (65,535 less the headers), not written. RFC 6587 (Historic): octet counting, or
  LF framing that splits a message holding an LF (§3.4.2); no standard port; not recommended for new deployments
  (§4).
- CEF, "Implementing ArcSight Common Event Format (CEF) - Version 27" (OpenText, SmartConnectors 25.1 docs): header
  `CEF:Version|Vendor|Product|Version|Device Event Class ID|Name|Severity|Extension`; in the header `|` and `\` are
  escaped with `\`; in the extension `=` and `\` are escaped and newlines written `\n`; UTF-8; Severity 0-10 (1-3 Low,
  4-6 Medium, 7-8 High, 9-10 Very-High) or names; Vendor and Product 63, Version 31, event class 1023, Name 512; `msg`
  1023; carried after a syslog header.

Tasks (test-first, in order):
1. SDK 0.7.0: a connection type may declare an SMTP server (`SmtpServer`: its config fields for host, port, security
   and sender, an optional username field and password secret field); `connection.smtp` sends a message to recipients
   and returns the refused ones, or probes (connect, EHLO, STARTTLS, AUTH, QUIT); `MailRefused` names the stage and
   reply code of a definite refusal; the catalog checks the declaration as data.
2. Core SMTP (`core/egress/smtp.py`): `smtplib` in a thread over a socket connected to an address the guard vetted,
   `_host` the configured name; implicit TLS or required STARTTLS (TLS 1.2+, the certificate checked), plaintext only
   to an allowlisted address; AUTH PLAIN or LOGIN only over TLS; the outcome classified (task 3's rulings).
3. The runtime's `connection.smtp`: tokens from the type's scopes; a definite refusal leaves the attempt clean, a
   connection lost after the payload doesn't; heartbeats while the thread works; refused when simulated; a plugin call
   may probe only.
4. Email: an `email` connection type (verify by probe) and `email.send_message`, the message model as a plain-text
   email to its recipients.
5. Syslog: a `syslog` connection type and `syslog.send_message`, RFC 5424 (or a CEF payload) over TLS, UDP or TCP.
6. Simulate: each node renders and reports what it would cut, sending nothing.
7. Proof: a workflow mailing and logging through RunGraph against a local SMTP server (STARTTLS) and local syslog
   receivers (TLS, UDP); simulated, nothing is sent.
8. Docs: the operator egress guide (SMTP modes and ports, syslog transports, the hosts to allow), the lifecycle guide.

Rulings:
- Ruling: 3c-2 is one slice, SMTP and syslog, as the owner named it - cost if wrong: a larger review.
- Ruling: SMTP goes through stdlib `smtplib` in a worker thread (D20's choice; no new dependency), on a socket the
  runtime connects to the guard's vetted address; `_host` is set to the configured name, which STARTTLS and implicit
  TLS check the certificate against - cost if wrong: one thread a send.
- Ruling: three security modes: `starttls` (required: not offered, refused or failed, nothing more is sent - RFC 3207
  names a missing `STARTTLS` an attack), `tls` (implicit, RFC 8314), `none` (only to an allowlisted address, D7, and
  never with a password, RFC 4954); TLS 1.2 or later (RFC 8997), the certificate validated against the configured
  host (RFC 8314 §5.3) - cost if wrong: a server without TLS needs an allowlist entry and no authentication.
- Ruling: the runtime authenticates (D4's `smtp_login`; the plugin never holds the password), with PLAIN, else LOGIN,
  only once TLS is up; never CRAM-MD5, `smtplib`'s first choice - cost if wrong: a server offering CRAM-MD5 alone
  can't be used.
- Ruling: nothing can be delivered until the payload is written (RFC 5321 §3.3), so a failure before it sends nothing:
  a 4yz, a 421 or a network failure is retryable, a 5yz fatal. After the end of data, a 250 is sent; a 4yz or 5yz is a
  definite non-delivery (§4.2.5) and leaves the attempt clean (4yz retryable, 5yz fatal); a connection lost or timed
  out after the payload is unknown (§4.5.3.2.6 warns of duplicates) - cost if wrong: a server that delivers after a
  4yz duplicates on retry.
- Ruling: when some recipients are refused, the message goes to the others (RFC 5321's buffer model; `smtplib`
  returns the refused); the step succeeds and names the refused recipients; all refused is a refusal - cost if wrong:
  a workflow must read `refused`.
- Ruling: the envelope and header sender are the connection's (`from_address`), never the node's, so a workflow can't
  send as anyone else - cost if wrong: one connection a sender.
- Ruling: recipients are `to` only, 1 to 50 (under RFC 5321's 100), ASCII addresses matched whole (no quoted local
  part, no SMTPUTF8); no cc or bcc, so every recipient sees the others - cost if wrong: hidden recipients wait for a
  later version.
- Ruling: the email is plain text, UTF-8 (`email.policy.SMTP`): From, To, Subject (the title, else the text's first
  line, at most 200 characters), Date, a Message-ID on the sender's domain (never the worker's host name),
  `Auto-Submitted: auto-generated` (RFC 3834); the body is the text, the fields as `label: value`, the links as
  `label: url` and the severity; no HTML - cost if wrong: no rich formatting.
- Ruling: EHLO names the sender's domain, never the worker's host name - cost if wrong: a server checking EHLO against
  reverse DNS may refuse.
- Ruling: one quota scope a server host (`email.server`, from the config's host): bursts of 5, then 1 a second; no
  quota is documented (D9's fallback) - cost if wrong: a fast workflow waits.
- Ruling: verify probes (D3's read-only adapter): connect, EHLO, STARTTLS, AUTH, QUIT, never MAIL - cost if wrong:
  none.
- Ruling: one session a send (connect to QUIT); 60 s for each socket operation; a timeout after the payload is
  unknown - cost if wrong: a slow server's success reads unknown.
- Ruling: syslog is RFC 5424 only: a UTF-8 MSG with the BOM; STRUCTURED-DATA, PROCID and MSGID nil (an SD-ID of ours
  needs a registered enterprise number); HOSTNAME and APP-NAME the connection's (`-` and `dewpoint` by default);
  TIMESTAMP UTC to the microsecond - cost if wrong: fields only in the MSG.
- Ruling: a syslog message is one line: the title, the text, `label: value` fields and `label <url>` links joined by
  ` | `; CR and LF become spaces - LF framing would split it, and receivers show lines - cost if wrong: multi-line
  text is flattened.
- Ruling: severities map info 6 (Informational), success 5 (Notice), warning 4 (Warning), critical 2 (Critical); the
  facility is the connection's, 0 to 23, 1 (user-level) by default - cost if wrong: none.
- Ruling: transports are `tls` (the default, 6514, octet counting, TLS 1.2 or later, the certificate checked, no
  client certificate: RFC 5425, 9662, D21), `udp` (514, one message a datagram, RFC 5426) and `tcp` (octet counting,
  or LF framing for legacy receivers, RFC 6587); plain transports only to allowlisted addresses (D7) - cost if wrong:
  an unlisted plain receiver is refused.
- Ruling: a UDP message is at most 2048 octets (receivers SHOULD accept 2048: RFC 5424 §6.1, RFC 5426 §3.2), a TCP or
  TLS one at most 8192 (RFC 5425 §4.3.1); the MSG is cut to fit, marked and reported - cost if wrong: a datagram
  fragmented on a small-MTU path may be lost.
- Ruling: the CEF option's MSG is `CEF:0|Dewpoint|Dewpoint|<version>|<event class>|<name>|<severity>|msg=…`, escaped
  as CEF v27 says; the Name the title (else the text's start) at most 512, `msg` the rest at most 1023; severity info
  3, success 1, warning 6, critical 10 - cost if wrong: a SIEM wanting other keys maps them itself.
- Ruling: every syslog send is ambiguous (D21): `sent` means the frame was handed over, never that it was received
  (UDP has no acknowledgement); a failure once a byte may have left is unknown - cost if wrong: none.
- Ruling: syslog has no quota scope (none is documented) and no secret (no client certificates in v1) - cost if
  wrong: a runaway workflow isn't slowed by the plugin.
- Ruling (task 2): the SMTP session is staged by hand (EHLO, STARTTLS, AUTH, MAIL, RCPT, DATA, payload) rather than
  through `smtplib.sendmail`, so the payload's first byte is the boundary between a refusal (nothing delivered) and
  `MaybeSent`; the session wraps the socket in TLS itself, the certificate checked against the configured name -
  cost if wrong: none.
- Ruling (task 2): only a 250 answers the message's end as sent; another 2yz is unknown, as is anything unreadable
  (RFC 5321 answers the end with 250) - cost if wrong: a server answering 251 there needs a person.
- Ruling (task 2): when every recipient is refused, a transient refusal among them makes the whole refusal transient
  (a retry may reach them), else it's permanent; a 421 to any RCPT ends the send - cost if wrong: a retry repeats
  permanent refusals.
- Ruling (task 2): the runtime puts a message on the wire whole or not at all: a bare CR or LF (how a second message
  is smuggled past a server), a NUL or a line past 998 octets is refused before connecting, as is a message past 10
  MiB - cost if wrong: a plugin's message must be well formed (`email.policy.SMTP` makes it so).
- Ruling (task 2): the username and password are printable ASCII (`smtplib` signs in with ASCII), at most 256 and
  1024 characters - cost if wrong: a non-ASCII password can't be used.
- Ruling (task 3): a probe takes a token from the type's scopes (it reaches the server) and never counts as a send
  (it sends no MAIL); a send heartbeats every 10 s while its thread works - cost if wrong: none.
- Ruling (task 4): the body is quoted-printable UTF-8, so every line on the wire is ASCII and short whatever the
  server's 8BITMIME; control characters in the subject and the sender's name become spaces; simulated, the email
  renders from a placeholder sender (the connection isn't opened) - cost if wrong: none.
- Ruling (task 4): verify names what failed: `auth_failed` (535 at AUTH), `refused`, `tls_unavailable`,
  `auth_unavailable`, `tls_verification_failed`, `egress_refused`, else `unreachable` - cost if wrong: none.
- Ruling (task 5): a syslog node sends through the step's guarded network (`ctx.net`) to the connection's host and
  port only, read from the connection's validated config; no SDK change: syslog has no credentials to apply - cost if
  wrong: none.
- Ruling (task 5): a CEF payload is sent without the BOM (RFC 5424's MSG-ANY): CEF readers expect `CEF:` first; its
  Device Version is the plugin's - cost if wrong: a strict receiver reads its encoding as unspecified.
- Ruling (task 5): simulated, a syslog message is cut for the default transport, TLS (8192 octets): the connection
  isn't opened, so its transport isn't known - cost if wrong: a UDP connection cuts more than the simulation shows.

Fresh-context review of 3c-2 (at a468385, 2026-10-08): one High, one Medium, four Low; no ruling challenge. Each is
fixed test-first, its protection checked by removing it (mutants named in each commit):
- H1 (`d47941d`): `smtplib` reads a reply's continuation lines without end, and sessions ran on the event loop's
  default executor, which the guard resolves names on: a tenant's own server (no allowlist entry, no certificate
  needed before STARTTLS) could flood a greeting until the worker ran out of memory, or drip a byte a minute and
  hold threads until DNS stalled for every guarded request. Ruling: a reply is at most 100 lines and 64 KiB; a
  session at most 120 s, aborted past it (unknown once the payload may have left, else nothing sent); sessions run on
  a pool of 8 threads of their own - cost if wrong: a send to a server slower than 120 s fails, and when 8 sessions
  are under way across the worker's tenants, further sends wait.
- M1 (`d47941d`): a cancel during `create_connection` or the implicit-TLS handshake closed nothing, and the session
  went on to deliver, or to the next address. An abort now sets a flag `_connect` checks before each address and
  after connecting; once a socket is open, closing it ends the session at its next read or write. An attempt and a
  plugin call keep one mail client and abort its sessions when they close.
- L3 (`97b345a`): an encoded word (`=?utf-8?b?...?=@x.il`) passed as an address, and a mail reader decoded the To
  header into recipients the envelope never had. Ruling: `MAIL_ADDRESS` refuses `=?` in a local part, and the To
  header is built from `Address` objects - cost if wrong: such an address, valid in RFC 5322, can't be mailed.
- L4 (`97b345a`): a CEF line over UDP reached 2155 octets. The name and the message are fitted, by octets, into what
  the header leaves, cut before an escape; an event class that leaves no room fails `syslog.too_large` before
  sending.
- L5 (`97b345a`): duplicate recipients muddled what was refused. Ruling: each recipient once (compared without case),
  refused by the runtime and the node - cost if wrong: a workflow must dedupe its list.
- L6 (`97b345a`): U+2028 and its like in a title crashed rendering, and the ambiguous node ended `outcome_unknown`
  though nothing was sent. Every line break `str.splitlines()` knows becomes a space in a header, and any rendering
  failure is `email.invalid_message`, fatal, before anything is sent.
- Also: `SmtpTarget`'s repr leaves the password out; `smtp_problems` reports an enum with an unhashable item rather
  than raising.

### 3c-2 checkpoint (2026-10-08, at bce79ea, local, not pushed)

- Built (tasks 1-8, test-first; the runtime's and syslog's tests were written before their code but run after it,
  while a mutation run held the tree, so their mutants are the proof): SDK 0.7.0 (afc0466); guarded SMTP (109344e);
  the runtime's `connection.smtp` (6d3eb25); email (abbc7ee); syslog (bb9a222); a host-less type opens with no HTTP,
  found by the proof (c926c49); the RunGraph proof (3781f48); the operator guides (a468385).
- Fresh-context review: H1, M1 and L3-L6 fixed test-first, each protection checked by removing it (d47941d, 97b345a,
  ledger bce79ea).
- Verified at bce79ea: 1,935 tests across the SDK, the catalog, connections, egress, logs, the worker, the API's
  connections and plugin calls, every plugin and the CLI; ruff, format, mypy, import contracts; gitleaks over the
  branch's commits finds nothing; CodeQL's python analysis finds nothing locally.
- Not run: the full suite (about 10 minutes, asked first); a Compose proof; any real mail server or syslog receiver
  (each needs the owner's say and a test account or receiver).
- Awaiting the owner: sign-off of this section's rulings; the full suite; push and PR.

A technical review of c092eb9 (pasted by the owner, 2026-10-08): M1 still reproducible, and one more Low; no
technical closure. Both fixed test-first, each protection checked by removing it (`a1cd3f4`):
- M1: `wrap_socket` detaches the raw socket before its blocking handshake, so an abort closed a dead socket and the
  handshake went on to deliver, for implicit TLS and STARTTLS, after a cancel, `aclose()` or a deadline that had
  answered `NotSent` (a retry could duplicate the mail). The TLS socket is made without its handshake and is the
  session's before it runs; a fence catches an abort that landed before. A test proxy holds the server's handshake
  records, opening the window in every mode.
- Found by stress runs of those tests (1 hang in 10 under load): an abort closed the socket from the event loop while
  the session's thread was blocked in OpenSSL, which a close doesn't reliably wake, and the descriptor's number could
  be reused by another socket; `SSLSocket.shutdown` also dropped the TLS object that thread used. Ruling: an abort only
  shuts the descriptor down (the blocked call wakes, every later one fails); only the session's own thread closes its
  socket, the live TLS one after a failed STARTTLS included - cost if wrong: none. 0 hangs in 80 stress runs after.
- L1: a session was registered only after vetting, and a closed client took new sends. `aclose()` sets a closed state,
  refused before vetting and checked after it, as the guarded websocket's fence; a closed client resolves nothing.
- CodeQL then flagged a test wrapping a socket with the test CA's context (`py/insecure-protocol`, no TLS floor it
  could see): the tests' client context now requires TLS 1.2, as the platform's (`d6da745`); CodeQL finds nothing.

### 3c-2 checkpoint, after the review of c092eb9 (2026-10-08, at d6da745, local, not pushed)

- Verified at d6da745: the whole backend suite, 4,478 passed and 8 skipped in 9 minutes with `-n auto`, the CEL gate
  tests among them (run by a mistake: a shell glob emptied the intended file list, so pytest ran everything; not the
  owner's authorized run, and CI keeps the gates apart); 1,950 tests across the affected areas at d0ec07a; ruff,
  format, mypy, import contracts; gitleaks over the branch's commits; CodeQL's python analysis finds nothing.
- Not run: a Compose proof; any real mail server or syslog receiver.
- Awaiting the owner: technical closure of M1 and L1; sign-off of this section's rulings (the review's new ones
  marked); push and PR.

A technical review of 82ae00b (pasted by the owner, 2026-10-08): M1 technically closed; L1 only partly: the
attempt's and a plugin call's mail client is made lazily, after the scope lookup and the quota wait, so a closure
during either recorded nothing and the resumed send (or probe) made a fresh client and went on. Fixed test-first
(`7616eb8`): both record their closure and refuse to make a client after it; each protection's removal fails a test.
A technical review only: no ruling sign-off or push authorization.
- The owner (2026-10-08): "ok, we're good. push and PR" (L1 technically closed; push and PR authorized), then signed
  off this section's rulings. `origin/main` had moved (#60, #61, #62): merged into the branch (63c40ff, no conflicts,
  no rebase, so every reviewed SHA stands); after it, 2,897 tests across both sides' areas pass, with ruff, mypy and
  the import contracts.
- 3c-2 MERGED by the owner (#63, merge 764a365, 2026-10-08), CI green after the owner reran a failed backend job (a
  2b-4a retention test's deadlock, unrelated; a separate session investigates it).

## 3d-1 ITSM: PagerDuty

Branch `feat/plugins-3d` from `origin/main` 764a365 (#63), started 2026-10-08 on the owner's "go" for 3d. A go to
build; this section's rulings await the owner's sign-off. No migration expected. No real PagerDuty call: tests and the
proof run against local fakes.

Facts checked (official sources, read 2026-10-08 by a research subagent; developer.pagerduty.com now redirects to
docs.pagerduty.com; never from memory):
- Events API v2 (docs.pagerduty.com `developer/send-alert-event`, `developer/events-api-v2-overview`, the
  `create-v2-event` reference, `developer/events-api-rate-limits`; support.pagerduty.com `service-regions`):
  - POST JSON to `https://events.pagerduty.com/v2/enqueue`; the EU region's Events API host is
    `https://events.eu.pagerduty.com` (its path isn't written out), and US-region requests with an EU key are
    forwarded; no Authorization header in any example: the `routing_key` is in the body;
  - `routing_key`: "the 32 character Integration Key"; `event_action`: trigger, acknowledge or resolve; `dedup_key`
    at most 255 characters, generated by PagerDuty when a trigger omits it, required otherwise; `payload.summary`
    (at most 1024), `payload.source` and `payload.severity` (critical, error, warning, info) required; `timestamp`,
    `component`, `group`, `class`, `custom_details` optional; `links` (`href`, `text`), `images` (https `src`);
  - 202 "Accepted" (body `status`, `message`, `dedup_key`), don't retry; 400 "Bad Request", don't retry; 429 and 5xx
    "retry after some time" (a few minutes, or 3 times 30 s apart: the pages differ); network errors retried;
  - about 120 calls a minute per integration key over a 60 s window, account limits too; a 429 isn't ingested;
  - an event with an open alert's `dedup_key` applies to it; after it's resolved, a trigger opens a new one and an
    acknowledge or resolve is dropped; an acknowledge or resolve with no open alert creates none; one sent through
    another routing key is dropped (the status of a dropped one isn't documented);
  - a payload is at most 512 KB.

Tasks (test-first, in order):
1. SDK 0.8.0: `BodyField(field, secret)`, a connection type's credentials as one top-level field of a request's JSON
   body (D4's `body_field`); the catalog checks it as data.
2. The runtime: a connection with a body field puts the secret into every request's JSON object body; a node can't
   set that field, nor send a body that isn't a JSON object; nothing is sent otherwise.
3. PagerDuty: a connection type (the region's host, the routing key) and `pagerduty.trigger_alert` (keyed),
   `pagerduty.acknowledge_alert` and `pagerduty.resolve_alert` (idempotent).
4. Simulate: each node renders its event and reports what it would cut, sending nothing.
5. Proof: a workflow triggering, acknowledging and resolving one alert through RunGraph against a local Events API
   fake; simulated, nothing is sent.
6. Docs: the operator guide's PagerDuty connection, its hosts and its quota.

Rulings:
- Ruling: 3d splits in two, as 3c did: 3d-1 PagerDuty (fully documented); 3d-2 ServiceNow, whose Resolved state value,
  mandatory resolution fields, `correlation_id` length and `short_description` length aren't documented, and whose
  query ignores an invalid part by default (a `reconcile()` must check what comes back) - cost if wrong: one more PR.
- Ruling: the routing key is the connection's secret, sent as the body's `routing_key` by the runtime (`BodyField`),
  never held by the plugin; the region picks the host, `events.pagerduty.com` or `events.eu.pagerduty.com`, the path
  `/v2/enqueue` on both (the EU path is the US one by inference: only the host is documented) - cost if wrong: an EU
  send fails with a 404 and nothing is sent; the US host forwards EU keys.
- Ruling: no verify hook: checking a routing key means sending an event, which would page someone - cost if wrong: a
  wrong key fails at its first send (400).
- Ruling: one quota scope a routing key: bursts of 20, then 100 a minute, never more than PagerDuty's 120 in any
  60 s - cost if wrong: a fast workflow waits.
- Ruling: `trigger_alert` is keyed: its `dedup_key` is the config's, else the step's idempotency key (64 hex), so a
  retried trigger joins the alert it opened; one resolved meanwhile opens a new alert (PagerDuty's documented
  behaviour; the outline's accepted cost). Acknowledge and resolve are idempotent (a repeat changes nothing); their
  `dedup_key` is required - cost if wrong: a retry after a resolve pages again.
- Ruling: a 202 is applied; a 400 is `pagerduty.invalid_event`, fatal; a 429 or 5xx is retried, the runtime waiting
  out a short `Retry-After` in the attempt - cost if wrong: none.
- Ruling: the trigger renders the message model: `summary` the title, else the text, at most 1024 characters; the
  message severity maps to PagerDuty's (info and success to info, warning, critical); `source` the config's (default
  `dewpoint`); `custom_details` the text and the fields; `links` the message's links; the event kept within 500,000
  bytes as sent (PagerDuty takes 512 KB), cut and reported - cost if wrong: a field a team wants maps elsewhere.
- Ruling: a simulated event renders and reports what it would cut, opening no connection, in the real output's shape
  (3c's precedent; D13's "exact request" isn't echoed) - cost if wrong: a simulation doesn't show the body.
- Ruling (task 2): a body-field connection's request must carry a JSON object body the field isn't in: no body, a
  non-object body, raw `content` (httpx would send it alone) or the node's own field is refused before anything is
  sent - cost if wrong: such a type can't serve a GET (PagerDuty has none).
- Ruling (task 3): a 2xx other than 202 is `pagerduty.unexpected`, retried (every PagerDuty event is keyed or
  idempotent, so a retry repeats nothing); the trigger's `class` is the config's `event_class` (a Python keyword);
  `custom_details` is `{text, fields: [{label, value}]}`, keeping repeated labels; a summary from the text is cut
  without being reported (the whole text is in the details), a title always fits (at most 1000) - cost if wrong: none.
  (The review's L5 replaces the last part: a summary is at most 1024 bytes, a title cut to fit reported.)

Fresh-context review of 3d-1 (at 5856876, 2026-10-08): no High, one Medium, seven Low, three weak tests, one
suspicion; no ruling challenged but simulate's, already awaiting sign-off. Each is fixed test-first, its protection
checked by removing it (24 mutants, all killed; `98ff5628`):
- M1: the nodes kept the SDK's default retries (3 attempts, 1 s then 2 s): a few seconds of PagerDuty 5xx and no
  page went out, against PagerDuty's advice ("retry after some time", "preferably with a backoff of a few minutes").
  Ruling: each PagerDuty node is retried after 30 s, 60 s, then 120 s, four attempts in three and a half minutes (a
  step may set its own number, not the interval) - cost if wrong: a retried trigger has 3.5 minutes, not 3 s, in
  which a human's resolve makes it open a second alert. The RunGraph proof cuts its first wait to 1 s (its local
  server doesn't skip time); the unit tests pin the schedule.
- L1: `credentials()` and `body_credentials()` returned nothing for an auth kind the runtime doesn't know (the catalog
  refuses one: defence in depth), so such a type would send without credentials. It's unusable now
  (`InvalidValueError`, so `ConnectionUnavailable`).
- L2: a node's key could pass the field check as a `str` subclass hashing elsewhere, putting a second `routing_key`
  on the wire (the runtime's last). The body must be exactly a `dict` with `str` keys.
- L3: the SDK and the catalog took a body field beside a stream (its handshake would open unauthenticated) or a
  verify (a read-only call can't carry a body). Ruling: a body-field type has neither - cost if wrong: a provider
  needing both waits for another auth kind.
- L4: a 408 or 425 was fatal. Ruling: both are retried as `pagerduty.unavailable` (transient in RFC 9110 and RFC
  8470; PagerDuty documents neither) - cost if wrong: an event PagerDuty would never take is tried four times.
- L5: a summary kept line breaks other than CR and LF, and other control characters; and its 1024 was counted in
  code points, while PagerDuty doesn't say its unit (a fatal 400 would lose the page). Ruling: every control
  character and line break becomes a space, and a summary is at most 1024 UTF-8 bytes, which fits any unit; a title
  cut to fit is reported as `title` - cost if wrong: a non-ASCII title is cut shorter than PagerDuty would take (the
  text stays whole in the details).
- L6: `Unsealed`'s repr held the secret, the base (a secret URL's), the header and the body credentials; none is in it
  now (no path printed it).
- L7: the dedup key's description promised the step's key "when empty", but an empty key is refused (as the repo's
  other optional strings are); it says "when not set" now. Wording only: no test.
- Weak tests: the largest-event test asserts the cut for every fill (each grows past the budget); a read-only channel
  and a probe are shown to send nothing through a body field. The proof's "no row holds the key" can't fail through
  these nodes' outputs; it stays as a guard against the runtime writing the body into a step's input.
- Suspicion, not confirmed: PagerDuty calls the Events API asynchronous and doesn't document the order it processes
  events in (docs.pagerduty.com `developer/events-api-v2-overview`, read 2026-10-08), so an acknowledge or resolve
  sent right after its trigger may be processed first and dropped. Ruling: a limit the operator guide states; the
  nodes neither wait nor check (checking needs the REST API and another credential) - cost if wrong: a workflow
  acknowledging at once may leave an alert open.

### 3d-1 checkpoint (2026-10-08, at 98ff562, local, not pushed)
- Tasks 1-6 done: SDK 0.8.0's `BodyField` (29889eb), the runtime's body field (580196c), the PagerDuty plugin and its
  simulation (56038b1), the RunGraph proof (30dbd26: a trigger answered 503 once and retried with one `dedup_key`,
  then acknowledged and resolved; simulated, nothing sent; its 7 wiring mutants killed, again after the retry change),
  the operator guide (5856876); the review's fixes (98ff562).
- Verified at 98ff562: 2,093 tests across the SDK, the catalog, connections, the worker, every plugin, the API and the
  CLI; ruff, format, mypy, import contracts; gitleaks over the branch's commits finds nothing; CodeQL's python
  analysis finds nothing locally, with CI's CLI and query filter.
- Not run: the full suite (about 10 minutes, asked first); a Compose proof; any real PagerDuty event (needs the
  owner's say and a test service: a real event pages someone).
- Awaiting the owner: sign-off of this section's rulings (the first ones, tasks 2 and 3, and the review's M1, L3, L4,
  L5 and the order limit; simulate's still departs from D13's exact request); the full suite; push and PR. 3d-2
  ServiceNow only on the owner's go.

The owner signed off this section's rulings (2026-10-08: "sign-of ok"), the review's M1, L3, L4, L5 and the order
limit included, simulate's departure from D13's exact request too; and authorized the full suite, push and PR.
- Merged `origin/main` 9cb4be3 (#64, no conflicts; no rebase, so the reviewed SHAs stand): 757bc49. Full suite there:
  4,325 passed (`-n auto`), the CEL gates 398 passed and 8 skipped; gitleaks over the branch's commits finds nothing;
  CodeQL's python analysis finds nothing locally.
- 3d-1 MERGED by the owner (#65, merge 16666f6, 2026-10-08), CI green.

## 3d-2 ITSM: ServiceNow

Branch `feat/plugins-3d2` from `origin/main` 16666f6 (#65), started 2026-10-08 on the owner's "let's go" for 3d-2. A
go to build; this section's rulings await the owner's sign-off. No migration and no SDK change expected (the API key is
a header: `HeaderAuth`). No real ServiceNow call: tests and the proof run against local fakes.

Facts checked (official sources, read 2026-10-08 by a research subagent, with spot checks of the Table API, the basic
auth restriction and the API key pages; never from memory; a fact only the Community or a KB excerpt gives is marked):
- Table API (www.servicenow.com/docs, Zurich `c_TableAPI`; REST response codes `r_RESTAPIHTTPResponseCodes`):
  - `POST /api/now/table/{table}`: 201, body `{"result": {...}}` with the new record's fields; `GET` lists records
    (`sysparm_query`, `sysparm_fields` ("Invalid fields are ignored"), `sysparm_limit` (default 10000, applied before
    ACLs), `sysparm_display_value` (default false), `sysparm_exclude_reference_link`); `PATCH
    /api/now/table/{table}/{sys_id}`: 200 with the updated record (its parameters `sysparm_display_value`,
    `sysparm_fields`, `sysparm_input_display_value`, `sysparm_query_no_domain`, `sysparm_view`);
  - versioned as `/api/now/{api_version}/table/{table}`, the unversioned path the latest; on no match "Version 1
    returns error code 404", "Version 2 returns success code 200 and an empty array";
  - "By default, if part of a query is invalid, such as an invalid field name, the instance ignores the invalid
    part" (`glide.invalid_query.returns_no_rows`, default false); escaping `^` inside a value isn't documented;
  - 400 bad request, 401 "not authorized to use the API", 403 "not permitted" (ACLs, "business rule or data policy
    constraints"), 404 (an ACL or no such resource), 500, 502, 503; no idempotency header; journal values aren't
    echoed in a response;
  - data policies bind "the REST Table API"; UI policies only forms.
- Authentication (REST APIs page; basic auth pages, Zurich and Australia; API key page, Brazil):
  - basic auth is "a legacy method", use "strongly discouraged"; "In zBoot scenarios, basic authentication is
    restricted by default"; enforcing, it allows only Web Services Access Only accounts, an MFA one-time password or
    the `snc_basic_auth_api_access` role (401 otherwise: an employee's blog);
  - OAuth client credentials: token endpoint `/oauth_token.do`, off by default
    (`glide.oauth.inbound.client.credential.grant_type.enabled`), tokens last 30 minutes;
  - API key (since Washington DC: Community advocate blog): plugin "API Key and HMAC Authentication"; an inbound
    authentication profile whose parameter is the `x-sn-apikey` header (or a query parameter), an optional prefix;
    a REST API Key record tied to a user, its expiry optional; a REST API Access Policy naming the API ("Token Based
    Auth isn't allowed in the Global REST API Policy"); the key's format isn't documented.
- Rate limits (inbound REST rate limiting, Zurich): admin-made hourly rules per user, role or all users, none
  documented by default; 429 with `Retry-After` (seconds), `X-RateLimit-Limit`, `X-RateLimit-Reset`,
  `X-RateLimit-Rule`. A full API semaphore queue answers 429 without `Retry-After` (KB3046852, excerpt only). Default
  quota rule "REST Table API request timeout": 60 s.
- Incident fields:
  - maximum lengths, documented only for the task fields a case inherits (Case API, Xanadu): `correlation_id` 100,
    `correlation_display` 100, `short_description` 160, `description`, `work_notes`, `comments`, `close_notes` 4,000;
  - `urgency` and `impact` 1 High, 2 Medium, 3 Low (Case API); priority follows from them;
  - states New, In Progress, On Hold, Resolved, Closed, Canceled (Zurich state model), their numbers not documented
    (Resolved 6: the Community only); `close_code` ("Resolution code") and `close_notes` ("Resolution notes"): no
    documented choice list, nor whether they're mandatory;
  - creating needs itil, sn_incident_write or admin; resolving itil, list_updater, sn_incident_write or admin; no
    field is marked mandatory, Caller included;
  - instances live at `https://<instance>.service-now.com`, or a custom URL (plugin `com.snc.customurl`).

Tasks (test-first, in order):
1. The connection type `servicenow`: the instance URL, the API key sent as `x-sn-apikey`, a quota scope, a verify
   hook that reads one incident.
2. `servicenow.create_incident` (reconcilable): renders the message model; `reconcile()` finds the step's incident by
   its `correlation_id`, checking each record the query returns.
3. `servicenow.update_incident` and `servicenow.resolve_incident` (idempotent); resolve checks the state it set.
4. `servicenow.add_work_note` (ambiguous: a note appends).
5. Simulate: each node renders and reports what it would cut, sending nothing.
6. Proof: a workflow creating, noting and resolving an incident through RunGraph against a local Table API fake, the
   create's first answer lost after the record was stored; simulated, nothing is sent.
7. Docs: the operator guide's ServiceNow connection, its setup and its quota.

Rulings:
- Ruling: the connection authenticates with a REST API key, sent as the `x-sn-apikey` header (`HeaderAuth`; the
  profile's prefix left empty); no basic auth (legacy, restricted by default on new instances) and no OAuth client
  credentials (off by default, and its 30-minute tokens need a token flow the runtime doesn't have) - cost if wrong: an
  instance whose admin won't create a key, a profile and a Table API access policy can't connect until another auth
  kind lands (D4's `basic` stays unbuilt).
- Ruling: the key is 16 to 1,024 printable ASCII characters, no space (its format isn't documented) - cost if wrong: a
  key of another form can't be stored.
- Ruling: the instance URL is `https://` and a lowercase host name, no port, no path (the default domain or a custom
  URL); requests go to `/api/now/v2/table/incident`, pinned to v2 so an empty query answers 200 - cost if wrong: an
  instance on another port or path can't connect.
- Ruling: one quota scope a key on an instance (`servicenow.key`): bursts of 10, then 2 a second (7,200 an hour); a
  429's `Retry-After` blocks it as D10 says (an hourly rule's can be long) - cost if wrong: a fast workflow waits, or
  an instance's own rule answers 429 first.
- Ruling: `create_incident` is reconcilable: its `correlation_id` is the config's, else the step's idempotency key (64
  hex); a config's is 1 to 100 of `A-Z a-z 0-9 . _ : -` (no query syntax: escaping isn't documented). `reconcile()`
  queries `correlation_id=<it>` and keeps only records whose `correlation_id` equals it (an ignored query returns
  others); one found is the step's incident, none means the create didn't land - cost if wrong: a record the key's
  user can't read (ACLs apply after the limit) is created again.
- Ruling: the create renders the message model: `short_description` the title, else the text, one line, at most 160
  characters; `description` the text, the fields and the links, at most 4,000 characters, cut and reported;
  `urgency` and `impact` from the severity (critical 1, warning 2, info and success 3) unless set; `caller_id`,
  `assignment_group` (sys_ids), `category`, `subcategory` and `contact_type` as given; `correlation_display`
  `Dewpoint` unless set. Raw values only (`sysparm_input_display_value` false) - cost if wrong: a team must look up
  sys_ids.
- Ruling: `resolve_incident` sets `state` to the config's value (default `6`, Resolved by the Community's account),
  `close_code` and `close_notes` (both required: their mandatory status isn't documented, and the choice list varies
  by instance), then checks the answer's `state` is the value it set, else `servicenow.not_resolved`, fatal - cost if
  wrong: an instance whose Resolved isn't 6 sets it in the config.
- Ruling: `add_work_note` appends a work note (or a customer-visible comment when asked), at most 4,000 characters,
  cut and reported; ambiguous (D22) - cost if wrong: none.
- Ruling: answers: the expected 201 or 200 is applied; 400 `servicenow.invalid_request`, 401
  `servicenow.unauthorized`, 403 `servicenow.forbidden`, 404 `servicenow.not_found`, another 4xx
  `servicenow.refused`, all fatal; 408, 425, a 5xx, or another 2xx retried (`servicenow.unavailable`,
  `servicenow.unexpected`): the runtime waits out a 429's `Retry-After` or retries a 429 without one; retries after
  5 s, 10 s, then 20 s (four attempts; nothing documented) - cost if wrong: a slow semaphore outlasts them.
- Ruling: verify reads one incident (`sysparm_limit=1`, `sysparm_fields=sys_id`): 200 `ok`, 401 `invalid_key`, 403
  `no_table_access`, else `unexpected_status`, or `unreachable` - cost if wrong: a key that can read but not write
  passes verify.
- Ruling: a simulated step renders and reports what it would cut, opening no connection, in the real output's shape
  (3c and 3d-1's precedent) - cost if wrong: a simulation doesn't show the body.
- Ruling (task 2): a sys_id is 32 lowercase hex characters (every documented example's form; no page states it), and
  an incident number 1 to 40 printable ASCII characters; an answer whose record is of another form is
  `servicenow.unexpected`, retried, so the retry's `reconcile()` looks again - cost if wrong: an instance with another
  form can't be used.
- Ruling (task 2): lengths count UTF-16 units (Java's count: never more than the characters, so it fits either) -
  cost if wrong: text with characters outside the BMP is cut a little early.
- Ruling (task 2): a configured `correlation_id` should name one incident: a retry adopts the oldest incident carrying
  it (the query orders by `sys_created_on`, at most 10 records read) - cost if wrong: a workflow reusing one id across
  runs has a retried create adopt an earlier run's incident.
- Ruling (task 2): a simulated create returns sys_id `0` x 32 and number `INC0000000`, labelled a fixture by D13 - cost
  if wrong: none (later simulated steps take it and send nothing).
- Ruling (tasks 3 and 4): the change nodes PATCH `/incident/{sys_id}` (a sys_id as task 2 rules, so no path can be
  named) and take only an answer for that sys_id, else `servicenow.unexpected`, retried. `update_incident` sets only
  the fields given, at least one: `short_description` (one line, cut to 160), `description` (cut to 4,000), `urgency`,
  `impact`, `state` (a raw value, 1 to 4 digits), `assignment_group` (a sys_id), `category`, `subcategory`; a value
  cut is reported - cost if wrong: a field a team needs waits for a version 2.
- Ruling (tasks 3 and 4): `close_code` is one line of at most 100 characters (the instance's code list isn't
  documented); `close_notes` and a note are cut to 4,000 and reported; a note is a work note unless `comments` is
  asked for - cost if wrong: none.
- Ruling (task 5): a simulated change returns its sys_id, number `INC0000000` (a fixture), resolve the state it
  would set, and what it would cut - cost if wrong: none.

Fresh-context review of 3d-2 (at 99e6ade, 2026-10-08): no High, four Medium, eight Low; one ruling challenged (M3).
Each fixed test-first, its protection checked by removing it (19 mutants, all killed; `6740070a`), but L5 (gone with
M3) and L7 (a ruling):
- M1: a 201 whose body it couldn't read was retried; when the key's user can create but not read the incident, the
  retry's search finds nothing and creates another. A 201 proves the incident exists: `servicenow.created_unreadable`,
  fatal, never retried.
- M2: a search answering only other records (the Table API ignoring a query part it can't read) was taken as "not
  created", and the step's own record may lie past the 10 read. Ruling: such an answer leaves the outcome unknown
  (`servicenow.unconfirmed`, `outcome_unknown`); only an empty answer means the create didn't land - cost if wrong: a
  person checks an instance whose search misbehaves instead of a second incident.
- M3 (ruling challenged): a configured `correlation_id` let a retry adopt the oldest incident carrying it: another
  run's, iteration's or tenant's. Ruling, replacing the first rulings' configured id: the `correlation_id` is always the
  step's idempotency key; a step can't set it - cost if wrong: a team can't stamp its own id there (it goes in the
  text or the fields).
- M4: a create still under way on the instance past the client's 30-second read could be missed by a search 5 s later,
  and created twice. Ruling: a create's retries wait 60 s, 120 s, then 240 s, past the Table API's 60-second
  transaction limit (default quota rule); update, resolve and notes keep 5 s, 10 s, 20 s - cost if wrong: a create
  answered 5xx waits a minute to try again.
- L1: the instance URL and key rules lived only in pydantic validators, while the API checks a connection against the
  manifest's JSON Schema (and a stored secret meets nothing else). Both are schema now: the URL a `pattern` (its last
  label starting with a letter, so no IPv4 address), the key `minLength`, `maxLength` and a `pattern`, and each `not`
  a newline (a schema pattern's `$` is Python's, which takes a final one).
- L2: an update took any 200 as applied, though an ACL or a business rule can drop a field. It asks back each field it
  set but the texts and compares (a reference's `value`): `servicenow.not_applied`, fatal. The create doesn't check
  the stored `correlation_id`; the operator guide says the key's user must be able to write it.
- L3: a note's `[code]...[/code]` renders as HTML where `glide.ui.security.allow_codetag` allows it (docs "Allow
  embedded HTML code"; Community). Ruling: in a note, a `[` opening `[code]` or `[/code]` (any case, spaces allowed) is
  sent as a full-width `［`, as Google Chat's `<` and `>` (3c-1) - cost if wrong: such text reads with a full-width
  bracket.
- L4: verify passed any 200; it expects the Table API's list now (`unexpected_answer` otherwise).
- L5: query-special values (`NULL`, `javascript:`) in a configured id: gone with M3.
- L6: a state of `06` was sent and then failed the check against `6`. Ruling: a state is `0` or 1 to 4 digits without a
  leading zero - cost if wrong: none.
- L7: resolving an incident already Closed or Canceled may move it back to Resolved where the instance allows it.
  Ruling: left to the instance's own rules (their numbers aren't documented, and reading first costs a request); the
  operator guide says so - cost if wrong: a late resolve reopens a closed incident's resolution.
- L8: docstrings and the guide claimed every unreadable answer was retried (a note's is `outcome_unknown`), that
  ServiceNow counts UTF-16 units (a ruling, not a fact) and that a retry never opens a second incident; corrected.

### 3d-2 checkpoint (2026-10-08, at 6740070, local, not pushed)
- Tasks 1-7 done: the connection type (f349c7c), the reconcilable create (f6f0028), update, resolve and notes with
  their simulations (f0378aa), the RunGraph proof (0c35b57: the create's first answer lost after the record was stored,
  the retry reconciling with no second incident, then a note and a resolve; simulated, nothing sent; its 7 wiring
  mutants killed), the operator guide (99e6ade); the review's fixes (6740070).
- Verified at 6740070: 2,283 tests across the SDK, the catalog, connections, the worker, every plugin, the API and the
  CLI; ruff, format, mypy, import contracts; gitleaks over the branch's commits finds nothing; CodeQL's python
  analysis finds nothing locally, with CI's CLI and query filter.
- Not run: the full suite (about 10 minutes, asked first); a Compose proof; any real ServiceNow call (needs the
  owner's say and a developer instance with an API key).
- Awaiting the owner: sign-off of this section's rulings (the first ones, tasks 2-5's, and the review's M2, M3, M4,
  L3, L6, L7; simulate's still departs from D13's exact request); the full suite; push and PR.

A technical review of 1eafe63 (pasted by the owner, 2026-10-08): no High; one Medium, in M1's fix; no technical
closure. Fixed test-first, its protection checked by removing it (`e5d3ff6e`):
- M1 (continued): a 201 whose body nests deeper than the JSON decoder's limit raised `RecursionError`, not
  `ValueError`: it escaped `_result()` and the create's handler, the worker took it for a retryable unexpected error,
  and under a read restriction (the search empty) each retry created another incident (the review reproduced two
  through RunGraph). Decoding now takes `ValueError` and `RecursionError` alike (`UNDECODABLE`), at both boundaries
  (`_result()` and verify): such a 201 is `servicenow.created_unreadable`, fatal; a search, an update's or a resolve's
  answer `servicenow.unexpected`, retried; a note's `outcome_unknown`; verify `unexpected_answer`. A unit test at each
  boundary and a RunGraph regression (one POST, one incident, the step failed `servicenow.created_unreadable`); 4
  mutants killed, the RunGraph test alone killing the create's.
- Not changed: other plugins decode with `except ValueError` too (Mist's client, stream and verify), none
  reconcilable, so there a deep body is an unexpected error retried or made `outcome_unknown` by the side-effect
  rules, never a second effect; turning `RecursionError` into `ValueError` in the runtime's `HttpResponse.json()` would
  cover every plugin, for the owner to decide.
- A technical review only: no ruling sign-off or push authorization.
- A closure review of 9cf5f21 (pasted by the owner, 2026-10-08): M1 technically closed, no new findings; its RunGraph
  regression gives one POST and one incident, and removing either decoding fix brings the failure back. Technical
  closure only: no ruling sign-off or push authorization.

The owner signed off this section's rulings (2026-10-08: "I'm good"), the review's M2, M3, M4, L3, L6 and L7 included,
simulate's departure from D13's exact request too; and authorized the full suite, push and PR.
- Full suite at bfc8e3c (on `origin/main` 16666f6, which hadn't moved): 4,522 passed (`-n auto`), the CEL gates 398
  passed and 8 skipped; gitleaks over the branch's commits finds nothing; CodeQL's python analysis finds nothing locally.

## Mist titles (2026-10-09)

The owner saw `mist.site_rogue_aps.list@1` listed as "List site rogue ps" (GET /node-types, a local stack). The split
skipped what no word matched, so the id's "A" was lost: fixed in 20b47e38, every letter now in a word. A technical
review (pasted by the owner): no blocking findings; technical review only.

The owner then proposed spellings (wxtag, vBeacon, 128T, ESL, NAC, CoA) and asked for the other titles to follow. In
chat (2026-10-09) the owner chose: wx and mx joined to their noun as the API spells them (wxtag, wxrule, wxtunnel,
mxedge, mxtunnel); AP everywhere; path values' field titles too ("Site ID"); names as Juniper writes them; PMA as
"Premium Analytics"; and had it built and committed locally (a679340d). Two design reviews (pasted by the owner)
shaped it: technical recommendations only.

- Ruling (awaiting the owner's sign-off): a title is the operationId, or a path value's name, in words, normalized
  through reviewed Mist terminology (`plugins/mist/titles.py`, `TERMS`): a term's lowercase words (one or two, the
  last maybe plural) are written as Mist writes them; a two-word term is tried first ("Mist Edge" over "Mist"); any
  other word keeps the id's acronym (WLAN, AAMW, E911) or is lowercase. The split stays lossless. Path value names
  keep the API's compounds ("Nacrule ID", "Mxcluster ID", "Vbeacon ID"); dot1x, cmd and the ids' typos stay as written.
  Display metadata: no contract hash changes, so sync stores the titles at `@1` - cost if wrong: a label.
- Two intentional corrections, each pinned by its expected title: `listApLEslVersions` drops the id's stray "L"
  ("List AP ESL versions"; its path is `ap_esl_versions`), a correction rather than casing; `listOrgPmaDashboards`
  adds letters ("List org Premium Analytics dashboards"): the OAS never writes "PMA", so this is a naming choice, not
  a confirmed spelling. PBN, PLF and SIRT are written in capitals by the OAS.
- Measured against 20b47e38: 131 of 294 generated node titles and 270 of 946 field titles change, the 294 contract
  hashes don't; over the whole OAS, 602 of 1,160 operation ids and path value names. Siblings read as their ids do:
  "Count org site mxedge events" beside "Search org Mist Edge events".
- Not run: the full suite. Awaiting the owner: review of the full title diff, sign-off of this ruling, push and PR.
- A technical review of a679340d and 5477ad7f (pasted by the owner, 2026-10-09): no blocking findings; the manifest
  comparison regenerated (131 node titles, 270 field titles, no other difference, the 294 contract hashes unchanged);
  across the OAS only the two documented corrections change a title's letters; the mxedge / "Mist Edge" siblings and
  the compound field titles ("Nacrule ID") are naming choices. Technical closure only: no ruling sign-off or push
  authorization.
