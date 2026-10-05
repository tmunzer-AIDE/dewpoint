# Sub-project 3 — first-party plugins and their runtime: outline

For the owner's rulings, 2026-10-05; nothing is built. Branch `docs/plugins-3-outline` from `origin/main` 6482c53
(migrations end at 0034). Read: architecture spec §3.3, §5, §6.6–6.7, §7, §8, §14, §15; engine-core §2, §3, §12; 2b
§3.5–3.8, §6.7, §8.3; the code. **V** marks an external fact verified where cited; **unverified** ones carry no design
weight unless stated.

## 1. What the code says

1. `StepContext` lacks `connection()` and `http` (`sdk/context.py:20`). RunGraph retries a mapped `RetryableError`
   even from an ambiguous node (`engine/runtime/execution.py:175`): a node raises it only when nothing was sent.
2. Publish never fills `workflow_versions.connection_ids` (`core/workflows/service.py:169`).
3. The API holds no Temporal client. Connection verify runs in `core` on the API's httpx client, safe only because the
   host comes from `MIST_CLOUDS` (`core/connections/mist_verify.py`).
4. `contract_hash` covers every manifest key but `title`/`description` (`engine/registry/catalog.py`): a new
   node-level key changes the flow@1 hashes, and `plugins sync` refuses them.
5. No `egress_allowlist` table; `connections.type` is free text (0006); the worker only SELECTs connections.
6. Ingress splits at `events_pointer` (`core/ingress/parsing.py`), losing a Mist envelope's `topic`; binding filters
   see one event.
7. RunGraph's retry timer is the manifest's (`execution.py:213`); honouring `Retry-After` across attempts means
   ENGINE_ABI 7 and republishing every workflow.
8. The 11 flow control nodes cover parent §6.2 plus `filter`, without widget hints or icons; engine-core §12 asks
   nothing more (D19).

## 2. Slices (each shippable, test-first on its own branch, one checkpoint)

- **3a-1 Egress and connections at run time:** the guard and allowlist (D7, D8), `ctx.http` and `ctx.net`, connection
  fields and `ctx.connection()` (D4–D6), rate buckets (D9, D10), SDK 0.2.0 (D12). Proof: testkit nodes through
  RunGraph against local fakes.
- **3a-2 Plugin calls and connection types:** `options()`/`verify()` (D3); connection types from manifests (D11),
  `mist` leaving `core` with its shape unchanged; flow completion (D19). Proof: a site picker end to end.
- **3b-1 Mist REST:** client and OAS (D1, D2), node types generated per curated operation (§5, D23, D24), any endpoint
  (D14), the policy map (D28), nested update (D15), errors and side effects (D16), simulate (D13), options, the
  webhook trigger (D17).
- **3b-2 Mist device utilities:** `ctx.ws`, the guarded websocket (D26), and one node per device utility, streamed
  (D27). Proof: a ping and a bounce-port node against a local stream fake.
- **3c Messaging:** the message model for Slack, Teams, Google Chat and webhooks (D18); SMTP (D20); syslog (D21).
- **3d ITSM:** PagerDuty and ServiceNow (D22).

Order: 3a-1, 3a-2, 3b-1, 3b-2, 3c, 3d; 3c and 3d need only 3a, so either can precede 3b.

## 3. Decisions (recommendation first)

