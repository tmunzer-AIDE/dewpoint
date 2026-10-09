# Webhook ingress: endpoints, events and their runs

Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §8.3 (with §2.5, §6.4 and §10.5).

A sender posts a webhook to `/hooks/<endpoint id>`. `dewpoint ingress` authenticates it, splits it into events and
records each, sealed to its tenant; the dispatcher matches each event to the endpoint's bindings and admits one run
request per matching workflow; the run starts as any other does ([runs](runs.md)).

> **A development-only prototype.** Until engine sub-project 2b-4 lifts it (after retention, key rotation and
> erasure), `dewpoint ingress` refuses to start unless the deployment's recorded environment is `development`, and its
> database function records nothing otherwise. Nothing here is for production data. Its keys rotate as
> [key rotation](key-rotation.md) says.

## Running it

`dewpoint ingress` is its own process with its own database login, `dewpoint_ingress_login`
([deployment](deployment.md#docker-compose-evaluation)), which has no table privilege: it resolves an endpoint and
records events only through three database functions. Its settings come from its environment only, never a `.env`
file:

| Setting | |
|---|---|
| `DEWPOINT_DATABASE_URL` | the ingress login's |
| `DEWPOINT_INGRESS_KEY_B64`, `DEWPOINT_INGRESS_KEY_ID` | the ingress key, 32 bytes (`openssl rand -base64 32`), which the API holds too |
| `DEWPOINT_INGRESS_TRUSTED_PROXIES` | the proxies whose `X-Forwarded-For` it believes, as addresses or networks; none by default |

It never holds a tenant's key: it refuses to start with `DEWPOINT_KEK_B64` (or `DEWPOINT_KEK_PREVIOUS_B64`) in its
environment. It seals each event to the tenant's public key; only the dispatcher opens events. The API's database role
can't read an event's sealed payload or a keypair's sealed private key either (migration 0034). That's read-access
hardening, no more: the API still makes keypairs, and its process holds the tenants' keyring.

In Docker Compose it runs only with the `ingress` profile and the development override:

```
COMPOSE_PROFILES=ingress docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --wait
```

`web` (nginx) proxies `/hooks/` to it on a network of their own, `hooks` (`DEWPOINT_HOOKS_SUBNET`, by default
`172.31.255.248/29`), the one range ingress believes `X-Forwarded-For` from. nginx writes the client it recovered into
that header, never a client's own, and streams each body to ingress as it arrives (a chunked one too), so ingress's
10 s whole-body deadline and its limit on requests in flight hold through it: a body trickled slower is a 408. Without
the profile, `/hooks/` answers 502.

### Behind a proxy

An address is believed from `X-Forwarded-For` only when the request comes from a configured proxy, and only from the
header's trusted end: right to left, past the proxies listed. Set `DEWPOINT_INGRESS_TRUSTED_PROXIES` to exactly the
proxies in front of ingress; anything wider lets a client choose its address, which the allowlist and the failure limit
below rely on. An IPv6 client is limited by its /64.

> **Behind a proxy, never leave `DEWPOINT_INGRESS_TRUSTED_PROXIES` empty.** Empty, ingress believes no
> `X-Forwarded-For`, so every caller is the proxy: an allowlist naming your senders refuses them all, one naming the
> proxy admits anyone who reaches it, and one sender's failures (a wrong secret, a body too large) count against the
> proxy, so the failure limit refuses every other sender behind it too. Nothing then identifies the caller. The
> Compose deployment sets it to the network `web` and ingress share; set it to your own proxies' addresses wherever
> another proxy fronts ingress.

## Endpoints

With `trigger.manage` (editors and up), under `/api/v1/t/{tenant}`; read with `workflow.view`:

| | |
|---|---|
| `POST /webhook-endpoints` | make one; answers 201 with its `path` and its `secret`, shown this once |
| `GET /webhook-endpoints`, `GET /webhook-endpoints/{id}` | its settings and its counters, never a secret |
| `PATCH /webhook-endpoints/{id}` | its name, `enabled`, allowlist, tolerance, body limit, HMAC header names |
| `POST /webhook-endpoints/{id}/secret` | a new secret, shown this once; deduplication carries on |

How an endpoint authenticates, its events pointer and where its events' ids are never change: make another endpoint
instead. The API needs the ingress key to make or rotate one (503 `ingress_key_missing` without it), and makes the
tenant's inbound keypair if it has none.

### Authentication

- **HMAC** (`"auth": "hmac"`): the sender signs `<timestamp>.<the exact raw body>` with HMAC-SHA256 under the secret,
  and sends the timestamp (Unix seconds) in `x-dewpoint-timestamp` and the hex signature (optionally prefixed
  `sha256=`) in `x-dewpoint-signature` (both names configurable). A timestamp more than the tolerance (300 s by
  default, 60 to 900) from ingress's clock is refused, which bounds a replay. Reformatting the body breaks the
  signature: it's the bytes that are signed.
- **Bearer** (the default): `Authorization: Bearer <token>`, the token high-entropy and made by Dewpoint; only its
  SHA-256 digest is kept.

Every failure before an attempt is recorded (an unknown or disabled endpoint, an address outside the allowlist, a bad
signature, an `erasing` tenant) is the same bodiless 401.

**Mist.** A Mist webhook signs only the body (`X-Mist-Signature-v2`, HMAC-SHA256 with no timestamp), so it can't use
the HMAC scheme above. Juniper's documentation says an `http-post` webhook can carry custom headers (names and values
together under 1,000 bytes) and names token-based authentication among their uses, so a bearer endpoint with the
header `Authorization: Bearer <token>` should serve. **This is unverified**: the documentation doesn't say whether
Mist allows the `Authorization` header name, and no real Mist delivery has confirmed it yet.

### Events and their ids

The body is one JSON object, or, with an events pointer (RFC 6901, such as `/events`), the array of objects there: 1 to
500 events. A body is refused whole (400 `malformed`) for invalid UTF-8, a duplicate key anywhere, `NaN` or an infinity,
a number past binary64's range, an escaped unpaired surrogate, an integer of more than 4,300 digits, nesting deeper than
64 levels, or any event that isn't an object or lacks a valid id.

Deduplication follows the endpoint's id source:
- **`pointer`**: each event's own id at a JSON pointer (`id_pointer`), a string or an integer, typed (`1` and `"1"` are
  two ids);
