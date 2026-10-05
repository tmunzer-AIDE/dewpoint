# Webhook ingress: endpoints, events and their runs

Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §8.3 (with §2.5, §6.4 and §10.5).

A sender posts a webhook to `/hooks/<endpoint id>`. `dewpoint ingress` authenticates it, splits it into events and
records each, sealed to its tenant; the dispatcher matches each event to the endpoint's bindings and admits one run
request per matching workflow; the run starts as any other does ([runs](runs.md)).

> **A development-only prototype.** Until engine sub-project 2b-4 adds key rotation, retention and erasure,
> `dewpoint ingress` refuses to start unless the deployment's recorded environment is `development`, and its
> database function records nothing otherwise. Nothing here is for production data.

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
| 429 `rate_limited`, `Retry-After` | short of a rate budget, or too many failures from this address |
| 429 `quota_exceeded`, `Retry-After: 30` | the endpoint's or the tenant's pending backlog is full |
| 429 `retained_full`, no `Retry-After` | the stored events are at their cap: nothing frees it before 2b-4 |
| 503 | too many requests in flight (`busy`, `Retry-After`), outside a development deployment, the database unavailable, or the tenant without an inbound key |

A refused attempt pays its rate budget as an accepted one does.

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

- **`matched`**, with the number of requests it admitted, or **`unmatched`** when no binding's filter held;
- **`dead`**, only when it can never be matched: its ciphertext fails under a keypair version proven on another event,
  or its payload isn't a JSON object; or after 5 failed attempts, backing off from 30 s. Each death is audited and
  alerted on (`inbound_event_dead`);
- **`cancelled`**, by an admin.

A failure that isn't the event's (a keypair version missing or not pairing with its public key, the tenant's data key
unreadable) leaves it pending, retried after a minute, alerted on (`event_key_unavailable`), its attempts untouched. A
dispatcher that stops before its commit leaves the event pending: matching is all or nothing.

`GET /webhook-endpoints/{id}/events` (with `workflow.view`) lists an endpoint's events' metadata, never a payload; dead
events only to admins. With `tenant.manage` (admins): `GET /inbound-events/dead`, `POST /inbound-events/{id}/cancel`
(a pending or dead event) and `POST /webhook-endpoints/{id}/cancel-pending`, each audited. `GET /inbound-usage` shows
the tenant's pending backlog and stored events against their quotas.

## Limits

Provisional (spec §15):

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

### Measured

`tests/probes/ingress_load.py` measures these, by hand and never in CI, each part on a disposable Postgres 16
container (`PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.ingress_load <part>`, from `backend/`). On one
development machine, **not production capacity**:

- **drain** (one dispatcher's own loop: a cycle, then its one-second sleep, at most 50 events a cycle, not the leader,
  with a Temporal that accepts each start at once): 23 events a second with one binding per event, 16.6 with three,
  13.0 with five. A real Temporal, the leader's own work and more bindings only lower it;
- **one tenant's endpoints together** (`tenant-drain`, each dispatcher a process of its own): four endpoints drained
  23.8 events a second against one endpoint's 22.9, and 24.7 with two dispatchers; two tenants with two dispatchers,
  25.6. **A second dispatcher adds almost nothing today**: both take the same candidates in the same order, and the
  second waits for each endpoint's row the first holds, to find its event matched. Making matching scale with
  dispatchers is a required decision of engine 2b-4, before production, after which this control is measured again;
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