**D1 Mist client — B: a thin async client on `ctx.http`, with the OAS as data.** The installed mistapi 0.63.1
(`/opt/homebrew/lib/python3.14/site-packages/mistapi`, read, not run) is sync, on `requests`, its async being
`to_thread` (`__init__.py:85`). It builds its own session, which can't be injected, so the guard is bypassed
(`__api_session.py:129`). Every constructor first loads `MIST_HOST`, `MIST_APITOKEN`, `MIST_VAULT_*` and `HTTPS_PROXY`
from the environment (`:360-402`); an explicit token then overrides the loaded one (`:176-182`), but a session built
without one silently runs on the ambient token, and `env_file` writes `os.environ` via `load_dotenv(override=True)`
(`:354`) for every later session. It has Vault, keyring and `input`/`getpass` paths (`:508`, `:525`) and calls `GET
/self` while constructing with a token (`:182`). It follows 30 redirects, with proxies and netrc via `trust_env`, and
an unchecked `next` URL that can send the token elsewhere (`__pagination.py:34`). It retries 429 on every method with
a blocking sleep, an uncapped `Retry-After` and token rotation (`__api_request.py:186-240`), and sets no timeouts
(`:277`). It logs URLs and queries at INFO (`:211`) and bodies at DEBUG, and prints to stdout. It calls
`os.system("")` at import (`__logger.py:18`): a real call, an empty command, a side effect rather than an injection.
Dependencies: requests, hvac, keyring, python-dotenv, sshkeyboard, tabulate, websocket-client, deprecation. Licence
MIT. Against §6.7: its own session, redirects, env proxies and the unchecked `next` bypass the guard and pinning.
Against `ctx.connection()`: env, dotenv, Vault and keyring credentials and the process-wide `os.environ` break
"decrypted in memory only, no cross-tenant cache". Upstream fixes would still leave it sync.

**D2 The OAS as data.** Vendor `mistsys/mist_openapi` `mist.openapi.json` at 0613a22 (**V**: OAS 3.1.0, 2609.1.0, 762
paths, 3.6 MB, MIT), gzipped with its SHA-256 and a `NOTICE` entry; a test pins each curated operationId's method and
path. **Owner's call:** its README says "for documentation only, and NOT for code generation, testing tools" (**V**
`README.md:8`). I recommend relying on it anyway: the curated map overrides it where it's wrong, and any endpoint
refuses what it doesn't describe.