- **`header`**: one id for the request, in a header (`id_header`), the item's index qualifying it;
- **`none`**: no id, and **nothing is deduplicated**: a sender that retries after losing a 200 records its events
  twice (at-least-once). Use `pointer` or `header` when that matters.

A repeated id with the same content (compared as canonical JSON, so key order and spacing don't matter) is
acknowledged and recorded once; with other content, the whole request is refused, 409 `event_id_reused`. Ids are never
stored: only keyed digests of them.

### Responses

| Status | When |
|---|---|
| 200 `{"accepted": n, "duplicates": d}` | recorded, once committed |
| 400 `malformed` | the body, as above |
| 401, no body | any failure before recording |
| 408 | the body took longer than 10 s |
| 409 `event_id_reused` | an id reused for other content |
| 413 `too_large` | past the endpoint's body limit (1 MiB by default, at most 5 MiB) or the global 5 MiB |
| 413 `over_limit`, no `Retry-After` | the delivery's credit is more than one tenant may hold even alone in an otherwise empty deployment ([below](#the-ingress-capacity)): no retry helps it; send fewer events at once |
| 429 `rate_limited`, `Retry-After` | short of a rate budget, or too many failures from this address |
| 429 `quota_exceeded`, `Retry-After: 30` | the endpoint's or the tenant's pending backlog is full |
| 429 `backlog_full`, `Retry-After` | the deployment's outstanding work is at its limit, or the tenant at its share of it ([below](#the-ingress-capacity)); 1 to 60 s, or 30 s while the capacity is unset |
| 429 `retained_full`, no `Retry-After` | the stored events are at their cap, until retention deletes ended events past the tenant's cutoff ([retention](retention.md)) |
| 503 | too many requests in flight (`busy`, `Retry-After`), outside a development deployment, the database unavailable, or the tenant without an inbound key |
| 503 `key_retired`, `Retry-After: 1` | the tenant's inbound keypair the delivery was sealed to was retired before it was recorded ([key rotation](key-rotation.md)); nothing is stored, and a retry is sealed to the newest |

A refused attempt pays its rate budget as an accepted one does.

**A refused delivery is the sender's to retry, and not every sender does.** A 4xx or 5xx leaves nothing in Dewpoint:
no event, no count of it, no log line for it, and nothing later replays it. A 429 or a 503 says when to try again
(`Retry-After`), but whether the sender retries, how often and for how long is the sender's: some retry with backoff
for a while, some drop the delivery at once, some disable a webhook that keeps failing. Check the sender's own
documentation before relying on an endpoint whose sender may be refused, and size its rates and quotas so that a burst
it really sends fits; what Dewpoint refused can't be recovered on its side.

## Bindings

With `trigger.manage`: `POST /webhook-endpoints/{id}/bindings` `{"workflow_id": ..., "filter": [...], "enabled": true}`,
`GET` the same path (with `workflow.view`), `PATCH` and `DELETE /webhook-bindings/{id}`. A binding names a workflow of
the endpoint's tenant, once per endpoint, at most 20 per endpoint. Its filter is at most 8 clauses
`{"pointer": "/type", "value": "ap_down"}`, every one of which must hold: typed equality on the event (a string, an
integer, a boolean or null; never a float). No filter matches every event.

Each matching binding admits one request, source `webhook`, key `evt:<event id>:<workflow id>`, the event as the
run's trigger input (`trigger`), checked against the workflow's input schema like any input: an event the schema
refuses is a `refused` request.

## What becomes of an event

The dispatcher matches events only while the production gate is on (always, in development), every tenant's oldest
first. An event is then:

- **`matched`**, with the number of requests it admitted, or **`unmatched`** when no binding's filter held. Its
  requests take the credit it was accepted with ([below](#the-ingress-capacity)); bindings enabled since need the
  deployment's room for the difference. Without it, the event stays pending (`backlog_full` in the dispatcher's
  report), nothing written, and the tenant's later events wait behind it, its order kept;
- **`dead`**, only when it can never be matched: its ciphertext fails under a keypair version proven on another event,
  or its payload isn't a JSON object; or after 5 failed attempts, backing off from 30 s. Each death is audited and
  alerted on (`inbound_event_dead`);
- **`cancelled`**, by an admin.

A failure that isn't the event's (a keypair version missing or not pairing with its public key, the tenant's data key
unreadable) leaves it pending, retried after a minute, alerted on (`event_key_unavailable`), its attempts untouched. A
match that fails unexpectedly (a bug) leaves it pending too, its attempts untouched: it's tried again 1, 2, 4, 8, 16,
then 30 minutes later, and the 7th failure in a row holds it for an operator, alerted on (`match_held`; see
[runs](runs.md#items-that-keep-failing)). A dispatcher that stops before its commit leaves the event pending: matching
is all or nothing.

`GET /webhook-endpoints/{id}/events` (with `workflow.view`) lists an endpoint's events' metadata, never a payload; dead
events only to admins. With `tenant.manage` (admins): `GET /inbound-events/dead`, `POST /inbound-events/{id}/cancel`
(a pending or dead event) and `POST /webhook-endpoints/{id}/cancel-pending`, each audited. `GET /inbound-usage` shows
the tenant's pending backlog and stored events against their quotas.

## Limits

Provisional (spec §15). **The event rates are development-only** until the deployment's ingress capacity is set
([below](#the-ingress-capacity)), which lowers them:

| Limit | Value |
|---|---|
| Requests in flight, per ingress process | 32 (503 past it) |
| Failed requests per address (an IPv6 /64) per minute, per process | 30 |
| Global body cap; endpoint body limit; body deadline | 5 MiB; 1 MiB by default; 10 s |
| Events per request | 500 |
| Per endpoint: requests; events; bytes | 20/s, burst 100; 10/s, burst 1,000; 2 MiB/s, burst 10 MiB or more |
| Per tenant: events; bytes | 10/s, burst 5,000; 10 MiB/s, burst 50 MiB |
| Pending, per endpoint; per tenant | 10,000 events, 64 MiB; 50,000 events, 256 MiB |
| Stored, per endpoint; per tenant | 100,000 events, 512 MiB; 250,000 events, 1 GiB |
| Matcher | 50 events a cycle per dispatcher; 20 bindings per endpoint |

The failure limit is each process's own, in a table of 65,536 addresses that drops the one that failed least recently
when full: past that many failing addresses in a minute, it's best-effort.

The event rates are set below what the dispatcher drains (below), for an endpoint and for a tenant alike: every match
holds its tenant's counter row, so a tenant's endpoints are matched one at a time and together drain no faster than
one does. The bursts are budgets for a spike, which the pending quotas then hold back. Those quotas are backpressure:
past one, ingress answers 429 `quota_exceeded` and the sender retries later. They promise no throughput: matching
drains what it can, and a sender faster than that is held back by the 429s, not served. These values are provisional,
for development: they aren't a promise with a real Temporal or with more bindings than measured.

### The ingress capacity

Events cost what their requests cost to start: an event becomes a request for each of its endpoint's enabled bindings
that matches it, and a dispatcher starts them one at a time (about 35 ms each on the dev server, [measured
below](#measured)). So a deployment's rates come from the starts measured on its own Temporal, with headroom, and how
much webhook work it holds outstanding from a wait its operators agree to. A platform admin sets the three values, none set by
default, through the API (D11; [deployment](deployment.md#the-ingress-capacity)): `dewpoint platform
set-ingress-capacity` signs in and asks it, and the change is audited with the admin's id and an attestation:

- `--starts-per-s`: the sustained starts a second a tenant's runs reached on this deployment's own Temporal and
  workers (`tests/probes/test_ingress_starts.py`, with slots enough that only the dispatcher bounds them);
- `--headroom`: the share of them ingress may use, above 0 and at most 1;
- `--queue-wait-s`: the wait, in seconds, its operators agree the outstanding webhook work may stand for at the
  budget's starts. It sizes the limit below; it isn't promised to anyone.

Once the first two are set, their product (starts × headroom a second) is the budget webhook work starts at, and an
endpoint's event rate follows from it, divided by its enabled bindings: with 8 starts a second measured and a headroom
of 0.5, an endpoint with 4 enabled bindings takes 1 event a second, and one with 1 binding up to 4. A rate configured
lower stays, the bursts stay as configured, and a tenant's rate stays as configured. A value left out keeps what it
was; `--unset` unsets all three.

**The deployment's outstanding-work limit.** With all three set, the whole deployment holds at most starts × headroom
× wait requests' worth of webhook work outstanding (never less than 40), shared by every tenant (2b-4b M3):

- **What counts.** A pending event counts its credit: its endpoint's enabled bindings when it was accepted, at least 1.
  A webhook request counts 1 while it's `queued` or `starting`. Nothing else does: manual, scheduled and re-run starts
  use what the headroom leaves.
- **Ingress's room.** Ingress fills the limit but 19, an event's most bindings but the one its credit holds: those
  are kept for events whose bindings grew since they were accepted, so they're never starved behind new deliveries.
- **Admission, at ingress.** A delivery is accepted only if its new events' credit fits ingress's room and the
  tenant's share of it:
  - a tenant with work outstanding already: the room divided by the tenants with work outstanding and one more (half
    of it when the tenant is alone). Keeping one share aside means a tenant arriving finds room once the others are at
    their shares;
  - a tenant with nothing outstanding (its first admission): the share it will have once counted, the room divided by
    the tenants with work outstanding, itself and one more, or an event's most bindings (20) if that's more. So no
    tenant takes the room for itself (alone, at most half of it), and an event of 20 bindings is admitted even at the
    least limit, alone, once its tenant has nothing outstanding.

  Otherwise the whole delivery is refused, 429 `backlog_full`, and nothing is stored; `Retry-After` is how long the
  budget's starts take to free what's missing (1 to 60 s), or 30 s while the capacity is unset. A delivery worth more
  than a tenant may hold even alone in an otherwise empty deployment (half the room, or 20) could never fit: 413
  `over_limit`. One database row holds the deployment's count, locked as each delivery is admitted, so deliveries at
  once, from any tenants and any ingress process, never pass the limit.
- **Matching.** An event's requests take its credit. Bindings enabled since it was accepted need the limit's room for
  the difference (what's kept from ingress holds one event's): without it the event waits, as above. Bindings disabled
  since give back what they held.
- **Release.** An event leaving `pending` (matched, unmatched, dead, cancelled) or deleted gives back its credit; a
  request leaving `queued` or `starting` (started, cancelled, dead) or deleted gives back 1; a tenant's erasure gives
  back all it held. The database counts each as the change commits, whatever code makes it.
- **Held by the database.** A commit that raised the count past the limit is refused, whatever code wrote it. During
  an upgrade to this version, a dispatcher still on the code before it matches without asking: its matches can use the
  19 kept for top-ups, never more than the limit (the match rolls back and its event waits). The shares and the reserve
  hold only for ingress and the dispatchers of this version.
- **Changing the capacity.** A change that would take the limit below the work already outstanding is refused, 409
  `ingress_capacity_below_outstanding`, until enough has drained; the change waits for any admission in flight, so
  what it counts includes it.
- **Checked.** The dispatcher's leader compares the count with what's really outstanding at most once a minute and
  alerts on any difference (`ingress_budget_drift`, error level). It never corrects it: a difference is a defect to
  find.

**Known limits, for now.** The drift check compares the deployment's total only: one tenant's count off one way and
another's off the other, or a wrong count of tenants with work outstanding (which every share divides by), goes unseen.
`Retry-After` is an estimate: a refused delivery still spends its rate budget (as every refused attempt does, above),
so the retry may then wait on its rate instead, and a refusal for a tenant's share is reckoned on the whole deployment's
starts, not the tenant's part of them, so it can be shorter than the wait. Work outstanding from before this version
(webhook requests queued or starting, counted when it arrives) above the limit drains only as those requests start or
end: until it's below the limit, no commit that adds to it goes through.

**The limit isn't a wait guarantee.** It bounds how much is outstanding, not how long an accepted event waits for its
runs to start: that depends on the dispatchers, Temporal, slots and each tenant's run limit. The dispatcher's rounds
give every tenant with due requests a turn each round ([runs](runs.md#the-dispatcher)), which is turn-taking, not a
rate. What was measured is [below](#measured), as measurements. `GET /api/v1/admin/platform/ingress-capacity` shows the
limit, what's outstanding and how many tenants have work outstanding.

Until all three are set, the limit is 50,000, development-only, and the event rates are the development-only ones in
the table. None of these is a production value: production's come from its own measured starts, a headroom and a wait
its operators agree to.

### Measured

`tests/probes/ingress_load.py` measures these, by hand and never in CI, each part on a disposable Postgres 16
container (`PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.ingress_load <part>`, from `backend/`). On one
development machine, **not production capacity**:

- **drain** (one dispatcher's own loop: a cycle, then its one-second sleep, at most 50 events a cycle, not the leader,
  with a Temporal that accepts each start at once): 23 events a second with one binding per event, 16.6 with three,
  13.0 with five. A real Temporal, the leader's own work and more bindings only lower it;
- **one tenant's endpoints together** (`tenant-drain`, each dispatcher a process of its own): four endpoints drained
  23.8 events a second against one endpoint's 22.9, and 24.7 with two dispatchers; two tenants with two dispatchers,
  25.6. **Before D9, a second dispatcher added almost nothing**: both took the same candidates in the same order, and
  the second waited for each endpoint's row the first held, to find its event matched. Since engine 2b-4b M3 (D9) the
  matcher takes the endpoint's row and then the tenant's counter row `SKIP LOCKED`: one held elsewhere passes its event
  by (`busy` or `busy_tenant`, counted in the cycle's report), never waited on. A pass probes a busy endpoint or tenant
  once and passes its other events by, and the next pass's pick leaves out what the last found busy, so no run of busy
  events, however long, starves the ones after it, and every other event keeps its tenant's order, oldest first;
- **D9's acceptance** (`scaling`: one dispatcher, then two, each a process of its own, on 100 events each of four
  independent tenants, 2026-10-08): a second dispatcher drains 1.75 times as fast at fan-out 1 (22.3 to 39.1 events a
  second), 1.9 times at 5 (10.6 to 20.2) and 1.8 times at 20 (3.8 to 6.9). Every tenant's backlog drained sooner (at
  fan-out 20, in 59 to 60 seconds against 105 to 108), none was left, the counters ended at zero pending, and each
  event admitted exactly one request a binding (8,000 of 8,000 at fan-out 20). **At fan-out 20 one dispatcher drains
  3.8 events a second, below the default endpoint and tenant rates of 10**: the rates are not yet set for it;
- **events to runs, with a real Temporal** (`tests/probes/test_ingress_starts.py`: a CLI dev server, a versioned engine
  worker, one dispatcher a cycle at a time, every other limit at its default, 200 short runs a case, 2026-10-09): since
  a dispatcher takes a tenant's next due request in the same cycle once it has started one
  ([runs](runs.md#the-dispatcher)), **a tenant's runs start about 8 to 11 a second**: 200 events became 200 runs in 25.5
  s at fan-out 1 (7.9 a second; from an event's arrival to its run's start, 15 s at the median, 24.5 s at most), 10
  events 200 runs in 21 s at fan-out 20 (9.5 a second), and 17.9 s (11.2 a second) with slots enough that only the
  dispatcher bounded them. Each start costs the dispatcher about 35 ms, one at a time, so one dispatcher starts at most
  about 28 a second, for all its tenants together, and about half that with its one-second sleep between cycles. Before,
  one a cycle, a tenant's runs started about 0.9 a second whatever the fan-out (40 runs in 46 s at fan-out 1, 100 in 110
  s at fan-out 20, 2026-10-08). **The default rates of 10 events a second aren't sustainable end to end**: at fan-out 1
  a tenant alone on its dispatcher keeps up with about 8 events a second; at fan-out 20, one every two seconds. Past
  that, events are accepted and matched, and their requests wait queued, up to the deployment's outstanding-work
  limit; the ingress capacity lowers the rates and sets the limit ([above](#the-ingress-capacity));
- **the deployment's budget, under load** (`tests/probes/test_ingress_budget_load.py`: a CLI dev server, one
  dispatcher a cycle at a time, slots enough that only it bounds the starts, 2026-10-09): a limit of 120 (30 starts a
  second, all for ingress, a 4 s wait; 101 for ingress), three tenants sending steadily for 40 s (1 binding at 8
  events a second, 5 at 2, 10 at 1) and a fourth in bursts (2 bindings; 10, 12 and 30 events at 10, 20 and 30 s). The
  outstanding work peaked at 81, four tenants at once, and the counters equalled the truth at the end. The steady
  tenants were each refused 49 to 60% of their deliveries (`backlog_full`) and started 4.1 to 4.3 runs a second. The
  burst of 20 requests' worth got in; the one of 24 didn't, more than a tenant arriving beside three others may take
  (20), and wasn't sent again; the one of 60, more than any tenant may hold even alone, was refused for good (413).
  **From an event's acceptance to its runs' start: 4.6 to 5.4 s at the median, 5.6 to 8.3 s at the 95th percentile,
  9.6 s at most** (measured, not promised: another machine, another Temporal, or more tenants, and they differ).
  Before shares kept one aside, the three steady tenants held the whole limit between them, and both of the fourth's
  bursts were refused;
- **what the budget's row costs** (`contention`: 16 tenants recording one event a call): 313 recordings a second on
  one connection, 837 on 8 and 769 on 32 (2.5, 8.0 and 34 ms at the median, 153 ms at the 99th percentile on 32),
  against 368, 1,223 and 1,453 before it: each recording, a refused one too, holds the row until it commits. Starts
  cost the dispatcher what they did (30 to 33 ms each, `test_ingress_starts.py`), their releases counted as they
  commit;
- **each limit on its own** (`buckets`, `quotas`), at its default: every rate bucket accepted what its burst and rate
  allow over the time taken, within one call (an endpoint's events 1,029 of 1,030; its bytes 15.5 of 16.0 MiB; a
  tenant's events 5,000 of 5,030, in calls of 100 events, so the 30 refilled never made a whole one; its bytes 76 of
  80 MiB), each refusal naming its wait (1 s, and 8 to 10 s for a 100-event call on a tenant's 10/s); every pending
  and retained quota refused exactly at its value (10,000 and 50,000 events, 64 and 256 MiB pending; 100,000 and
  250,000 events, 512 MiB and 1 GiB stored), a pending one with `Retry-After: 30`, a stored one with none, and a
  sender's retry was still acknowledged at each; a recording took about as long at a quota (22 to 41 ms for a
  500-event or 4 MiB call) as on an empty endpoint;
- a match transaction holds its endpoint's row about 16 ms (20 ms at the 95th percentile); recording on that endpoint
  while it's matched back to back takes about 13 ms instead of 2;
- one ingress process recorded 1 KiB events at about 160 a second one at a time (median 6 ms) and 540 to 600 a second
  with 8 to 32 in flight (median 11 to 47 ms; the 95th percentile reached 164 ms at 32, its database pool's limit), in
  about 155 MiB;
- parsing and sealing run on its event loop: 0.3 ms for a 1 KiB event, about 150 ms for 500 events in 1 MiB (the
  sealing, 0.3 ms an event, dominates), about 195 ms for 5 MiB of small numbers;
- picking the candidates ranks every pending event: 6.5 ms at 10,000 pending, 61 ms at 200,000;
- the failure limiter's 65,536 addresses take about 12.6 MiB.
