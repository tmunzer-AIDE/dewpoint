# Sub-project 3 — ledger

The outline (`docs/plugins-3-outline`, revision 5, 02b7e62) was approved as recommended by the owner on 2026-10-06
(D1–D28). This file records, per slice, the tasks, the mid-slice rulings ("Ruling: what - why - cost if wrong") the
owner rules on at the checkpoint, and open questions.

## 3a-1 Egress and connections at run time

Branch `feat/plugins-3a1` from `origin/main` 6482c53.

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

Open questions:
- `tests/apps/dispatcher/test_triggers_end_to_end.py::test_a_short_outage_fires_each_missed_time_and_admits_each_once`
  failed once in the full parallel run under extra load (a 4 s tick gap on Temporal's dev server where 2 s was
  expected) and passes alone; this slice touches no schedule or dispatcher code. Load-sensitive, not a regression.
- An intermittent `PytestUnraisableExceptionWarning` (a `GeneratorExit` in RunGraph's `_drive` while Temporal tears down
  a terminated batch) comes from `tests/apps/worker/test_real_server.py::test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used`;
  3a-1 changes no engine code. Pre-existing, worth its own issue.