**D3 Plugin code outside runs — C: a DB-mediated call served by the worker.** The API checks `connection.use` and
inserts a `plugin_calls` row: tenant, kind, node ref or connection type, field, connection id and the
`connection.revision` it read, query, `expires_at` (now + 30 s); then notifies. A worker claims it under `SKIP
LOCKED`, only for refs its build has, by writing a fresh random `claim_token` and `lease_until` (15 s). Acceptance is
fenced: the result is written, encrypted under the tenant key, only by `UPDATE … WHERE id = :id AND claim_token =
:token AND lease_until > now() AND expires_at > now() AND state = 'claimed'`, so an earlier execution of the same
worker, a lapsed lease, an expired call or a row the caller abandoned takes nothing. The API applies only an accepted
result, and a verify result additionally by compare-and-set on the revision it verified
(`core/connections/service.py`, as today). The API waits up to 10 s, then deletes the row; a worker sweep deletes
expired ones. Reclaiming a lapsed lease is safe because hooks outside runs are read-only by construction: they get
`ctx.http` limited to GET and HEAD, never `ctx.ws` (a websocket's handshake is a GET but its frames can command) nor
`ctx.net`; any other protocol goes through an explicitly read-only adapter (for example an SMTP probe: connect, EHLO,
STARTTLS, AUTH, QUIT, never MAIL). Verify for webhook-URL types is a host and syntax check only. Rejected: A, the API
starts workflows (its Temporal credentials could then start `RunGraph` around admission and the gate; Temporal OSS has
no per-type authorization); B, the dispatcher starts one (a new workflow-id kind, codec context, latency). Cost: the
spec's "options activities" become worker-side calls.

**D4 `ctx.connection(id)` in a run.** Allowed ids are only the literal connection fields of this step's node in the
run's version graph, read from the DB by run id (a subset of `connection_ids`). The row's tenant must be the
activity's (from the workflow id), and its type in `node.credentials`. The secret is decrypted per call, never cached
across attempts or tenants. Refused in simulate mode; a missing or mistyped connection is fatal
`connection_unavailable` before anything is sent. Plugins never hold the secret: the type declares its auth — `header`
(Mist `Authorization: Token {api_token}`, **V** OAS `securitySchemes`), `basic`, `bearer`, `url` (the webhook URL is
the secret), `body_field` (PagerDuty `routing_key`), `smtp_login` — and `ctx.http`/`ctx.net` apply it.

**D5 The secret joins the run's secret index (2b §3.7) before the first request.** Outputs and messages repeating it
are claimed or masked, in later steps too. Cost: an encrypted copy per root run until retention. Alternative: an
in-memory matcher for this attempt only.

**D6 Connection fields.** `connection_field("mist")` is a literal-only UUID with `x-dewpoint-connection`. Publish
refuses one not naming a tenant connection of that type and fills `connection_ids` (no ABI bump). Deleting a
connection that an enabled workflow's active closure or a queued request names gets 409 `connection_in_use`.

**D7 The SSRF guard (`core/egress`), used by the worker on every connect and the API at connection creation.** One
`getaddrinfo` per connect; refused if any answer is non-global (loopback, private, link-local, CGNAT, multicast,
reserved, unspecified, IPv4 inside mapped/NAT64/6to4/Teredo) unless an allowlist entry covers it. Connect to the
vetted IP, SNI and certificate checked against the hostname (**V** httpcore 1.0.9
`AsyncConnectionPool(network_backend=…)`, `server_hostname` from the request host). No proxies (`trust_env=False`);
https only, http only to allowlisted destinations; no redirects unless a node opts into up to 3 same-origin hops, each
re-vetted; cross-host refused (stricter than §6.7). Connect 5 s, the step timeout overall, 10 MiB streamed (fatal past
it), CR/LF in headers refused, one pool per attempt. Errors carry the outcome: `EgressRefused` fatal, `NotSent`
retryable, `MaybeSent` per node policy; logs name the type only. `ctx.net` gives TCP, TLS, UDP and SMTP the same
vetting and pinning.

**D8 `egress_allowlist`.** An entry is a CIDR, an optional port range, a tenant id (NULL = every tenant, set
explicitly) and a note; managed by `dewpoint platform egress add|list|remove`, audited; checked at connection creation
(host resolved and vetted) and on every connect. Tenant-scoped, so one MSP customer's internal range never opens to
another.

**D9 Rate buckets, keyed by the provider's quota scope.** `rate_buckets` (tenant, scope key, capacity, refill/s,
tokens, `refilled_at`, `blocked_until`); a request takes one token from every bucket its connection type names, in one
`UPDATE … RETURNING` in key order; an empty bucket waits up to 10 s (heartbeating), then fails `cooldown` (D10).
Scopes follow the documented quota, so connections and URLs sharing it share a budget. Mist: a token scope (an HMAC of
the token under the tenant's key, never the token) and an org scope (cloud, `org_id`), because the docs say 5,000
calls an hour per token in one place and per organization in two others (**V** `guides/api-requests/rate-limit.md`;
unresolved, kept so until verified); its streams charge a third (D26). Google Chat: per space, the space id read from
the webhook URL's `spaces/{space}` path (**V** quickstart URL format; 1/s per space). Slack: per channel (**V**), but
a webhook URL doesn't name its channel, so the scope is the workspace from the URL if 3c verifies its format, else one
Slack scope per tenant: under-using the quota, never exceeding it. Coordination stays within a tenant: a bucket shared
across tenants would reveal that two tenants hold one token. Defaults (a §15 item): Mist 50 burst and 1.25/s per
scope; Slack and Google Chat 1/s.

**D10 Rejections, `Retry-After` and long cooldowns, without an ABI bump.** A status code never makes an ambiguous send
retryable by itself: a 503 with `Retry-After`, or a 429, doesn't prove the request wasn't applied upstream. A
connection type may list, per operation, answers its provider documents as rejected before processing; none is
verified yet, so an ambiguous node meeting 429 or 5xx after sending is `outcome_unknown` (cost if wrong: such a write
needs a person instead of a retry; the buckets keep it rare). Idempotent, keyed and reconcilable nodes retry 429 and
5xx under their policy, honouring `Retry-After`: up to 20 s inside the attempt; longer sets the scope's
`blocked_until` (capped at 1 h). Two codes keep attempts apart: `rate_limited` means the provider answered this
attempt 429 or 503; `cooldown` means this attempt sent nothing because the scope is blocked. Each attempt's own row
keeps its outcome, so an earlier `outcome_unknown` is never hidden by a later `cooldown`. When attempts run out the
step fails and follows its error policy, deliberately in 3a: a five-minute cooldown can outlast three attempts. The
deadline is shown on the connection's status (each scope's `blocked_until`), not in step messages: 2b §6.7 withholds
computed text, and a typed per-step field would change the projection. Durable deferral (RunGraph sleeping until
`blocked_until`, with that field) needs ENGINE_ABI 7, new golden histories and republishing every workflow, so it's
proposed separately.

