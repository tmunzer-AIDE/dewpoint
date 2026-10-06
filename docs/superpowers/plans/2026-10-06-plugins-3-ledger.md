# Sub-project 3 — ledger

The outline (`docs/plugins-3-outline`, revision 5, 02b7e62) was approved as recommended by the owner on 2026-10-06
(D1–D28). This file records, per slice, the tasks, the mid-slice rulings ("Ruling: what - why - cost if wrong") the
owner rules on at the checkpoint, and open questions.

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
- Ruling: titles are the operationId in words ("List org sites"), descriptions the OAS's first paragraph cut at 300
  characters, no icon - display metadata, changeable without a version - cost if wrong: none.
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