**D11 Connection types from manifests.** A type declares key, label, config schema, secret schema (secret fields
`x-sensitive`), auth (D4), host rule and whether it has `verify()`. Hosts: Mist its 12 clouds (**V** OAS `servers`)
and their stream hosts (D26); Google Chat `chat.googleapis.com` (**V**); Slack and Teams free under D7 until 3c
verifies a pattern; the rest free under D7 and D8. The API validates by schema only; an unknown type is refused until
`plugins sync` ran.

**D12 SDK 0.2.0, additive.** `ctx.connection()`, `ctx.http`, `ctx.net`, `ctx.ws` (D26), `Node.options()`,
connection-type `verify()`; manifest keys `connection_types`, `triggers`, `icon` and `options` fields, each emitted
only when set so flow@1's hashes don't move; `icon` joins `_DISPLAY`.

**D13 Simulate never sends.** Mist returns the 2xx OAS example (**V**: 677 of 807 operations have one), else a value
synthesized from the schema, labelled a fixture. Messaging and ITSM return the exact request, secrets masked, and a
fixture output.

**D14 Any endpoint: two nodes with static policies, inside the connection's scope.** RunGraph decides a lost or
timed-out attempt's retry from the manifest's static `side_effect` (`execution.py:1567`), so one generic node can't
pick it per method. `mist.api.read`: GET only, side effect none. `mist.api.write`: any other method, always
`ambiguous`; an operation verified idempotent is reached through its curated node instead. OAS membership and the
method authorize nothing by themselves. Both nodes reach only an operation the policy map (D28) allows for that node,
whose path also passes the scope rule: under `/api/v1/orgs/{org_id}/` with the connection's org forced; under
`/api/v1/sites/{site_id}/` with a site checked to belong to that org (one `GET /sites/{id}` per attempt); or in an
explicitly approved list of constants and metadata (for example `/api/v1/const/…`). Always refused, whatever the map
says: `/api/v1/msps/…`, `/api/v1/self/…`, login, logout, register, recover and other account or authentication routes,
installer and invite routes, and anything outside `/api/v1`. Path parameters are format-checked and URL-encoded; the
body is checked against the OAS; the output is undeclared, so claimed whole with taint. Capabilities: `mist.read` and
`mist.write`; the OAS has no machine-readable privileges (**V**: no operation-level `x-`).

**D15 Nested update.** Mist's PUT is a top-level merge: an omitted scalar is kept, an included object or array
replaces that structure whole (**V** Juniper `restful-api-overview`, `updateSiteInfo`). Merge with current (default)
GETs, applies Keep / Set / Null per field rebuilding each touched structure whole, then PUTs; Replace sends only the
set fields. No ETag in the OAS (**V**), so the race warning always shows. The preview is the exact body, sensitive
fields masked. Idempotent.

**D16 Mist errors and side effects, per operation with evidence.** 4xx fatal (`mist.bad_request`, `mist.unauthorized`,
`mist.forbidden`, `mist.not_found`); 429 and 5xx per D10 (the OAS lists no 5xx, **V**; Mist's 5xx behaviour
unverified). The HTTP method alone isn't evidence of retry safety, so each curated operation's policy is in the policy
map (D28) with its evidence, and an operation without evidence is `ambiguous`. Proposed: get, list and search none;
update `idempotent` (evidence: PUT is a documented top-level merge, so the same body leaves the same state, **V**);
ack `idempotent` (evidence to record in 3b, else ambiguous); delete `idempotent`, a 404 on a retry reported as
"applied or already absent"; restart and create `ambiguous`, unless the ledger verifies a marker field `reconcile()`
can search (a shared name could match someone else's object). Secret-named output fields (`psk`, `passphrase`,
`secret`, `password`, `token`, `community`, `key`…) are `x-sensitive`; undeclared positions are claimed with taint.

**D17 Mist webhook trigger, on 2b-3b's ingress unchanged.** The endpoint records the whole `{topic, events}` envelope
(**V** OAS `webhooks`, 30 topics) with no events pointer; bindings filter on `/topic`; pills are typed per topic. Auth
is a bearer token in the webhook's `headers` (**V**, under 1,000 bytes); whether Mist sends `Authorization` is
unverified, so by 2b-4's D13 the trigger is unsupported in production until a real delivery confirms it — the owner's
test, since it writes a webhook in a test org. `id_source: none`. 3b writes nothing to Mist: it shows the URL and
header to paste.

**D18 Message model.** Title, text with refs, label/value fields, link buttons, severity; a value past a target's
limit is cut and marked. Slack: Block Kit; 200 `ok`; 400/403/404/410 fatal; 429 with `Retry-After` (**V**). Teams: an
Adaptive Card through a Workflows webhook (**V**; O365 connectors retired 2026-05-22); success code and 429
unverified, so any non-2xx is unknown; "Anyone" URLs only. Google Chat: `text` (**V**), `cardsV2` only once cards over
webhooks are verified. Webhook: the model as JSON, or a template body.

**D19 Flow completion.** `x-widget`/`x-group` hints (display-only, no new versions), icons, and `x-dewpoint-picker`
start-form pickers via D3. No new nodes; config migrations wait for the first vN+1. Owner: anything else?

**D20 Sends are ambiguous.** Retryable only when nothing was sent (`NotSent`, an empty or blocked bucket); 4xx fatal;
anything after the first byte, a 429 or 5xx included, is unknown unless 3c verifies the provider documents it as
rejected before processing (D10). SMTP: stdlib `smtplib` in a thread with `_get_socket` returning the guard's pinned
socket (**V** 3.12 and 3.14); STARTTLS or implicit TLS on 465, plain only to allowlisted hosts. Alternative:
aiosmtplib 5.1.3 (MIT, no required dependencies, **V**), a new dependency.

**D21 Syslog.** RFC 5424 (**V**) with an optional CEF v27 payload and its escaping (**V**); UDP one message per
datagram; TLS on 6514 with octet counting, TLS 1.2+, server certificate checked (RFC 5425, 9662); TCP octet-counted,
or LF framing for legacy receivers (RFC 6587). No client certificates in v1. Every send ambiguous.

**D22 ITSM.** PagerDuty Events v2 is `keyed` (**V**): `dedup_key` is configured or `ctx.idempotency_key()` (64 hex,
limit 255); a retried trigger joins the open alert, but opens a new one if it was resolved meanwhile (accepted cost);
202 applied, 400 fatal, 429/5xx/network retried. ServiceNow create is `reconcilable`: `correlation_id` (**V**: a
remote record's id) defaults to the idempotency key and `reconcile()` queries it (its length unverified, the ledger
checks); update and resolve are idempotent; a work note is ambiguous (it appends).

**D23 One node type per curated operation.** Generated at build time from the map and the OAS
(`mist.<scope>_<resource>.<action>`, about 262 types), each with static config (path, query, body) and output (2xx
response) schemas, because refs, taint and pills read the manifest. Re-vendoring the OAS changes some schemas, and so
contract hashes: those types ship as new versions while the old stay until retired (engine-core §4.5). The manifest's
size is measured in 3b; if it's too large, Mist splits into per-scope plugins. Rejected: generic `mist.object.*` nodes
picking the resource in config, whose outputs would be undeclared, so always claimed and tainted, with no typed pills.

**D24 Held back means unavailable in 3b, to every node.** Held: inventory claim (`addOrgInventory`) and assignment
(`updateOrgInventoryAssignment`, which can also delete records); rogue deauth; firmware upgrades (`upgradeDevice`,
`upgradeSiteMxEdges`); bulk forms and the PSK list delete (empty means all); CSV PSK import; Marvis client delete;
Mist Edge support upload; the deprecated audit-log list; and the utilities D27 holds. The policy map (D28) refuses
them to curated nodes, `mist.api.*` and utilities alike, at publish and again at run time. Inventory assignment
without its delete op, and device upgrade, are the first candidates afterwards (both `ambiguous`).

**D25 Migrations.** 0041 (3a-1): `egress_allowlist`, `rate_buckets`; 0042 (3a-2): `plugin_calls`. Both chain from 0034
while 2b-4a holds 0035–0040; whichever merges second re-points its first `down_revision` to the other's head (linear
history). Never autogenerate.

**D26 `ctx.ws`: a guarded websocket (added 2026-10-05 for device utilities).** wss only. The guard resolves, vets and
pins (D7) and hands the connected socket to `websockets` (`sock=`, `server_hostname=` for SNI and the certificate,
`proxy=None`; its default `proxy=True` reads proxy settings from the environment; **V** installed 17.1
`websockets/asyncio/client.py`). The runtime applies the connection type's auth header (D4). Limits: opening 5 s, 1
MiB a message, 10 MiB an attempt, a duration within the step timeout; pings every 60 s with a 45 s timeout; the
attempt heartbeats while it reads; one connection per call, never shared. Mist (**V** docs `guides/websockets/hosts`,
`best-practices`, `rate-limits`): host = the REST host with `api.` → `api-ws.`, path `/api-ws/v1/stream`,
`Authorization: Token`; `{"subscribe": channel}` is answered `channel_subscribed` or `subscribe_failed`; a data
message's `data` may be an object or a JSON string, itself possibly another envelope, so it's decoded strictly and
bounded. Per token: 2,000 connections an hour and 2,000 channels a connection, a 429 past them, so opening a stream
takes a token from the token's stream scope (D9; default 1,800/h). **Needs approval:** `websockets` 17.1
(BSD-3-Clause, **V**), already in `uv.lock` through `uvicorn[standard]`, becomes a direct dependency; the alternative,
wsproto, is a new package. Stream channels as run triggers (long-lived subscriptions) stay out of scope: they'd need a
subscriber process like ingress.

**D27 Device utilities.** One node type per utility (appendix: 19 diagnostic, 11 disruptive, 13 held back; each exists
and isn't deprecated in the OAS, **V**; its shape and retry safety are reviewed into the policy map in 3b). Its OAS
200 response decides the mode: a `session` means output on `/sites/{site_id}/devices/{device_id}/cmd` (**V** docs
samples); an empty one, REST only. Buffering: the node subscribes, waits for `channel_subscribed` (10 s), POSTs, and
buffers every data message (at most 256 and 1 MiB) until the answer names the `session`; then it keeps buffered and
later messages whose `data.session` matches and discards the rest, and a message without a session is discarded, never
accepted. Output: `{accepted, session, lines, received, ended_by, completion_known, truncated}`, ANSI stripped;
`ended_by` is `finished` (a table command's `"finished": true` in `raw`, **V** docs sample, or the operation's
documented final message recorded in the map), `idle` (10 s), `max_duration`, `cancelled` or `stream_lost`;
`completion_known` is true only for `finished`. Failure classes: before the POST (connecting, `subscribe_failed`, no
ack, `cooldown`) nothing was sent: `RetryableError`. The POST: `NotSent` retryable, 4xx fatal, 429, 5xx and
`MaybeSent` per D10. After an accepted POST, a reviewed repeatable diagnostic maps no session, buffer overflow, no
first message in 30 s (`mist.no_output`) and a stream lost before any output to `RetryableError`, and ends with output
otherwise. Every other utility, disruptive or unreviewed, maps each of those, and any end without completion evidence
(`mist.completion_unknown`), to `OutcomeUnknownError`, never `RetryableError`, since an ambiguous manifest doesn't
stop a mapped retryable error being retried. Owner's call: that rule drops the collected output with the failure (a
handled failure has no output); the alternative returns it as success with `completion_known: false` for the workflow
to branch on. Repeatable means individually reviewed in D28 with its device types, permitted parameters, execution
bounds and repeated-execution behaviour; a `show_*` name is no evidence. Capabilities: `mist.diagnose` for
diagnostics, `mist.write` for disruptive ones. Heartbeat on every message and at least every 10 s, which is how
Temporal delivers a cancel; RunGraph sets no heartbeat timeout (start-to-close only), so a lost worker shows only at
the step timeout, and adding one would change commands (ABI 7, not proposed). On cancel or any exit the node
unsubscribes and closes in `finally`; a command already started on the device runs on (no documented cancel,
unverified), so a cancelled disruptive step is `outcome_unknown`. Held back besides shells, the ZTP password, config
dumps and firmware or reprovision actions: monitor traffic, top and clear policy hit count, which answer a second
`wss://…?jwt=` URL whose protocol is undocumented (**V**); that JWT is a credential and is never stored.

**D28 One operation-policy map for Mist.** One generated data file, the single source for curated nodes,
`mist.api.read`/`write` and utilities, checked at publish and at run time: an entry per OAS operation with its state
(`allowed`, `held`, `denied`), the nodes that may reach it, its capability, its scope class (org, member site, or
approved metadata; D14), its side effect with the evidence for it, and for utilities its stream mode, completion
evidence, supported device types, permitted parameters, execution bounds and repeated-execution behaviour. Deprecated
operations are `denied`; D14's always-refused routes can't be allowed. **Owner's call — operations nobody reviewed:**
(a, recommended) `held`, reads included: only reviewed, scope-safe operations are allowed, the appendix's being the
first reviewed set; (b) unreviewed reads allowed through `mist.api.read`, but only inside D14's independently enforced
scope, never the whole OAS. "Exists and isn't deprecated" stays separate from "shape, scope and retry semantics
verified".

## 4. Dependencies, images, tests

One dependency for approval: `websockets` 17.1 becomes direct (D26). Otherwise nothing new: httpx 0.28.1, httpcore
1.0.9, jsonschema, cryptography and respx are locked; the Mist OAS is vendored data (MIT). Tests make no real external
calls: SSRF through an injected resolver (rebinding as two answers) and local HTTP/TLS servers behind test allowlist
entries; respx; asyncio SMTP and syslog fakes; contract tests (parent §12). A read-only Mist smoke against a test org
happens only with the owner's say, at 3b's checkpoint.

## 5. Initial curated Mist resources

262 REST operations over 54 resources and 30 device utilities (D27), every operationId **V** to exist and not be
deprecated (shape, scope and retry semantics are D28's, in 3b), listed with method and path in
`2026-10-05-plugins-3-mist-resources.md` (generated from the OAS by a script that fails on a missing or deprecated
id). It includes the owner's additions of 2026-10-05. **Org scope:** org, sites, site groups, device search, inventory
(read), WLANs, WLAN templates, network / RF / gateway / site templates, device profiles, PSKs, networks, services,
service and security policies, IDP / AAMW / SecIntel profiles, NAC rules and tags, user MACs, guests, assets and asset
filters, Mist Edges, clusters and tunnels, WxRules, WxTags, alarm templates, alarms (search, ack), clients and events
(wireless, wired, NAC, WAN, devices, Mist Edges; search and count), audit logs (`listOrgAuditLogs`, not the deprecated
`/logs`), stats, webhooks and topics. **Site scope:** site, settings, devices (list, get, update, restart), WLANs,
PSKs, maps, map stacks, assets, asset filters, WxRules (and derived), WxTags, Mist Edges (and events), clients (four
kinds), rogues, insights, stats. Full CRUD where the OAS has it. Pagination (**V**
`guides/api-requests/pagination.md`): lists use `limit`/`page` (at most 1,000) and `X-Page-*` headers; searches follow
the body's `next`, checked to stay on the connection's host and path; every list node takes a page cap.

## 6. Process

Per slice: tests first, a fresh-context review for fail-open paths, fixes test-first, a one-page checkpoint.
Ambiguities are taken fail-closed and recorded in `docs/superpowers/plans/<date>-plugins-3-ledger.md` as "Ruling:
<what> - <why> - <cost if wrong>". Nothing outward-facing (push, PR, real Mist or SaaS call) without the owner.
