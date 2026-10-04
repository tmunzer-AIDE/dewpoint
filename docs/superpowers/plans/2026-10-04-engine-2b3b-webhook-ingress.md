# Engine 2b-3b: Webhook Ingress — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A webhook a sender posts to Dewpoint becomes runs. `dewpoint ingress` authenticates it, splits it into
events and records each sealed to its tenant; the dispatcher matches each event to its bindings and admits one request
per matching workflow through `admit_request`. Ingress stays a gated prototype: it records nothing outside a
development deployment until 2b-4 supplies rotation, retention and erasure.

**Architecture:**
- **Keys, the event store and its functions (milestone 1).** The ingress key, which only ingress and the API hold,
  seals each endpoint's HMAC secret and dedupe-digest key; bearer tokens are kept as digests. An event's identity is a
  keyed digest of its typed id, and its content a keyed digest of its canonical bytes. Each tenant has versioned X25519
  keypairs, the private key sealed with its data key and checked against its public key on every load. Migration 0032
  holds endpoints, counters, bindings and events. Ingress has no table privilege: three SECURITY DEFINER functions
  resolve an endpoint and record a batch under one lock order, and a refusal pays its rate budget.
- **The ingress process (milestone 2).** Its own app, settings and login. A hook's checks come in a fixed order:
  requests in flight, the address's failures, the body's cap and deadline, then the endpoint, its allowlist and the
  authentication, every failure the same bodiless 401. Strict parsing, splitting, typed ids, sealing, and every
  attempt's outcome mapped, 200 only once committed.
- **Matching and management (milestone 3).** Every dispatcher matches while the gate is on, fairly across tenants,
  under the lock order; an event is matched, unmatched, dead (only when confirmed, or after five attempts) or waits on a
  platform failure. The leader recounts the counters under their locks. The API manages endpoints, bindings and events:
  secrets shown once, cancels by admins.
- **Proofs, the probe, Compose and docs (milestone 4).** An end-to-end proof with the keyring's real keys and canaries.
  The load probe, in the repo and run by hand, measures each limit on its own, and sets the event rates below the drain
  it measured. Compose runs ingress under its own profile behind nginx, which streams bodies to it; CI proves a signed
  event through it; the guide.

**Tech Stack:** Python 3.12, FastAPI and uvicorn (ingress's own app), SQLAlchemy async with asyncpg, Alembic,
PostgreSQL 16 (forced row-level security, SECURITY DEFINER functions) through testcontainers (`postgres:16-alpine`),
`cryptography` (X25519, HKDF, AES-256-GCM, HMAC), Temporal Python SDK 1.33.0 and CLI dev server 1.9.1, typer, pytest
with pytest-xdist, ruff, mypy strict, import-linter; Compose and nginx; `uv`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`: revision 8 is approved (#33), and the revision 9
draft lands with this plan on branch `docs/engine-2b3b-plan`. Sections: §2.5 (the gate), §6.4 (keypair rewrap),
§6.5 (erasure's lock), §7.9 (open before production), §8.3 (webhook ingress), §9 (codes), §10.5 (pending work), §12
(testing), §13 (earlier specs), §14 (tables, grants) and §15 (values). Also the parent spec's §4.4 and §12.

## Global Constraints

- Every event ends in `admit_request`, through the dispatcher's matcher; ingress never starts a run, and nothing is
  matched while the gate is off.
- Ingress records nothing outside a development deployment (the owner's ruling 8): `dewpoint ingress` refuses to
  start, and the recording function refuses, unless `ingress_environment()` returns `development`.
- Ingress has no table privilege and never holds a tenant's key: only its three functions, and it refuses to start
  with a key-encryption key in its environment. Only the dispatcher opens events.
- One lock order for every path that touches events or their counters: the gate's lock (the matcher), the tenant's
  lifecycle lock (shared; exclusively only for 2b-4's erasure), endpoint rows in id order, the tenant's counter row,
  then event rows.
- No value from an event, a secret or a token appears in plain metadata, a log, a code or a message: codes are fixed,
  a log names an exception's type, a settings error quotes no value, and ids are stored only as keyed digests.
- Every new table forces row-level security, with tenant-scoped policies for the API and the dispatcher only;
  cross-tenant reads are functions returning ids only (`event_candidates()`, `recount_candidates()`).
- An alert or a warning about an outcome is logged only once its transaction has committed.
- Docker runs only the approved images (`postgres:16-alpine`, ryuk, `temporalio/temporal:1.9.1`); the Compose proof
  runs in CI.
- Migrations 0031–0033 upgrade, downgrade and upgrade again over existing rows.
- Fix findings test-first. Run focused checks at each milestone, and the whole suite once, at the end.
- The load probe's numbers are one machine's measurements, never a production capacity or a throughput promise.

## Review Focus

These are the input classes and failure modes most likely to bite a person running this that no task's tests
exercise. §7.9 keeps them open before production, and the reviewer weighs each deliberately:
- **A sender at the event rates, with a real Temporal and more bindings.** The defaults (10 events/s an endpoint and a
  tenant) sit below the drain the probe measured with a fake Temporal and up to five bindings; a real deployment drains
  less. Past the pending quota, ingress answers 429: backpressure, not a guarantee.
- **More than one dispatcher.** A second adds almost nothing today: both take the same candidates in the same order.
  Making matching scale with dispatchers is a required decision of 2b-4, before production, after which the probe's
  separate-tenant control is measured again.
- **A flood of failing addresses.** The failure limit is each process's, in a table of 65,536 addresses that drops the
  least recently failed when full: past that, it's best-effort.
- **A large pending backlog.** `event_candidates()` ranks every pending event: 6.5 ms at 10,000, about 60 ms at 200,000.
- **A Mist webhook's bearer token.** Mist's documentation allows custom headers but doesn't say whether it allows
  `Authorization`; no real delivery has confirmed it.

## File structure

New:
- `backend/migrations/versions/0031_tenant_event_keys.py`, `0032_webhook_ingress.py`, `0033_event_matching.py`: the
  tenants' keypairs; endpoints, counters, bindings, events and ingress's functions; the matcher's and the recount's
  candidates and the API's cancel grants.
- `backend/src/dewpoint/core/crypto/ingress.py` (the ingress key, secrets) and `core/crypto/events.py` (sealing).
- `backend/src/dewpoint/core/ingress/`: `identity.py`, `keys.py`, `parsing.py`, `pointer.py`, `filters.py`,
  `counters.py`.
- `backend/src/dewpoint/core/models/ingress.py`.
- `backend/src/dewpoint/apps/ingress/`: `main.py`, `config.py`, `addresses.py`, `limits.py`, `auth.py`, `endpoints.py`,
  `batch.py`, `recording.py`.
- `backend/src/dewpoint/apps/dispatcher/matching.py` and `recount.py`.
- `backend/src/dewpoint/apps/webhooks.py` and `apps/api/routes/webhooks.py`.
- `backend/tests/probes/ingress_load.py` (run by hand), `deploy/compose/ci/ingress-proof.py`,
  `docs/operations/ingress.md`, and the tests listed in each task.

Changed:
- `apps/cli/main.py` (`keys ensure-tenants`, `dewpoint ingress`), `apps/api/main.py`, `apps/dispatcher/main.py`,
  `core/config.py`, `core/tenancy/service.py`, `core/models/__init__.py`, `backend/pyproject.toml` (an import
  contract).
- Compose, nginx and CI: `deploy/compose/docker-compose.yml`, `.env.example`, `initdb/10-roles.sh`,
  `deploy/docker/nginx.conf`, `.github/workflows/ci.yml`; docs: `deployment.md`, `runs.md`.

## How the steps give code

Each task's code is given as a unified diff against the tree the previous task left, in the task's record. The diffs
are a prototype's commits, and each was replayed onto that tree in two steps. First its tests ran alone, and failed as
the record says (or passed, for a task that adds only a proof of what earlier tasks built). Then the rest of the diff
was applied, and the tests passed. New files appear whole, as `new file mode` diffs. In the replay's outputs, local
paths are shortened to `<replay>` (the replay's checkout), `<venv>` and `<python>`.

The prototype is the local branch `proto/2b3b-v2`, cut from `main` at `9fb4ee5`, with one commit per task:
- `proto/2b3b-v1` was built milestone by milestone, with the owner's checkpoint after each; all four milestones were
  approved as prototype checkpoints.
- `proto/2b3b-v2` rebuilds it in ten tasks. Its tasks 4 and 5 are folded into one (the owner's ruling: no deployable
  commit answering an authenticated request with 501), and each review fix-up is folded into the task that owns the
  files it changes. Two files take a state no prototype commit had: migration 0032 at Task 3 stops before Task 9's
  measured rate defaults, and `matching.py` at Task 6 comes before Task 7 moves its counter release to
  `core.ingress.counters`. The replay found one more fix: a race test that failed while holding a match left its
  transaction open, and the teardown's truncate waited for it for ever (the replay's own run of Task 7's tests before
  their code hung). Each race module now releases what it holds at teardown (`f462f0b` on `proto/2b3b-v1`, folded into
  Tasks 5 to 7). Task 10's proof test names its new task number. Its last tree is `proto/2b3b-v1`'s (`f462f0b`) but for
  that line.

Each commit was verified this way:
- its tree was reproduced exactly by the replay, its tests failing before its code and passing after, with the
  exceptions each record shows;
- CI's static checks passed on every task's tree: ruff and its formatter (without their caches), mypy and
  import-linter;
- at each checkpoint, the milestone's focused tests passed (the counts the checkpoints give), and the migrations went
  up, down and up again over existing rows.

Per the owner's ruling on the outline, the whole suite runs once, at the end, not at every task.

## Executing this plan

Run it inline, in one session, from the prototype's commits; the diffs aren't typed again. Work on `feat/engine-2b3b`,
cut from `main` once this plan's docs have merged (they change only `docs/superpowers`). For each task in order:
1. Read the task.
2. Run `git cherry-pick --no-commit <the task's commit>`, and check that nothing conflicts.
3. Commit with `git commit -C <the task's commit>`, which keeps the prototype's message.

The task's record (its tests, how they failed and passed, and its diff) is historical: it isn't run again for each
task.

**Checkpoints:** after Task 3 (keys and the event store), Task 4 (the ingress process), Task 7 (matching and
management) and Task 10 (proofs, the probe, Compose and docs), run the milestone's focused tests, then stop for the
owner's review. Group pytest's arguments by directory: pytest 9.1.1 loses a directory's conftest fixtures when the
arguments revisit it after a file of its parent. After Task 10, run the whole suite and the static checks once, then a
fresh reviewer reviews the whole branch.

**Milestone 4's open condition:** the Compose ingress proof's CI step (Task 10) runs in this branch's pull request;
the owner's approval doesn't claim it passed. Production sign-off stays separate (§7.9).

A conflict, a failing focused test or a failing final check is a finding: stop and report it, and don't patch around
it. The diffs below remain the plan's record of every change.

## The owner's rulings (2026-10-04)

On the outline, before the prototype. Its milestones are this plan's: milestone 1 is Tasks 1 to 3, milestone 2 Task 4,
milestone 3 Tasks 5 to 7 and milestone 4 Tasks 8 to 10.

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

**The owner's second review (2026-10-04):** approved `event_id_reused` as a 409, the canonical-JSON content digest,
the provisional retained caps, the global pre-authentication 503 and refusing production startup; corrected:
1. no event row claimed before the tenant's lock: candidates return ids; the gate's and tenant's locks shared, then
   endpoint → tenant counter → event row `SKIP LOCKED`, `pending` rechecked after the claim; ingress holds the
   tenant's lifecycle lock shared while recording; both orders race-tested;
2. the recount counts under the counter locks;
3. the startup guard through an ingress-executable read of the recorded environment, failing when it's absent or not
   `development`;
4. refusal budgets: which failed authenticated attempts spend rate budget, inserts still all or nothing; a body-read
   deadline and abuse protection independent of endpoints; no meaningful `Retry-After` promised for the retained cap;
   canonicalization explicit, duplicate keys refused.

**Open and separate:** issues #16, #18 and #26; §7.9's production items; 2b-3a's deferred minors; 2b-4 (retention,
the erasure transition, key rotation and retirement, lifting the gate on ingress and on runs).

## The owner's milestone rulings (2026-10-04)

Each milestone was approved as a prototype checkpoint, not production sign-off. Each hold's fixes are folded into the
tasks named.

1. **Milestone 1.** Held once. The sealed size's check refused valid bodies (canonical floats expand: a 761-byte body
   sealed to 2,926 bytes), so it allows 5 times the body limit plus 128 bytes an event; a byte burst could make a
   permitted request wait for ever, so every burst covers the largest charge its row permits; the recording function
   read its clock before its locks; a binding's workflow wasn't bound to the endpoint's tenant, now a composite key (all
   Task 3). Accepted: a separate keypair helper, `DEWPOINT_INGRESS_KEY_B64`, the outcome names, the ORM models in
   milestone 3. The same gap in merged tables (`run_requests`, `csv_uploads`, `csv_mappings`, `schedules`) is issue #35,
   outside 2b-3b.
2. **Milestone 2.** Held twice. First: a truncated sealed secret raised a 500, and a malformed one is now refused (Task
   1); the key-encryption-key guard ran only in the CLI, and runs at the app's startup too; an oversized numeric
   `Content-Length` is a counted 413 (both Task 4). Then the size contract: an endpoint's byte burst covers the larger
   of its largest sealed batch and the global body cap, which is at most 5 MiB (Tasks 3 and 4). Accepted provisionally:
   the failure table's 65,536 addresses, past which the limit is best-effort. The outline's Tasks 4 and 5 are one task
   (Task 4): no deployable commit answers an authenticated request with 501. The recording function doesn't clamp the
   length it's told: a later hardening of direct calls refuses an impossible one explicitly, never normalizes it.
3. **Milestone 3.** Held once. Viewers saw dead events through an endpoint's event list (Task 7); a private key wasn't
   checked against its public key, so a rewrapped mismatch made valid events dead under a verified version: each load
   now checks the pair, and a mismatch is a platform failure, the events kept pending (Tasks 2 and 6); alerts were
   logged before their transaction committed (Task 6). Accepted: an endpoint disabled after its events were recorded
   still has them matched. The load probe was to measure the candidates' ranking over the whole backlog and how long a
   match holds its endpoint's row.
4. **Milestone 4.** Held three times. nginx buffered bodies, so ingress's deadline and its in-flight limit didn't hold
   through it: it streams them now, and a slow upload through it gets its 408 (Task 10). The event rate isn't set from a
   probe that skipped the loop's sleep: the drain was measured through the dispatcher's own loop with representative
   fan-out, and the endpoint's default set below it with headroom; a quota's 429 is backpressure, never a throughput
   promise. The tenant's rate was measured, not set by analogy: each limit on its own, and one tenant's endpoints
   draining together; its default is 10/s too (Task 9). The probe is in the repo, run by hand, out of routine CI. Making
   matching scale with dispatchers is deferred to production sign-off, a required decision of 2b-4 (changing the
   candidates' order or the matcher's locks now would reopen milestone 3's fairness and races), after which the probe's
   separate-tenant control is measured again. The approval doesn't claim the Compose proof has passed CI: this branch's
   pull request runs it.

## Milestone 1 — Keys, the event store and its functions

### Task 1: The ingress key, endpoint secrets and an event's typed identity

**Commit:** `7dc02fb` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/src/dewpoint/core/crypto/ingress.py`, `backend/src/dewpoint/core/ingress/__init__.py`,
`backend/src/dewpoint/core/ingress/identity.py`, `backend/tests/core/crypto/test_ingress_key.py`,
`backend/tests/core/ingress/__init__.py`, `backend/tests/core/ingress/test_identity.py`

**Modify:** `backend/src/dewpoint/core/config.py`

**What it does:**

The ingress key (DEWPOINT_INGRESS_KEY_B64 and its id), which only ingress and the API hold, seals an endpoint's HMAC
secret and its dedupe-digest key, each bound to its purpose and the endpoint's id; a sealed secret names its key's id,
and one that isn't the layout (format, a non-empty UTF-8 key id, the nonce, at least a tag) is refused as malformed,
never an index error. Bearer tokens are 256 random bits kept as their SHA-256 digest, compared in constant time.

An event's identity: its dedupe key is an HMAC of the id its sender gave it, typed (an integer 1 and a string "1" are
two ids), or of a request's header id and the item's index; none when the endpoint's events carry no id. Its content
digest is the same key's HMAC of its canonical bytes, one written procedure (sorted keys, no whitespace, strings as
parsed, shortest floats, UTF-8), at most 4.5 times the raw JSON.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/core/crypto/test_ingress_key.py tests/core/ingress/test_identity.py`. Replay result (exit 1), shortened:

```
_____________ ERROR collecting tests/core/ingress/test_identity.py _____________
ImportError while importing test module '<replay>/t1/backend/tests/core/ingress/test_identity.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
<python>/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/core/ingress/test_identity.py:14: in <module>
    from dewpoint.core.ingress import identity
E   ModuleNotFoundError: No module named 'dewpoint.core.ingress'
=========================== short test summary info ============================
ERROR tests/core/crypto/test_ingress_key.py - ImportError while importing tes...
ERROR tests/core/ingress/test_identity.py - ImportError while importing test ...
2 errors in 5.43s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.........................................                                [100%]
41 passed in 18.95s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 7dc02fb && git commit -C 7dc02fb`

The diff:

```diff
diff --git a/backend/src/dewpoint/core/config.py b/backend/src/dewpoint/core/config.py
index 3416c7c..535076a 100644
--- a/backend/src/dewpoint/core/config.py
+++ b/backend/src/dewpoint/core/config.py
@@ -13,6 +13,9 @@ class Settings(BaseSettings):
     kek_id: str = "env-1"
     kek_previous_b64: str | None = None  # set only during a KEK rollout (see docs/operations/key-rotation.md)
     kek_previous_id: str | None = None
+    # Sealing endpoint secrets (engine 2b spec §8.3): ingress and the API only; never a tenant's data key.
+    ingress_key_b64: str | None = None
+    ingress_key_id: str = "ingress-1"
     public_origin: str = Field(description="Browser origin, e.g. https://dewpoint.example.com")
     rp_id: str | None = None  # WebAuthn RP ID; defaults to host of public_origin
     mfa_required: bool = True
diff --git a/backend/src/dewpoint/core/crypto/ingress.py b/backend/src/dewpoint/core/crypto/ingress.py
new file mode 100644
index 0000000..d4e78b3
--- /dev/null
+++ b/backend/src/dewpoint/core/crypto/ingress.py
@@ -0,0 +1,97 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The ingress key (engine 2b spec §8.3): an endpoint's secrets — its HMAC secret and its dedupe-digest key — sealed
+under `DEWPOINT_INGRESS_KEY_B64`, which only ingress and the API hold, never under a tenant's data key, so ingress
+authenticates and deduplicates without one. A sealed secret names its key's id: one sealed under another key is
+refused by it (rotation is 2b-4's). A bearer token is high-entropy, made by Dewpoint, and kept only as its SHA-256
+digest."""
+
+import base64
+import hashlib
+import hmac
+import os
+import secrets
+
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+
+from dewpoint.core.config import Settings
+
+FORMAT_V1 = b"\x01"
+NONCE, TAG = 12, 16
+HMAC_SECRET = "endpoint.hmac"  # noqa: S105 - a purpose's name, not a credential (an endpoint's id is the context)
+DEDUPE_KEY = "endpoint.dedupe"
+BEARER_PREFIX = "dwp_"
+
+
+class IngressKeyMissingError(LookupError):
+    """A process that needs the ingress key (ingress, the API's endpoint routes) was started without one."""
+
+
+class UnknownIngressKeyError(LookupError):
+    """A secret sealed under an ingress key this process doesn't hold."""
+
+
+class MalformedSecretError(ValueError):
+    """Bytes that aren't a sealed secret's layout: format, id length, id, nonce, then at least a tag."""
+
+
+class IngressKey:
+    def __init__(self, key_id: str, key: bytes) -> None:
+        if len(key) != 32:
+            raise ValueError("the ingress key must be 32 bytes")
+        if not 0 < len(key_id.encode()) < 256:
+            raise ValueError("the ingress key's id must be 1 to 255 bytes")
+        self.key_id, self._aes = key_id, AESGCM(key)
+
+    @staticmethod
+    def _aad(purpose: str, context: str) -> bytes:
+        return f"dewpoint|ingress|{purpose}|{context}".encode()
+
+    def seal(self, purpose: str, context: str, plaintext: bytes) -> bytes:
+        kid, nonce = self.key_id.encode(), os.urandom(NONCE)
+        sealed = self._aes.encrypt(nonce, plaintext, self._aad(purpose, context))
+        return FORMAT_V1 + bytes([len(kid)]) + kid + nonce + sealed
+
+    def open(self, purpose: str, context: str, blob: bytes) -> bytes:
+        """Raises MalformedSecretError for bytes that aren't the layout, UnknownIngressKeyError for another key's
+        secret, and InvalidTag for one that doesn't authenticate."""
+        if len(blob) < 2 or blob[:1] != FORMAT_V1:
+            raise MalformedSecretError("not a sealed secret of a known format")
+        size = blob[1]
+        if size == 0 or len(blob) < 2 + size + NONCE + TAG:
+            raise MalformedSecretError("a sealed secret too short for its layout")
+        try:
+            kid = blob[2 : 2 + size].decode()
+        except UnicodeDecodeError:
+            raise MalformedSecretError("a sealed secret's key id isn't UTF-8") from None
+        if kid != self.key_id:
+            raise UnknownIngressKeyError(kid)
+        rest = blob[2 + size :]
+        return self._aes.decrypt(rest[:NONCE], rest[NONCE:], self._aad(purpose, context))
+
+    @classmethod
+    def from_settings(cls, settings: Settings) -> "IngressKey":
+        if not settings.ingress_key_b64:
+            raise IngressKeyMissingError("DEWPOINT_INGRESS_KEY_B64 is required by ingress and the API's endpoints")
+        return cls(settings.ingress_key_id, base64.b64decode(settings.ingress_key_b64))
+
+
+def new_bearer_token() -> str:
+    """256 random bits: what a sender presents, shown once; Dewpoint keeps only its digest."""
+    return BEARER_PREFIX + secrets.token_urlsafe(32)
+
+
+def new_hmac_secret() -> str:
+    return secrets.token_urlsafe(32)
+
+
+def new_dedupe_key() -> bytes:
+    return os.urandom(32)
+
+
+def bearer_digest(token: str) -> bytes:
+    return hashlib.sha256(token.encode()).digest()
+
+
+def bearer_matches(token: str, digest: bytes) -> bool:
+    """In constant time, whatever the token."""
+    return hmac.compare_digest(bearer_digest(token), digest)
diff --git a/backend/src/dewpoint/core/ingress/__init__.py b/backend/src/dewpoint/core/ingress/__init__.py
new file mode 100644
index 0000000..9881313
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/__init__.py
@@ -0,0 +1 @@
+# SPDX-License-Identifier: Apache-2.0
diff --git a/backend/src/dewpoint/core/ingress/identity.py b/backend/src/dewpoint/core/ingress/identity.py
new file mode 100644
index 0000000..5de5e76
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/identity.py
@@ -0,0 +1,65 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An event's identity (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline). Its dedupe key is an HMAC,
+under its endpoint's dedupe-digest key, of the id its sender gave it, typed (an integer `1` and a string `"1"` are two
+ids); a batch-level header id is qualified by the item's index; an event without an id has none, and nothing
+deduplicates it. Its content digest, the same key's HMAC of its canonical bytes, tells a duplicate from an id reused for
+other content. Ids are never stored: only these digests are."""
+
+import hashlib
+import hmac
+import json
+from typing import Literal
+
+type IdSource = Literal["pointer", "header", "none"]
+MAX_ID_CHARS = 255
+# Canonical bytes are at most this many times the raw JSON they came from: strings, whitespace and integers never grow,
+# and a float grows most from a 4-character `1e15` to the 18 of `1000000000000000.0`. The recording function's
+# backstop and the byte bursts are sized by it (the owner's M1 review).
+CANONICAL_EXPANSION = 4.5
+
+
+class InvalidEventIdError(ValueError):
+    """An id that isn't a non-empty string, or an integer, of at most 255 characters."""
+
+
+def _hmac(key: bytes, message: bytes) -> bytes:
+    return hmac.new(key, message, hashlib.sha256).digest()
+
+
+def _bounded(text: str) -> str:
+    if not 0 < len(text) <= MAX_ID_CHARS:
+        raise InvalidEventIdError("an event id is 1 to 255 characters")
+    return text
+
+
+def _typed(event_id: object) -> bytes:
+    if isinstance(event_id, str):
+        return b"s:" + _bounded(event_id).encode()
+    if isinstance(event_id, int) and not isinstance(event_id, bool):
+        if event_id.bit_length() > 1024:  # far past 255 digits, before `str` (which refuses past 4,300)
+            raise InvalidEventIdError("an event id is 1 to 255 characters")
+        return b"i:" + _bounded(str(event_id)).encode()
+    raise InvalidEventIdError("an event id is a string or an integer")
+
+
+def dedupe_key(key: bytes, source: IdSource, event_id: str | int | None, index: int) -> bytes | None:
+    """The event's dedupe key, or None when its endpoint's events carry no id. Raises InvalidEventIdError."""
+    if source == "none":
+        return None
+    if source == "pointer":
+        return _hmac(key, b"event:" + _typed(event_id))
+    if not isinstance(event_id, str):
+        raise InvalidEventIdError("a request's id is a string")
+    return _hmac(key, f"batch:{_bounded(event_id)}:{index}".encode())
+
+
+def content_digest(key: bytes, canonical: bytes) -> bytes:
+    return _hmac(key, b"content:" + canonical)
+
+
+def canonical(event: object) -> bytes:
+    """An event's canonical bytes, one written procedure, so no parser decides identity: object keys sorted by code
+    point, no whitespace, strings as parsed (only `"`, the backslash and control characters escaped, no normalization),
+    integers in decimal, floats in their shortest round-trip form, encoded as UTF-8. Raises ValueError for NaN or an
+    infinity and UnicodeEncodeError for an unpaired surrogate (ingress refuses both before here)."""
+    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
diff --git a/backend/tests/core/crypto/test_ingress_key.py b/backend/tests/core/crypto/test_ingress_key.py
new file mode 100644
index 0000000..04cd994
--- /dev/null
+++ b/backend/tests/core/crypto/test_ingress_key.py
@@ -0,0 +1,86 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The ingress key (engine 2b spec §8.3; 2b-3b task 1): an endpoint's secrets (its HMAC secret, its dedupe-digest key)
+are sealed under `DEWPOINT_INGRESS_KEY`, which only ingress and the API hold, never under a tenant's data key, so
+ingress authenticates and deduplicates without one. A bearer token is high-entropy, made by Dewpoint, and kept only as
+its SHA-256 digest."""
+
+import base64
+import hashlib
+
+import pytest
+from cryptography.exceptions import InvalidTag
+
+from dewpoint.core.config import Settings
+from dewpoint.core.crypto import ingress
+
+KEY = ingress.IngressKey("ingress-1", bytes(range(32)))
+
+
+def settings(**given: str) -> Settings:
+    return Settings(database_url="postgresql+asyncpg://x", kek_b64=base64.b64encode(bytes(32)).decode(),
+                    public_origin="https://dewpoint.test", **given)  # type: ignore[arg-type]  # fmt: skip
+
+
+def test_a_sealed_secret_opens_only_under_its_purpose_and_context() -> None:
+    blob = KEY.seal(ingress.HMAC_SECRET, "endpoint-1", b"s3cret")
+    assert b"s3cret" not in blob
+    assert KEY.open(ingress.HMAC_SECRET, "endpoint-1", blob) == b"s3cret"
+    for purpose, context in ((ingress.DEDUPE_KEY, "endpoint-1"), (ingress.HMAC_SECRET, "endpoint-2")):
+        with pytest.raises(InvalidTag):
+            KEY.open(purpose, context, blob)
+
+
+def test_a_tampered_secret_is_refused() -> None:
+    blob = bytearray(KEY.seal(ingress.HMAC_SECRET, "e", b"s3cret"))
+    blob[-1] ^= 1
+    with pytest.raises(InvalidTag):
+        KEY.open(ingress.HMAC_SECRET, "e", bytes(blob))
+
+
+def test_a_secret_sealed_under_another_ingress_key_is_refused_by_its_id() -> None:
+    other = ingress.IngressKey("ingress-2", bytes(32))
+    with pytest.raises(ingress.UnknownIngressKeyError):
+        KEY.open(ingress.HMAC_SECRET, "e", other.seal(ingress.HMAC_SECRET, "e", b"x"))
+
+
+@pytest.mark.parametrize(
+    "blob",
+    [
+        b"",
+        b"\x01",  # the format, then nothing (the owner's M2 review)
+        b"\x02" + b"\x09ingress-1" + bytes(28),  # another format
+        b"\x01\x09ingress-1",  # no nonce
+        b"\x01\x20ingress-1" + bytes(28),  # an id longer than the blob says it has
+        b"\x01\x00" + bytes(28),  # an empty id
+        b"\x01\x02\xff\xfe" + bytes(28),  # an id that isn't UTF-8
+        b"\x01\x09ingress-1" + bytes(12) + bytes(15),  # shorter than a tag
+    ],
+)
+def test_a_malformed_sealed_secret_is_refused_as_malformed_never_an_index_error(blob: bytes) -> None:
+    with pytest.raises(ingress.MalformedSecretError):
+        KEY.open(ingress.HMAC_SECRET, "e", blob)
+    assert issubclass(ingress.MalformedSecretError, ValueError)
+
+
+def test_the_key_is_32_bytes_and_read_from_the_settings() -> None:
+    with pytest.raises(ValueError, match="32 bytes"):
+        ingress.IngressKey("k", bytes(16))
+    with pytest.raises(ingress.IngressKeyMissingError):
+        ingress.IngressKey.from_settings(settings())
+    loaded = ingress.IngressKey.from_settings(
+        settings(ingress_key_b64=base64.b64encode(bytes(range(32))).decode(), ingress_key_id="ingress-1")
+    )
+    assert loaded.open(ingress.HMAC_SECRET, "e", KEY.seal(ingress.HMAC_SECRET, "e", b"x")) == b"x"
+
+
+def test_a_bearer_token_is_high_entropy_and_kept_as_its_digest() -> None:
+    token = ingress.new_bearer_token()
+    assert token.startswith("dwp_") and len(token) >= 40 and token != ingress.new_bearer_token()
+    digest = ingress.bearer_digest(token)
+    assert digest == hashlib.sha256(token.encode()).digest()
+    assert ingress.bearer_matches(token, digest) and not ingress.bearer_matches(token + "x", digest)
+
+
+def test_an_endpoints_secrets_are_fresh_random_bytes() -> None:
+    assert len(ingress.new_hmac_secret()) >= 43 and ingress.new_hmac_secret() != ingress.new_hmac_secret()
+    assert len(ingress.new_dedupe_key()) == 32 and ingress.new_dedupe_key() != ingress.new_dedupe_key()
diff --git a/backend/tests/core/ingress/__init__.py b/backend/tests/core/ingress/__init__.py
new file mode 100644
index 0000000..9881313
--- /dev/null
+++ b/backend/tests/core/ingress/__init__.py
@@ -0,0 +1 @@
+# SPDX-License-Identifier: Apache-2.0
diff --git a/backend/tests/core/ingress/test_identity.py b/backend/tests/core/ingress/test_identity.py
new file mode 100644
index 0000000..cfa3597
--- /dev/null
+++ b/backend/tests/core/ingress/test_identity.py
@@ -0,0 +1,80 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An event's identity (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline): its dedupe key is an HMAC, under
+its endpoint's dedupe-digest key, of the id the sender gave it, typed, so an integer `1` and a string `"1"` are two
+ids; a batch-level header id is qualified by the item's index; an event without an id has none, and nothing
+deduplicates it. Its content digest, the same key's HMAC of its canonical bytes, tells a duplicate from an id reused
+for other content."""
+
+import hashlib
+import hmac
+import json
+
+import pytest
+
+from dewpoint.core.ingress import identity
+
+KEY = bytes(range(32))
+
+
+def test_a_pointer_id_is_typed_so_an_integer_and_its_string_differ() -> None:
+    as_int = identity.dedupe_key(KEY, "pointer", 1, 0)
+    as_str = identity.dedupe_key(KEY, "pointer", "1", 0)
+    assert as_int is not None and as_str is not None and as_int != as_str
+    assert as_int == hmac.new(KEY, b"event:i:1", hashlib.sha256).digest()
+    assert as_str == hmac.new(KEY, b"event:s:1", hashlib.sha256).digest()
+    assert identity.dedupe_key(KEY, "pointer", "1", 7) == as_str  # an event's own id: its position doesn't matter
+
+
+def test_a_header_id_is_qualified_by_the_items_index() -> None:
+    first, second = identity.dedupe_key(KEY, "header", "req-9", 0), identity.dedupe_key(KEY, "header", "req-9", 1)
+    assert first != second
+    assert first == hmac.new(KEY, b"batch:req-9:0", hashlib.sha256).digest()
+
+
+def test_an_event_without_an_id_has_no_dedupe_key() -> None:
+    assert identity.dedupe_key(KEY, "none", None, 0) is None
+
+
+def test_the_keys_depend_on_the_endpoints_dedupe_key() -> None:
+    assert identity.dedupe_key(KEY, "pointer", "a", 0) != identity.dedupe_key(bytes(32), "pointer", "a", 0)
+
+
+@pytest.mark.parametrize("given", [True, False, 1.5, None, "", "x" * 256, [1], {"id": 1}, 10**300])
+def test_an_id_that_isnt_a_short_string_or_integer_is_refused(given: object) -> None:
+    with pytest.raises(identity.InvalidEventIdError):
+        identity.dedupe_key(KEY, "pointer", given, 0)  # type: ignore[arg-type]
+
+
+def test_a_header_id_must_be_a_short_string() -> None:
+    for given in ("", "x" * 256, 7):
+        with pytest.raises(identity.InvalidEventIdError):
+            identity.dedupe_key(KEY, "header", given, 0)  # type: ignore[arg-type]
+
+
+def test_the_content_digest_is_keyed_and_apart_from_any_dedupe_key() -> None:
+    digest = identity.content_digest(KEY, b'{"a":1}')
+    assert digest == hmac.new(KEY, b'content:{"a":1}', hashlib.sha256).digest()
+    assert digest != identity.content_digest(bytes(32), b'{"a":1}')
+    assert digest != identity.dedupe_key(KEY, "pointer", '{"a":1}', 0)
+
+
+def test_canonical_bytes_follow_the_written_procedure() -> None:
+    """Keys sorted by code point, no whitespace, strings as parsed (only quotes, backslashes and controls escaped),
+    integers in decimal, floats in their shortest round-trip form, UTF-8."""
+    event = json.loads('{ "b": 2, "a": [1, 1.0, 1e2, "\\u00e9\\/\\n"] }')
+    assert identity.canonical(event) == '{"a":[1,1.0,100.0,"é/\\n"],"b":2}'.encode()
+
+
+@pytest.mark.parametrize(
+    "raw",
+    [
+        '{"a":1e15}', '{"a":9E15}', '{"a":-1e15}', '{"a":1e9}', '{"a":1e14}', '{"a":1e-5}', '{"a":1e300}',
+        '{"a":[' + ",".join(["1e15"] * 150) + "]}", '{"a" : [ 1e14 , 1e15 ]}', '{"a":12345678901234567890}',
+        '{"\\u00e9\\/":"\\ud83d\\ude00"}',
+    ],
+)  # fmt: skip
+def test_canonical_bytes_are_at_most_four_and_a_half_times_the_raw_json(raw: str) -> None:
+    """The bound the recording function's backstop and the byte bursts are sized by (the owner's M1 review): strings,
+    whitespace and integers never grow; a float can, at most from a 4-character `1e15` to the 18 of
+    `1000000000000000.0`."""
+    assert len(identity.canonical(json.loads(raw))) <= identity.CANONICAL_EXPANSION * len(raw.encode())
```

### Task 2: Each tenant's inbound X25519 keypair, and sealing an event to it

**Commit:** `83f5935` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/migrations/versions/0031_tenant_event_keys.py`, `backend/src/dewpoint/core/crypto/events.py`,
`backend/src/dewpoint/core/ingress/keys.py`, `backend/src/dewpoint/core/models/ingress.py`,
`backend/tests/core/crypto/test_event_sealing.py`, `backend/tests/core/ingress/test_event_keys.py`

**Modify:** `backend/src/dewpoint/apps/cli/main.py`, `backend/src/dewpoint/core/models/__init__.py`,
`backend/src/dewpoint/core/tenancy/service.py`, `backend/tests/apps/cli/test_keys.py`, `backend/tests/conftest.py`

**What it does:**

Sealing: an ephemeral X25519 key agreed with the tenant's public key, HKDF-SHA256 (the two public keys the salt) and
AES-256-GCM, the tenant, endpoint, event id and keypair version in the associated data; a known answer pinned and
derived independently, tamper, wrong-key and missing-version tests. `tenant_event_keys` (0031) keeps each version's
public key and its private key sealed with the tenant's data key (`event.private`, the version its context); every
load of a private key checks it pairs with the version's public key, and a mismatch (or a key of the wrong length) is
the keypair's failure, never an event's. `create_tenant` makes version 1; `dewpoint keys ensure-tenants` makes it for
tenants that predate it, as the key admin.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/cli/test_keys.py tests/core/crypto/test_event_sealing.py tests/core/ingress/test_event_keys.py`. Replay
  result (exit 1), shortened:

```
tests/core/ingress/test_event_keys.py:22: in <module>
    from dewpoint.core.ingress import keys as event_keys
E   ImportError: cannot import name 'keys' from 'dewpoint.core.ingress' (<replay>/t2/backend/src/dewpoint/core/ingress/__init__.py)
=================================== FAILURES ===================================
[gw0] darwin -- Python 3.14.7 <venv>/bin/python
E   AssertionError: assert (0, 'created ... tenant(s)\n') == (0, 'created ... tenant(s)\n')
      At index 1 diff: 'created a data key for 2 tenant(s)\n' != 'created a data key for 2 tenant(s)\ncreated an inbound keypair for 2 tenant(s)\n'
      Use -v to get more diff
<replay>/t2/backend/tests/apps/cli/test_keys.py:101: AssertionError: assert (0, 'created ... tenant(s)\n') == (0, 'created ... tenant(s)\n')
=========================== short test summary info ============================
FAILED tests/apps/cli/test_keys.py::test_ensure_tenants_gives_every_tenant_without_a_key_one
ERROR tests/core/crypto/test_event_sealing.py - ImportError while importing t...
ERROR tests/core/ingress/test_event_keys.py - ImportError while importing tes...
1 failed, 2 passed, 2 errors in 13.99s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...................                                                      [100%]
19 passed in 17.67s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 83f5935 && git commit -C 83f5935`

The diff:

```diff
diff --git a/backend/migrations/versions/0031_tenant_event_keys.py b/backend/migrations/versions/0031_tenant_event_keys.py
new file mode 100644
index 0000000..3591068
--- /dev/null
+++ b/backend/migrations/versions/0031_tenant_event_keys.py
@@ -0,0 +1,41 @@
+# SPDX-License-Identifier: Apache-2.0
+"""tenant_event_keys: each tenant's inbound X25519 keypairs (engine 2b spec §8.3, §6.4), versioned; the private key
+sealed with the tenant's data key. The API makes one with a tenant, the key admin for tenants that predate them, the
+dispatcher reads them to open events; ingress never reads the table (its resolver returns the public key)"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0031"
+down_revision = "0030"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "tenant_event_keys",
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
+        sa.Column("version", sa.Integer, primary_key=True),
+        sa.Column("public_key", sa.LargeBinary, nullable=False),
+        sa.Column("private_sealed", sa.LargeBinary, nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.CheckConstraint("version >= 1", name="tenant_event_keys_version"),
+        sa.CheckConstraint("octet_length(public_key) = 32", name="tenant_event_keys_public"),
+    )
+    for statement in (
+        "ALTER TABLE tenant_event_keys ENABLE ROW LEVEL SECURITY",
+        "ALTER TABLE tenant_event_keys FORCE ROW LEVEL SECURITY",
+        "CREATE POLICY tenant_event_keys_scope ON tenant_event_keys TO dewpoint_api, dewpoint_dispatch, dewpoint_admin "
+        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+        # Like data keys: the key admin keys every tenant that predates its keypair.
+        "CREATE POLICY tenant_event_keys_key_admin ON tenant_event_keys TO dewpoint_admin USING (true) WITH CHECK (true)",
+        "GRANT SELECT, INSERT ON tenant_event_keys TO dewpoint_api, dewpoint_admin",
+        "GRANT SELECT ON tenant_event_keys TO dewpoint_dispatch",
+    ):
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.drop_table("tenant_event_keys")
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 4d8fbd8..5d0c16d 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -41,7 +41,7 @@ from dewpoint.core.plugins.registry import (
     list_node_types,
     sync_plugins,
 )
-from dewpoint.core.tenancy.service import NotKeyAdminError, ensure_tenant_keys
+from dewpoint.core.tenancy.service import NotKeyAdminError, ensure_tenant_event_keys, ensure_tenant_keys
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.sdk import ManifestError
 
@@ -230,16 +230,17 @@ def keys_ensure_tenants() -> None:
     Idempotent. Run as dewpoint_admin, as Compose's migrate step does: it lists tenants under row-level security."""
     keyring = Keyring(KekSet.from_settings(get_settings()))
 
-    async def _run(s: AsyncSession) -> list[uuid.UUID]:
+    async def _run(s: AsyncSession) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
         async with s.begin():
-            return await ensure_tenant_keys(s, keyring)
+            return await ensure_tenant_keys(s, keyring), await ensure_tenant_event_keys(s, keyring)
 
     try:
-        created = asyncio.run(_in_session(_run))
+        created, paired = asyncio.run(_in_session(_run))
     except NotKeyAdminError as e:
         typer.echo(f"ERROR: {e}")
         raise typer.Exit(2) from None
     typer.echo(f"created a data key for {len(created)} tenant(s)")
+    typer.echo(f"created an inbound keypair for {len(paired)} tenant(s)")
 
 
 @plugins_cli.command("sync")
diff --git a/backend/src/dewpoint/core/crypto/events.py b/backend/src/dewpoint/core/crypto/events.py
new file mode 100644
index 0000000..58d72b6
--- /dev/null
+++ b/backend/src/dewpoint/core/crypto/events.py
@@ -0,0 +1,90 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Sealing an inbound event to its tenant (engine 2b spec §8.3): an ephemeral X25519 key agreed with the tenant's
+public key, HKDF-SHA256 (salt: the ephemeral then the tenant's public key; info `dewpoint|inbound-event|v1`), and
+AES-256-GCM. Ingress holds only the public key, so it seals and never opens; the dispatcher opens with the private
+key. A sealed event names its keypair's version, and its tenant, endpoint, own id and that version are its associated
+data, so one moved to another row doesn't open.
+
+Layout: `0x01`, the version (4 bytes, big-endian), the ephemeral public key (32), the nonce (12), then the ciphertext
+and its tag (16)."""
+
+import os
+import struct
+import uuid
+
+from cryptography.hazmat.primitives import hashes
+from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+from cryptography.hazmat.primitives.kdf.hkdf import HKDF
+from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
+
+FORMAT_V1 = b"\x01"
+INFO = b"dewpoint|inbound-event|v1"
+OVERHEAD = 1 + 4 + 32 + 12 + 16  # what sealing adds to a payload
+
+
+def _raw_public(key: X25519PrivateKey) -> bytes:
+    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
+
+
+def _aad(tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID, version: int) -> bytes:
+    return f"dewpoint|event|{tenant_id}|{endpoint_id}|{event_id}|{version}".encode()
+
+
+def _key(shared: bytes, ephemeral_public: bytes, recipient_public: bytes) -> AESGCM:
+    return AESGCM(HKDF(hashes.SHA256(), 32, ephemeral_public + recipient_public, INFO).derive(shared))
+
+
+def public_of(private_key: bytes) -> bytes:
+    """The raw public key of a raw X25519 private key."""
+    return _raw_public(X25519PrivateKey.from_private_bytes(private_key))
+
+
+def generate_keypair() -> tuple[bytes, bytes]:
+    """A new keypair: its raw private and public keys, 32 bytes each."""
+    private = X25519PrivateKey.generate()
+    return private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()), _raw_public(private)
+
+
+def seal_with(
+    ephemeral_private: bytes, nonce: bytes, public_key: bytes, version: int, *, tenant_id: uuid.UUID,
+    endpoint_id: uuid.UUID, event_id: uuid.UUID, plaintext: bytes,
+) -> bytes:  # fmt: skip
+    """`seal`, with the ephemeral key and the nonce given: for a known answer only. Never reuse either."""
+    ephemeral = X25519PrivateKey.from_private_bytes(ephemeral_private)
+    ephemeral_public = _raw_public(ephemeral)
+    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public_key))
+    sealed = _key(shared, ephemeral_public, public_key).encrypt(
+        nonce, plaintext, _aad(tenant_id, endpoint_id, event_id, version)
+    )
+    return FORMAT_V1 + struct.pack(">I", version) + ephemeral_public + nonce + sealed
+
+
+def seal(
+    public_key: bytes, version: int, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID,
+    plaintext: bytes,
+) -> bytes:  # fmt: skip
+    """`plaintext` sealed to the tenant's public key of `version`, bound to its tenant, endpoint and id."""
+    ephemeral = X25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
+    return seal_with(ephemeral, os.urandom(12), public_key, version, tenant_id=tenant_id, endpoint_id=endpoint_id,
+                     event_id=event_id, plaintext=plaintext)  # fmt: skip
+
+
+def version_of(blob: bytes) -> int:
+    """The version of the keypair a sealed event names. Raises ValueError for another format."""
+    if blob[:1] != FORMAT_V1 or len(blob) < OVERHEAD:
+        raise ValueError("a sealed event in an unknown format")
+    return int(struct.unpack(">I", blob[1:5])[0])
+
+
+def open_sealed(
+    private_key: bytes, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID, blob: bytes
+) -> bytes:
+    """The plaintext of a sealed event of this tenant, endpoint and id. Raises `InvalidTag` when it doesn't open."""
+    version = version_of(blob)
+    ephemeral_public, nonce = blob[5:37], blob[37:49]
+    private = X25519PrivateKey.from_private_bytes(private_key)
+    shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
+    return _key(shared, ephemeral_public, _raw_public(private)).decrypt(
+        nonce, blob[49:], _aad(tenant_id, endpoint_id, event_id, version)
+    )
diff --git a/backend/src/dewpoint/core/ingress/keys.py b/backend/src/dewpoint/core/ingress/keys.py
new file mode 100644
index 0000000..e919113
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/keys.py
@@ -0,0 +1,77 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A tenant's inbound keypairs (engine 2b spec §8.3, §6.4): made with the tenant and, for tenants that predate them, by
+the key admin; versioned from the start. The private key is sealed with the tenant's data key, so only a role that
+reads data keys (the dispatcher) opens it, through its cached key source. A version that isn't there fails closed:
+rotating keypairs and re-wrapping them before a data key retires are 2b-4's."""
+
+import hmac
+import uuid
+
+from sqlalchemy import func, select, text
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
+from dewpoint.core.crypto import events
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.models.ingress import TenantEventKey
+
+PURPOSE = "event.private"
+
+
+class NoEventKeyError(LookupError):
+    """A tenant has no inbound keypair of that version, or none at all (or row-level security hides it)."""
+
+
+class EventKeyMismatchError(NoEventKeyError):
+    """A keypair whose private key opens but isn't its public key's pair (rewrapped with another key): the events
+    sealed to that public key can't be opened with it, through no fault of theirs (the owner's M3 review)."""
+
+
+async def ensure_event_key(s: AsyncSession, keyring: Keyring, tenant_id: uuid.UUID) -> int:
+    """The tenant's current keypair version, made (version 1) if it has none, in the caller's tenant scope."""
+    await s.execute(
+        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:event-key:{tenant_id}"}
+    )
+    current = (
+        await s.execute(select(func.max(TenantEventKey.version)).where(TenantEventKey.tenant_id == tenant_id))
+    ).scalar_one()
+    if current is not None:
+        return int(current)
+    private, public = events.generate_keypair()
+    sealed = await keyring.encrypt(s, tenant_id=tenant_id, purpose=PURPOSE, context="1", plaintext=private)
+    s.add(TenantEventKey(tenant_id=tenant_id, version=1, public_key=public, private_sealed=sealed))
+    await s.flush()
+    return 1
+
+
+async def public_key(s: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, bytes]:
+    """The tenant's current version and its public key."""
+    row = (
+        await s.execute(
+            select(TenantEventKey).where(TenantEventKey.tenant_id == tenant_id)
+            .order_by(TenantEventKey.version.desc()).limit(1)
+        )
+    ).scalar_one_or_none()  # fmt: skip
+    if row is None:
+        raise NoEventKeyError(f"tenant {tenant_id} has no inbound keypair")
+    return row.version, row.public_key
+
+
+async def private_key(s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, version: int) -> bytes:
+    """The private key of the tenant's keypair `version`, opened with its data key, and checked against the version's
+    public key. Raises NoEventKeyError, EventKeyMismatchError among them."""
+    row = await s.get(TenantEventKey, (tenant_id, version))
+    if row is None:
+        raise NoEventKeyError(f"tenant {tenant_id} has no inbound keypair {version}")
+    try:
+        private = await ClaimCipher(keys, purpose=PURPOSE).open(str(tenant_id), str(version), row.private_sealed)
+    except ClaimUnreadableError:
+        raise NoEventKeyError(f"tenant {tenant_id}'s inbound keypair {version} doesn't open") from None
+    try:
+        paired = hmac.compare_digest(events.public_of(private), row.public_key)  # checked at every load
+    except ValueError:  # not even a key's length
+        paired = False
+    if not paired:
+        raise EventKeyMismatchError(f"tenant {tenant_id}'s inbound keypair {version} isn't a pair")
+    return private
diff --git a/backend/src/dewpoint/core/models/__init__.py b/backend/src/dewpoint/core/models/__init__.py
index c7dd63c..98e649b 100644
--- a/backend/src/dewpoint/core/models/__init__.py
+++ b/backend/src/dewpoint/core/models/__init__.py
@@ -4,6 +4,7 @@ from dewpoint.core.models import (
     claims,
     connections,
     identity,
+    ingress,
     keys,
     plugins,
     requests,
@@ -16,6 +17,6 @@ from dewpoint.core.models import (
 from dewpoint.core.models.base import Base
 
 __all__ = [
-    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "schedules",
+    "Base", "audit", "claims", "connections", "identity", "ingress", "keys", "plugins", "requests", "runs", "schedules",
     "tenancy", "uploads", "workflows",
 ]  # fmt: skip
diff --git a/backend/src/dewpoint/core/models/ingress.py b/backend/src/dewpoint/core/models/ingress.py
new file mode 100644
index 0000000..de01fd9
--- /dev/null
+++ b/backend/src/dewpoint/core/models/ingress.py
@@ -0,0 +1,23 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook ingress (engine 2b spec §8.3): a tenant's inbound keypairs."""
+
+import uuid
+from datetime import datetime
+
+from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
+from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy.orm import Mapped, mapped_column
+
+from dewpoint.core.models.base import Base
+
+
+class TenantEventKey(Base):
+    """A version of a tenant's X25519 keypair: ingress seals events to its public key; its private key is sealed with
+    the tenant's data key (purpose `event.private`, its version the context)."""
+
+    __tablename__ = "tenant_event_keys"
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
+    version: Mapped[int] = mapped_column(Integer, primary_key=True)
+    public_key: Mapped[bytes] = mapped_column(LargeBinary)
+    private_sealed: Mapped[bytes] = mapped_column(LargeBinary)
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
diff --git a/backend/src/dewpoint/core/tenancy/service.py b/backend/src/dewpoint/core/tenancy/service.py
index e608ab7..0d3db87 100644
--- a/backend/src/dewpoint/core/tenancy/service.py
+++ b/backend/src/dewpoint/core/tenancy/service.py
@@ -8,6 +8,8 @@ from dewpoint.core.auth.users import get_user_by_email
 from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import tenant_scope, user_scope
+from dewpoint.core.ingress.keys import ensure_event_key
+from dewpoint.core.models.ingress import TenantEventKey
 from dewpoint.core.models.keys import DataKey
 from dewpoint.core.models.tenancy import Membership, Tenant
 
@@ -26,7 +28,8 @@ class ActorNotAuthorizedError(Exception):
 
 
 async def create_tenant(s: AsyncSession, keyring: Keyring, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
-    """A tenant, its owner, and its data key: the payload codec only reads keys (engine 2b spec §6.3)."""
+    """A tenant, its owner, its data key (the payload codec only reads keys, engine 2b spec §6.3) and its inbound
+    keypair (§8.3)."""
     tid = uuid.uuid4()
     await tenant_scope(s, tid)
     tenant = Tenant(id=tid, name=name, slug=slug)
@@ -35,6 +38,7 @@ async def create_tenant(s: AsyncSession, keyring: Keyring, *, name: str, slug: s
     s.add(Membership(tenant_id=tid, user_id=owner_id, role="owner"))
     await s.flush()
     await keyring.ensure_key(s, tid)
+    await ensure_event_key(s, keyring, tid)
     return tenant
 
 
@@ -56,6 +60,19 @@ async def ensure_tenant_keys(s: AsyncSession, keyring: Keyring) -> list[uuid.UUI
     return created
 
 
+async def ensure_tenant_event_keys(s: AsyncSession, keyring: Keyring) -> list[uuid.UUID]:
+    """An inbound keypair for every tenant that has none — tenants created before 2b-3b — and which ones got one. As
+    `ensure_tenant_keys`, it runs as the key admin, which lists every tenant under row-level security."""
+    if not (await s.execute(text("SELECT pg_has_role(current_user, 'dewpoint_admin', 'USAGE')"))).scalar_one():
+        raise NotKeyAdminError("run it as a dewpoint_admin login: it lists every tenant under row-level security.")
+    keyed = select(TenantEventKey.tenant_id).where(TenantEventKey.tenant_id == Tenant.id).exists()
+    created = list((await s.execute(select(Tenant.id).where(~keyed).order_by(Tenant.id))).scalars())
+    for tid in created:
+        await tenant_scope(s, tid)
+        await ensure_event_key(s, keyring, tid)
+    return created
+
+
 async def list_user_tenants(s: AsyncSession, user_id: uuid.UUID) -> list[tuple[Tenant, str]]:
     await user_scope(s, user_id)
     rows = await s.execute(
diff --git a/backend/tests/apps/cli/test_keys.py b/backend/tests/apps/cli/test_keys.py
index 9da4c5c..008017b 100644
--- a/backend/tests/apps/cli/test_keys.py
+++ b/backend/tests/apps/cli/test_keys.py
@@ -98,7 +98,13 @@ def test_ensure_tenants_gives_every_tenant_without_a_key_one(pg_url, _test_users
     )
     _env(monkeypatch, _url_for(pg_url, "dewpoint_admin"), DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
     first = r.invoke(app, ["keys", "ensure-tenants"])
-    assert (first.exit_code, first.output) == (0, "created a data key for 2 tenant(s)\n")
+    assert (first.exit_code, first.output) == (
+        0,
+        "created a data key for 2 tenant(s)\ncreated an inbound keypair for 2 tenant(s)\n",
+    )  # and an inbound keypair (2b-3b)
     again = r.invoke(app, ["keys", "ensure-tenants"])
-    assert (again.exit_code, again.output) == (0, "created a data key for 0 tenant(s)\n")
+    assert (again.exit_code, again.output) == (
+        0,
+        "created a data key for 0 tenant(s)\ncreated an inbound keypair for 0 tenant(s)\n",
+    )
     assert "old=2" in r.invoke(app, ["keys", "status"]).output
diff --git a/backend/tests/conftest.py b/backend/tests/conftest.py
index 4ac98fb..a69a3c4 100644
--- a/backend/tests/conftest.py
+++ b/backend/tests/conftest.py
@@ -91,6 +91,13 @@ async def admin_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[as
     await eng.dispose()
 
 
+@pytest.fixture(scope="session")
+async def ingress_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
+    eng = make_engine(_url_for(pg_url, "dewpoint_ingress"))
+    yield make_sessionmaker(eng)
+    await eng.dispose()
+
+
 @pytest.fixture(scope="session")
 async def auditor_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
     eng = make_engine(_url_for(pg_url, "dewpoint_auditor"))
diff --git a/backend/tests/core/crypto/test_event_sealing.py b/backend/tests/core/crypto/test_event_sealing.py
new file mode 100644
index 0000000..b55c818
--- /dev/null
+++ b/backend/tests/core/crypto/test_event_sealing.py
@@ -0,0 +1,84 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Sealing an inbound event to its tenant (engine 2b spec §8.3; 2b-3b task 2): an ephemeral X25519 key agreed with the
+tenant's public key, HKDF-SHA256 (salt: the ephemeral then the tenant's public key; info `dewpoint|inbound-event|v1`)
+and AES-256-GCM. Ingress holds only the public key, so it seals and never opens. A sealed event names its keypair's
+version, and its tenant, endpoint, own id and that version are its associated data: moved to another row, it doesn't
+open."""
+
+import struct
+import uuid
+
+import pytest
+from cryptography.exceptions import InvalidTag
+from cryptography.hazmat.primitives import hashes
+from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+from cryptography.hazmat.primitives.kdf.hkdf import HKDF
+from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
+
+from dewpoint.core.crypto import events
+
+TENANT, ENDPOINT, EVENT = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
+IDS = {"tenant_id": TENANT, "endpoint_id": ENDPOINT, "event_id": EVENT}
+PRIVATE, EPHEMERAL, NONCE = bytes(range(32)), bytes(range(32, 64)), bytes(range(12))
+KNOWN = (  # the sealed bytes of `{"a":1}` under the inputs above
+    "0100000007358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254000102030405060708090a0b"
+    "a839c98cfc857c572099b9aa59ca2038554873e8602ac6"
+)
+
+
+def public_of(private: bytes) -> bytes:
+    return X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
+
+
+def test_the_scheme_as_written_with_a_known_answer() -> None:
+    public = public_of(PRIVATE)
+    blob = events.seal_with(EPHEMERAL, NONCE, public, 7, plaintext=b'{"a":1}', **IDS)
+    ephemeral_public = public_of(EPHEMERAL)
+    assert blob[:1] == b"\x01" and struct.unpack(">I", blob[1:5]) == (7,)
+    assert blob[5:37] == ephemeral_public and blob[37:49] == NONCE
+    shared = X25519PrivateKey.from_private_bytes(EPHEMERAL).exchange(X25519PublicKey.from_public_bytes(public))
+    key = HKDF(hashes.SHA256(), 32, ephemeral_public + public, b"dewpoint|inbound-event|v1").derive(shared)
+    aad = f"dewpoint|event|{TENANT}|{ENDPOINT}|{EVENT}|7".encode()
+    assert AESGCM(key).decrypt(NONCE, blob[49:], aad) == b'{"a":1}'  # derived here, independently
+    assert blob.hex() == KNOWN  # and pinned: a change to the format is deliberate
+    assert events.open_sealed(PRIVATE, blob=blob, **IDS) == b'{"a":1}'
+
+
+def test_a_sealed_event_opens_with_its_tenants_private_key_only() -> None:
+    private, public = events.generate_keypair()
+    assert public_of(private) == public
+    blob = events.seal(public, 3, plaintext=b"payload", **IDS)
+    assert b"payload" not in blob and events.version_of(blob) == 3
+    assert len(blob) == len(b"payload") + events.OVERHEAD
+    assert events.open_sealed(private, blob=blob, **IDS) == b"payload"
+    assert events.seal(public, 3, plaintext=b"payload", **IDS) != blob  # a fresh ephemeral key each time
+    other, _ = events.generate_keypair()
+    with pytest.raises(InvalidTag):
+        events.open_sealed(other, blob=blob, **IDS)
+
+
+@pytest.mark.parametrize("moved", ["tenant_id", "endpoint_id", "event_id"])
+def test_a_sealed_event_moved_to_another_row_doesnt_open(moved: str) -> None:
+    private, public = events.generate_keypair()
+    blob = events.seal(public, 1, plaintext=b"payload", **IDS)
+    with pytest.raises(InvalidTag):
+        events.open_sealed(private, blob=blob, **(IDS | {moved: uuid.uuid4()}))
+
+
+@pytest.mark.parametrize("at", [2, 10, 40, 60])  # its version, its ephemeral key, its nonce, its ciphertext
+def test_a_tampered_sealed_event_doesnt_open(at: int) -> None:
+    private, public = events.generate_keypair()
+    blob = bytearray(events.seal(public, 1, plaintext=b"payload-long-enough", **IDS))
+    blob[at] ^= 1
+    with pytest.raises(InvalidTag):
+        events.open_sealed(private, blob=bytes(blob), **IDS)
+
+
+def test_an_unknown_format_is_refused() -> None:
+    private, public = events.generate_keypair()
+    blob = events.seal(public, 1, plaintext=b"x", **IDS)
+    with pytest.raises(ValueError, match="format"):
+        events.open_sealed(private, blob=b"\x02" + blob[1:], **IDS)
+    with pytest.raises(ValueError, match="format"):
+        events.open_sealed(private, blob=blob[:20], **IDS)
diff --git a/backend/tests/core/ingress/test_event_keys.py b/backend/tests/core/ingress/test_event_keys.py
new file mode 100644
index 0000000..3d61fef
--- /dev/null
+++ b/backend/tests/core/ingress/test_event_keys.py
@@ -0,0 +1,114 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A tenant's inbound keypair (engine 2b spec §8.3, §6.4; 2b-3b task 2): made with the tenant, and by
+`ensure_tenant_event_keys` for tenants that predate it, versioned from the start; its private key sealed with the
+tenant's data key (purpose `event.private`, its version the context), which the dispatcher opens through its cached
+key source. A version that isn't there fails closed. Ingress never reads the table: its resolver returns the public
+key."""
+
+import os
+import uuid
+
+import pytest
+from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
+from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.crypto.kek import Kek, KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.ingress import keys as event_keys
+from dewpoint.core.tenancy import service
+
+KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
+
+
+async def new_tenant(owner, api, slug: str = "acme") -> uuid.UUID:
+    async with owner() as s, s.begin():
+        user = await create_user(s, email=f"{slug}@corp.test", password="violet-otter-canyon-42")
+    async with api() as s, s.begin():  # as the API creates it
+        return (await service.create_tenant(s, KEYRING, name=slug, slug=slug, owner_id=user.id)).id
+
+
+async def test_a_new_tenant_has_an_inbound_keypair_its_dispatcher_opens(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        version, public = await event_keys.public_key(s, tenant)
+        private = await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, version)
+    assert version == 1
+    derived = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
+    assert derived == public
+
+
+async def test_tenants_without_a_keypair_get_one_once_from_the_key_admin(
+    owner_sessionmaker, admin_sessionmaker, api_sessionmaker
+) -> None:
+    older, keyed = uuid.uuid4(), await new_tenant(owner_sessionmaker, api_sessionmaker, "keyed")
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T','older')"), {"t": older})
+        await KEYRING.ensure_key(s, older)
+    async with admin_sessionmaker() as s, s.begin():
+        assert await service.ensure_tenant_event_keys(s, KEYRING) == [older]
+        assert await service.ensure_tenant_event_keys(s, KEYRING) == []
+    async with api_sessionmaker() as s, s.begin():
+        with pytest.raises(service.NotKeyAdminError):
+            await service.ensure_tenant_event_keys(s, KEYRING)
+    async with owner_sessionmaker() as s:
+        rows = (await s.execute(text("select tenant_id, version from tenant_event_keys order by tenant_id"))).all()
+    assert sorted(rows) == sorted([(older, 1), (keyed, 1)])
+
+
+async def test_a_missing_keypair_or_version_fails_closed(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        with pytest.raises(event_keys.NoEventKeyError):
+            await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 2)
+        await tenant_scope(s, uuid.uuid4())  # another tenant's scope: row-level security hides the keypair
+        with pytest.raises(event_keys.NoEventKeyError):
+            await event_keys.public_key(s, tenant)
+
+
+async def test_the_keypairs_table_is_tenant_scoped_and_closed_to_ingress(
+    owner_sessionmaker, api_sessionmaker, ingress_sessionmaker
+) -> None:
+    await new_tenant(owner_sessionmaker, api_sessionmaker)
+    async with owner_sessionmaker() as s:
+        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'tenant_event_keys'")
+        assert tuple((await s.execute(query)).one()) == (True, True)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, uuid.uuid4())
+        assert (await s.execute(text("select count(*) from tenant_event_keys"))).scalar_one() == 0
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with ingress_sessionmaker() as s:
+            await s.execute(text("select count(*) from tenant_event_keys"))
+
+
+@pytest.mark.parametrize("other", ["another valid key", "not a key's length"])
+async def test_a_private_key_that_isnt_its_public_keys_pair_fails_closed(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, other
+) -> None:
+    """The owner's M3 review: a version rewrapped with another valid private key opens, but isn't the key ingress
+    seals to. Each load checks the pair, and a mismatch is the keypair's failure, never an event's."""
+    from dewpoint.core.crypto import events
+
+    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
+    other = events.generate_keypair()[0] if other == "another valid key" else b"sixteen bytes!!!"
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        rewrapped = await KEYRING.encrypt(s, tenant_id=tenant, purpose=event_keys.PURPOSE, context="1", plaintext=other)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenant_event_keys set private_sealed = :p where tenant_id = :t"),
+                        {"p": rewrapped, "t": tenant})  # fmt: skip
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        with pytest.raises(event_keys.EventKeyMismatchError) as refused:
+            await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 1)
+    assert isinstance(refused.value, event_keys.NoEventKeyError)
```

### Task 3: The event store, ingress's three functions under one lock order, and its login

**Commit:** `a5dd5e7` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/migrations/versions/0032_webhook_ingress.py`, `backend/tests/core/ingress/support.py`,
`backend/tests/core/ingress/test_ingress_guard.py`, `backend/tests/core/ingress/test_ingress_schema.py`,
`backend/tests/core/ingress/test_recording.py`

**Modify:** `.github/workflows/ci.yml`, `backend/tests/deploy/test_compose.py`, `deploy/compose/.env.example`,
`deploy/compose/docker-compose.yml`, `deploy/compose/initdb/10-roles.sh`, `docs/operations/deployment.md`

**What it does:**

Migration 0032: webhook_endpoints (authentication, allowlist, body limit, id source, rate buckets, pending and retained
counters and quotas), tenant_event_counters, trigger_bindings (a workflow of the endpoint's own tenant, by a composite
key; one per endpoint and workflow) and inbound_events, under forced row-level security. Ingress has no table
privilege: only `ingress_environment()`, `resolve_webhook_endpoint()` and `record_inbound_events()`, SECURITY DEFINER,
search_path pinned, closed to PUBLIC. The recording function takes the tenant from the endpoint's row, the tenant's
lifecycle lock shared, the endpoint's row, then the counter row; reads its clock after the locks; checks the batch
itself (count, alignment, digests, key version, a sealed size within 5 times the body limit plus 128 bytes an event);
spends the rate budget before deciding, so a refusal pays; refuses an id reused for other content, then the retained
caps (no wait), then the pending quotas (30 s); and inserts all or nothing. Every byte burst covers the largest charge
an endpoint permits: its largest sealed batch, or the global 5 MiB body cap. Nothing is recorded outside a development
deployment. The ingress login in Compose's init, env and CI, its test sessionmaker; the lock-order races.

**A later task refines this.** Task 9 sets both event rates' defaults, an endpoint's (200/s here) and a tenant's
(1,000/s here), to 10/s, below the drain its load probe measured.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/core/ingress/test_ingress_guard.py tests/core/ingress/test_ingress_schema.py
  tests/core/ingress/test_recording.py tests/deploy/test_compose.py`. Replay result (exit 1), shortened:

```
FAILED tests/core/ingress/test_recording.py::test_a_full_retained_cap_fails_closed_without_a_retry_time[retained_bytes_max]
FAILED tests/core/ingress/test_recording.py::test_a_disabled_endpoint_or_an_erasing_tenant_records_and_spends_nothing[update tenants set status = 'erasing' where id = :t]
FAILED tests/core/ingress/test_recording.py::test_the_tenants_counters_and_quotas_apply_across_its_endpoints
FAILED tests/core/ingress/test_recording.py::test_a_tenant_marked_erasing_first_is_refused_by_a_recording_that_waited
FAILED tests/core/ingress/test_recording.py::test_the_function_checks_the_batch_itself_whatever_its_caller_says
FAILED tests/core/ingress/test_recording.py::test_a_recording_holds_the_tenants_lock_until_it_commits
FAILED tests/core/ingress/test_recording.py::test_a_disabled_endpoint_or_an_erasing_tenant_records_and_spends_nothing[update webhook_endpoints set enabled = false where id = :e]
FAILED tests/core/ingress/test_recording.py::test_a_body_whose_canonical_json_grows_is_still_accepted
FAILED tests/core/ingress/test_recording.py::test_a_request_at_the_largest_permitted_size_is_recorded_from_a_full_bucket
FAILED tests/core/ingress/test_recording.py::test_every_permitted_request_fits_its_bursts
FAILED tests/core/ingress/test_recording.py::test_a_refusal_of_the_largest_body_read_is_charged_from_a_full_smallest_bucket
FAILED tests/core/ingress/test_recording.py::test_the_refill_is_reckoned_from_after_the_locks
FAILED tests/deploy/test_compose.py::test_the_database_init_makes_an_ingress_login_from_its_password
35 failed, 7 passed in 20.50s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..........................................                               [100%]
42 passed in 23.97s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit a5dd5e7 && git commit -C a5dd5e7`

The diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 5ee444f..c085e9d 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -86,6 +86,7 @@ jobs:
             echo "DEWPOINT_AUDITOR_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_WORKER_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_DISPATCH_DB_PASSWORD=$(openssl rand -hex 16)"
+            echo "DEWPOINT_INGRESS_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_KEK_B64=$(openssl rand -base64 32)"
             echo "DEWPOINT_AUDIT_SIGNING_KEY_B64=$(openssl rand -base64 32)"
           } > .env
diff --git a/backend/migrations/versions/0032_webhook_ingress.py b/backend/migrations/versions/0032_webhook_ingress.py
new file mode 100644
index 0000000..076e15c
--- /dev/null
+++ b/backend/migrations/versions/0032_webhook_ingress.py
@@ -0,0 +1,423 @@
+# SPDX-License-Identifier: Apache-2.0
+"""webhook ingress's tables and functions (engine 2b spec §8.3, §14; the owner's rulings on the 2b-3b outline):
+`webhook_endpoints` (with their rate buckets, quotas and counters), `tenant_event_counters`, `trigger_bindings` and
+`inbound_events`, each under forced row-level security, an event and a binding tied to their endpoint's tenant by a
+foreign key. Ingress gets no table privilege: only three SECURITY DEFINER functions, each with a pinned `search_path`,
+closed to `PUBLIC`. One lock order for every writer of the counters: the tenant's lifecycle lock (shared), the
+endpoint's row, the tenant's counter row, then event rows."""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0032"
+down_revision = "0031"
+branch_labels = None
+depends_on = None
+
+MIB = 1024 * 1024
+MAX_BODY_BYTES = 5 * MIB  # the largest body limit an endpoint may set, and ingress's global cap (its setting's bound)
+
+
+def _counters() -> list[sa.Column]:
+    return [
+        sa.Column(name, sa.BigInteger, nullable=False, server_default="0")
+        for name in ("pending_events", "pending_bytes", "retained_events", "retained_bytes")
+    ]
+
+
+def _quotas(pending_events: int, pending_bytes: int, retained_events: int, retained_bytes: int) -> list[sa.Column]:
+    return [
+        sa.Column("pending_events_max", sa.BigInteger, nullable=False, server_default=str(pending_events)),
+        sa.Column("pending_bytes_max", sa.BigInteger, nullable=False, server_default=str(pending_bytes)),
+        sa.Column("retained_events_max", sa.BigInteger, nullable=False, server_default=str(retained_events)),
+        sa.Column("retained_bytes_max", sa.BigInteger, nullable=False, server_default=str(retained_bytes)),
+    ]
+
+
+def _bucket(name: str, per_s: float, burst: int) -> list[sa.Column]:
+    """A token bucket: its rate, its burst, and its tokens (full to start)."""
+    return [
+        sa.Column(f"{name}_per_s", sa.Float, nullable=False, server_default=str(per_s)),
+        sa.Column(f"{name}_burst", sa.BigInteger, nullable=False, server_default=str(burst)),
+        sa.Column(f"{name}_tokens", sa.Float, nullable=False, server_default=str(burst)),
+    ]
+
+
+RECORD = r"""
+CREATE FUNCTION record_inbound_events(
+    p_endpoint uuid, p_refusal text, p_bytes_read bigint, p_ids uuid[], p_sealed bytea[], p_key_versions integer[],
+    p_dedupe bytea[], p_digests bytea[]
+) RETURNS jsonb
+LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+DECLARE
+    v_environment text;
+    v_tenant uuid;
+    v_status text;
+    e public.webhook_endpoints%ROWTYPE;
+    c public.tenant_event_counters%ROWTYPE;
+    v_n integer := coalesce(cardinality(p_ids), 0);
+    v_refusal text := p_refusal;
+    v_sealed bigint := 0;
+    v_bytes bigint;
+    v_events integer;
+    v_now timestamptz;
+    v_wait double precision;
+    v_new integer[] := '{}';
+    v_new_bytes bigint := 0;
+    v_duplicates integer := 0;
+    v_found bytea;
+    v_seen boolean;
+    i integer;
+    j integer;
+BEGIN
+    SELECT environment INTO v_environment FROM public.platform_settings WHERE id = 1;
+    IF v_environment IS DISTINCT FROM 'development' THEN  -- a gated prototype until 2b-4 (the owner's ruling 8)
+        RETURN jsonb_build_object('outcome', 'environment');
+    END IF;
+    SELECT tenant_id INTO v_tenant FROM public.webhook_endpoints WHERE id = p_endpoint;  -- an endpoint's never changes
+    IF NOT FOUND THEN
+        RETURN jsonb_build_object('outcome', 'unknown');
+    END IF;
+    -- The lock order: the tenant's lifecycle lock (shared), the endpoint's row, the tenant's counter row.
+    PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:tenant:' || v_tenant::text, 0));
+    SELECT * INTO e FROM public.webhook_endpoints WHERE id = p_endpoint FOR UPDATE;
+    SELECT status INTO v_status FROM public.tenants WHERE id = v_tenant;
+    IF NOT e.enabled OR v_status IS DISTINCT FROM 'active' THEN
+        RETURN jsonb_build_object('outcome', 'unknown');
+    END IF;
+    INSERT INTO public.tenant_event_counters (tenant_id) VALUES (v_tenant) ON CONFLICT (tenant_id) DO NOTHING;
+    SELECT * INTO c FROM public.tenant_event_counters WHERE tenant_id = v_tenant FOR UPDATE;
+
+    -- The attempt's shape, checked here whatever the caller says (the owner's M1 check).
+    IF v_refusal IS NULL THEN
+        IF v_n = 0 OR v_n > 500
+            OR cardinality(p_sealed) IS DISTINCT FROM v_n OR cardinality(p_key_versions) IS DISTINCT FROM v_n
+            OR cardinality(p_dedupe) IS DISTINCT FROM v_n OR cardinality(p_digests) IS DISTINCT FROM v_n THEN
+            v_refusal := 'malformed';
+        ELSIF EXISTS (SELECT 1 FROM unnest(p_ids, p_sealed, p_key_versions, p_dedupe, p_digests) AS x(id, s, v, d, g)
+                      WHERE x.id IS NULL OR x.s IS NULL OR x.v IS NULL OR (x.d IS NULL) <> (x.g IS NULL)
+                         OR octet_length(x.d) <> 32 OR octet_length(x.g) <> 32
+                         OR x.v NOT IN (SELECT k.version FROM public.tenant_event_keys k WHERE k.tenant_id = v_tenant))
+              OR (SELECT count(DISTINCT x) FROM unnest(p_ids) AS x) <> v_n THEN
+            v_refusal := 'malformed';
+        ELSE
+            SELECT coalesce(sum(octet_length(x)), 0) INTO v_sealed FROM unnest(p_sealed) AS x;
+            -- Canonical bytes are at most 4.5 times the raw body (a float like `1e15` grows to
+            -- `1000000000000000.0`), and sealing adds 65 bytes an event: every permitted body fits.
+            IF v_sealed > 5 * e.body_limit::bigint + 128 * v_n THEN
+                v_refusal := 'too_large';
+            END IF;
+        END IF;
+    ELSIF v_refusal NOT IN ('too_large', 'malformed') THEN
+        v_refusal := 'malformed';
+    END IF;
+    v_bytes := greatest(coalesce(p_bytes_read, 0), v_sealed, 0);
+    v_events := CASE WHEN v_refusal IS NULL THEN v_n ELSE 0 END;
+
+    -- The rate limits, by the clock as it is now, after the locks: refill, then spend before deciding anything else,
+    -- and keep what's spent.
+    v_now := clock_timestamp();
+    e.request_tokens := least(e.request_burst, e.request_tokens + e.request_per_s * extract(epoch FROM v_now - e.refilled_at));
+    e.event_tokens := least(e.event_burst, e.event_tokens + e.event_per_s * extract(epoch FROM v_now - e.refilled_at));
+    e.byte_tokens := least(e.byte_burst, e.byte_tokens + e.byte_per_s * extract(epoch FROM v_now - e.refilled_at));
+    c.event_tokens := least(c.event_burst, c.event_tokens + c.event_per_s * extract(epoch FROM v_now - c.refilled_at));
+    c.byte_tokens := least(c.byte_burst, c.byte_tokens + c.byte_per_s * extract(epoch FROM v_now - c.refilled_at));
+    v_wait := greatest(
+        (1 - e.request_tokens) / e.request_per_s,
+        (v_events - e.event_tokens) / e.event_per_s,
+        (v_bytes - e.byte_tokens) / e.byte_per_s,
+        (v_events - c.event_tokens) / c.event_per_s,
+        (v_bytes - c.byte_tokens) / c.byte_per_s,
+        0
+    );
+    IF v_wait > 0 THEN  -- short of a token: nothing spent, only the refill kept
+        UPDATE public.webhook_endpoints SET request_tokens = e.request_tokens, event_tokens = e.event_tokens,
+            byte_tokens = e.byte_tokens, refilled_at = v_now WHERE id = p_endpoint;
+        UPDATE public.tenant_event_counters SET event_tokens = c.event_tokens, byte_tokens = c.byte_tokens,
+            refilled_at = v_now WHERE tenant_id = v_tenant;
+        RETURN jsonb_build_object('outcome', 'rate_limited', 'retry_after', greatest(1, ceil(v_wait))::integer);
+    END IF;
+    UPDATE public.webhook_endpoints SET request_tokens = e.request_tokens - 1, event_tokens = e.event_tokens - v_events,
+        byte_tokens = e.byte_tokens - v_bytes, refilled_at = v_now WHERE id = p_endpoint;
+    UPDATE public.tenant_event_counters SET event_tokens = c.event_tokens - v_events,
+        byte_tokens = c.byte_tokens - v_bytes, refilled_at = v_now WHERE tenant_id = v_tenant;
+    IF v_refusal IS NOT NULL THEN
+        RETURN jsonb_build_object('outcome', v_refusal);
+    END IF;
+
+    -- Duplicates and reused ids: a plain read of committed events (ingress never locks an existing event row).
+    FOR i IN 1 .. v_n LOOP
+        IF p_dedupe[i] IS NULL THEN
+            v_new := v_new || i;
+            CONTINUE;
+        END IF;
+        v_seen := false;
+        FOR j IN 1 .. i - 1 LOOP
+            IF p_dedupe[j] = p_dedupe[i] THEN
+                IF p_digests[j] <> p_digests[i] THEN
+                    RETURN jsonb_build_object('outcome', 'event_id_reused');
+                END IF;
+                v_seen := true;
+                EXIT;
+            END IF;
+        END LOOP;
+        IF v_seen THEN
+            v_duplicates := v_duplicates + 1;
+            CONTINUE;
+        END IF;
+        SELECT content_digest INTO v_found FROM public.inbound_events
+         WHERE tenant_id = v_tenant AND endpoint_id = p_endpoint AND dedupe_key = p_dedupe[i];
+        IF FOUND THEN
+            IF v_found <> p_digests[i] THEN
+                RETURN jsonb_build_object('outcome', 'event_id_reused');
+            END IF;
+            v_duplicates := v_duplicates + 1;
+        ELSE
+            v_new := v_new || i;
+        END IF;
+    END LOOP;
+    SELECT coalesce(sum(octet_length(p_sealed[k])), 0) INTO v_new_bytes FROM unnest(v_new) AS k;
+
+    -- The retained caps first (nothing frees them before 2b-4), then the pending quotas; duplicates bypass both.
+    IF e.retained_events + cardinality(v_new) > e.retained_events_max OR e.retained_bytes + v_new_bytes > e.retained_bytes_max
+        OR c.retained_events + cardinality(v_new) > c.retained_events_max OR c.retained_bytes + v_new_bytes > c.retained_bytes_max THEN
+        RETURN jsonb_build_object('outcome', 'retained_full');
+    END IF;
+    IF e.pending_events + cardinality(v_new) > e.pending_events_max OR e.pending_bytes + v_new_bytes > e.pending_bytes_max
+        OR c.pending_events + cardinality(v_new) > c.pending_events_max OR c.pending_bytes + v_new_bytes > c.pending_bytes_max THEN
+        RETURN jsonb_build_object('outcome', 'quota_exceeded', 'retry_after', 30);
+    END IF;
+
+    INSERT INTO public.inbound_events (id, tenant_id, endpoint_id, dedupe_key, content_digest, key_version, sealed, size_bytes)
+    SELECT p_ids[k], v_tenant, p_endpoint, p_dedupe[k], p_digests[k], p_key_versions[k], p_sealed[k], octet_length(p_sealed[k])
+      FROM unnest(v_new) AS k;
+    UPDATE public.webhook_endpoints SET pending_events = pending_events + cardinality(v_new),
+        pending_bytes = pending_bytes + v_new_bytes, retained_events = retained_events + cardinality(v_new),
+        retained_bytes = retained_bytes + v_new_bytes WHERE id = p_endpoint;
+    UPDATE public.tenant_event_counters SET pending_events = pending_events + cardinality(v_new),
+        pending_bytes = pending_bytes + v_new_bytes, retained_events = retained_events + cardinality(v_new),
+        retained_bytes = retained_bytes + v_new_bytes WHERE tenant_id = v_tenant;
+    RETURN jsonb_build_object('outcome', 'recorded', 'accepted', cardinality(v_new), 'duplicates', v_duplicates);
+END
+$$"""
+
+RESOLVE = """
+CREATE FUNCTION resolve_webhook_endpoint(p_endpoint uuid)
+RETURNS TABLE (
+    tenant_id uuid, enabled boolean, tenant_active boolean, auth_kind text, bearer_digest bytea, hmac_secret bytea,
+    signature_header text, timestamp_header text, tolerance_s integer, allowlist cidr[], body_limit integer,
+    id_source text, id_pointer text, id_header text, events_pointer text, dedupe_key bytea, key_version integer,
+    public_key bytea
+)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+    SELECT e.tenant_id, e.enabled, t.status = 'active', e.auth_kind, e.bearer_digest, e.hmac_secret,
+           e.signature_header, e.timestamp_header, e.tolerance_s, e.allowlist, e.body_limit, e.id_source,
+           e.id_pointer, e.id_header, e.events_pointer, e.dedupe_key, k.version, k.public_key
+      FROM public.webhook_endpoints e
+      JOIN public.tenants t ON t.id = e.tenant_id
+      LEFT JOIN LATERAL (
+          SELECT version, public_key FROM public.tenant_event_keys
+           WHERE tenant_event_keys.tenant_id = e.tenant_id ORDER BY version DESC LIMIT 1
+      ) k ON true
+     WHERE e.id = p_endpoint
+$$"""
+
+ENVIRONMENT = """
+CREATE FUNCTION ingress_environment() RETURNS text
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+    SELECT environment FROM public.platform_settings WHERE id = 1
+$$"""
+
+FUNCTIONS = (
+    "ingress_environment()",
+    "resolve_webhook_endpoint(uuid)",
+    "record_inbound_events(uuid, text, bigint, uuid[], bytea[], integer[], bytea[], bytea[])",
+)
+TABLES = ("webhook_endpoints", "tenant_event_counters", "trigger_bindings", "inbound_events")
+
+
+def upgrade() -> None:
+    op.create_unique_constraint("workflows_tenant", "workflows", ["id", "tenant_id"])  # for a binding's workflow
+    op.create_table(
+        "webhook_endpoints",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        sa.Column("name", sa.Text, nullable=False),
+        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
+        sa.Column("auth_kind", sa.String(16), nullable=False),
+        sa.Column("bearer_digest", sa.LargeBinary, nullable=True),
+        sa.Column("hmac_secret", sa.LargeBinary, nullable=True),  # sealed under the ingress key
+        sa.Column("signature_header", sa.Text, nullable=True),
+        sa.Column("timestamp_header", sa.Text, nullable=True),
+        sa.Column("tolerance_s", sa.Integer, nullable=False, server_default="300"),
+        sa.Column("allowlist", pg.ARRAY(pg.CIDR), nullable=False, server_default="{}"),  # empty: any address
+        sa.Column("body_limit", sa.Integer, nullable=False, server_default=str(MIB)),
+        sa.Column("id_source", sa.String(16), nullable=False, server_default="none"),
+        sa.Column("id_pointer", sa.Text, nullable=True),
+        sa.Column("id_header", sa.Text, nullable=True),
+        sa.Column("events_pointer", sa.Text, nullable=True),  # none: the body is one event
+        sa.Column("dedupe_key", sa.LargeBinary, nullable=False),  # sealed under the ingress key
+        *_bucket("request", 20, 100),
+        *_bucket("event", 200, 1000),
+        *_bucket("byte", 2 * MIB, 10 * MIB),
+        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        *_counters(),
+        *_quotas(10_000, 64 * MIB, 100_000, 512 * MIB),
+        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.UniqueConstraint("id", "tenant_id", name="webhook_endpoints_tenant"),
+        sa.CheckConstraint("auth_kind IN ('bearer', 'hmac')", name="webhook_endpoints_auth_kind"),
+        sa.CheckConstraint("(auth_kind = 'bearer') = (bearer_digest IS NOT NULL)", name="webhook_endpoints_bearer"),
+        sa.CheckConstraint(
+            "(auth_kind = 'hmac') = (hmac_secret IS NOT NULL AND signature_header IS NOT NULL "
+            "AND timestamp_header IS NOT NULL)",
+            name="webhook_endpoints_hmac",
+        ),
+        sa.CheckConstraint("tolerance_s BETWEEN 60 AND 900", name="webhook_endpoints_tolerance"),
+        sa.CheckConstraint(f"body_limit BETWEEN 1 AND {MAX_BODY_BYTES}", name="webhook_endpoints_body_limit"),
+        sa.CheckConstraint("id_source IN ('pointer', 'header', 'none')", name="webhook_endpoints_id_source"),
+        sa.CheckConstraint("(id_source = 'pointer') = (id_pointer IS NOT NULL)", name="webhook_endpoints_id_pointer"),
+        sa.CheckConstraint("(id_source = 'header') = (id_header IS NOT NULL)", name="webhook_endpoints_id_header"),
+        sa.CheckConstraint(
+            "request_per_s > 0 AND event_per_s > 0 AND byte_per_s > 0 AND request_burst >= 1",
+            name="webhook_endpoints_rates",
+        ),
+        # A burst below the largest charge an endpoint permits would refuse that request for ever: 500 events, and the
+        # larger of the backstop's largest sealed batch (five times the body limit, plus 128 bytes for each of 500
+        # events) and the largest body ingress reads before it authenticates, the global cap (MAX_BODY_BYTES): a body
+        # past a small limit is refused, and pays, for every byte read (the owner's M2 review).
+        sa.CheckConstraint(
+            f"event_burst >= 500 AND byte_burst >= greatest(5 * body_limit::bigint + {128 * 500}, {MAX_BODY_BYTES})",
+            name="webhook_endpoints_bursts",
+        ),
+        sa.CheckConstraint(
+            "pending_events >= 0 AND pending_bytes >= 0 AND retained_events >= 0 AND retained_bytes >= 0",
+            name="webhook_endpoints_counters",
+        ),
+    )
+    op.create_table(
+        "tenant_event_counters",
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
+        *_bucket("event", 1000, 5000),
+        *_bucket("byte", 10 * MIB, 50 * MIB),
+        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        *_counters(),
+        *_quotas(50_000, 256 * MIB, 250_000, 1024 * MIB),
+        sa.CheckConstraint(  # the largest charge any endpoint permits (its body limit at most 5 MiB)
+            f"event_per_s > 0 AND byte_per_s > 0 AND event_burst >= 500 "
+            f"AND byte_burst >= {5 * MAX_BODY_BYTES + 128 * 500}",
+            name="tenant_event_counters_bursts",
+        ),
+        sa.CheckConstraint(
+            "pending_events >= 0 AND pending_bytes >= 0 AND retained_events >= 0 AND retained_bytes >= 0",
+            name="tenant_event_counters_counters",
+        ),
+    )
+    op.create_table(
+        "trigger_bindings",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
+        sa.Column("endpoint_id", pg.UUID(as_uuid=True), nullable=False),
+        sa.Column("workflow_id", pg.UUID(as_uuid=True), nullable=False),
+        sa.Column("filter", pg.JSONB, nullable=False, server_default="[]"),  # typed JSON-pointer equalities, all held
+        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
+        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.ForeignKeyConstraint(
+            ["endpoint_id", "tenant_id"],
+            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
+            name="trigger_bindings_endpoint",
+        ),
+        sa.ForeignKeyConstraint(  # a workflow of the binding's own tenant (the owner's M1 review)
+            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="trigger_bindings_workflow"
+        ),
+        sa.UniqueConstraint("tenant_id", "endpoint_id", "workflow_id", name="trigger_bindings_one"),
+        sa.CheckConstraint(
+            "jsonb_typeof(filter) = 'array' AND jsonb_array_length(filter) <= 8", name="trigger_bindings_filter"
+        ),
+    )
+    op.create_table(
+        "inbound_events",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
+        sa.Column("endpoint_id", pg.UUID(as_uuid=True), nullable=False),
+        sa.Column("dedupe_key", sa.LargeBinary, nullable=True),
+        sa.Column("content_digest", sa.LargeBinary, nullable=True),
+        sa.Column("key_version", sa.Integer, nullable=False),
+        sa.Column("sealed", sa.LargeBinary, nullable=False),
+        sa.Column("size_bytes", sa.Integer, nullable=False),
+        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
+        sa.Column("reason", sa.String(64), nullable=True),
+        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
+        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
+        sa.Column("request_count", sa.Integer, nullable=True),
+        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
+        sa.ForeignKeyConstraint(
+            ["endpoint_id", "tenant_id"],
+            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
+            name="inbound_events_endpoint",
+        ),
+        sa.UniqueConstraint("tenant_id", "endpoint_id", "dedupe_key", name="inbound_events_dedupe"),
+        sa.CheckConstraint(
+            "status IN ('pending', 'matched', 'unmatched', 'cancelled', 'dead')", name="inbound_events_status"
+        ),
+        sa.CheckConstraint("(dedupe_key IS NULL) = (content_digest IS NULL)", name="inbound_events_identity"),
+        sa.CheckConstraint("size_bytes = octet_length(sealed)", name="inbound_events_size"),
+        sa.CheckConstraint("(status = 'pending') = (ended_at IS NULL)", name="inbound_events_ended"),
+    )
+    op.create_index("inbound_events_pending", "inbound_events", ["tenant_id", "received_at"],
+                    postgresql_where=sa.text("status = 'pending'"))  # fmt: skip
+    statements = [
+        *(
+            statement
+            for table in TABLES
+            for statement in (
+                f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
+                f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
+                f"CREATE POLICY {table}_scope ON {table} TO dewpoint_api, dewpoint_dispatch "
+                "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+            )
+        ),
+        # The API manages endpoints and bindings and reads events; the dispatcher matches. Ingress: no table at all.
+        "GRANT SELECT, INSERT ON webhook_endpoints TO dewpoint_api",
+        "GRANT UPDATE (name, enabled, bearer_digest, hmac_secret, signature_header, timestamp_header, tolerance_s, "
+        "allowlist, body_limit, id_source, id_pointer, id_header, events_pointer, request_per_s, request_burst, "
+        "event_per_s, event_burst, byte_per_s, byte_burst, updated_at) ON webhook_endpoints TO dewpoint_api",
+        "GRANT SELECT ON webhook_endpoints TO dewpoint_dispatch",
+        "GRANT UPDATE (pending_events, pending_bytes, retained_events, retained_bytes) ON webhook_endpoints "
+        "TO dewpoint_dispatch",
+        "GRANT SELECT, INSERT ON tenant_event_counters TO dewpoint_api",
+        "GRANT SELECT ON tenant_event_counters TO dewpoint_dispatch",
+        "GRANT UPDATE (pending_events, pending_bytes, retained_events, retained_bytes) ON tenant_event_counters "
+        "TO dewpoint_dispatch",
+        "GRANT SELECT, INSERT, DELETE ON trigger_bindings TO dewpoint_api",
+        "GRANT UPDATE (filter, enabled) ON trigger_bindings TO dewpoint_api",
+        "GRANT SELECT ON trigger_bindings TO dewpoint_dispatch",
+        "GRANT SELECT ON inbound_events TO dewpoint_api, dewpoint_dispatch",
+        "GRANT UPDATE (status, reason, attempts, next_attempt_at, request_count, ended_at) ON inbound_events "
+        "TO dewpoint_dispatch",
+        ENVIRONMENT,
+        RESOLVE,
+        RECORD,
+        *(
+            statement
+            for function in FUNCTIONS
+            for statement in (
+                f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC",
+                f"GRANT EXECUTE ON FUNCTION {function} TO dewpoint_ingress",
+            )
+        ),
+    ]
+    for statement in statements:
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    for function in reversed(FUNCTIONS):
+        op.execute(f"DROP FUNCTION {function}")
+    for table in reversed(TABLES):
+        op.drop_table(table)
+    op.drop_constraint("workflows_tenant", "workflows")
diff --git a/backend/tests/core/ingress/support.py b/backend/tests/core/ingress/support.py
new file mode 100644
index 0000000..826905a
--- /dev/null
+++ b/backend/tests/core/ingress/support.py
@@ -0,0 +1,82 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's tables in a test: a tenant with its inbound keypair, an endpoint, and calls to the recording function as
+the ingress login."""
+
+import hashlib
+import os
+import uuid
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.crypto.kek import Kek, KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.ingress.keys import ensure_event_key
+
+KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
+RECORD = text(
+    "select record_inbound_events(:e, :refusal, :read, cast(:ids as uuid[]), cast(:sealed as bytea[]), "
+    "cast(:versions as integer[]), cast(:dedupe as bytea[]), cast(:digests as bytea[]))"
+)
+
+
+async def endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
+    """A tenant (with its keypair) and one of its endpoints, a bearer one unless `columns` say otherwise."""
+    tenant, endpoint_id = uuid.uuid4(), uuid.uuid4()
+    async with owner() as s, s.begin():
+        user = (await create_user(s, email=f"{tenant.hex[:10]}@corp.test", password="violet-otter-canyon-42")).id
+        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": tenant, "s": tenant.hex})
+        await ensure_event_key(s, KEYRING, tenant)
+        values = {"auth_kind": "bearer", "bearer_digest": hashlib.sha256(b"token").digest(),
+                  "dedupe_key": b"sealed-dedupe-key"} | columns  # fmt: skip
+        names = ", ".join(values)
+        await s.execute(
+            text(f"insert into webhook_endpoints (id, tenant_id, name, created_by, {names}) "  # noqa: S608
+                 f"values (:id, :t, 'hooks', :u, {', '.join(':' + k for k in values)})"),
+            {"id": endpoint_id, "t": tenant, "u": user} | values,
+        )  # fmt: skip
+    return tenant, endpoint_id
+
+
+def key(n: int) -> bytes:
+    return hashlib.sha256(f"key-{n}".encode()).digest()
+
+
+def digest(n: int) -> bytes:
+    return hashlib.sha256(f"digest-{n}".encode()).digest()
+
+
+async def record(
+    ingress: Any, endpoint_id: uuid.UUID, events: list[tuple[bytes | None, bytes | None, bytes]] | None = None, *,
+    refusal: str | None = None, read: int = 0, versions: list[int] | None = None, ids: list[uuid.UUID] | None = None,
+) -> dict[str, Any]:  # fmt: skip
+    """The recording function's outcome for `events`, each (dedupe key, content digest, sealed bytes), committed."""
+    given = events or []
+    params = {
+        "e": endpoint_id, "refusal": refusal, "read": read,
+        "ids": ids if ids is not None else [uuid.uuid4() for _ in given],
+        "sealed": [sealed for _, _, sealed in given], "versions": versions or [1] * len(given),
+        "dedupe": [dedupe for dedupe, _, _ in given], "digests": [d for _, d, _ in given],
+    }  # fmt: skip
+    async with ingress() as s, s.begin():
+        return dict((await s.execute(RECORD, params)).scalar_one())
+
+
+async def state(owner: Any, endpoint_id: uuid.UUID) -> dict[str, Any]:
+    async with owner() as s:
+        row = (await s.execute(text("select * from webhook_endpoints where id = :e"), {"e": endpoint_id})).mappings()
+        return dict(row.one())
+
+
+async def tenant_state(owner: Any, tenant: uuid.UUID) -> dict[str, Any]:
+    async with owner() as s:
+        found = await s.execute(text("select * from tenant_event_counters where tenant_id = :t"), {"t": tenant})
+        return dict(found.mappings().one())
+
+
+async def events_of(owner: Any, endpoint_id: uuid.UUID) -> list[dict[str, Any]]:
+    async with owner() as s:
+        found = await s.execute(text("select * from inbound_events where endpoint_id = :e order by received_at, id"),
+                                {"e": endpoint_id})  # fmt: skip
+        return [dict(r) for r in found.mappings()]
diff --git a/backend/tests/core/ingress/test_ingress_guard.py b/backend/tests/core/ingress/test_ingress_guard.py
new file mode 100644
index 0000000..5bad88a
--- /dev/null
+++ b/backend/tests/core/ingress/test_ingress_guard.py
@@ -0,0 +1,23 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress stays a development-only prototype until 2b-4 (the owner's rulings 8 and 13): the recording function records
+nothing unless the recorded environment is `development`, absent included, whatever the process checked."""
+
+from sqlalchemy import text
+
+from dewpoint.core.platform.service import PRODUCTION, record_environment
+from tests.core.ingress.support import digest, endpoint, events_of, key, record
+
+
+async def test_without_a_recorded_environment_nothing_is_recorded(owner_sessionmaker, ingress_sessionmaker) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "environment"}
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+async def test_in_production_nothing_is_recorded(owner_sessionmaker, ingress_sessionmaker) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "environment"}
+    async with ingress_sessionmaker() as s:
+        assert (await s.execute(text("select ingress_environment()"))).scalar_one() == "production"
diff --git a/backend/tests/core/ingress/test_ingress_schema.py b/backend/tests/core/ingress/test_ingress_schema.py
new file mode 100644
index 0000000..ed8e772
--- /dev/null
+++ b/backend/tests/core/ingress/test_ingress_schema.py
@@ -0,0 +1,146 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's tables and functions (engine 2b spec §8.3, §14; the owner's rulings 3 and 8 on the 2b-3b outline): every
+table under forced row-level security; ingress holding **no table privilege**, only `EXECUTE` on its three SECURITY
+DEFINER functions, each with a pinned `search_path` and closed to everyone else; an event and a binding belonging to
+their endpoint's tenant by a foreign key; one binding per endpoint and workflow."""
+
+import uuid
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError, IntegrityError
+
+from dewpoint.core.db import tenant_scope
+from tests.core.ingress.support import endpoint
+from tests.support.workflows import seed_workflow
+
+TABLES = ("webhook_endpoints", "trigger_bindings", "inbound_events", "tenant_event_counters")
+FUNCTIONS = (
+    "ingress_environment()",
+    "resolve_webhook_endpoint(uuid)",
+    "record_inbound_events(uuid, text, bigint, uuid[], bytea[], integer[], bytea[], bytea[])",
+)
+ROLES = ("dewpoint_api", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin", "dewpoint_auditor")
+
+
+async def test_ingress_tables_force_row_level_security(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        rows = (await s.execute(text("select relname, relrowsecurity and relforcerowsecurity from pg_class "
+                                     "where relname = any(:t)"), {"t": list(TABLES)})).all()  # fmt: skip
+    assert sorted(rows) == sorted((t, True) for t in TABLES)
+
+
+async def test_ingress_has_no_table_privilege_at_all(owner_sessionmaker, ingress_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        granted = (await s.execute(text(
+            "select table_name, privilege_type from information_schema.role_table_grants "
+            "where grantee = 'dewpoint_ingress'"
+        ))).all()  # fmt: skip
+    assert granted == []
+    for table in (*TABLES, "tenant_event_keys", "platform_settings", "tenants", "data_keys", "run_requests"):
+        with pytest.raises(DBAPIError, match="permission denied"):
+            async with ingress_sessionmaker() as s:
+                await s.execute(text(f"select 1 from {table} limit 1"))  # noqa: S608
+
+
+async def test_only_ingress_executes_its_functions(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        for function in FUNCTIONS:
+            allowed = text("select has_function_privilege(:r, :f, 'EXECUTE')")
+            assert (await s.execute(allowed, {"r": "dewpoint_ingress", "f": function})).scalar_one() is True
+            for role in ROLES:
+                assert (await s.execute(allowed, {"r": role, "f": function})).scalar_one() is False, (role, function)
+            acl = (await s.execute(text("select proacl::text from pg_proc where oid = cast(:f as regprocedure)"),
+                                   {"f": function})).scalar_one()  # fmt: skip
+            assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))  # no grant to PUBLIC
+
+
+async def test_the_functions_are_definers_with_a_pinned_search_path(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        for function in FUNCTIONS:
+            query = text("select prosecdef, proconfig from pg_proc where oid = cast(:f as regprocedure)")
+            found = await s.execute(query, {"f": function})
+            assert tuple(found.one()) == (True, ["search_path=public, pg_temp"])
+
+
+async def test_an_event_and_a_binding_belong_to_their_endpoints_tenant(owner_sessionmaker) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    other, _ = await endpoint(owner_sessionmaker)
+    _, workflow, _ = await seed_workflow(owner_sessionmaker)
+    for statement, params in (
+        ("insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes) "
+         "values (:i, :t, :e, 1, '\\x01', 1)", {}),
+        ("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
+         "select :i, :t, :e, :w, created_by from webhook_endpoints where id = :e", {"w": workflow}),
+    ):  # fmt: skip
+        with pytest.raises(IntegrityError):
+            async with owner_sessionmaker() as s, s.begin():
+                await s.execute(text(statement), {"i": uuid.uuid4(), "t": other, "e": endpoint_id} | params)
+
+
+async def test_one_binding_per_endpoint_and_workflow(owner_sessionmaker) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
+                                {"e": endpoint_id})).scalar_one()  # fmt: skip
+        workflow = uuid.uuid4()
+        await s.execute(text("insert into workflows(id,tenant_id,name,enabled,draft) values (:w,:t,'W',true,'{}')"),
+                        {"w": workflow, "t": tenant})  # fmt: skip
+        insert = text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
+                      "values (:i, :t, :e, :w, :u)")  # fmt: skip
+        await s.execute(insert, {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": workflow, "u": user})
+    with pytest.raises(IntegrityError):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(insert, {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": workflow, "u": user})
+
+
+async def test_the_api_and_the_dispatcher_see_ingress_rows_within_their_tenant_only(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    for maker in (api_sessionmaker, dispatch_sessionmaker):
+        for scope, seen in ((tenant, 1), (uuid.uuid4(), 0)):
+            async with maker() as s, s.begin():
+                await tenant_scope(s, scope)
+                found = await s.execute(
+                    text("select count(*) from webhook_endpoints where id = :e"), {"e": endpoint_id}
+                )
+                assert found.scalar_one() == seen
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_the_resolver_returns_what_ingress_decides_with_and_nothing_for_another_id(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    async with ingress_sessionmaker() as s:
+        found = (await s.execute(text("select * from resolve_webhook_endpoint(:e)"), {"e": endpoint_id})).mappings()
+        row = dict(found.one())
+        unknown = (await s.execute(text("select * from resolve_webhook_endpoint(:e)"), {"e": uuid.uuid4()})).all()
+        environment = (await s.execute(text("select ingress_environment()"))).scalar_one()
+    assert (row["tenant_id"], row["enabled"], row["tenant_active"], row["auth_kind"]) == (tenant, True, True, "bearer")
+    assert (row["key_version"], len(row["public_key"]), row["body_limit"], row["id_source"]) == (1, 32, 1048576, "none")
+    assert unknown == [] and environment == "development"
+
+
+async def test_without_a_recorded_environment_ingress_reads_none(ingress_sessionmaker) -> None:
+    async with ingress_sessionmaker() as s:
+        assert (await s.execute(text("select ingress_environment()"))).scalar_one() is None
+
+
+async def test_a_binding_cant_point_to_another_tenants_workflow(owner_sessionmaker, api_sessionmaker) -> None:
+    """The owner's M1 review: a binding's workflow belongs to its tenant, by a foreign key, so not even the API's own
+    insert, scoped to its tenant, can bind another tenant's workflow."""
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    _, foreign, _ = await seed_workflow(owner_sessionmaker)
+    async with owner_sessionmaker() as s:
+        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
+                                {"e": endpoint_id})).scalar_one()  # fmt: skip
+    with pytest.raises(IntegrityError):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(
+                text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
+                     "values (:i, :t, :e, :w, :u)"),
+                {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": foreign, "u": user},
+            )  # fmt: skip
diff --git a/backend/tests/core/ingress/test_recording.py b/backend/tests/core/ingress/test_recording.py
new file mode 100644
index 0000000..fca47d5
--- /dev/null
+++ b/backend/tests/core/ingress/test_recording.py
@@ -0,0 +1,313 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`record_inbound_events`, ingress's privileged boundary (engine 2b spec §8.3; the owner's rulings and second review on
+the 2b-3b outline). Under the tenant's lifecycle lock (shared), the endpoint's row and then the tenant's counter row,
+it spends the rate budget first and commits it whatever it decides; it checks the batch itself (its count, its actual
+sealed bytes, its shape), never trusting the caller's sizes; it acknowledges a duplicate and refuses an id reused for
+other content; it applies the pending quotas and the retained caps; and it inserts events all or nothing. It never
+raises for a refusal: it returns the outcome."""
+
+import asyncio
+import json
+import uuid
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import IntegrityError
+
+from dewpoint.core.crypto import events
+from dewpoint.core.ingress import identity
+from tests.core.ingress.support import digest, endpoint, events_of, key, record, state, tenant_state
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def test_events_are_recorded_pending_and_counted(owner_sessionmaker, ingress_sessionmaker) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    before = await state(owner_sessionmaker, endpoint_id)
+    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"a" * 70), (None, None, b"b" * 80)],
+                           read=200)  # fmt: skip
+    assert outcome == {"outcome": "recorded", "accepted": 2, "duplicates": 0}
+    rows = await events_of(owner_sessionmaker, endpoint_id)
+    assert sorted((r["status"], r["size_bytes"], r["tenant_id"]) for r in rows) == [
+        ("pending", 70, tenant), ("pending", 80, tenant)
+    ]  # fmt: skip
+    after, counters = await state(owner_sessionmaker, endpoint_id), await tenant_state(owner_sessionmaker, tenant)
+    assert (after["pending_events"], after["pending_bytes"], after["retained_events"], after["retained_bytes"]) == (
+        2, 150, 2, 150
+    )  # fmt: skip
+    assert (counters["pending_events"], counters["retained_bytes"]) == (2, 150)
+    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
+    assert before["event_tokens"] - after["event_tokens"] == pytest.approx(2, abs=1)
+    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(200, abs=50)
+
+
+async def test_a_duplicate_is_acknowledged_and_an_id_reused_for_other_content_refuses_the_batch(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, request_per_s=0.001, event_per_s=0.001)  # no refill to speak of
+    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    again = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one"), (key(2), digest(2), b"two")])
+    assert again == {"outcome": "recorded", "accepted": 1, "duplicates": 1}
+    before = await state(owner_sessionmaker, endpoint_id)
+    reused = await record(ingress_sessionmaker, endpoint_id, [(key(3), digest(3), b"three"), (key(1), digest(9), b"x")])
+    assert reused == {"outcome": "event_id_reused"}
+    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # the batch recorded nothing, key 3 included
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)  # it paid its budget
+    assert before["event_tokens"] - after["event_tokens"] == pytest.approx(2, abs=1)
+
+
+async def test_within_one_batch_a_repeated_id_is_a_duplicate_or_a_reuse(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    same = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one"), (key(1), digest(1), b"one")])
+    assert same == {"outcome": "recorded", "accepted": 1, "duplicates": 1}
+    other = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two"), (key(2), digest(3), b"t")])
+    assert other == {"outcome": "event_id_reused"}
+
+
+async def test_events_without_ids_are_each_their_own(owner_sessionmaker, ingress_sessionmaker) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    twice = await record(ingress_sessionmaker, endpoint_id, [(None, None, b"same"), (None, None, b"same")])
+    assert twice == {"outcome": "recorded", "accepted": 2, "duplicates": 0}
+
+
+@pytest.mark.parametrize("refusal", ["too_large", "malformed"])
+async def test_a_refusal_made_after_authentication_pays_its_request_and_its_bytes(
+    owner_sessionmaker, ingress_sessionmaker, refusal: str
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    before = await state(owner_sessionmaker, endpoint_id)
+    assert await record(ingress_sessionmaker, endpoint_id, refusal=refusal, read=5000) == {"outcome": refusal}
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
+    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(5000, abs=100)
+    assert after["event_tokens"] == pytest.approx(before["event_tokens"], abs=1)
+
+
+async def test_short_of_tokens_an_attempt_spends_nothing_and_says_how_long_to_wait(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=0, request_per_s=0.5)
+    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    assert outcome["outcome"] == "rate_limited" and 1 <= outcome["retry_after"] <= 2
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+async def test_repeated_refusals_exhaust_the_bucket_as_accepted_requests_do(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=3, request_burst=3, request_per_s=0.01)
+    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    outcomes = [
+        (await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(2), b"x")]))["outcome"] for _ in range(3)
+    ]
+    assert outcomes == ["event_id_reused", "event_id_reused", "rate_limited"]
+
+
+async def test_a_pending_quota_refuses_new_events_but_not_a_duplicate(owner_sessionmaker, ingress_sessionmaker) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, pending_events_max=1)
+    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    full = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two")])
+    assert full == {"outcome": "quota_exceeded", "retry_after": 30}
+    duplicate = await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    assert duplicate == {"outcome": "recorded", "accepted": 0, "duplicates": 1}
+
+
+@pytest.mark.parametrize("column", ["retained_events_max", "retained_bytes_max"])
+async def test_a_full_retained_cap_fails_closed_without_a_retry_time(
+    owner_sessionmaker, ingress_sessionmaker, column: str
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, **{column: 4})
+    await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")])
+    if column == "retained_events_max":
+        async with owner_sessionmaker() as s, s.begin():  # matched since: no longer pending, still retained
+            await s.execute(text("update webhook_endpoints set pending_events = 0, retained_events = 4 where id = :e"),
+                            {"e": endpoint_id})  # fmt: skip
+    outcome = await record(ingress_sessionmaker, endpoint_id, [(key(2), digest(2), b"two")])
+    assert outcome == {"outcome": "retained_full"}
+
+
+async def test_the_tenants_counters_and_quotas_apply_across_its_endpoints(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    tenant, first = await endpoint(owner_sessionmaker)
+    await record(ingress_sessionmaker, first, [(key(1), digest(1), b"one")])
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenant_event_counters set pending_events_max = 1 where tenant_id = :t"),
+                        {"t": tenant})  # fmt: skip
+        second = uuid.uuid4()
+        copy = text(
+            "insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, bearer_digest, dedupe_key) "
+            "select :n, tenant_id, 'other', created_by, auth_kind, bearer_digest, dedupe_key "
+            "from webhook_endpoints where id = :e"
+        )
+        await s.execute(copy, {"n": second, "e": first})
+    assert await record(ingress_sessionmaker, second, [(key(2), digest(2), b"two")]) == {
+        "outcome": "quota_exceeded", "retry_after": 30
+    }  # fmt: skip
+
+
+async def test_the_function_checks_the_batch_itself_whatever_its_caller_says(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    """The owner's M1 check: called directly as the ingress login, an oversized or misshapen batch records nothing,
+    and sizes are the sealed bytes' own, never the caller's."""
+    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000)
+    one = [(key(1), digest(1), b"x")]
+    for given, kwargs, expected in (
+        ([(None, None, b"x")] * 501, {}, "malformed"),  # past 500 events
+        ([(None, None, b"x" * 5200)], {}, "too_large"),  # past five times the body limit, plus 128 bytes an event
+        (one, {"versions": [2]}, "malformed"),  # a keypair version the tenant doesn't have
+        (one, {"versions": [1, 1]}, "malformed"),  # arrays that don't line up
+        ([(key(1), None, b"x")], {}, "malformed"),  # a dedupe key without its digest
+        ([(b"short", digest(1), b"x")], {}, "malformed"),  # a digest that isn't 32 bytes
+        ([(None, None, b"x"), (None, None, b"y")], {"ids": [uuid.UUID(int=7)] * 2}, "malformed"),  # one id twice
+        ([], {}, "malformed"),  # no events and no refusal
+    ):
+        assert await record(ingress_sessionmaker, endpoint_id, given, **kwargs) == {"outcome": expected}
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+    before = await state(owner_sessionmaker, endpoint_id)
+    await record(ingress_sessionmaker, endpoint_id, [(None, None, b"z" * 900)], read=1)  # understating what it read
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert before["byte_tokens"] - after["byte_tokens"] == pytest.approx(900, abs=100)  # the sealed bytes' own size
+    assert (await events_of(owner_sessionmaker, endpoint_id))[0]["size_bytes"] == 900
+
+
+@pytest.mark.parametrize("change", ["update webhook_endpoints set enabled = false where id = :e",
+                                    "update tenants set status = 'erasing' where id = :t"])  # fmt: skip
+async def test_a_disabled_endpoint_or_an_erasing_tenant_records_and_spends_nothing(
+    owner_sessionmaker, ingress_sessionmaker, change: str
+) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text(change), {"e": endpoint_id, "t": tenant})
+    before = await state(owner_sessionmaker, endpoint_id)
+    assert await record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]) == {"outcome": "unknown"}
+    assert (await state(owner_sessionmaker, endpoint_id))["request_tokens"] == before["request_tokens"]
+    assert await record(ingress_sessionmaker, uuid.uuid4(), [(key(1), digest(1), b"one")]) == {"outcome": "unknown"}
+
+
+async def lock_waiters(owner) -> int:
+    async with owner() as s:
+        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
+                    ).scalar_one())  # fmt: skip
+
+
+async def test_a_tenant_marked_erasing_first_is_refused_by_a_recording_that_waited(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    """The owner's second review: ingress holds the tenant's lifecycle lock shared while it records, so marking a tenant
+    `erasing` (2b-4's transition takes that lock exclusively) can't commit between ingress's check and its insert."""
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(
+            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:tenant:{tenant}"}
+        )
+        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": tenant})
+        pending = asyncio.create_task(record(ingress_sessionmaker, endpoint_id, [(key(1), digest(1), b"one")]))
+        for _ in range(300):
+            if await lock_waiters(owner_sessionmaker):
+                break
+            await asyncio.sleep(0.01)
+        else:
+            raise AssertionError("the recording didn't wait for the tenant's lock")
+    assert await pending == {"outcome": "unknown"}
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+async def test_a_recording_holds_the_tenants_lock_until_it_commits(owner_sessionmaker, ingress_sessionmaker) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    lock = text("select pg_advisory_xact_lock(hashtextextended(:k, 0))")
+    async with ingress_sessionmaker() as s, s.begin():
+        from tests.core.ingress.support import RECORD
+
+        params = {"e": endpoint_id, "refusal": None, "read": 0, "ids": [uuid.uuid4()], "sealed": [b"one"],
+                  "versions": [1], "dedupe": [key(1)], "digests": [digest(1)]}  # fmt: skip
+        assert dict((await s.execute(RECORD, params)).scalar_one())["outcome"] == "recorded"
+        with pytest.raises(Exception, match="lock timeout|canceling statement"):
+            async with owner_sessionmaker() as other, other.begin():
+                await other.execute(text("set local lock_timeout = '200ms'"))
+                await other.execute(lock, {"k": f"dewpoint:tenant:{tenant}"})
+    async with owner_sessionmaker() as other, other.begin():  # committed: erasure may proceed, after the insert
+        await other.execute(lock, {"k": f"dewpoint:tenant:{tenant}"})
+    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 1
+
+
+MIB = 1024 * 1024
+
+
+async def test_a_body_whose_canonical_json_grows_is_still_accepted(owner_sessionmaker, ingress_sessionmaker) -> None:
+    """The owner's M1 review: canonical floats grow (`1e15` is `1000000000000000.0`), so a permitted body's sealed
+    bytes may pass twice its size; the backstop is five times the body limit, plus 128 bytes an event."""
+    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000)
+    raw = '{"a":[' + ",".join(["1e15"] * 198) + "]}"
+    assert len(raw) <= 1000
+    sealed = identity.canonical(json.loads(raw)) + bytes(events.OVERHEAD)  # a sealed event's size
+    assert len(sealed) > 2 * 1000 + 128  # what the first backstop refused
+    outcome = await record(ingress_sessionmaker, endpoint_id, [(None, None, sealed)], read=len(raw))
+    assert outcome == {"outcome": "recorded", "accepted": 1, "duplicates": 0}
+
+
+async def test_every_permitted_request_fits_its_bursts(owner_sessionmaker) -> None:
+    """A burst smaller than the largest charge an endpoint permits would refuse such a request for ever: the database
+    refuses that endpoint, and the tenant's bursts cover the largest any endpoint permits. The largest byte charge is
+    the larger of its largest sealed batch (five times its body limit plus 128 bytes for each of 500 events) and the
+    largest body ingress reads before authenticating, the global 5 MiB cap: a body past a small limit is refused, and
+    pays, for every byte read (the owner's M2 review). The largest event charge is 500."""
+    for columns in (
+        {"body_limit": 5 * MIB},
+        {"body_limit": 5 * MIB, "byte_burst": 5 * 5 * MIB + 64_000 - 1},
+        {"body_limit": 1, "byte_burst": 5 * 1 + 64_000},  # its sealed batch fits; a 5 MiB body read doesn't
+        {"body_limit": 1000, "byte_burst": 5 * MIB - 1},
+        {"event_burst": 499},
+    ):
+        with pytest.raises(IntegrityError):
+            await endpoint(owner_sessionmaker, **columns)
+    await endpoint(owner_sessionmaker, body_limit=5 * MIB, byte_burst=5 * 5 * MIB + 64_000)
+    await endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB)
+    tenant, _ = await endpoint(owner_sessionmaker)
+    for change in ("byte_burst = 25 * 1048576", "event_burst = 499"):
+        with pytest.raises(IntegrityError):
+            async with owner_sessionmaker() as s, s.begin():
+                counters = text("insert into tenant_event_counters (tenant_id) values (:t) on conflict do nothing")
+                await s.execute(counters, {"t": tenant})
+                await s.execute(text(f"update tenant_event_counters set {change} where tenant_id = :t"), {"t": tenant})
+
+
+async def test_a_request_at_the_largest_permitted_size_is_recorded_from_a_full_bucket(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1000, byte_burst=5 * MIB, byte_tokens=5 * MIB)
+    largest = [(None, None, b"x" * (5 * 1000 + 128))]  # the backstop's largest for one event
+    assert (await record(ingress_sessionmaker, endpoint_id, largest, read=1000))["outcome"] == "recorded"
+
+
+async def test_a_refusal_of_the_largest_body_read_is_charged_from_a_full_smallest_bucket(
+    owner_sessionmaker, ingress_sessionmaker
+) -> None:
+    """The owner's M2 review: a body as large as the global cap, past a 1-byte limit, is `too_large`, never short of
+    tokens, from the smallest burst the schema allows."""
+    _, endpoint_id = await endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB, byte_tokens=5 * MIB)
+    outcome = await record(ingress_sessionmaker, endpoint_id, refusal="too_large", read=5 * MIB)
+    assert outcome == {"outcome": "too_large"}
+
+
+async def test_the_refill_is_reckoned_from_after_the_locks(owner_sessionmaker, ingress_sessionmaker) -> None:
+    """The owner's M1 review: a recording that waited for its endpoint's row is credited with the time it waited, so
+    contention never throttles it by a stale clock. Empty at half a token a second, it waits 2.5 s and has one."""
+    _, endpoint_id = await endpoint(owner_sessionmaker, request_tokens=0, request_per_s=0.5)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("select 1 from webhook_endpoints where id = :e for update"), {"e": endpoint_id})
+        await s.execute(text("update webhook_endpoints set refilled_at = clock_timestamp() where id = :e"),
+                        {"e": endpoint_id})  # fmt: skip
+        pending = asyncio.create_task(record(ingress_sessionmaker, endpoint_id, [(None, None, b"one")]))
+        for _ in range(300):
+            if await lock_waiters(owner_sessionmaker):
+                break
+            await asyncio.sleep(0.01)
+        else:
+            raise AssertionError("the recording didn't wait for the endpoint's row")
+        await asyncio.sleep(2.5)
+    assert (await pending)["outcome"] == "recorded"
diff --git a/backend/tests/deploy/test_compose.py b/backend/tests/deploy/test_compose.py
index 257bbc4..914dde2 100644
--- a/backend/tests/deploy/test_compose.py
+++ b/backend/tests/deploy/test_compose.py
@@ -16,6 +16,7 @@ ENV = {
     "DEWPOINT_AUDITOR_DB_PASSWORD": "auditor-pw",
     "DEWPOINT_WORKER_DB_PASSWORD": "worker-pw",
     "DEWPOINT_DISPATCH_DB_PASSWORD": "dispatch-pw",
+    "DEWPOINT_INGRESS_DB_PASSWORD": "ingress-pw",
     "DEWPOINT_KEK_B64": "k" * 44,
     "DEWPOINT_AUDIT_SIGNING_KEY_B64": "s" * 44,
     "DEWPOINT_TEMPORAL_NAMESPACE": "dewpoint-ci",
@@ -103,3 +104,16 @@ def test_a_dispatcher_that_exits_is_restarted() -> None:
     """The whole-branch review: a dispatcher process that ends (whatever the cause) comes back, so queued runs keep
     starting once what stopped it recovers."""
     assert service("dispatcher")["restart"] == "unless-stopped"
+
+
+def test_the_database_init_makes_an_ingress_login_from_its_password() -> None:
+    """2b-3b: ingress logs in as `dewpoint_ingress_login`, which a fresh database's init creates in the group role, from
+    `DEWPOINT_INGRESS_DB_PASSWORD`; CI writes one like every other login's."""
+    assert environment("postgres")["DEWPOINT_INGRESS_DB_PASSWORD"] == "ingress-pw"
+    init = (COMPOSE.parent / "initdb" / "10-roles.sh").read_text()
+    assert '-v ingress_pw="$DEWPOINT_INGRESS_DB_PASSWORD"' in init
+    assert "CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD :'ingress_pw' IN ROLE dewpoint_ingress;" in init
+    assert "rolname='dewpoint_ingress') THEN CREATE ROLE dewpoint_ingress NOLOGIN" in init
+    ci = (COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml").read_text()
+    assert 'echo "DEWPOINT_INGRESS_DB_PASSWORD=$(openssl rand -hex 16)"' in ci
+    assert "DEWPOINT_INGRESS_DB_PASSWORD=" in (COMPOSE.parent / ".env.example").read_text()
diff --git a/deploy/compose/.env.example b/deploy/compose/.env.example
index dff9e36..9782536 100644
--- a/deploy/compose/.env.example
+++ b/deploy/compose/.env.example
@@ -5,6 +5,7 @@ DEWPOINT_ADMIN_DB_PASSWORD=   # openssl rand -base64 24  (key-management CLI: de
 DEWPOINT_AUDITOR_DB_PASSWORD= # openssl rand -base64 24  (audit anchor/verify only)
 DEWPOINT_WORKER_DB_PASSWORD=  # openssl rand -base64 24  (the worker: runs and their steps)
 DEWPOINT_DISPATCH_DB_PASSWORD= # openssl rand -base64 24  (starting runs: dewpoint dev run)
+DEWPOINT_INGRESS_DB_PASSWORD= # openssl rand -base64 24  (webhook ingress: no table, three functions)
 DEWPOINT_KEK_B64=             # openssl rand -base64 32
 DEWPOINT_AUDIT_SIGNING_KEY_B64=  # python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
 DEWPOINT_PUBLIC_ORIGIN=http://localhost:8080
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
index 7741576..f991bb9 100644
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -30,6 +30,7 @@ services:
       DEWPOINT_AUDITOR_DB_PASSWORD: ${DEWPOINT_AUDITOR_DB_PASSWORD:?set in .env}
       DEWPOINT_WORKER_DB_PASSWORD: ${DEWPOINT_WORKER_DB_PASSWORD:?set in .env}
       DEWPOINT_DISPATCH_DB_PASSWORD: ${DEWPOINT_DISPATCH_DB_PASSWORD:?set in .env}
+      DEWPOINT_INGRESS_DB_PASSWORD: ${DEWPOINT_INGRESS_DB_PASSWORD:?set in .env}
     volumes: [pgdata:/var/lib/postgresql/data, ./initdb:/docker-entrypoint-initdb.d:ro]
     healthcheck: { test: ["CMD-SHELL", "pg_isready -U dewpoint_owner -d dewpoint"], interval: 5s, retries: 20 }
 
diff --git a/deploy/compose/initdb/10-roles.sh b/deploy/compose/initdb/10-roles.sh
index 0826b51..d4c7d76 100755
--- a/deploy/compose/initdb/10-roles.sh
+++ b/deploy/compose/initdb/10-roles.sh
@@ -4,17 +4,19 @@ set -eu
 psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
   -v api_pw="$DEWPOINT_API_DB_PASSWORD" -v admin_pw="$DEWPOINT_ADMIN_DB_PASSWORD" \
   -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" -v worker_pw="$DEWPOINT_WORKER_DB_PASSWORD" \
-  -v dispatch_pw="$DEWPOINT_DISPATCH_DB_PASSWORD" <<'SQL'
+  -v dispatch_pw="$DEWPOINT_DISPATCH_DB_PASSWORD" -v ingress_pw="$DEWPOINT_INGRESS_DB_PASSWORD" <<'SQL'
 DO $$ BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_api') THEN CREATE ROLE dewpoint_api NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_admin') THEN CREATE ROLE dewpoint_admin NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_worker') THEN CREATE ROLE dewpoint_worker NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_dispatch') THEN CREATE ROLE dewpoint_dispatch NOLOGIN; END IF;
+  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_ingress') THEN CREATE ROLE dewpoint_ingress NOLOGIN; END IF;
 END $$;
 CREATE ROLE dewpoint_api_login LOGIN PASSWORD :'api_pw' IN ROLE dewpoint_api;
 CREATE ROLE dewpoint_admin_login LOGIN PASSWORD :'admin_pw' IN ROLE dewpoint_admin;
 CREATE ROLE dewpoint_auditor_login LOGIN PASSWORD :'auditor_pw' IN ROLE dewpoint_auditor;
 CREATE ROLE dewpoint_worker_login LOGIN PASSWORD :'worker_pw' IN ROLE dewpoint_worker;
 CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD :'dispatch_pw' IN ROLE dewpoint_dispatch;
+CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD :'ingress_pw' IN ROLE dewpoint_ingress;
 SQL
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index cd86635..2d2c89e 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -247,10 +247,12 @@ image has a new engine ABI, publish every workflow again after upgrading (above)
 overlap.
 
 The worker, and the dispatcher and `dewpoint dev run`, log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
-(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
-database predates them creates them once, as the database owner:
+(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`), and webhook ingress as `dewpoint_ingress_login`
+(`DEWPOINT_INGRESS_DB_PASSWORD`), whose role holds no table, only its three functions. A fresh install creates them. An
+install whose database predates them creates them once, as the database owner:
 
 ```sql
 CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
 CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
+CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD '<ingress password>' IN ROLE dewpoint_ingress;
 ```
```

**Checkpoint (milestone 1).** Focused: `tests/core/ingress`, `tests/core/crypto`, `tests/core/tenancy`,
`tests/apps/cli`, `tests/deploy` (144 passed on Task 3's tree); the migrations 0030 → 0032 → 0030 → 0032 over existing
rows. The owner held it once (milestone ruling 1) and approved it as a prototype checkpoint (2026-10-04).

## Milestone 2 — The ingress process

### Task 4: `dewpoint ingress`, a hook's checks, and its events parsed, sealed and recorded

**Commit:** `8319fe3` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/src/dewpoint/apps/ingress/__init__.py`, `backend/src/dewpoint/apps/ingress/addresses.py`,
`backend/src/dewpoint/apps/ingress/auth.py`, `backend/src/dewpoint/apps/ingress/batch.py`,
`backend/src/dewpoint/apps/ingress/config.py`, `backend/src/dewpoint/apps/ingress/endpoints.py`,
`backend/src/dewpoint/apps/ingress/limits.py`, `backend/src/dewpoint/apps/ingress/main.py`,
`backend/src/dewpoint/apps/ingress/recording.py`, `backend/src/dewpoint/core/ingress/parsing.py`,
`backend/src/dewpoint/core/ingress/pointer.py`, `backend/tests/apps/cli/test_ingress_cli.py`,
`backend/tests/apps/ingress/__init__.py`, `backend/tests/apps/ingress/support.py`,
`backend/tests/apps/ingress/test_addresses.py`, `backend/tests/apps/ingress/test_auth.py`,
`backend/tests/apps/ingress/test_batch.py`, `backend/tests/apps/ingress/test_config.py`,
`backend/tests/apps/ingress/test_hooks.py`, `backend/tests/apps/ingress/test_hooks_recording.py`,
`backend/tests/apps/ingress/test_limits.py`, `backend/tests/apps/ingress/test_startup.py`,
`backend/tests/core/ingress/test_parsing.py`

**Modify:** `backend/pyproject.toml`, `backend/src/dewpoint/apps/cli/main.py`, `backend/tests/core/ingress/support.py`

**What it does:**

Ingress's own app, settings (its environment only; no key-encryption key, which refuses the app and the CLI alike; an
ingress key of 32 bytes; a global body cap of at most 5 MiB) and CLI command, starting only in a development deployment
with the server's own X-Forwarded-For handling off. `POST /hooks/<endpoint_id>` checks, in this order: at most 32
requests in flight (503, before the body); an address's failures, 30 a minute per process in a bounded table, an IPv6
client by its /64 (429, before any database call); the global cap (413; a declared length compared by its digits) and
the body's 10 s deadline (408), both counted; then the endpoint, the address against its allowlist (X-Forwarded-For
only through configured proxies, read from the trusted end) and the authentication (an HMAC of `<timestamp>.<raw body>`
within the tolerance, or a bearer token, in constant time), every failure the same bodiless 401. After it: strict
parsing (invalid UTF-8, a duplicate key, NaN, `1e400`, an escaped unpaired surrogate, a 4,300-digit integer or nesting
past 64 levels refuse the body), events from the body or an RFC 6901 pointer, typed ids, canonical bytes sealed to the
tenant's key, and every attempt's outcome mapped (200 with its counts once committed, 413, 400, 409, 429 with or
without a wait, 503, the same 401 for an endpoint that stopped serving). An import contract keeps ingress from the API,
the dispatcher, the worker, Temporal and the tenant keys' code.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/cli/test_ingress_cli.py tests/apps/ingress/test_addresses.py tests/apps/ingress/test_auth.py
  tests/apps/ingress/test_batch.py tests/apps/ingress/test_config.py tests/apps/ingress/test_hooks.py
  tests/apps/ingress/test_hooks_recording.py tests/apps/ingress/test_limits.py tests/apps/ingress/test_startup.py
  tests/core/ingress/test_parsing.py`. Replay result (exit 1), shortened:

```
FAILED tests/apps/cli/test_ingress_cli.py::test_a_key_encryption_key_in_its_environment_refuses_the_start[DEWPOINT_KEK_B64]
FAILED tests/apps/cli/test_ingress_cli.py::test_in_development_it_serves_without_the_servers_proxy_headers
FAILED tests/apps/cli/test_ingress_cli.py::test_a_key_encryption_key_in_its_environment_refuses_the_start[DEWPOINT_KEK_PREVIOUS_B64]
FAILED tests/apps/cli/test_ingress_cli.py::test_outside_development_it_refuses_to_start
ERROR tests/apps/ingress/test_addresses.py - ImportError while importing test...
ERROR tests/apps/ingress/test_auth.py - ImportError while importing test modu...
ERROR tests/apps/ingress/test_batch.py - ImportError while importing test mod...
ERROR tests/apps/ingress/test_config.py - ImportError while importing test mo...
ERROR tests/apps/ingress/test_hooks.py - ImportError while importing test mod...
ERROR tests/apps/ingress/test_hooks_recording.py - ImportError while importin...
ERROR tests/apps/ingress/test_limits.py - ImportError while importing test mo...
ERROR tests/apps/ingress/test_startup.py - ImportError while importing test m...
ERROR tests/core/ingress/test_parsing.py - ImportError while importing test m...
4 failed, 9 errors in 14.75s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........................................................................ [ 61%]
..............................................                           [100%]
118 passed in 36.77s
```

Evidence beyond the replay: through nginx (a probe configuration in the local `dewpoint-web:dev` image, which the owner
approved for this probe), at milestone 2: an allowlisted client was served; another was refused, also when it put the
first one's address in `X-Forwarded-For`, and limited after its failures without limiting the first; trusting no proxy,
ingress took every client for nginx's own address and refused it (6 of 6).

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 8319fe3 && git commit -C 8319fe3`

The diff:

```diff
diff --git a/backend/pyproject.toml b/backend/pyproject.toml
index 3272fae..99994e8 100644
--- a/backend/pyproject.toml
+++ b/backend/pyproject.toml
@@ -163,6 +163,15 @@ forbidden_modules = [
   "sqlalchemy", "asyncpg", "fastapi", "pydantic", "jsonschema", "httpx", "temporalio", "cryptography",
 ]
 
+[[tool.importlinter.contracts]]
+name = "ingress imports neither the API, the dispatcher, the worker nor Temporal, and no tenant key's code (spec §8.3)"
+type = "forbidden"
+source_modules = ["dewpoint.apps.ingress"]
+forbidden_modules = [
+  "dewpoint.apps.api", "dewpoint.apps.dispatcher", "dewpoint.apps.worker", "dewpoint.apps.admission", "temporalio",
+  "dewpoint.core.crypto.kek", "dewpoint.core.crypto.keyring", "dewpoint.core.crypto.keys", "dewpoint.core.ingress.keys",
+]
+
 [[tool.importlinter.contracts]]
 name = "engine.runtime is deterministic: no clock, randomness, I/O or threads (spec §6)"
 type = "forbidden"
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 5d0c16d..29a36cb 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -375,6 +375,43 @@ def worker() -> None:
         raise typer.Exit(3) from None
 
 
+@app.command("ingress")
+def ingress(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8001, min=1, max=65535)) -> None:
+    """Serve webhook ingress, `/hooks/<endpoint_id>` (engine 2b spec §8.3), in a development deployment only until
+    engine 2b-4. The server's own X-Forwarded-For handling stays off: ingress believes it only from the proxies in
+    DEWPOINT_INGRESS_TRUSTED_PROXIES."""
+    import uvicorn
+
+    from dewpoint.apps.ingress.config import IngressSettings
+    from dewpoint.apps.ingress.main import (
+        IngressRefusedError,
+        create_app,
+        refuse_key_encryption_key,
+        require_development,
+    )
+
+    try:
+        refuse_key_encryption_key(os.environ)
+    except IngressRefusedError as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
+    settings = IngressSettings()  # read from the environment
+
+    async def _check() -> None:
+        engine = make_engine(settings.database_url)
+        try:
+            await require_development(make_sessionmaker(engine))
+        finally:
+            await engine.dispose()
+
+    try:
+        asyncio.run(_check())
+    except IngressRefusedError as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
+    uvicorn.run(create_app(settings), host=host, port=port, proxy_headers=False, server_header=False)
+
+
 @asynccontextmanager
 async def _temporal() -> AsyncIterator[Client]:
     """A Temporal client, once this process's namespace is the one this deployment recorded (engine 2b spec §2.1).
diff --git a/backend/src/dewpoint/apps/ingress/__init__.py b/backend/src/dewpoint/apps/ingress/__init__.py
new file mode 100644
index 0000000..864d903
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/__init__.py
@@ -0,0 +1,4 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook ingress (engine 2b spec §8.3): its own process and database login, `/hooks/<endpoint_id>`. It holds the
+ingress key, never a tenant's data key, and has no table privilege: it resolves an endpoint and records events only
+through the database's SECURITY DEFINER functions."""
diff --git a/backend/src/dewpoint/apps/ingress/addresses.py b/backend/src/dewpoint/apps/ingress/addresses.py
new file mode 100644
index 0000000..2b60603
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/addresses.py
@@ -0,0 +1,61 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A request's client address (the owner's ruling 11). `X-Forwarded-For` is believed only from a configured proxy
+(`DEWPOINT_INGRESS_TRUSTED_PROXIES`, none by default), read from its trusted end: right to left, past trusted hops
+only, so an entry a client wrote itself is never its address. An IPv6 client is limited by its /64, which one host
+usually holds whole."""
+
+from collections.abc import Sequence
+from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
+
+type Address = IPv4Address | IPv6Address
+type Network = IPv4Network | IPv6Network
+
+
+def parse_proxies(raw: str) -> tuple[Network, ...]:
+    """Comma- or space-separated addresses and networks. Raises ValueError, naming the setting, for any entry that isn't
+    one, a network with host bits set included: a bad value must never trust the wrong peers."""
+    networks = []
+    for entry in raw.replace(",", " ").split():
+        try:
+            networks.append(ip_network(entry))
+        except ValueError:
+            raise ValueError(f"DEWPOINT_INGRESS_TRUSTED_PROXIES: not an address or network: {entry!r}") from None
+    return tuple(networks)
+
+
+def _parse(text: str) -> Address | None:
+    """An address, an IPv4 client on a dual-stack socket (`::ffff:a.b.c.d`) as its IPv4 address."""
+    try:
+        address = ip_address(text.strip())
+    except ValueError:
+        return None
+    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
+        return address.ipv4_mapped
+    return address
+
+
+def client_address(peer: str | None, forwarded: Sequence[str], trusted: Sequence[Network]) -> Address | None:
+    """The client's address: the peer's, or, from a trusted peer, the rightmost forwarded entry past trusted hops. An
+    entry that isn't an address stops the walk at the last address trusted to have seen it."""
+    current = _parse(peer) if peer else None
+    if current is None:
+        return None
+    entries = [entry for value in forwarded for entry in value.split(",")]
+    for entry in reversed(entries):
+        if not any(current in network for network in trusted):
+            break
+        parsed = _parse(entry)
+        if parsed is None:
+            break
+        current = parsed
+    return current
+
+
+def limiter_key(address: Address | None) -> str:
+    if address is None:
+        return "unknown"
+    if isinstance(address, IPv6Address):
+        if address.ipv4_mapped is not None:
+            return str(address.ipv4_mapped)
+        return str(ip_network(f"{address}/64", strict=False))
+    return str(address)
diff --git a/backend/src/dewpoint/apps/ingress/auth.py b/backend/src/dewpoint/apps/ingress/auth.py
new file mode 100644
index 0000000..fd59198
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/auth.py
@@ -0,0 +1,52 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A request's authentication (engine 2b spec §8.3; the owner's ruling 2): an HMAC-SHA256, under the endpoint's
+secret, of `<timestamp>.` and the exact raw body, its timestamp (Unix seconds) within the endpoint's tolerance either
+way; or a bearer token whose SHA-256 is the endpoint's digest. Each is compared in constant time. Anything else, a
+secret this process can't open included, is a failure: the caller answers every one with the same 401."""
+
+import hashlib
+import hmac
+
+import structlog
+from cryptography.exceptions import InvalidTag
+from starlette.datastructures import Headers
+
+from dewpoint.apps.ingress.endpoints import Endpoint
+from dewpoint.core.crypto.ingress import HMAC_SECRET, IngressKey, UnknownIngressKeyError, bearer_matches
+
+log = structlog.get_logger("dewpoint.ingress")
+MAX_TIMESTAMP_DIGITS = 12
+
+
+def _bearer(endpoint: Endpoint, headers: Headers) -> bool:
+    scheme, _, token = headers.get("authorization", "").partition(" ")
+    token = token.strip()
+    if scheme.lower() != "bearer" or not token or not token.isascii() or endpoint.bearer_digest is None:
+        return False
+    return bearer_matches(token, endpoint.bearer_digest)
+
+
+def _signed(endpoint: Endpoint, headers: Headers, body: bytes, now: float, key: IngressKey) -> bool:
+    if endpoint.hmac_secret is None or endpoint.timestamp_header is None or endpoint.signature_header is None:
+        return False
+    stamp = headers.get(endpoint.timestamp_header, "")
+    signature = headers.get(endpoint.signature_header, "").strip().lower().removeprefix("sha256=")
+    if not (stamp.isascii() and stamp.isdigit() and len(stamp) <= MAX_TIMESTAMP_DIGITS) or not signature.isascii():
+        return False
+    if abs(now - int(stamp)) > endpoint.tolerance_s:
+        return False
+    try:
+        secret = key.open(HMAC_SECRET, str(endpoint.id), endpoint.hmac_secret)
+    except (UnknownIngressKeyError, InvalidTag, ValueError) as e:
+        log.warning("ingress_secret_unopenable", endpoint_id=str(endpoint.id), error=type(e).__name__)
+        return False
+    expected = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
+    return hmac.compare_digest(expected.encode(), signature.encode())
+
+
+def authenticate(endpoint: Endpoint, headers: Headers, body: bytes, now: float, key: IngressKey) -> bool:
+    if endpoint.auth_kind == "bearer":
+        return _bearer(endpoint, headers)
+    if endpoint.auth_kind == "hmac":
+        return _signed(endpoint, headers, body, now, key)
+    return False
diff --git a/backend/src/dewpoint/apps/ingress/batch.py b/backend/src/dewpoint/apps/ingress/batch.py
new file mode 100644
index 0000000..d8edf69
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/batch.py
@@ -0,0 +1,70 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An authenticated body as the batch ingress records (engine 2b spec §8.3; the owner's ruling 4). Its events are split
+from the strictly parsed body; each gets a new id, its dedupe key from the id its sender gave it (typed, at the
+endpoint's pointer) or from the request's header id and its index, its content digest, and its canonical bytes sealed
+to the tenant's newest public key, bound to the tenant, the endpoint and the event's id. Any event without a valid id
+refuses the whole body."""
+
+import uuid
+from dataclasses import dataclass
+from typing import cast
+
+from dewpoint.apps.ingress.endpoints import Endpoint
+from dewpoint.core.crypto import events
+from dewpoint.core.ingress.identity import IdSource, InvalidEventIdError, canonical, content_digest, dedupe_key
+from dewpoint.core.ingress.parsing import MalformedError, events_of, parse
+from dewpoint.core.ingress.pointer import PointerError, resolve
+
+
+@dataclass(frozen=True)
+class Batch:
+    ids: list[uuid.UUID]
+    sealed: list[bytes]
+    versions: list[int]
+    dedupe: list[bytes | None]
+    digests: list[bytes | None]
+
+
+def _given_id(endpoint: Endpoint, event: dict[str, object], header_id: str | None) -> str | int | None:
+    if endpoint.id_source == "pointer" and endpoint.id_pointer is not None:
+        try:
+            found = resolve(event, endpoint.id_pointer)
+        except PointerError:
+            raise MalformedError from None
+        return found if isinstance(found, (str, int)) else None  # dedupe_key refuses None and a bool
+    if endpoint.id_source == "header":
+        if header_id is None:
+            raise MalformedError
+        return header_id
+    return None
+
+
+def prepare(endpoint: Endpoint, body: bytes, header_id: str | None, dedupe_secret: bytes | None) -> Batch:
+    """Raises MalformedError. `dedupe_secret` is the endpoint's opened dedupe key: None only when its events carry no
+    id."""
+    if endpoint.public_key is None or endpoint.key_version is None:
+        raise ValueError("the tenant has no inbound key")  # the caller fails closed first
+    if endpoint.id_source not in ("pointer", "header", "none"):
+        raise ValueError("an id source the schema doesn't allow")
+    source = cast(IdSource, endpoint.id_source)
+    if source != "none" and dedupe_secret is None:
+        raise ValueError("an endpoint with ids needs its dedupe key")
+    batch = Batch([], [], [], [], [])
+    for index, event in enumerate(events_of(parse(body), endpoint.events_pointer)):
+        try:
+            key = dedupe_key(dedupe_secret or b"", source, _given_id(endpoint, event, header_id), index)
+        except InvalidEventIdError:
+            raise MalformedError from None
+        content = canonical(event)
+        event_id = uuid.uuid4()
+        batch.ids.append(event_id)
+        batch.sealed.append(
+            events.seal(
+                endpoint.public_key, endpoint.key_version, tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id,
+                event_id=event_id, plaintext=content,
+            )
+        )  # fmt: skip
+        batch.versions.append(endpoint.key_version)
+        batch.dedupe.append(key)
+        batch.digests.append(content_digest(dedupe_secret, content) if key is not None and dedupe_secret else None)
+    return batch
diff --git a/backend/src/dewpoint/apps/ingress/config.py b/backend/src/dewpoint/apps/ingress/config.py
new file mode 100644
index 0000000..4abae62
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/config.py
@@ -0,0 +1,50 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's own settings, from its environment only: its database login, the ingress key and its limits. No
+key-encryption key: ingress never holds a tenant's data key (engine 2b spec §8.3), so it has no setting for one."""
+
+import base64
+import binascii
+
+from pydantic import Field, field_validator
+from pydantic_settings import BaseSettings, SettingsConfigDict
+
+from dewpoint.apps.ingress.addresses import parse_proxies
+
+MIB = 1024 * 1024
+# The largest body limit an endpoint may set. The database sizes every endpoint's byte burst to cover a body this large
+# (migration 0032), so a larger cap would make a body past a small limit a 429 for ever (the owner's M2 review).
+MAX_BODY_CAP = 5 * MIB
+
+
+class IngressSettings(BaseSettings):
+    # The environment only, never a `.env` file: a shared one may hold the key-encryption key.
+    # Errors never quote a value: a key of the wrong length may still be a real key.
+    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=None, extra="ignore", hide_input_in_errors=True)
+
+    database_url: str  # the ingress login's: no table privilege, only ingress's functions
+    ingress_key_b64: str
+    ingress_key_id: str = "ingress-1"
+    # Proxies whose X-Forwarded-For is believed (the owner's ruling 11): none by default.
+    ingress_trusted_proxies: str = ""
+    # The limits before authentication (§15, provisional; the load probe revisits them).
+    ingress_max_in_flight: int = 32
+    ingress_address_failures: int = 30  # failed requests per address (an IPv6 /64) a minute, per process
+    ingress_body_cap: int = Field(default=MAX_BODY_CAP, ge=1, le=MAX_BODY_CAP)
+    ingress_body_deadline_s: float = 10
+
+    @field_validator("ingress_key_b64")
+    @classmethod
+    def _key(cls, value: str) -> str:
+        try:
+            decoded = base64.b64decode(value, validate=True)
+        except binascii.Error:
+            decoded = b""
+        if len(decoded) != 32:
+            raise ValueError("DEWPOINT_INGRESS_KEY_B64 must be 32 bytes, base64-encoded (openssl rand -base64 32)")
+        return value
+
+    @field_validator("ingress_trusted_proxies")
+    @classmethod
+    def _proxies(cls, value: str) -> str:
+        parse_proxies(value)
+        return value
diff --git a/backend/src/dewpoint/apps/ingress/endpoints.py b/backend/src/dewpoint/apps/ingress/endpoints.py
new file mode 100644
index 0000000..5be443f
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/endpoints.py
@@ -0,0 +1,43 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An endpoint as ingress sees it: what `resolve_webhook_endpoint()` returns, ingress's only read of one."""
+
+import uuid
+from collections.abc import Sequence
+from dataclasses import dataclass
+
+from sqlalchemy import text
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps.ingress.addresses import Network
+
+RESOLVE = text("select * from resolve_webhook_endpoint(:e)")
+
+
+@dataclass(frozen=True)
+class Endpoint:
+    id: uuid.UUID
+    tenant_id: uuid.UUID
+    enabled: bool
+    tenant_active: bool
+    auth_kind: str
+    bearer_digest: bytes | None
+    hmac_secret: bytes | None  # sealed under the ingress key
+    signature_header: str | None
+    timestamp_header: str | None
+    tolerance_s: int
+    allowlist: Sequence[Network]  # empty: any address
+    body_limit: int
+    id_source: str
+    id_pointer: str | None
+    id_header: str | None
+    events_pointer: str | None
+    dedupe_key: bytes  # sealed under the ingress key
+    key_version: int | None  # the tenant's newest inbound key; none when it has none
+    public_key: bytes | None
+
+
+async def resolve(session: AsyncSession, endpoint_id: uuid.UUID) -> Endpoint | None:
+    row = (await session.execute(RESOLVE, {"e": endpoint_id})).mappings().one_or_none()
+    if row is None:
+        return None
+    return Endpoint(id=endpoint_id, **{k: v for k, v in row.items()} | {"allowlist": tuple(row["allowlist"] or ())})
diff --git a/backend/src/dewpoint/apps/ingress/limits.py b/backend/src/dewpoint/apps/ingress/limits.py
new file mode 100644
index 0000000..1ffbb9f
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/limits.py
@@ -0,0 +1,51 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's limits before authentication (engine 2b spec §8.3; the owner's rulings 5 and 7), which depend on nothing
+an endpoint has, so none tells a sender an endpoint exists. Both are each process's own, in memory: a failed request
+costs no database write."""
+
+import math
+from collections import OrderedDict
+
+
+class FailureLimiter:
+    """Failed requests per address in fixed windows: an address that has failed `failures` times in the window its
+    first failure opened is refused until that window ends. The table is bounded: a full one drops the address that
+    failed least recently (in constant time, so a flood of addresses costs each request no more)."""
+
+    def __init__(self, failures: int, window_s: float, max_entries: int = 65_536) -> None:
+        self.failures, self.window_s, self.max_entries = failures, window_s, max_entries
+        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()  # address -> (window start, failures)
+
+    def __len__(self) -> int:
+        return len(self._windows)
+
+    def blocked(self, key: str, now: float) -> int | None:
+        """The whole seconds until `key` may try again, or None."""
+        window = self._windows.get(key)
+        if window is None or now >= window[0] + self.window_s or window[1] < self.failures:
+            return None
+        return max(1, math.ceil(window[0] + self.window_s - now))
+
+    def fail(self, key: str, now: float) -> None:
+        window = self._windows.pop(key, None)
+        if window is None or now >= window[0] + self.window_s:
+            window = (now, 0)
+        while len(self._windows) >= self.max_entries:
+            self._windows.popitem(last=False)
+        self._windows[key] = (window[0], window[1] + 1)  # last: the most recent failure
+
+
+class InFlight:
+    """The requests a process is serving; one past the limit is refused before its body is read."""
+
+    def __init__(self, limit: int) -> None:
+        self.limit, self.count = limit, 0
+
+    def try_acquire(self) -> bool:
+        if self.count >= self.limit:
+            return False
+        self.count += 1
+        return True
+
+    def release(self) -> None:
+        self.count -= 1
diff --git a/backend/src/dewpoint/apps/ingress/main.py b/backend/src/dewpoint/apps/ingress/main.py
new file mode 100644
index 0000000..7b4f3e4
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/main.py
@@ -0,0 +1,228 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's app (engine 2b spec §8.3). `POST /hooks/<endpoint_id>` checks, in this order: the requests in flight (503,
+before the body is read); the address's failures (429, before any database call); the body against the global cap
+(413) and its deadline (408); then the endpoint, the address against its allowlist and the authentication, every
+failure the same bodiless 401. Failures before authentication count against the address. An authenticated attempt is
+split, identified and sealed, and recorded or refused, all or nothing, by `record_inbound_events`, whose committed
+outcome is the response. It refuses to start unless the recorded environment is `development`: a gated prototype until
+2b-4 (the owner's rulings 8 and 13), and refuses to be made with a key-encryption key in its environment."""
+
+import asyncio
+import base64
+import os
+import time
+import uuid
+from collections.abc import AsyncIterator, Callable, Mapping, Sequence
+from contextlib import asynccontextmanager
+
+import structlog
+from cryptography.exceptions import InvalidTag
+from fastapi import FastAPI, Request
+from fastapi.responses import JSONResponse, Response
+from sqlalchemy import text
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from starlette.datastructures import Headers
+from starlette.requests import ClientDisconnect
+
+from dewpoint.apps.ingress.addresses import Address, Network, client_address, limiter_key, parse_proxies
+from dewpoint.apps.ingress.auth import authenticate
+from dewpoint.apps.ingress.batch import prepare
+from dewpoint.apps.ingress.config import IngressSettings
+from dewpoint.apps.ingress.endpoints import Endpoint, resolve
+from dewpoint.apps.ingress.limits import FailureLimiter, InFlight
+from dewpoint.apps.ingress.recording import UNKNOWN, record, respond
+from dewpoint.core.crypto.ingress import DEDUPE_KEY, IngressKey, UnknownIngressKeyError
+from dewpoint.core.db import make_engine, make_sessionmaker, unavailable
+from dewpoint.core.ingress.parsing import MalformedError
+from dewpoint.core.platform.service import DEVELOPMENT
+
+log = structlog.get_logger("dewpoint.ingress")
+
+
+class IngressRefusedError(RuntimeError):
+    """Ingress refuses to start; the message says why."""
+
+
+class BodyTooLargeError(Exception):
+    pass
+
+
+KEK_VARIABLES = ("DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64")
+
+
+def refuse_key_encryption_key(environ: Mapping[str, str]) -> None:
+    """Ingress never holds a tenant's data key (engine 2b spec §8.3): a key-encryption key in its environment refuses
+    its start, whichever way it's started. The message names the variable, never its value."""
+    present = [name for name in KEK_VARIABLES if environ.get(name)]
+    if present:
+        raise IngressRefusedError(
+            f"refusing to start: {', '.join(present)} is set. Ingress never holds a tenant's data key: remove the "
+            "key-encryption key from its environment."
+        )
+
+
+async def require_development(sessions: async_sessionmaker[AsyncSession]) -> None:
+    async with sessions() as s:
+        environment = (await s.execute(text("select ingress_environment()"))).scalar_one_or_none()
+    if environment != DEVELOPMENT:
+        raise IngressRefusedError(
+            f"refusing to start: ingress serves only a development deployment until engine 2b-4 (recorded: "
+            f"{environment or 'none'})"
+        )
+
+
+def declared_over(declared: str, cap: int) -> bool:
+    """Whether a declared Content-Length says more than `cap`, compared by its digits before any conversion: one too
+    long for `int()` is still past the cap (the owner's M2 review). Anything but ASCII digits isn't a length; the
+    bytes are counted as they arrive."""
+    if not (declared.isascii() and declared.isdigit()):
+        return False
+    digits = declared.lstrip("0")
+    return len(digits) > len(str(cap)) or int(digits or "0") > cap
+
+
+async def read_body(request: Request, cap: int, deadline_s: float) -> bytes:
+    """The whole body, refused one byte past `cap` as it arrives (a chunked body declares no length), and within
+    `deadline_s`; raises BodyTooLargeError or TimeoutError."""
+    if declared_over(request.headers.get("content-length", ""), cap):
+        raise BodyTooLargeError
+    chunks, size = [], 0
+    async with asyncio.timeout(deadline_s):
+        async for chunk in request.stream():
+            size += len(chunk)
+            if size > cap:
+                raise BodyTooLargeError
+            chunks.append(chunk)
+    return b"".join(chunks)
+
+
+def _error(status: int, code: str, retry_after: int | None = None) -> Response:
+    headers = {"retry-after": str(retry_after)} if retry_after is not None else None
+    return JSONResponse({"error": code}, status_code=status, headers=headers)
+
+
+def _allowed(address: Address | None, allowlist: Sequence[Network]) -> bool:
+    return not allowlist or (address is not None and any(address in network for network in allowlist))
+
+
+def create_app(settings: IngressSettings | None = None, *, clock: Callable[[], float] = time.time) -> FastAPI:
+    refuse_key_encryption_key(os.environ)
+    settings = settings or IngressSettings()  # read from the environment
+    trusted = parse_proxies(settings.ingress_trusted_proxies)
+    key = IngressKey(settings.ingress_key_id, base64.b64decode(settings.ingress_key_b64))
+
+    @asynccontextmanager
+    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
+        await require_development(app.state.sessionmaker)
+        yield
+        await app.state.engine.dispose()
+
+    app = FastAPI(title="Dewpoint ingress", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
+    app.state.engine = make_engine(settings.database_url)
+    app.state.sessionmaker = make_sessionmaker(app.state.engine)
+    limiter = FailureLimiter(settings.ingress_address_failures, window_s=60)
+    in_flight = InFlight(settings.ingress_max_in_flight)
+
+    @app.get("/health/live")
+    async def live() -> dict[str, str]:
+        return {"status": "ok"}
+
+    @app.get("/health/ready")
+    async def ready() -> Response:
+        try:
+            async with app.state.engine.connect() as conn:
+                await conn.execute(text("select ingress_environment()"))
+        except Exception:  # any failure means not ready; never leak details
+            return JSONResponse({"status": "unavailable"}, status_code=503)
+        return JSONResponse({"status": "ready"})
+
+    async def _resolve(sessions: async_sessionmaker[AsyncSession], raw_id: str) -> Endpoint | None:
+        try:
+            endpoint_id = uuid.UUID(raw_id)
+        except ValueError:
+            return None
+        async with sessions() as s:
+            return await resolve(s, endpoint_id)
+
+    async def _serve(raw_id: str, request: Request) -> Response:
+        address = client_address(
+            request.client.host if request.client else None, request.headers.getlist("x-forwarded-for"), trusted
+        )
+        who = limiter_key(address)
+        wait = limiter.blocked(who, clock())
+        if wait is not None:
+            return _error(429, "rate_limited", retry_after=wait)
+        try:
+            body = await read_body(request, settings.ingress_body_cap, settings.ingress_body_deadline_s)
+        except BodyTooLargeError:
+            limiter.fail(who, clock())
+            return _error(413, "too_large")
+        except TimeoutError:
+            limiter.fail(who, clock())
+            return Response(status_code=408, headers={"connection": "close"})
+        except ClientDisconnect:
+            return Response(status_code=400)  # nobody reads it
+        try:
+            endpoint = await _resolve(request.app.state.sessionmaker, raw_id)
+        except Exception as e:
+            if not unavailable(e):
+                raise
+            log.warning("ingress_database_unavailable", error=type(e).__name__)
+            return _error(503, "unavailable", retry_after=5)
+        if (
+            endpoint is None
+            or not endpoint.enabled
+            or not endpoint.tenant_active
+            or not _allowed(address, endpoint.allowlist)
+            or not authenticate(endpoint, request.headers, body, clock(), key)
+        ):
+            limiter.fail(who, clock())
+            return Response(status_code=401)
+        return await _attempt(request.app.state.sessionmaker, endpoint, request.headers, body, who)
+
+    async def _attempt(
+        sessions: async_sessionmaker[AsyncSession], endpoint: Endpoint, headers: Headers, body: bytes, who: str
+    ) -> Response:
+        """An authenticated attempt, recorded or refused by the recording function, which also charges a refusal."""
+        if endpoint.public_key is None or endpoint.key_version is None:  # fail closed (the owner's ruling 8)
+            log.warning("ingress_no_inbound_key", tenant_id=str(endpoint.tenant_id))
+            return _error(503, "unavailable")
+        refusal, batch = None, None
+        if len(body) > endpoint.body_limit:
+            refusal = "too_large"
+        else:
+            try:
+                secret = (
+                    key.open(DEDUPE_KEY, str(endpoint.id), endpoint.dedupe_key)
+                    if endpoint.id_source != "none"
+                    else None
+                )
+            except (UnknownIngressKeyError, InvalidTag, ValueError) as e:
+                log.warning("ingress_secret_unopenable", endpoint_id=str(endpoint.id), error=type(e).__name__)
+                return _error(503, "unavailable")
+            try:
+                batch = prepare(endpoint, body, headers.get(endpoint.id_header) if endpoint.id_header else None, secret)
+            except MalformedError:
+                refusal = "malformed"
+        try:
+            outcome = await record(sessions, endpoint.id, read=len(body), batch=batch, refusal=refusal)
+        except Exception as e:
+            if not unavailable(e):
+                raise
+            log.warning("ingress_database_unavailable", error=type(e).__name__)
+            return _error(503, "unavailable", retry_after=5)
+        if outcome["outcome"] == UNKNOWN:  # it stopped serving since it was resolved
+            limiter.fail(who, clock())
+            return Response(status_code=401)
+        return respond(outcome)
+
+    @app.post("/hooks/{endpoint_id}")
+    async def hook(endpoint_id: str, request: Request) -> Response:
+        if not in_flight.try_acquire():
+            return _error(503, "busy", retry_after=1)
+        try:
+            return await _serve(endpoint_id, request)
+        finally:
+            in_flight.release()
+
+    return app
diff --git a/backend/src/dewpoint/apps/ingress/recording.py b/backend/src/dewpoint/apps/ingress/recording.py
new file mode 100644
index 0000000..12ed505
--- /dev/null
+++ b/backend/src/dewpoint/apps/ingress/recording.py
@@ -0,0 +1,61 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Every authenticated attempt goes through `record_inbound_events` (engine 2b spec §8.3), which spends the endpoint's
+and the tenant's rate budget, refuses or records all or nothing, and says what it did; its outcome is the response,
+given only once its transaction has committed."""
+
+import uuid
+from typing import Any
+
+from fastapi.responses import JSONResponse, Response
+from sqlalchemy import text
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps.ingress.batch import Batch
+
+RECORD = text(
+    "select record_inbound_events(:e, :refusal, :read, cast(:ids as uuid[]), cast(:sealed as bytea[]), "
+    "cast(:versions as integer[]), cast(:dedupe as bytea[]), cast(:digests as bytea[]))"
+)
+UNKNOWN = "unknown"  # the endpoint or its tenant stopped serving since it was resolved: the caller's 401
+
+
+async def record(
+    sessions: async_sessionmaker[AsyncSession], endpoint_id: uuid.UUID, *, read: int, batch: Batch | None = None,
+    refusal: str | None = None,
+) -> dict[str, Any]:  # fmt: skip
+    """The function's outcome, committed. `refusal` (`too_large` or `malformed`) records nothing but pays."""
+    given = batch or Batch([], [], [], [], [])
+    params = {
+        "e": endpoint_id, "refusal": refusal, "read": read, "ids": given.ids, "sealed": given.sealed,
+        "versions": given.versions, "dedupe": given.dedupe, "digests": given.digests,
+    }  # fmt: skip
+    async with sessions() as s, s.begin():
+        outcome: dict[str, Any] = (await s.execute(RECORD, params)).scalar_one()
+    return dict(outcome)
+
+
+def _error(status: int, code: str, retry_after: int | None = None) -> Response:
+    headers = {"retry-after": str(retry_after)} if retry_after is not None else None
+    return JSONResponse({"error": code}, status_code=status, headers=headers)
+
+
+def respond(outcome: dict[str, Any]) -> Response:
+    """The response for every outcome but `unknown`, whose 401 the caller gives (and counts)."""
+    match outcome["outcome"]:
+        case "recorded":
+            return JSONResponse({"accepted": outcome["accepted"], "duplicates": outcome["duplicates"]})
+        case "rate_limited":
+            return _error(429, "rate_limited", retry_after=int(outcome["retry_after"]))
+        case "too_large":
+            return _error(413, "too_large")
+        case "malformed":
+            return _error(400, "malformed")
+        case "event_id_reused":
+            return _error(409, "event_id_reused")
+        case "quota_exceeded":
+            return _error(429, "quota_exceeded", retry_after=int(outcome["retry_after"]))
+        case "retained_full":
+            return _error(429, "retained_full")  # nothing frees it before 2b-4: no Retry-After
+        case "environment":
+            return _error(503, "unavailable")
+    raise ValueError("an outcome the recording function doesn't give")
diff --git a/backend/src/dewpoint/core/ingress/parsing.py b/backend/src/dewpoint/core/ingress/parsing.py
new file mode 100644
index 0000000..7d15f54
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/parsing.py
@@ -0,0 +1,104 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A webhook body's strict parsing (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline), so no parser's
+leniency decides what an event is: UTF-8 JSON only, and a duplicate key in any object, NaN or an infinity, a number past
+binary64's range, an escaped unpaired surrogate, an integer of more than 4,300 digits, or nesting deeper than 64 levels
+refuses the whole body. Its events are the body itself, or the array at the endpoint's events pointer: objects only, 1
+to 500 of them."""
+
+import json
+import math
+import re
+from collections.abc import Iterable
+from typing import Any
+
+from dewpoint.core.ingress.pointer import PointerError, resolve
+
+MAX_EVENTS = 500
+# Levels of nesting, the body's own value the first: the engine's limit for a document (engine.graph.model), so an
+# event's depth never depends on an interpreter's recursion limit, here or wherever its run's trigger is walked.
+MAX_DEPTH = 64
+MAX_INT_DIGITS = 4300  # Python's own default limit, held here whatever the interpreter is configured with
+# A lone surrogate can only come from an escape: strict UTF-8 decoding refuses an encoded one.
+SURROGATE_ESCAPE = re.compile(r"\\u[dD][89a-fA-F]")
+
+
+class MalformedError(ValueError):
+    """A body refused whole: `400 malformed`. Its message is fixed and never quotes the body."""
+
+    def __init__(self) -> None:
+        super().__init__("malformed")
+
+
+def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
+    found = dict(pairs)
+    if len(found) != len(pairs):
+        raise ValueError("a duplicate key")
+    return found
+
+
+def _constant(_: str) -> float:
+    raise ValueError("NaN or an infinity")
+
+
+def _float(text: str) -> float:
+    value = float(text)
+    if not math.isfinite(value):
+        raise ValueError("past binary64's range")
+    return value
+
+
+def _int(text: str) -> int:
+    if len(text.lstrip("-")) > MAX_INT_DIGITS:
+        raise ValueError("an integer past 4,300 digits")
+    return int(text)
+
+
+def _checked(document: object, strings: bool) -> None:
+    """At most MAX_DEPTH levels of objects and arrays; with `strings`, every string and key encodes as UTF-8 (no
+    unpaired surrogate). Iterative: no recursion limit decides."""
+    stack: list[tuple[object, int]] = [(document, 1)]
+    while stack:
+        value, depth = stack.pop()
+        if isinstance(value, (dict, list)) and depth > MAX_DEPTH:
+            raise ValueError("nested too deep")
+        children: Iterable[object]
+        if isinstance(value, dict):
+            if strings:
+                for key in value:
+                    key.encode()
+            children = value.values()
+        elif isinstance(value, list):
+            children = value
+        else:
+            if strings and isinstance(value, str):
+                value.encode()
+            continue
+        stack.extend((child, depth + 1) for child in children if strings or isinstance(child, (dict, list)))
+
+
+def parse(body: bytes) -> object:
+    try:
+        text = body.decode("utf-8")
+        document = json.loads(
+            text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float, parse_int=_int
+        )
+        _checked(document, strings=SURROGATE_ESCAPE.search(text) is not None)
+    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeError are ValueErrors
+        raise MalformedError from None
+    return document
+
+
+def events_of(document: object, events_pointer: str | None) -> list[dict[str, Any]]:
+    if events_pointer is None:
+        items = [document]
+    else:
+        try:
+            found = resolve(document, events_pointer)
+        except PointerError:
+            raise MalformedError from None
+        if not isinstance(found, list):
+            raise MalformedError
+        items = found
+    if not 1 <= len(items) <= MAX_EVENTS or not all(isinstance(item, dict) for item in items):
+        raise MalformedError
+    return items  # type: ignore[return-value]  # each checked a dict above
diff --git a/backend/src/dewpoint/core/ingress/pointer.py b/backend/src/dewpoint/core/ingress/pointer.py
new file mode 100644
index 0000000..170e0d8
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/pointer.py
@@ -0,0 +1,28 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A JSON pointer (RFC 6901), resolved against a parsed document: where an endpoint's events and ids are, and what a
+binding's filter compares."""
+
+import re
+
+INDEX = re.compile(r"0|[1-9][0-9]*")
+
+
+class PointerError(LookupError):
+    """A pointer that doesn't resolve in the document (its text is never quoted: it may carry a value)."""
+
+
+def resolve(document: object, pointer: str) -> object:
+    if pointer == "":
+        return document
+    if not pointer.startswith("/"):
+        raise PointerError("a pointer is empty or starts with '/'")
+    value = document
+    for raw in pointer.split("/")[1:]:
+        token = raw.replace("~1", "/").replace("~0", "~")
+        if isinstance(value, dict) and token in value:
+            value = value[token]
+        elif isinstance(value, list) and INDEX.fullmatch(token) and int(token) < len(value):
+            value = value[int(token)]
+        else:
+            raise PointerError("the pointer doesn't resolve")
+    return value
diff --git a/backend/tests/apps/cli/test_ingress_cli.py b/backend/tests/apps/cli/test_ingress_cli.py
new file mode 100644
index 0000000..211d893
--- /dev/null
+++ b/backend/tests/apps/cli/test_ingress_cli.py
@@ -0,0 +1,62 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`dewpoint ingress` serves webhook ingress (engine 2b spec §8.3): from its own settings, never with a key-encryption
+key in its environment, only in a development deployment, and with the server's own proxy-header handling off (ingress
+reads X-Forwarded-For itself, from configured proxies only)."""
+
+import asyncio
+import base64
+import os
+
+import pytest
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli.main import app
+from dewpoint.core.db import make_engine, make_sessionmaker
+from dewpoint.core.platform.service import DEVELOPMENT, PRODUCTION, record_environment
+from tests.conftest import _url_for
+
+
+def _record(pg_url: str, environment: str) -> None:
+    async def run() -> None:
+        engine = make_engine(pg_url)
+        async with make_sessionmaker(engine)() as s, s.begin():
+            await record_environment(s, environment=environment, namespace="default")
+        await engine.dispose()
+
+    asyncio.run(run())
+
+
+@pytest.fixture
+def served(monkeypatch, pg_url, _test_users):  # type: ignore[no-untyped-def]
+    calls = []
+    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_ingress"))
+    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(os.urandom(32)).decode())
+    for name in ("DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"):
+        monkeypatch.delenv(name, raising=False)
+    return calls
+
+
+def test_in_development_it_serves_without_the_servers_proxy_headers(served, pg_url) -> None:
+    _record(pg_url, DEVELOPMENT)
+    result = CliRunner().invoke(app, ["ingress", "--port", "8100"])
+    assert result.exit_code == 0, result.output
+    assert served == [{"host": "127.0.0.1", "port": 8100, "proxy_headers": False, "server_header": False}]
+
+
+def test_outside_development_it_refuses_to_start(served, pg_url) -> None:
+    result = CliRunner().invoke(app, ["ingress"])
+    assert (result.exit_code, served) == (2, [])
+    assert "development deployment" in result.output
+    _record(pg_url, PRODUCTION)
+    result = CliRunner().invoke(app, ["ingress"])
+    assert (result.exit_code, served) == (2, [])
+
+
+@pytest.mark.parametrize("name", ["DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"])
+def test_a_key_encryption_key_in_its_environment_refuses_the_start(served, monkeypatch, name) -> None:
+    monkeypatch.setenv(name, base64.b64encode(b"k" * 32).decode())
+    result = CliRunner().invoke(app, ["ingress"])
+    assert (result.exit_code, served) == (2, [])
+    assert name in result.output
+    assert base64.b64encode(b"k" * 32).decode() not in result.output
diff --git a/backend/tests/apps/ingress/__init__.py b/backend/tests/apps/ingress/__init__.py
new file mode 100644
index 0000000..9881313
--- /dev/null
+++ b/backend/tests/apps/ingress/__init__.py
@@ -0,0 +1 @@
+# SPDX-License-Identifier: Apache-2.0
diff --git a/backend/tests/apps/ingress/support.py b/backend/tests/apps/ingress/support.py
new file mode 100644
index 0000000..288291c
--- /dev/null
+++ b/backend/tests/apps/ingress/support.py
@@ -0,0 +1,71 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's app in a test: its settings for the ingress login, endpoints whose secrets are sealed under the test's
+ingress key, a client at a chosen address, and a clock the test moves."""
+
+import base64
+import hashlib
+import hmac
+import os
+import uuid
+from typing import Any
+
+import httpx
+
+from dewpoint.apps.ingress.config import IngressSettings
+from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey, bearer_digest
+from tests.conftest import _url_for
+from tests.core.ingress.support import endpoint
+
+KEY_BYTES = os.urandom(32)
+KEY = IngressKey("ingress-1", KEY_BYTES)
+SECRET = b"s3cret-of-the-endpoint"
+TOKEN = "dwp_token-of-the-endpoint"  # noqa: S105 - a test's token
+NOW = 1_800_000_000.0
+CLIENT = ("198.51.100.7", 40000)
+
+
+class Clock:
+    def __init__(self) -> None:
+        self.now = NOW
+
+    def __call__(self) -> float:
+        return self.now
+
+
+def settings(pg_url: str, **overrides: Any) -> IngressSettings:
+    url, key = _url_for(pg_url, "dewpoint_ingress"), base64.b64encode(KEY_BYTES).decode()
+    return IngressSettings(**{"database_url": url, "ingress_key_b64": key} | overrides)
+
+
+def sealed_dedupe_key(endpoint_id: uuid.UUID, key: bytes | None = None) -> bytes:
+    return KEY.seal(DEDUPE_KEY, str(endpoint_id), key or os.urandom(32))
+
+
+async def hmac_endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
+    endpoint_id = uuid.uuid4()
+    values = {
+        "auth_kind": "hmac", "bearer_digest": None, "hmac_secret": KEY.seal(HMAC_SECRET, str(endpoint_id), SECRET),
+        "signature_header": "x-signature", "timestamp_header": "x-timestamp",
+        "dedupe_key": sealed_dedupe_key(endpoint_id),
+    }  # fmt: skip
+    return await endpoint(owner, endpoint_id, **values | columns)
+
+
+async def bearer_endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
+    endpoint_id = uuid.uuid4()
+    values = {"auth_kind": "bearer", "bearer_digest": bearer_digest(TOKEN)}
+    return await endpoint(owner, endpoint_id, **values | {"dedupe_key": sealed_dedupe_key(endpoint_id)} | columns)
+
+
+def signed(body: bytes, now: float = NOW, secret: bytes = SECRET) -> dict[str, str]:
+    stamp = str(int(now))
+    signature = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
+    return {"x-timestamp": stamp, "x-signature": signature}
+
+
+def bearer() -> dict[str, str]:
+    return {"authorization": f"Bearer {TOKEN}"}
+
+
+def client(app: Any, address: tuple[str, int] = CLIENT) -> httpx.AsyncClient:
+    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=address), base_url="http://ingress")
diff --git a/backend/tests/apps/ingress/test_addresses.py b/backend/tests/apps/ingress/test_addresses.py
new file mode 100644
index 0000000..18b9435
--- /dev/null
+++ b/backend/tests/apps/ingress/test_addresses.py
@@ -0,0 +1,68 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A request's client address (the owner's ruling 11): the TCP peer, unless the peer is a configured proxy, in which
+case `X-Forwarded-For` is read from its trusted end: right to left, past trusted hops only. With no proxy configured
+(the default), a client's own `X-Forwarded-For` is ignored."""
+
+from ipaddress import ip_address, ip_network
+
+import pytest
+
+from dewpoint.apps.ingress.addresses import client_address, limiter_key, parse_proxies
+
+NGINX = parse_proxies("172.18.0.0/16")
+
+
+def test_with_no_proxy_configured_a_forwarded_header_is_ignored() -> None:
+    assert client_address("198.51.100.7", ["203.0.113.9"], ()) == ip_address("198.51.100.7")
+
+
+def test_a_peer_that_is_no_proxy_is_the_client_whatever_it_forwards() -> None:
+    assert client_address("198.51.100.7", ["203.0.113.9"], NGINX) == ip_address("198.51.100.7")
+
+
+def test_a_trusted_proxy_forwards_the_client() -> None:
+    assert client_address("172.18.0.5", ["203.0.113.9"], NGINX) == ip_address("203.0.113.9")
+
+
+def test_a_spoofed_entry_left_of_the_trusted_end_is_never_the_client() -> None:
+    # The client sent `X-Forwarded-For: 10.9.9.9`; the proxy appended the address it saw.
+    assert client_address("172.18.0.5", ["10.9.9.9, 203.0.113.9"], NGINX) == ip_address("203.0.113.9")
+    assert client_address("172.18.0.5", ["10.9.9.9", "203.0.113.9"], NGINX) == ip_address("203.0.113.9")
+
+
+def test_trusted_hops_are_walked_past() -> None:
+    two = parse_proxies("172.18.0.0/16, 192.0.2.10")
+    assert client_address("172.18.0.5", ["203.0.113.9, 192.0.2.10"], two) == ip_address("203.0.113.9")
+
+
+def test_an_unparsable_entry_stops_the_walk_at_the_last_address_trusted_to_have_seen_it() -> None:
+    assert client_address("172.18.0.5", ["203.0.113.9, not-an-address"], NGINX) == ip_address("172.18.0.5")
+    assert client_address("172.18.0.5", [], NGINX) == ip_address("172.18.0.5")
+
+
+def test_no_peer_is_no_address() -> None:
+    assert client_address(None, ["203.0.113.9"], NGINX) is None
+    assert client_address("not-an-address", [], ()) is None
+
+
+def test_an_ipv6_client_is_limited_by_its_64_and_an_ipv4_one_by_itself() -> None:
+    assert limiter_key(ip_address("2001:db8:1:2:aaaa::1")) == limiter_key(ip_address("2001:db8:1:2:bbbb::2"))
+    assert limiter_key(ip_address("2001:db8:1:2::1")) != limiter_key(ip_address("2001:db8:1:3::1"))
+    assert limiter_key(ip_address("203.0.113.9")) != limiter_key(ip_address("203.0.113.10"))
+    assert limiter_key(ip_address("::ffff:203.0.113.9")) == limiter_key(ip_address("203.0.113.9"))
+    assert limiter_key(None) == "unknown"
+
+
+def test_proxies_are_parsed_strictly() -> None:
+    assert parse_proxies("") == ()
+    assert parse_proxies(" 10.0.0.1 ,2001:db8::/32") == (ip_network("10.0.0.1/32"), ip_network("2001:db8::/32"))
+    with pytest.raises(ValueError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
+        parse_proxies("10.0.0.0/33")
+    with pytest.raises(ValueError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
+        parse_proxies("10.0.0.1/8")  # host bits set: say what's meant
+
+
+def test_an_ipv4_client_on_a_dual_stack_socket_is_its_ipv4_address() -> None:
+    assert client_address("::ffff:203.0.113.9", [], ()) == ip_address("203.0.113.9")
+    assert client_address("172.18.0.5", ["::ffff:203.0.113.9"], NGINX) == ip_address("203.0.113.9")
+    assert client_address("::ffff:172.18.0.5", ["203.0.113.9"], NGINX) == ip_address("203.0.113.9")
diff --git a/backend/tests/apps/ingress/test_auth.py b/backend/tests/apps/ingress/test_auth.py
new file mode 100644
index 0000000..391f9c2
--- /dev/null
+++ b/backend/tests/apps/ingress/test_auth.py
@@ -0,0 +1,101 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Authentication (the owner's ruling 2): an HMAC-SHA256 under the endpoint's secret of `<timestamp>.<the exact raw
+body>`, its timestamp within the endpoint's tolerance, or a bearer token matching the endpoint's digest; compared in
+constant time. Anything else is a failure, never an error."""
+
+import hashlib
+import hmac
+import os
+import uuid
+from dataclasses import replace
+
+from starlette.datastructures import Headers
+
+from dewpoint.apps.ingress.auth import authenticate
+from dewpoint.apps.ingress.endpoints import Endpoint
+from dewpoint.core.crypto.ingress import HMAC_SECRET, IngressKey, bearer_digest
+
+KEY = IngressKey("ingress-1", os.urandom(32))
+ID = uuid.uuid4()
+SECRET = b"s3cret-of-the-endpoint"
+BODY = b'{"topic": "alarms", "events": [{"id": 1}]}'
+NOW = 1_800_000_000.0
+
+HMAC = Endpoint(
+    id=ID, tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="hmac", bearer_digest=None,
+    hmac_secret=KEY.seal(HMAC_SECRET, str(ID), SECRET), signature_header="x-signature",
+    timestamp_header="x-timestamp", tolerance_s=300, allowlist=(), body_limit=1024 * 1024, id_source="none",
+    id_pointer=None, id_header=None, events_pointer=None, dedupe_key=b"", key_version=1, public_key=b"\0" * 32,
+)  # fmt: skip
+BEARER = replace(HMAC, auth_kind="bearer", hmac_secret=None, bearer_digest=bearer_digest("dwp_token"))
+
+
+def _signed(stamp: str, body: bytes = BODY, secret: bytes = SECRET) -> Headers:
+    signature = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
+    return Headers({"x-timestamp": stamp, "x-signature": signature})
+
+
+def test_a_signature_of_the_exact_bytes_within_the_tolerance_authenticates() -> None:
+    assert authenticate(HMAC, _signed(str(int(NOW))), BODY, NOW, KEY)
+    assert authenticate(HMAC, _signed(str(int(NOW) - 300)), BODY, NOW, KEY)
+    assert authenticate(HMAC, _signed(str(int(NOW) + 300)), BODY, NOW, KEY)
+
+
+def test_the_signature_may_be_upper_case_or_prefixed() -> None:
+    headers = _signed(str(int(NOW)))
+    assert authenticate(HMAC, Headers({**headers, "x-signature": headers["x-signature"].upper()}), BODY, NOW, KEY)
+    assert authenticate(HMAC, Headers({**headers, "x-signature": "sha256=" + headers["x-signature"]}), BODY, NOW, KEY)
+
+
+def test_a_timestamp_outside_the_tolerance_fails_a_replay_included() -> None:
+    assert not authenticate(HMAC, _signed(str(int(NOW) - 301)), BODY, NOW, KEY)
+    assert not authenticate(HMAC, _signed(str(int(NOW) + 301)), BODY, NOW, KEY)
+
+
+def test_other_bytes_another_secret_or_a_moved_timestamp_fail() -> None:
+    stamp = str(int(NOW))
+    assert not authenticate(HMAC, _signed(stamp), BODY + b" ", NOW, KEY)  # reformatted: other bytes
+    assert not authenticate(HMAC, _signed(stamp, secret=b"another"), BODY, NOW, KEY)
+    moved = Headers({**_signed(stamp), "x-timestamp": str(int(NOW) - 1)})
+    assert not authenticate(HMAC, moved, BODY, NOW, KEY)
+
+
+def test_missing_or_odd_headers_fail_without_an_error() -> None:
+    stamp = str(int(NOW))
+    signature = _signed(stamp)["x-signature"]
+    for headers in (
+        {},
+        {"x-timestamp": stamp},
+        {"x-signature": signature},
+        {"x-timestamp": f" {stamp}", "x-signature": signature},
+        {"x-timestamp": "1e9", "x-signature": signature},
+        {"x-timestamp": "-" + stamp, "x-signature": signature},
+        {"x-timestamp": "9" * 400, "x-signature": signature},
+        {"x-timestamp": stamp[:-1] + "²", "x-signature": signature},  # a digit to `str.isdigit`, but not ASCII
+        {"x-timestamp": stamp, "x-signature": "é" * 64},
+        {"x-timestamp": stamp, "x-signature": ""},
+    ):
+        assert not authenticate(HMAC, Headers(headers), BODY, NOW, KEY), headers
+
+
+def test_a_secret_this_process_cannot_open_fails() -> None:
+    other = IngressKey("ingress-2", os.urandom(32))
+    endpoint = replace(HMAC, hmac_secret=other.seal(HMAC_SECRET, str(ID), SECRET))
+    assert not authenticate(endpoint, _signed(str(int(NOW))), BODY, NOW, KEY)
+    swapped = replace(HMAC, hmac_secret=KEY.seal(HMAC_SECRET, str(uuid.uuid4()), SECRET))  # another endpoint's
+    assert not authenticate(swapped, _signed(str(int(NOW))), BODY, NOW, KEY)
+    for malformed in (b"", b"\x01", b"\x01\x09ingress-1", b"\x02" + bytes(40)):  # truncated, another format
+        assert not authenticate(replace(HMAC, hmac_secret=malformed), _signed(str(int(NOW))), BODY, NOW, KEY)
+
+
+def test_a_bearer_token_authenticates_by_its_digest() -> None:
+    assert authenticate(BEARER, Headers({"authorization": "Bearer dwp_token"}), BODY, NOW, KEY)
+    assert authenticate(BEARER, Headers({"authorization": "bearer dwp_token"}), BODY, NOW, KEY)
+    for value in ("Bearer dwp_other", "Basic dwp_token", "Bearer", "dwp_token", "Bearer  ", "Bearer é"):
+        assert not authenticate(BEARER, Headers({"authorization": value}), BODY, NOW, KEY), value
+    assert not authenticate(BEARER, Headers({}), BODY, NOW, KEY)
+
+
+def test_a_signed_request_doesnt_pass_a_bearer_endpoint_nor_a_token_an_hmac_one() -> None:
+    assert not authenticate(BEARER, _signed(str(int(NOW))), BODY, NOW, KEY)
+    assert not authenticate(HMAC, Headers({"authorization": "Bearer dwp_token"}), BODY, NOW, KEY)
diff --git a/backend/tests/apps/ingress/test_batch.py b/backend/tests/apps/ingress/test_batch.py
new file mode 100644
index 0000000..9599183
--- /dev/null
+++ b/backend/tests/apps/ingress/test_batch.py
@@ -0,0 +1,89 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An authenticated body as the batch ingress records (engine 2b spec §8.3; the owner's ruling 4): its events split,
+each with a new id, its typed dedupe key and content digest (none for an endpoint whose events carry no id), and its
+canonical bytes sealed to the tenant's public key, bound to the tenant, the endpoint and the event's id."""
+
+import json
+import os
+import uuid
+from dataclasses import replace
+
+import pytest
+from cryptography.exceptions import InvalidTag
+
+from dewpoint.apps.ingress.batch import prepare
+from dewpoint.apps.ingress.endpoints import Endpoint
+from dewpoint.core.crypto import events
+from dewpoint.core.ingress.identity import canonical, content_digest, dedupe_key
+from dewpoint.core.ingress.parsing import MalformedError
+
+PRIVATE, PUBLIC = events.generate_keypair()
+SECRET = os.urandom(32)
+ENDPOINT = Endpoint(
+    id=uuid.uuid4(), tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="bearer", bearer_digest=b"",
+    hmac_secret=None, signature_header=None, timestamp_header=None, tolerance_s=300, allowlist=(),
+    body_limit=1024 * 1024, id_source="none", id_pointer=None, id_header=None, events_pointer=None, dedupe_key=b"",
+    key_version=3, public_key=PUBLIC,
+)  # fmt: skip
+POINTER = replace(ENDPOINT, id_source="pointer", id_pointer="/id", events_pointer="/events")
+HEADER = replace(ENDPOINT, id_source="header", id_header="x-batch-id", events_pointer="/events")
+
+
+def _opened(endpoint: Endpoint, event_id: uuid.UUID, blob: bytes) -> bytes:
+    return events.open_sealed(
+        PRIVATE, tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id, event_id=event_id, blob=blob
+    )
+
+
+def test_a_body_without_ids_is_one_event_with_no_dedupe() -> None:
+    batch = prepare(ENDPOINT, b'{ "b": 2, "a": [1, 1.0] }', None, None)
+    assert (len(batch.ids), batch.versions, batch.dedupe, batch.digests) == (1, [3], [None], [None])
+    assert _opened(ENDPOINT, batch.ids[0], batch.sealed[0]) == b'{"a":[1,1.0],"b":2}'  # canonical bytes are sealed
+    assert len(batch.sealed[0]) == len(b'{"a":[1,1.0],"b":2}') + events.OVERHEAD
+
+
+def test_a_sealed_event_opens_only_as_its_own() -> None:
+    batch = prepare(ENDPOINT, b'{"a": 1}', None, None)
+    with pytest.raises(InvalidTag):
+        _opened(replace(ENDPOINT, id=uuid.uuid4()), batch.ids[0], batch.sealed[0])
+    with pytest.raises(InvalidTag):
+        _opened(ENDPOINT, uuid.uuid4(), batch.sealed[0])
+
+
+def test_pointer_ids_are_typed_and_identify_content_not_formatting() -> None:
+    body = {"events": [{"id": 1, "v": "x"}, {"id": "1", "v": "x"}]}
+    batch = prepare(POINTER, json.dumps(body).encode(), None, SECRET)
+    assert batch.dedupe == [dedupe_key(SECRET, "pointer", 1, 0), dedupe_key(SECRET, "pointer", "1", 1)]
+    assert batch.dedupe[0] != batch.dedupe[1]  # 1 and "1" are two ids
+    assert batch.digests == [content_digest(SECRET, canonical(event)) for event in body["events"]]
+    again = prepare(POINTER, b'{"events":[{"v":"x","id":1}]}', None, SECRET)  # reformatted, keys reordered
+    assert (again.dedupe[0], again.digests[0]) == (batch.dedupe[0], batch.digests[0])
+    assert again.ids[0] != batch.ids[0]  # each attempt's events get new internal ids
+
+
+def test_a_header_id_names_each_event_by_its_index() -> None:
+    batch = prepare(HEADER, b'{"events": [{"v": 1}, {"v": 1}]}', "delivery-7", SECRET)
+    assert batch.dedupe == [dedupe_key(SECRET, "header", "delivery-7", i) for i in (0, 1)]
+    assert batch.dedupe[0] != batch.dedupe[1]
+
+
+@pytest.mark.parametrize(
+    ("endpoint", "body", "header"),
+    [
+        (POINTER, b'{"events": [{"v": 1}]}', None),  # no id
+        (POINTER, b'{"events": [{"id": true}]}', None),
+        (POINTER, b'{"events": [{"id": 1.5}]}', None),
+        (POINTER, b'{"events": [{"id": {"x": 1}}]}', None),
+        (POINTER, b'{"events": [{"id": ""}]}', None),
+        (POINTER, b'{"events": [{"id": "' + b"x" * 256 + b'"}]}', None),
+        (POINTER, b'{"events": [{"id": 1}, {"id": null}]}', None),  # one bad id refuses all
+        (HEADER, b'{"events": [{"v": 1}]}', None),  # no header
+        (HEADER, b'{"events": [{"v": 1}]}', ""),
+        (ENDPOINT, b'{"a": 1, "a": 2}', None),
+        (ENDPOINT, b"[]", None),
+        (POINTER, b'{"events": {"id": 1}}', None),
+    ],
+)
+def test_an_event_without_a_valid_id_or_a_malformed_body_refuses_the_whole_body(endpoint, body, header) -> None:
+    with pytest.raises(MalformedError):
+        prepare(endpoint, body, header, SECRET)
diff --git a/backend/tests/apps/ingress/test_config.py b/backend/tests/apps/ingress/test_config.py
new file mode 100644
index 0000000..e5014ec
--- /dev/null
+++ b/backend/tests/apps/ingress/test_config.py
@@ -0,0 +1,58 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's settings come from its own environment only: never a `.env` file, which in a shared checkout or image may
+hold the key-encryption key ingress must never read (engine 2b spec §8.3)."""
+
+import base64
+
+import pytest
+from pydantic import ValidationError
+
+from dewpoint.apps.ingress.config import IngressSettings
+
+
+def test_a_dotenv_file_is_never_read(tmp_path, monkeypatch) -> None:
+    for name in ("DEWPOINT_DATABASE_URL", "DEWPOINT_INGRESS_KEY_B64"):
+        monkeypatch.delenv(name, raising=False)
+    (tmp_path / ".env").write_text(
+        "DEWPOINT_DATABASE_URL=postgresql+asyncpg://x@db/x\n"
+        f"DEWPOINT_INGRESS_KEY_B64={base64.b64encode(b'i' * 32).decode()}\n"
+    )
+    monkeypatch.chdir(tmp_path)
+    with pytest.raises(ValidationError):
+        IngressSettings()
+
+
+def test_its_environment_is_read_and_a_bad_proxy_refused(monkeypatch) -> None:
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
+    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(b"i" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_INGRESS_TRUSTED_PROXIES", "172.18.0.0/16")
+    assert IngressSettings().ingress_trusted_proxies == "172.18.0.0/16"
+    monkeypatch.setenv("DEWPOINT_INGRESS_TRUSTED_PROXIES", "172.18.0.1/16")
+    with pytest.raises(ValidationError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
+        IngressSettings()
+
+
+@pytest.mark.parametrize(
+    ("cap", "valid"), [(5 * 1024 * 1024, True), (1, True), (5 * 1024 * 1024 + 1, False), (0, False)]
+)
+def test_the_global_body_cap_is_at_most_5_mib(monkeypatch, cap: int, valid: bool) -> None:
+    """The database's bursts are sized to cover a body this large (the owner's M2 review): a larger cap set in the
+    configuration would make a body past a small endpoint limit a 429 for ever."""
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
+    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(b"i" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_INGRESS_BODY_CAP", str(cap))
+    if valid:
+        assert IngressSettings().ingress_body_cap == cap
+    else:
+        with pytest.raises(ValidationError, match="ingress_body_cap"):
+            IngressSettings()
+
+
+@pytest.mark.parametrize("key", ["", "not base64!", base64.b64encode(b"short").decode()])
+def test_an_ingress_key_that_isnt_32_bytes_of_base64_is_refused_by_name(monkeypatch, key: str) -> None:
+    """Compose passes an empty key when none is set: ingress says which setting to fix, never quoting a value."""
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://x@db/x")
+    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", key)
+    with pytest.raises(ValidationError, match="DEWPOINT_INGRESS_KEY_B64") as refused:
+        IngressSettings()
+    assert not key or key not in str(refused.value)
diff --git a/backend/tests/apps/ingress/test_hooks.py b/backend/tests/apps/ingress/test_hooks.py
new file mode 100644
index 0000000..61764b3
--- /dev/null
+++ b/backend/tests/apps/ingress/test_hooks.py
@@ -0,0 +1,209 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`POST /hooks/<endpoint_id>` before an attempt is recorded (engine 2b spec §8.3; the owner's rulings 2, 5, 7 and 11
+and the second review), in this order: at most so many requests in flight (503, before the body is read); an address
+that has failed too often (429, before any database call); the global body cap (413) and the body's deadline (408),
+both counted against the address; then the endpoint, the address against its allowlist and the authentication, every
+failure one bodiless 401, counted against the address."""
+
+import asyncio
+import uuid
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.ingress.main import create_app, declared_over
+from dewpoint.core.db import make_engine, make_sessionmaker
+from tests.apps.ingress.support import Clock, bearer, bearer_endpoint, client, hmac_endpoint, settings, signed
+
+BODY = b'{"event": "ping"}'
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+@pytest.fixture
+async def make_app(pg_url, _test_users):  # type: ignore[no-untyped-def]
+    apps = []
+
+    def make(**overrides):  # type: ignore[no-untyped-def]
+        clock = Clock()
+        app = create_app(settings(pg_url, **overrides), clock=clock)
+        app.state.clock = clock
+        apps.append(app)
+        return app
+
+    yield make
+    for app in apps:
+        await app.state.engine.dispose()
+
+
+def _authenticated(response) -> bool:  # type: ignore[no-untyped-def]
+    """Past every check, and recorded."""
+    return response.status_code == 200 and response.json() == {"accepted": 1, "duplicates": 0}
+
+
+async def test_health(make_app) -> None:
+    async with client(make_app()) as c:
+        assert (await c.get("/health/live")).json() == {"status": "ok"}
+        assert (await c.get("/health/ready")).json() == {"status": "ready"}
+
+
+async def test_a_signed_and_a_bearer_request_pass(make_app, owner_sessionmaker) -> None:
+    _, signed_endpoint = await hmac_endpoint(owner_sessionmaker)
+    _, bearer_endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    async with client(make_app()) as c:
+        assert _authenticated(await c.post(f"/hooks/{signed_endpoint}", content=BODY, headers=signed(BODY)))
+        assert _authenticated(await c.post(f"/hooks/{bearer_endpoint_id}", content=BODY, headers=bearer()))
+
+
+async def test_every_refusal_before_recording_is_the_same_bodiless_401(make_app, owner_sessionmaker) -> None:
+    _, endpoint_id = await hmac_endpoint(owner_sessionmaker)
+    _, disabled = await hmac_endpoint(owner_sessionmaker, enabled=False)
+    erasing, of_erasing = await hmac_endpoint(owner_sessionmaker)
+    _, fenced = await hmac_endpoint(owner_sessionmaker, allowlist=["203.0.113.0/24"])
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": erasing})
+    app = make_app()
+    stale = signed(BODY, now=app.state.clock.now - 301)
+    refusals = {
+        "unknown endpoint": (f"/hooks/{uuid.uuid4()}", signed(BODY)),
+        "not an id": ("/hooks/not-a-uuid", signed(BODY)),
+        "disabled endpoint": (f"/hooks/{disabled}", signed(BODY)),
+        "erasing tenant": (f"/hooks/{of_erasing}", signed(BODY)),
+        "disallowed address": (f"/hooks/{fenced}", signed(BODY)),
+        "wrong signature": (f"/hooks/{endpoint_id}", signed(BODY, secret=b"another")),
+        "stale timestamp": (f"/hooks/{endpoint_id}", stale),
+        "unsigned": (f"/hooks/{endpoint_id}", {}),
+        "a token for a signed endpoint": (f"/hooks/{endpoint_id}", bearer()),
+    }
+    seen = set()
+    async with client(app) as c:
+        for name, (path, headers) in refusals.items():
+            response = await c.post(path, content=BODY, headers=headers)
+            assert (response.status_code, response.content) == (401, b""), name
+            seen.add(tuple(sorted(response.headers.items())))
+    assert len(seen) == 1  # the same headers too
+
+
+async def test_a_spoofed_forwarded_address_never_passes_an_allowlist(make_app, owner_sessionmaker) -> None:
+    _, fenced = await hmac_endpoint(owner_sessionmaker, allowlist=["203.0.113.0/24"])
+    spoofed = signed(BODY) | {"x-forwarded-for": "203.0.113.5"}
+    async with client(make_app()) as c:  # no proxy configured: the header is ignored
+        assert (await c.post(f"/hooks/{fenced}", content=BODY, headers=spoofed)).status_code == 401
+    behind = make_app(ingress_trusted_proxies="198.51.100.0/24")  # the client (198.51.100.7) is now a proxy
+    async with client(behind) as c:
+        assert _authenticated(await c.post(f"/hooks/{fenced}", content=BODY, headers=spoofed))
+        prepended = signed(BODY) | {"x-forwarded-for": "203.0.113.5, 192.0.2.1"}  # its client wrote the first
+        assert (await c.post(f"/hooks/{fenced}", content=BODY, headers=prepended)).status_code == 401
+    async with client(make_app(), address=("203.0.113.5", 40000)) as c:
+        assert _authenticated(await c.post(f"/hooks/{fenced}", content=BODY, headers=signed(BODY)))
+
+
+async def test_an_address_over_its_failures_is_refused_before_any_database_call(make_app, owner_sessionmaker) -> None:
+    _, endpoint_id = await hmac_endpoint(owner_sessionmaker)
+    app = make_app(ingress_address_failures=3)
+    async with client(app) as c:
+        for _ in range(3):
+            assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY, headers=signed(BODY))).status_code == 401
+        sessions, app.state.sessionmaker = app.state.sessionmaker, None  # any database call now fails the request
+        refused = await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY))
+        assert (refused.status_code, refused.json(), refused.headers["retry-after"]) == (
+            429, {"error": "rate_limited"}, "60",
+        )  # fmt: skip
+        app.state.sessionmaker = sessions
+    async with client(app, address=("192.0.2.44", 40000)) as c:  # another address isn't
+        assert _authenticated(await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY)))
+    app.state.clock.now += 60  # its minute is over
+    async with client(app) as c:
+        assert _authenticated(await c.post(f"/hooks/{endpoint_id}", content=BODY, headers=signed(BODY)))
+
+
+async def test_the_limit_counts_an_ipv6_client_by_its_64(make_app) -> None:
+    app = make_app(ingress_address_failures=2)
+    async with client(app, address=("2001:db8:1:2::1", 40000)) as c:
+        await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)
+    async with client(app, address=("2001:db8:1:2::ffff", 40000)) as c:
+        await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)
+        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429
+
+
+async def test_a_body_past_the_global_cap_is_413_and_counts_against_its_address(make_app) -> None:
+    app = make_app(ingress_body_cap=1000, ingress_address_failures=2)
+
+    async def chunked():  # no Content-Length: refused one byte past the cap as it arrives
+        for _ in range(11):
+            yield b"x" * 100
+
+    async with client(app) as c:
+        declared = await c.post(f"/hooks/{uuid.uuid4()}", content=b"x" * 1001)
+        assert (declared.status_code, declared.json()) == (413, {"error": "too_large"})
+        streamed = await c.post(f"/hooks/{uuid.uuid4()}", content=chunked())
+        assert (streamed.status_code, streamed.json()) == (413, {"error": "too_large"})
+        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429
+
+
+async def test_a_body_slower_than_its_deadline_is_408_and_closed_and_counts(make_app) -> None:
+    app = make_app(ingress_body_deadline_s=0.2, ingress_address_failures=1)
+
+    async def slow():
+        yield b'{"event":'
+        await asyncio.sleep(5)
+        yield b' "ping"}'
+
+    async with client(app) as c:
+        timed_out = await c.post(f"/hooks/{uuid.uuid4()}", content=slow())
+        assert (timed_out.status_code, timed_out.headers["connection"]) == (408, "close")
+        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429
+
+
+async def test_past_the_in_flight_limit_a_request_is_503_before_its_body_is_read(make_app) -> None:
+    app = make_app(ingress_max_in_flight=1)
+    release, read = asyncio.Event(), []
+
+    async def held():
+        await release.wait()
+        yield BODY
+
+    async def counted():
+        read.append(True)
+        yield BODY
+
+    async with client(app) as c:
+        first = asyncio.create_task(c.post(f"/hooks/{uuid.uuid4()}", content=held()))
+        await asyncio.sleep(0.05)
+        busy = await c.post(f"/hooks/{uuid.uuid4()}", content=counted())
+        assert (busy.status_code, busy.json(), busy.headers["retry-after"]) == (503, {"error": "busy"}, "1")
+        assert read == []
+        release.set()
+        assert (await first).status_code == 401
+        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 401  # the slot came back
+
+
+async def test_an_unavailable_database_is_503_and_not_the_clients_failure(make_app) -> None:
+    app = make_app(ingress_address_failures=1)
+    down = make_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
+    app.state.sessionmaker = make_sessionmaker(down)
+    async with client(app) as c:
+        for _ in range(2):
+            response = await c.post(f"/hooks/{uuid.uuid4()}", content=BODY, headers=signed(BODY))
+            assert (response.status_code, response.json(), response.headers["retry-after"]) == (
+                503, {"error": "unavailable"}, "5",
+            )  # fmt: skip
+    await down.dispose()
+
+
+async def test_a_declared_length_past_any_integer_limit_is_the_counted_413(make_app) -> None:
+    """A digit string too long for `int()` (the owner's M2 review) is still a length past the cap."""
+    app = make_app(ingress_address_failures=1)
+    async with client(app) as c:
+        huge = await c.post(f"/hooks/{uuid.uuid4()}", content=b"x", headers={"content-length": "9" * 5000})
+        assert (huge.status_code, huge.json()) == (413, {"error": "too_large"})
+        assert (await c.post(f"/hooks/{uuid.uuid4()}", content=BODY)).status_code == 429
+
+
+def test_a_declared_length_is_compared_without_converting_an_unbounded_string() -> None:
+    cap = 5 * 1024 * 1024
+    assert declared_over("9" * 5000, cap) and declared_over(str(cap + 1), cap) and declared_over("1" + "0" * 8, cap)
+    assert (
+        not declared_over(str(cap), cap) and not declared_over("0" * 5000 + "12", cap) and not declared_over("0", cap)
+    )
+    for odd in ("", "1²", "-1", "+5", " 5", "1e9", "١٢"):  # not a length: the bytes are counted as they arrive
+        assert not declared_over(odd, cap), odd
diff --git a/backend/tests/apps/ingress/test_hooks_recording.py b/backend/tests/apps/ingress/test_hooks_recording.py
new file mode 100644
index 0000000..e7f898f
--- /dev/null
+++ b/backend/tests/apps/ingress/test_hooks_recording.py
@@ -0,0 +1,225 @@
+# SPDX-License-Identifier: Apache-2.0
+"""After authentication, every attempt goes through `record_inbound_events` (engine 2b spec §8.3; "Work limits" in the
+2b-3b outline): over the endpoint's body limit 413, malformed 400 (both paying their rate budget), short of tokens 429
+with `Retry-After`, an id reused for other content 409, over a pending quota 429 (`Retry-After` 30), over a retained cap
+429 without one, recorded 200 with its counts, answered only once committed. A tenant without an inbound key fails
+closed."""
+
+import json
+import os
+import uuid
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.ingress import main
+from dewpoint.apps.ingress.main import create_app
+from dewpoint.core.crypto import events
+from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET, IngressKey
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.ingress import keys as event_keys
+from tests.apps.ingress.support import (
+    SECRET,
+    Clock,
+    bearer,
+    bearer_endpoint,
+    client,
+    hmac_endpoint,
+    sealed_dedupe_key,
+    settings,
+    signed,
+)
+from tests.core.ingress.support import KEYRING, endpoint, events_of, state
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+MIB = 1024 * 1024
+ALARMS = json.dumps({"topic": "alarms", "events": [{"id": "a-1", "type": "ap_down"}, {"id": "a-2", "type": "ap_up"}]})
+
+
+@pytest.fixture
+async def app(pg_url, _test_users):  # type: ignore[no-untyped-def]
+    application = create_app(settings(pg_url), clock=Clock())
+    yield application
+    await application.state.engine.dispose()
+
+
+async def _post(app, endpoint_id: uuid.UUID, body: bytes | str, **headers: str):  # type: ignore[no-untyped-def]
+    raw = body.encode() if isinstance(body, str) else body
+    async with client(app) as c:
+        return await c.post(f"/hooks/{endpoint_id}", content=raw, headers=bearer() | headers)
+
+
+async def test_a_batch_is_recorded_sealed_to_its_tenant_and_counted(
+    app, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant, endpoint_id = await bearer_endpoint(
+        owner_sessionmaker, id_source="pointer", id_pointer="/id", events_pointer="/events"
+    )
+    response = await _post(app, endpoint_id, ALARMS)
+    assert (response.status_code, response.json()) == (200, {"accepted": 2, "duplicates": 0})
+    rows = await events_of(owner_sessionmaker, endpoint_id)
+    assert [r["status"] for r in rows] == ["pending", "pending"]
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        private = await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 1)
+    opened = sorted(
+        events.open_sealed(private, tenant_id=tenant, endpoint_id=endpoint_id, event_id=r["id"], blob=r["sealed"])
+        for r in rows
+    )
+    assert opened == [b'{"id":"a-1","type":"ap_down"}', b'{"id":"a-2","type":"ap_up"}']
+    assert (await state(owner_sessionmaker, endpoint_id))["pending_events"] == 2
+
+
+async def test_a_retried_batch_is_acknowledged_and_an_id_reused_for_other_content_is_409(
+    app, owner_sessionmaker
+) -> None:
+    _, endpoint_id = await hmac_endpoint(
+        owner_sessionmaker, id_source="pointer", id_pointer="/id", events_pointer="/events"
+    )
+    body = ALARMS.encode()
+    assert (await _post(app, endpoint_id, body, **signed(body))).json() == {"accepted": 2, "duplicates": 0}
+    reformatted = json.dumps(json.loads(body), indent=2).encode()  # the same content, other bytes
+    again = await _post(app, endpoint_id, reformatted, **signed(reformatted))
+    assert (again.status_code, again.json()) == (200, {"accepted": 0, "duplicates": 2})
+    reused = json.dumps({"events": [{"id": "a-3"}, {"id": "a-1", "type": "other"}]}).encode()
+    refused = await _post(app, endpoint_id, reused, **signed(reused))
+    assert (refused.status_code, refused.json()) == (409, {"error": "event_id_reused"})
+    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # a-3 wasn't recorded either
+
+
+async def test_without_ids_each_attempt_is_new_events(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    for _ in range(2):
+        assert (await _post(app, endpoint_id, '{"ping": 1}')).json() == {"accepted": 1, "duplicates": 0}
+    assert len(await events_of(owner_sessionmaker, endpoint_id)) == 2  # at-least-once, as documented
+
+
+async def test_a_header_id_names_the_batch(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(
+        owner_sessionmaker, id_source="header", id_header="x-delivery", events_pointer="/events"
+    )
+    body = '{"events": [{"v": 1}, {"v": 1}]}'
+    assert (await _post(app, endpoint_id, body, **{"x-delivery": "d-9"})).json() == {"accepted": 2, "duplicates": 0}
+    assert (await _post(app, endpoint_id, body, **{"x-delivery": "d-9"})).json() == {"accepted": 0, "duplicates": 2}
+    missing = await _post(app, endpoint_id, body)
+    assert (missing.status_code, missing.json()) == (400, {"error": "malformed"})
+
+
+@pytest.mark.parametrize(
+    "body",
+    [
+        b'{"a": 1, "a": 1}',
+        b'{"a": 1e400}',  # overflow (the owner's M2 check)
+        b'{"a": "\\ud800"}',  # an escaped unpaired surrogate (the owner's M2 check)
+        b'{"a": NaN}',
+        b"[1]",
+        b"\xff",
+    ],
+)
+async def test_a_malformed_body_is_400_and_pays_its_budget(app, owner_sessionmaker, body: bytes) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    before = await state(owner_sessionmaker, endpoint_id)
+    response = await _post(app, endpoint_id, body)
+    assert (response.status_code, response.json()) == (400, {"error": "malformed"})
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+async def test_a_body_over_the_endpoints_limit_is_413_and_pays_for_its_bytes(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, body_limit=100)
+    before = await state(owner_sessionmaker, endpoint_id)
+    response = await _post(app, endpoint_id, json.dumps({"pad": "x" * 200}))
+    assert (response.status_code, response.json()) == (413, {"error": "too_large"})
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert before["request_tokens"] - after["request_tokens"] == pytest.approx(1, abs=0.1)
+    assert before["byte_tokens"] - after["byte_tokens"] >= 211
+    assert (await _post(app, endpoint_id, '{"pad": "fits"}')).status_code == 200
+
+
+async def test_short_of_tokens_is_429_with_the_wait(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, request_burst=1, request_per_s=0.01, request_tokens=1)
+    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
+    limited = await _post(app, endpoint_id, '{"n": 2}')
+    assert (limited.status_code, limited.json()) == (429, {"error": "rate_limited"})
+    assert 90 <= int(limited.headers["retry-after"]) <= 100
+
+
+async def test_over_a_pending_quota_is_429_retry_in_30(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, pending_events_max=1)
+    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
+    over = await _post(app, endpoint_id, '{"n": 2}')
+    assert (over.status_code, over.json(), over.headers["retry-after"]) == (429, {"error": "quota_exceeded"}, "30")
+
+
+async def test_over_a_retained_cap_is_429_without_a_retry_after(app, owner_sessionmaker) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, retained_events_max=1)
+    assert (await _post(app, endpoint_id, '{"n": 1}')).status_code == 200
+    full = await _post(app, endpoint_id, '{"n": 2}')
+    assert (full.status_code, full.json()) == (429, {"error": "retained_full"})
+    assert "retry-after" not in full.headers
+
+
+async def test_a_tenant_without_an_inbound_key_fails_closed(app, owner_sessionmaker) -> None:
+    tenant, endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("delete from tenant_event_keys where tenant_id = :t"), {"t": tenant})
+    response = await _post(app, endpoint_id, '{"n": 1}')
+    assert (response.status_code, response.json()) == (503, {"error": "unavailable"})
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+async def test_an_endpoint_disabled_after_it_was_resolved_is_the_same_401(app, owner_sessionmaker, monkeypatch) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    resolved = main.resolve
+
+    async def then_disabled(s, found_id):  # type: ignore[no-untyped-def]
+        endpoint = await resolved(s, found_id)
+        async with owner_sessionmaker() as o, o.begin():
+            await o.execute(text("update webhook_endpoints set enabled = false where id = :e"), {"e": found_id})
+        return endpoint
+
+    monkeypatch.setattr(main, "resolve", then_disabled)
+    response = await _post(app, endpoint_id, '{"n": 1}')
+    assert (response.status_code, response.content) == (401, b"")
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+@pytest.mark.parametrize("sealed", ["malformed", "another key's"])
+async def test_an_unopenable_hmac_secret_is_the_401_and_an_unopenable_dedupe_key_503(
+    app, owner_sessionmaker, sealed
+) -> None:
+    other = IngressKey("ingress-2", os.urandom(32))
+    endpoint_id = uuid.uuid4()
+    secret = b"\x01" if sealed == "malformed" else other.seal(HMAC_SECRET, str(endpoint_id), SECRET)
+    _, signed_endpoint = await endpoint(
+        owner_sessionmaker, endpoint_id, auth_kind="hmac", bearer_digest=None, hmac_secret=secret,
+        signature_header="x-signature", timestamp_header="x-timestamp", dedupe_key=sealed_dedupe_key(endpoint_id),
+    )  # fmt: skip
+    body = b'{"n": 1}'
+    refused = await _post(app, signed_endpoint, body, **signed(body))
+    assert (refused.status_code, refused.content) == (401, b"")
+    dedupe_id = uuid.uuid4()
+    dedupe = b"\x01" if sealed == "malformed" else other.seal(DEDUPE_KEY, str(dedupe_id), os.urandom(32))
+    _, pointer_endpoint = await bearer_endpoint(
+        owner_sessionmaker, id_source="pointer", id_pointer="/id", dedupe_key=dedupe
+    )
+    unavailable = await _post(app, pointer_endpoint, '{"id": 1}')
+    assert (unavailable.status_code, unavailable.json()) == (503, {"error": "unavailable"})
+    assert await events_of(owner_sessionmaker, pointer_endpoint) == []
+
+
+@pytest.mark.parametrize("size", [70_000, 5 * MIB])
+async def test_at_the_smallest_burst_a_body_up_to_the_global_cap_past_a_tiny_limit_is_413(
+    app, owner_sessionmaker, size: int
+) -> None:
+    """The owner's M2 review: with `body_limit=1` the schema used to allow a 64,005-byte burst, and a 70,000-byte body
+    (under the global cap) was a 429 for ever, never its 413. Now the smallest burst the schema allows covers the
+    global cap: from a full bucket, any body ingress reads before authenticating gets its 413, paid for."""
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker, body_limit=1, byte_burst=5 * MIB, byte_tokens=5 * MIB)
+    response = await _post(app, endpoint_id, b"x" * size)
+    assert (response.status_code, response.json()) == (413, {"error": "too_large"})
+    after = await state(owner_sessionmaker, endpoint_id)
+    assert after["request_tokens"] == pytest.approx(99, abs=0.1)
+    assert 5 * MIB - after["byte_tokens"] == pytest.approx(size, abs=1)
diff --git a/backend/tests/apps/ingress/test_limits.py b/backend/tests/apps/ingress/test_limits.py
new file mode 100644
index 0000000..04b25b1
--- /dev/null
+++ b/backend/tests/apps/ingress/test_limits.py
@@ -0,0 +1,41 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress's limits before authentication (the owner's rulings 5 and 7): each address may fail 30 requests a minute in
+a process, held in a bounded table in memory; and at most 32 requests are in flight in a process."""
+
+from dewpoint.apps.ingress.limits import FailureLimiter, InFlight
+
+
+def test_an_address_is_refused_once_it_has_failed_its_limit_until_its_minute_ends() -> None:
+    limiter = FailureLimiter(failures=3, window_s=60)
+    for t in (0.0, 1.0, 2.0):
+        assert limiter.blocked("a", t) is None
+        limiter.fail("a", t)
+    assert limiter.blocked("a", 2.5) == 58  # whole seconds, rounded up, until the window that began at 0 ends
+    assert limiter.blocked("b", 2.5) is None  # another address isn't affected
+    assert limiter.blocked("a", 60.0) is None  # a new window
+
+
+def test_failures_in_an_earlier_window_dont_count() -> None:
+    limiter = FailureLimiter(failures=2, window_s=60)
+    limiter.fail("a", 0.0)
+    limiter.fail("a", 61.0)
+    assert limiter.blocked("a", 61.5) is None
+
+
+def test_the_table_is_bounded_dropping_the_address_that_failed_least_recently() -> None:
+    limiter = FailureLimiter(failures=1, window_s=60, max_entries=2)
+    limiter.fail("a", 0.0)
+    limiter.fail("b", 30.0)
+    limiter.fail("a", 31.0)  # a failed again: b is now the least recent
+    limiter.fail("c", 70.0)  # b goes
+    assert len(limiter) == 2
+    assert limiter.blocked("b", 70.0) is None
+    assert limiter.blocked("c", 70.0) is not None
+
+
+def test_in_flight_admits_up_to_its_limit() -> None:
+    gate = InFlight(2)
+    assert gate.try_acquire() and gate.try_acquire()
+    assert not gate.try_acquire()
+    gate.release()
+    assert gate.try_acquire()
diff --git a/backend/tests/apps/ingress/test_startup.py b/backend/tests/apps/ingress/test_startup.py
new file mode 100644
index 0000000..19e132b
--- /dev/null
+++ b/backend/tests/apps/ingress/test_startup.py
@@ -0,0 +1,64 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Ingress stays a gated prototype until 2b-4 (the owner's rulings 8 and 13): it starts only when the recorded
+environment is `development`, read through `ingress_environment()`, its only way to read it."""
+
+import base64
+
+import pytest
+
+from dewpoint.apps.ingress.main import IngressRefusedError, create_app
+from dewpoint.core.platform.service import DEVELOPMENT, PRODUCTION, record_environment
+from tests.apps.ingress.support import bearer, bearer_endpoint, client, settings
+from tests.core.ingress.support import events_of
+
+
+async def _starts(pg_url: str) -> None:
+    app = create_app(settings(pg_url))
+    try:
+        async with app.router.lifespan_context(app):
+            pass
+    finally:
+        await app.state.engine.dispose()
+
+
+async def test_without_a_recorded_environment_ingress_refuses_to_start(pg_url, _test_users) -> None:
+    with pytest.raises(IngressRefusedError, match=r"development deployment .*\(recorded: none\)"):
+        await _starts(pg_url)
+
+
+async def test_in_production_ingress_refuses_to_start(pg_url, _test_users, owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    with pytest.raises(IngressRefusedError, match=r"\(recorded: production\)"):
+        await _starts(pg_url)
+
+
+async def test_in_development_ingress_starts(pg_url, _test_users, owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="default")
+    await _starts(pg_url)
+
+
+async def test_an_attempt_outside_development_is_503_and_records_nothing(
+    pg_url, _test_users, owner_sessionmaker
+) -> None:
+    _, endpoint_id = await bearer_endpoint(owner_sessionmaker)
+    app = create_app(settings(pg_url))  # a test transport skips the startup check: the function refuses anyway
+    try:
+        async with client(app) as c:
+            response = await c.post(f"/hooks/{endpoint_id}", content=b'{"n": 1}', headers=bearer())
+    finally:
+        await app.state.engine.dispose()
+    assert (response.status_code, response.json()) == (503, {"error": "unavailable"})
+    assert await events_of(owner_sessionmaker, endpoint_id) == []
+
+
+@pytest.mark.parametrize("name", ["DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"])
+def test_a_key_encryption_key_in_its_environment_refuses_the_app_itself(pg_url, monkeypatch, name) -> None:
+    """Not only `dewpoint ingress`: an app made directly (uvicorn's factory, an embedding) refuses too (the owner's M2
+    review), before its lifespan, so a server run with its lifespan off can't skip the check."""
+    value = base64.b64encode(b"k" * 32).decode()
+    monkeypatch.setenv(name, value)
+    with pytest.raises(IngressRefusedError, match=name) as refused:
+        create_app(settings(pg_url))
+    assert value not in str(refused.value)
diff --git a/backend/tests/core/ingress/support.py b/backend/tests/core/ingress/support.py
index 826905a..34be320 100644
--- a/backend/tests/core/ingress/support.py
+++ b/backend/tests/core/ingress/support.py
@@ -21,9 +21,9 @@ RECORD = text(
 )
 
 
-async def endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
+async def endpoint(owner: Any, endpoint_id: uuid.UUID | None = None, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
     """A tenant (with its keypair) and one of its endpoints, a bearer one unless `columns` say otherwise."""
-    tenant, endpoint_id = uuid.uuid4(), uuid.uuid4()
+    tenant, endpoint_id = uuid.uuid4(), endpoint_id or uuid.uuid4()
     async with owner() as s, s.begin():
         user = (await create_user(s, email=f"{tenant.hex[:10]}@corp.test", password="violet-otter-canyon-42")).id
         await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": tenant, "s": tenant.hex})
diff --git a/backend/tests/core/ingress/test_parsing.py b/backend/tests/core/ingress/test_parsing.py
new file mode 100644
index 0000000..abc01ec
--- /dev/null
+++ b/backend/tests/core/ingress/test_parsing.py
@@ -0,0 +1,102 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A body's strict parsing and its events (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline and the M2
+checks): UTF-8 JSON only; a duplicate key anywhere, NaN or an infinity, a number past binary64's range (`1e400`), an
+escaped unpaired surrogate, an integer of more than 4,300 digits, or nesting deeper than 64 levels refuses the whole
+body; events are the body itself or the array at the endpoint's events pointer, objects only, 1 to 500 of them."""
+
+import json
+
+import pytest
+
+from dewpoint.core.ingress.parsing import MAX_DEPTH, MAX_EVENTS, MalformedError, events_of, parse
+from dewpoint.core.ingress.pointer import PointerError, resolve
+
+
+def test_a_plain_object_parses() -> None:
+    assert parse(b'{"a": [1, 2.5, "x", null, true], "b": {"c": -3}}') == {
+        "a": [1, 2.5, "x", None, True], "b": {"c": -3},
+    }  # fmt: skip
+
+
+@pytest.mark.parametrize(
+    ("name", "body"),
+    [
+        ("not UTF-8", b'{"a": "\xff"}'),
+        ("UTF-16", '{"a": 1}'.encode("utf-16")),
+        ("not JSON", b"{'a': 1}"),
+        ("trailing data", b'{"a": 1} {"b": 2}'),
+        ("empty", b""),
+        ("a duplicate key", b'{"a": 1, "a": 1}'),
+        ("a nested duplicate key", b'{"a": [{"b": 1, "c": 2, "b": 3}]}'),
+        ("NaN", b'{"a": NaN}'),
+        ("Infinity", b'{"a": Infinity}'),
+        ("-Infinity", b'{"a": -Infinity}'),
+        ("overflow", b'{"a": 1e400}'),
+        ("negative overflow", b'{"a": [-1e400]}'),
+        ("an escaped lone high surrogate", b'{"a": "\\ud800"}'),
+        ("an escaped lone low surrogate", b'{"a": ["x\\udc00y"]}'),
+        ("a surrogate in a key", b'{"\\udbff": 1}'),
+        ("reversed surrogates", b'{"a": "\\udc00\\ud800"}'),
+        ("an integer past 4,300 digits", b'{"a": ' + b"9" * 4301 + b"}"),
+        ("a negative one", b'{"a": -' + b"9" * 4301 + b"}"),
+        ("65 levels", b"[" * 65 + b"]" * 65),
+        ("65 levels of objects", b'{"a":' * 64 + b"[]" + b"}" * 64),
+        ("far too deep", b"[" * 100_000 + b"]" * 100_000),
+        ("far too deep, objects", b'{"a":' * 100_000 + b"1" + b"}" * 100_000),
+    ],
+)
+def test_a_body_is_refused_whole(name: str, body: bytes) -> None:
+    with pytest.raises(MalformedError):
+        parse(body)
+
+
+def test_what_strict_parsing_still_accepts() -> None:
+    assert parse(b'{"a": "\\ud83d\\ude00"}') == {"a": "\U0001f600"}  # a paired escape is one character
+    assert parse(b'{"a": "\\\\ud800"}') == {"a": "\\ud800"}  # an escaped backslash, then text
+    assert parse(b'{"a": ' + b"9" * 4300 + b"}") == {"a": int("9" * 4300)}
+    assert parse(b'{"a": 1e308, "b": 5e-324, "c": 1e-400}') == {"a": 1e308, "b": 5e-324, "c": 0.0}
+    assert parse('{"é": "ü"}'.encode()) == {"é": "ü"}
+    assert MAX_DEPTH == 64
+    parse(b"[" * 64 + b"]" * 64)
+    parse(b'{"a":' * 63 + b"[1]" + b"}" * 63)
+    parse(b'{"a":' * 63 + b'["\\ud83d\\ude00"]' + b"}" * 63)  # strings checked too: still 64 levels
+
+
+def test_the_refusal_quotes_nothing_of_the_body() -> None:
+    with pytest.raises(MalformedError) as refused:
+        parse(b'{"secret": "canary-7f3a", "secret": 1}')
+    assert "canary" not in str(refused.value)
+    assert refused.value.__cause__ is None and refused.value.__suppress_context__
+
+
+def test_without_an_events_pointer_the_body_is_one_event() -> None:
+    assert events_of({"a": 1}, None) == [{"a": 1}]
+    for document in ([{"a": 1}], "x", 1, None):
+        with pytest.raises(MalformedError):
+            events_of(document, None)
+
+
+def test_an_events_pointer_names_an_array_of_objects() -> None:
+    document = {"topic": "alarms", "events": [{"id": 1}, {"id": 2}]}
+    assert events_of(document, "/events") == [{"id": 1}, {"id": 2}]
+    assert events_of([{"id": 1}], "") == [{"id": 1}]
+    for bad in ({"events": {"id": 1}}, {"events": []}, {"events": [{"id": 1}, 2]}, {"events": [[]]}, {"other": []}):
+        with pytest.raises(MalformedError):
+            events_of(bad, "/events")
+
+
+def test_at_most_500_events() -> None:
+    assert len(events_of({"e": [{}] * MAX_EVENTS}, "/e")) == 500
+    with pytest.raises(MalformedError):
+        events_of({"e": [{}] * (MAX_EVENTS + 1)}, "/e")
+
+
+def test_a_pointer_resolves_as_rfc_6901_says() -> None:
+    document = json.loads('{"a/b": {"m~n": [10, {"x": 1}]}, "": 5, "0": "zero"}')
+    assert resolve(document, "") == document
+    assert resolve(document, "/a~1b/m~0n/1/x") == 1
+    assert resolve(document, "/") == 5
+    assert resolve(document, "/0") == "zero"
+    for pointer in ("a", "/missing", "/a~1b/m~0n/2", "/a~1b/m~0n/-", "/a~1b/m~0n/01", "/a~1b/m~0n/+1", "/0/x"):
+        with pytest.raises(PointerError):
+            resolve(document, pointer)
```

**Checkpoint (milestone 2).** Focused: as milestone 1, with `tests/apps/ingress` (262 passed); no migration. The nginx
probe (Task 4's evidence). The owner held it twice (milestone ruling 2) and approved it as a prototype checkpoint
(2026-10-04).

## Milestone 3 — Matching and management

### Task 5: Every dispatcher matches inbound events while the gate is on, fairly, under one lock order

**Commit:** `54dab51` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/migrations/versions/0033_event_matching.py`, `backend/src/dewpoint/apps/dispatcher/matching.py`,
`backend/src/dewpoint/core/ingress/filters.py`, `backend/tests/apps/dispatcher/inbound.py`,
`backend/tests/apps/dispatcher/test_matching.py`, `backend/tests/core/ingress/test_filters.py`,
`backend/tests/core/ingress/test_matching_schema.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/core/models/ingress.py`,
`backend/tests/apps/dispatcher/test_main.py`

**What it does:**

`event_candidates(n)` (0033, the dispatcher's alone) picks pending, due events, ids only, every tenant's oldest before
any tenant's second. Each is matched in its own transaction: the gate's and the tenant's lifecycle locks shared, the
gate, the environment and the tenant rechecked under them; the endpoint row, the tenant's counter row, then the event
row with SKIP LOCKED, rechecked pending and due. It's opened with the tenant's private key; each enabled binding whose
filter holds (typed JSON-pointer equality, at most 8 clauses) admits one request, in workflow-id order: source
`webhook`, key `evt:<event id>:<workflow id>`, the event as the trigger, frozen or recorded refused. The event becomes
`matched` with its request count or `unmatched`, and its pending counters are released. More enabled bindings than 20
wait with an alert. A cycle matches only when it observed the current build. ORM models for the ingress tables; 0033
also adds the recount's pacing and the API's cancel grants. Races: two dispatchers on one event and one endpoint, a
duplicate's insertion against matching, and the matcher against the exclusive tenant lock, each way. A race test that
fails while holding a match releases it at teardown: a regression fails, never hangs the suite.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/dispatcher/test_main.py tests/apps/dispatcher/test_matching.py tests/core/ingress/test_filters.py
  tests/core/ingress/test_matching_schema.py`. Replay result (exit 1), shortened:

```
    [SQL: update inbound_events set status = 'cancelled', reason = 'cancelled', ended_at = now() where id = any($1)]
    [parameters: ([UUID('1cf1e420-1be3-48fc-857b-f1fdbb4dbea0'), UUID('00707f1e-fbd6-4718-acb7-4253d5f58ade')],)]
    (Background on this error at: https://sqlalche.me/e/21/f405)
<venv>/lib/python3.14/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:840: sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) permission denied for table inbound_events
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_main.py::test_a_cycle_matches_events_only_when_it_observed_the_current_build
FAILED tests/core/ingress/test_matching_schema.py::test_every_tenants_oldest_due_event_comes_before_any_tenants_second
FAILED tests/core/ingress/test_matching_schema.py::test_only_due_pending_events_are_candidates
FAILED tests/core/ingress/test_matching_schema.py::test_a_tenant_is_recounted_at_most_every_ten_minutes
FAILED tests/core/ingress/test_matching_schema.py::test_the_candidate_functions_are_the_dispatchers_alone
FAILED tests/core/ingress/test_matching_schema.py::test_the_api_cancels_within_its_tenant_and_releases_the_pending_counters
ERROR tests/apps/dispatcher/test_matching.py - ImportError while importing te...
ERROR tests/core/ingress/test_filters.py - ImportError while importing test m...
6 failed, 2 passed, 2 errors in 16.89s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.......................................                                  [100%]
39 passed in 22.90s
```

Evidence beyond the replay: the race tests' release at teardown (from `f462f0b`, on `proto/2b3b-v1`): with a race test
made to fail while it holds a match, its module failed in 8 s; without the release, it gave no result in 60 s.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 54dab51 && git commit -C 54dab51`

The diff:

```diff
diff --git a/backend/migrations/versions/0033_event_matching.py b/backend/migrations/versions/0033_event_matching.py
new file mode 100644
index 0000000..e5b1e77
--- /dev/null
+++ b/backend/migrations/versions/0033_event_matching.py
@@ -0,0 +1,73 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What matching, cancelling and the recount need (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b
+outline): `event_candidates(n)`, the dispatcher's pick of pending events, ids only and locking nothing, fair across
+tenants (every tenant's oldest due event before any tenant's second); `recount_candidates(n)`, the tenants whose
+counters the leader recounts, each at most every 10 minutes, by `recounted_at`; the API's grants to cancel events
+within its tenant and release their pending counters."""
+
+from alembic import op
+
+revision = "0033"
+down_revision = "0032"
+branch_labels = None
+depends_on = None
+
+EVENT_CANDIDATES = """
+CREATE FUNCTION event_candidates(max_events integer)
+RETURNS TABLE (tenant_id uuid, event_id uuid, endpoint_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  SELECT ranked.tenant_id, ranked.id, ranked.endpoint_id FROM (
+    SELECT e.tenant_id, e.id, e.endpoint_id, e.received_at,
+           row_number() OVER (PARTITION BY e.tenant_id ORDER BY e.received_at, e.id) AS rank
+      FROM public.inbound_events e
+     WHERE e.status = 'pending' AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
+  ) ranked
+  ORDER BY ranked.rank, ranked.received_at, ranked.id
+  LIMIT max_events
+$$"""
+
+RECOUNT_CANDIDATES = """
+CREATE FUNCTION recount_candidates(max_tenants integer)
+RETURNS TABLE (tenant_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  SELECT c.tenant_id FROM public.tenant_event_counters c
+   WHERE c.recounted_at IS NULL OR c.recounted_at <= now() - interval '10 minutes'
+   ORDER BY c.recounted_at NULLS FIRST, c.tenant_id
+   LIMIT max_tenants
+$$"""
+
+FUNCTIONS = ("event_candidates(integer)", "recount_candidates(integer)")
+
+
+def upgrade() -> None:
+    op.execute("ALTER TABLE tenant_event_counters ADD COLUMN recounted_at timestamptz")
+    for statement in (
+        EVENT_CANDIDATES,
+        RECOUNT_CANDIDATES,
+        *(
+            statement
+            for function in FUNCTIONS
+            for statement in (
+                f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC",
+                f"GRANT EXECUTE ON FUNCTION {function} TO dewpoint_dispatch",
+            )
+        ),
+        "GRANT UPDATE (recounted_at) ON tenant_event_counters TO dewpoint_dispatch",
+        # An admin's cancel (tenant.manage): the event's end, and the pending counters it releases.
+        "GRANT UPDATE (status, reason, ended_at) ON inbound_events TO dewpoint_api",
+        "GRANT UPDATE (pending_events, pending_bytes) ON webhook_endpoints TO dewpoint_api",
+        "GRANT UPDATE (pending_events, pending_bytes) ON tenant_event_counters TO dewpoint_api",
+    ):
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    for statement in (
+        "REVOKE UPDATE (pending_events, pending_bytes) ON tenant_event_counters FROM dewpoint_api",
+        "REVOKE UPDATE (pending_events, pending_bytes) ON webhook_endpoints FROM dewpoint_api",
+        "REVOKE UPDATE (status, reason, ended_at) ON inbound_events FROM dewpoint_api",
+        "REVOKE UPDATE (recounted_at) ON tenant_event_counters FROM dewpoint_dispatch",
+        *(f"DROP FUNCTION {function}" for function in FUNCTIONS),
+        "ALTER TABLE tenant_event_counters DROP COLUMN recounted_at",
+    ):
+        op.execute(statement)
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 1997b3c..634a3f0 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -1,8 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
 """The dispatcher process (engine 2b spec §7.3), role `dewpoint_dispatch`. It checks the deployment's environment
 before it connects to Temporal (§2.1), encrypts every start with the tenant's key (§6.2), and each cycle observes the
-current build, dispatches what's due, and reports; the one that leads the reconciler (§7.6) also settles what starts
-left uncertain, and reports that apart."""
+current build, dispatches what's due, matches inbound events (§8.3), and reports; the one that leads the reconciler
+(§7.6) also settles what starts left uncertain, and reports that apart."""
 
 import asyncio
 import uuid
@@ -17,6 +17,7 @@ from temporalio.worker import Worker
 from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.dispatcher.cancels import send_cancels
 from dewpoint.apps.dispatcher.dispatch import Rotation, dispatch_once
+from dewpoint.apps.dispatcher.matching import Verified, match_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
 from dewpoint.apps.dispatcher.schedule_sync import check_misses, sync_schedules
@@ -47,12 +48,13 @@ async def current_build(client: Client) -> str | None:
 
 async def cycle(
     sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings, *,
-    instance: uuid.UUID, reconciler: uuid.UUID, leader: Leader, rotation: Rotation,
+    instance: uuid.UUID, reconciler: uuid.UUID, leader: Leader, rotation: Rotation, verified: Verified | None = None,
 ) -> None:  # fmt: skip
-    """One cycle: observe the current build, dispatch what's due, report; the leader also reconciles, sends cancels,
-    keeps the Temporal Schedules in step with their rows and reads their missed firings. An observation that fails
-    (Temporal, or the database, briefly unavailable) dispatches nothing this cycle, and the next one asks again; the
-    record it didn't refresh ages out for admission (§7.2)."""
+    """One cycle: observe the current build, dispatch what's due, match inbound events, report; the leader also
+    reconciles, sends cancels, keeps the Temporal Schedules in step with their rows and reads their missed firings. An
+    observation that fails (Temporal, or the database, briefly unavailable) dispatches and matches nothing this cycle,
+    and the next one asks again: admission would refuse a matched event's requests for good without a fresh record of
+    the build (§7.2), which ages out meanwhile."""
     try:
         build = await observe(sessionmaker, await current_build(client))
     except Exception as e:
@@ -60,6 +62,9 @@ async def cycle(
         build = None
     build_id = build.build_id if build else ""
     done = await dispatch_once(sessionmaker, client, keys, settings, build, rotation) if build else {}
+    if build:
+        matched = await match_once(sessionmaker, keys, verified if verified is not None else Verified())
+        done.update({f"event_{k}": v for k, v in matched.items()})
     await report(sessionmaker, instance, build_id, {"current_build": bool(build), **done})
     if await leader.leading():
         settled = await reconcile_once(sessionmaker, client, keys, settings)
@@ -105,11 +110,11 @@ async def run(settings: Settings) -> None:
         instance = uuid.uuid4()
         reconciler, leader = uuid.uuid5(instance, "reconciler"), Leader(engine)
         log.info("dispatcher_started", instance=str(instance), build=this_build())
-        rotation = Rotation()
+        rotation, verified = Rotation(), Verified()
 
         async def one() -> None:
             await cycle(sessionmaker, client, keys, settings, instance=instance, reconciler=reconciler, leader=leader,
-                        rotation=rotation)  # fmt: skip
+                        rotation=rotation, verified=verified)  # fmt: skip
 
         try:
             async with admission_worker(
diff --git a/backend/src/dewpoint/apps/dispatcher/matching.py b/backend/src/dewpoint/apps/dispatcher/matching.py
new file mode 100644
index 0000000..6446f1c
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/matching.py
@@ -0,0 +1,204 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Matching inbound events (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b outline), in every
+dispatcher, only while the gate is on.
+
+`event_candidates(n)` picks pending events, ids only and locking nothing, fair across tenants. Each is then matched in
+a transaction of its own, under the one lock order: the gate's lock and the tenant's lifecycle lock, both shared (the
+gate's disable and 2b-4's erasure take them exclusively), with the gate, the recorded environment and the tenant
+rechecked under them; the event's endpoint row; the tenant's counter row; and only then the event row, `FOR UPDATE
+SKIP LOCKED`, rechecked still pending and due (another dispatcher may have finished it). Holding the endpoint's row
+serializes ingress and matching on one endpoint.
+
+The event is opened with the tenant's private key and, for each enabled binding of its endpoint whose filter holds, in
+workflow-id order (§7.2), one request is admitted: source `webhook`, key `evt:<event id>:<workflow id>`, the event as
+the trigger. Admission freezes it or records it `refused`; either is a request. The event is recorded `matched` with
+its request count, or `unmatched`, and its pending counters are released, together. A recheck that fails changes
+nothing; more enabled bindings than the cap (refused when they're written) wait, with an alert."""
+
+import json
+import uuid
+from collections import Counter
+from datetime import timedelta
+
+import structlog
+from sqlalchemy import func, or_, select, text, update
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps import admission
+from dewpoint.apps.dispatcher.dispatch import GATE_LOCK, tenant_lock
+from dewpoint.core.crypto import events
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.ingress import keys as event_keys
+from dewpoint.core.ingress.filters import matches
+from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
+from dewpoint.core.models.platform import PlatformSettings
+from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.platform.service import PRODUCTION
+from dewpoint.core.plugins import lifecycle
+from dewpoint.engine.runtime.activities import LIVE
+
+log = structlog.get_logger("dewpoint.dispatcher.matching")
+BATCH = 50  # events a cycle (§15, provisional)
+MAX_BINDINGS = 20  # an endpoint's enabled bindings, refused past it when written, rechecked here
+WAIT = timedelta(minutes=1)  # a wait that's no fault of the event's: retried after it, its attempts untouched
+SOURCE = "webhook"
+GATE_OFF = "gate_off"
+ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
+TENANT_ERASING = "tenant_erasing"
+SKIPPED = "skipped"
+FAN_OUT_EXCEEDED = "fan_out_exceeded"
+ROLLED_BACK = (GATE_OFF, ENVIRONMENT_NOT_RECORDED, TENANT_ERASING, SKIPPED)
+
+
+class Verified:
+    """The tenants' keypair versions that have opened an event in this process: a version that has is known good."""
+
+    def __init__(self) -> None:
+        self._versions: set[tuple[uuid.UUID, int]] = set()
+
+    def add(self, tenant_id: uuid.UUID, version: int) -> None:
+        self._versions.add((tenant_id, version))
+
+    def __contains__(self, item: object) -> bool:
+        return item in self._versions
+
+
+async def _after_event_locked() -> None:
+    """Runs once a match holds its event's row. A no-op; the race tests hold a match here."""
+
+
+def gate_off(platform: PlatformSettings | None) -> str | None:
+    """Why nothing is matched now, or None: no recorded environment, or a production deployment's runs off."""
+    if platform is None:
+        return ENVIRONMENT_NOT_RECORDED
+    if platform.environment == PRODUCTION and not platform.production_runs:
+        return GATE_OFF
+    return None
+
+
+async def _lock(s: AsyncSession, key: str) -> None:
+    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})
+
+
+async def match_once(
+    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, batch: int = BATCH
+) -> dict[str, int]:
+    """One cycle's matching: nothing while the gate is off; otherwise each candidate in turn. What happened, counted.
+    A match that fails (a bug, an outage) is logged by type and leaves its event as it was."""
+    async with sessionmaker() as s:
+        waiting = gate_off(await s.get(PlatformSettings, 1))
+        if waiting is not None:
+            return {waiting: 1}
+        query = text("select tenant_id, event_id, endpoint_id from event_candidates(:n)")
+        picked = (await s.execute(query, {"n": batch})).all()
+    counts: Counter[str] = Counter()
+    for tenant_id, event_id, endpoint_id in picked:
+        try:
+            counts[await match_event(sessionmaker, keys, verified, tenant_id=tenant_id, event_id=event_id,
+                                     endpoint_id=endpoint_id)] += 1  # fmt: skip
+        except Exception as e:
+            log.error("event_match_failed", tenant_id=str(tenant_id), event_id=str(event_id), error=type(e).__name__)
+            counts["error"] += 1
+    return dict(counts)
+
+
+async def match_event(
+    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, tenant_id: uuid.UUID,
+    event_id: uuid.UUID, endpoint_id: uuid.UUID,
+) -> str:  # fmt: skip
+    """One event's matching transaction: `matched`, `unmatched`, or why it waits or was passed by."""
+    async with sessionmaker() as s, s.begin():
+        outcome = await _match(s, keys, verified, tenant_id, event_id, endpoint_id)
+        if outcome in ROLLED_BACK:
+            await s.rollback()
+        return outcome
+
+
+async def _match(
+    s: AsyncSession, keys: KeySource, verified: Verified, tenant_id: uuid.UUID, event_id: uuid.UUID,
+    endpoint_id: uuid.UUID,
+) -> str:  # fmt: skip
+    await lifecycle.assert_read_committed(s)
+    await tenant_scope(s, tenant_id)
+    await _lock(s, GATE_LOCK)
+    await _lock(s, tenant_lock(tenant_id))
+    waiting = gate_off(await s.get(PlatformSettings, 1, populate_existing=True))
+    if waiting is not None:
+        return waiting
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    if tenant is None or tenant.status != "active":
+        return TENANT_ERASING
+    endpoint = (
+        await s.execute(
+            select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()  # fmt: skip
+    if endpoint is None:
+        return SKIPPED
+    await s.execute(select(TenantEventCounters.tenant_id).where(TenantEventCounters.tenant_id == tenant_id)
+                    .with_for_update())  # fmt: skip
+    event = (
+        await s.execute(
+            select(InboundEvent)
+            .where(
+                InboundEvent.id == event_id,
+                InboundEvent.endpoint_id == endpoint_id,
+                InboundEvent.status == "pending",
+                or_(InboundEvent.next_attempt_at.is_(None), InboundEvent.next_attempt_at <= func.statement_timestamp()),
+            )
+            .with_for_update(skip_locked=True)
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()
+    if event is None:
+        return SKIPPED
+    await _after_event_locked()
+    private = await event_keys.private_key(s, keys, tenant_id, event.key_version)
+    plaintext = events.open_sealed(private, tenant_id=tenant_id, endpoint_id=endpoint_id, event_id=event.id,
+                                   blob=event.sealed)  # fmt: skip
+    verified.add(tenant_id, event.key_version)
+    payload = json.loads(plaintext)
+    bindings = (
+        await s.execute(
+            select(TriggerBinding)
+            .where(TriggerBinding.endpoint_id == endpoint_id, TriggerBinding.enabled.is_(True))
+            .order_by(TriggerBinding.workflow_id)
+            .limit(MAX_BINDINGS + 1)
+        )
+    ).scalars().all()  # fmt: skip
+    if len(bindings) > MAX_BINDINGS:
+        log.error("event_fan_out_exceeded", endpoint_id=str(endpoint_id), event_id=str(event.id))
+        event.next_attempt_at = func.statement_timestamp() + WAIT
+        await s.flush()
+        return FAN_OUT_EXCEEDED
+    admitted = 0
+    for binding in bindings:
+        if not matches(binding.filter, payload):
+            continue
+        await admission.admit_request(
+            s, keys, tenant_id=tenant_id, workflow_id=binding.workflow_id, source=SOURCE, actor_id=None, mode=LIVE,
+            idempotency_key=f"evt:{event.id}:{binding.workflow_id}", input=payload,
+            details={"endpoint_id": str(endpoint_id), "event_id": str(event.id), "binding_id": str(binding.id)},
+        )  # fmt: skip
+        admitted += 1
+    event.status = "matched" if admitted else "unmatched"
+    event.request_count = admitted
+    event.ended_at = func.statement_timestamp()
+    await release(s, tenant_id, endpoint_id, event.size_bytes)
+    await s.flush()
+    return event.status
+
+
+async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
+    """An event's pending counters released, on its endpoint and its tenant, whose rows the caller holds. Never below
+    zero: a drift the recount corrects doesn't block an event's end."""
+    for model, where in ((WebhookEndpoint, WebhookEndpoint.id == endpoint_id),
+                         (TenantEventCounters, TenantEventCounters.tenant_id == tenant_id)):  # fmt: skip
+        await s.execute(
+            update(model).where(where).values(
+                pending_events=func.greatest(model.pending_events - events_n, 0),
+                pending_bytes=func.greatest(model.pending_bytes - size, 0),
+            )
+        )  # fmt: skip
diff --git a/backend/src/dewpoint/core/ingress/filters.py b/backend/src/dewpoint/core/ingress/filters.py
new file mode 100644
index 0000000..92aac07
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/filters.py
@@ -0,0 +1,59 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A binding's filter (engine 2b spec §8.3): at most 8 typed JSON-pointer equalities on the event, all of which must
+hold; none matches every event. No CEL. Equality is of canonical JSON, so it's typed: `1`, `1.0`, `true` and `"1"` are
+four values. A filter is checked when it's written: each clause a pointer (RFC 6901, at most 256 characters) and a
+scalar value (a string of at most 1,024 characters, a 64-bit integer, a boolean or null; never a float, whose equality
+is a question of formatting)."""
+
+from typing import Any
+
+from dewpoint.core.ingress.identity import canonical
+from dewpoint.core.ingress.pointer import PointerError, resolve
+
+MAX_CLAUSES = 8
+MAX_POINTER_CHARS = 256
+MAX_VALUE_CHARS = 1024
+INT_RANGE = (-(2**63), 2**63 - 1)
+
+
+class FilterError(ValueError):
+    """A filter that isn't one; the message says what's wrong, never quoting a value."""
+
+
+def matches(clauses: list[dict[str, Any]], event: object) -> bool:
+    for clause in clauses:
+        try:
+            found = resolve(event, clause["pointer"])
+        except PointerError:
+            return False
+        if canonical(found) != canonical(clause["value"]):
+            return False
+    return True
+
+
+def _scalar(value: object) -> bool:
+    if value is None or isinstance(value, bool):
+        return True
+    if isinstance(value, int):
+        return INT_RANGE[0] <= value <= INT_RANGE[1]
+    return isinstance(value, str) and len(value) <= MAX_VALUE_CHARS
+
+
+def validated(given: object) -> list[dict[str, Any]]:
+    """`given`, when it's a filter. Raises FilterError."""
+    if not isinstance(given, list):
+        raise FilterError("A filter is a list of clauses.")
+    if len(given) > MAX_CLAUSES:
+        raise FilterError(f"A filter has at most {MAX_CLAUSES} clauses.")
+    for clause in given:
+        if not isinstance(clause, dict) or set(clause) != {"pointer", "value"}:
+            raise FilterError("Each clause is exactly a pointer and a value.")
+        pointer = clause["pointer"]
+        if not isinstance(pointer, str) or not pointer.startswith("/") or len(pointer) > MAX_POINTER_CHARS:
+            raise FilterError(f"A clause's pointer starts with '/' and has at most {MAX_POINTER_CHARS} characters.")
+        if not _scalar(clause["value"]):
+            raise FilterError(
+                f"A clause's value is a string of at most {MAX_VALUE_CHARS} characters, a 64-bit integer, a boolean "
+                "or null."
+            )
+    return given
diff --git a/backend/src/dewpoint/core/models/ingress.py b/backend/src/dewpoint/core/models/ingress.py
index de01fd9..9305e39 100644
--- a/backend/src/dewpoint/core/models/ingress.py
+++ b/backend/src/dewpoint/core/models/ingress.py
@@ -1,11 +1,12 @@
 # SPDX-License-Identifier: Apache-2.0
-"""Webhook ingress (engine 2b spec §8.3): a tenant's inbound keypairs."""
+"""Webhook ingress (engine 2b spec §8.3): a tenant's inbound keypairs, its endpoints, counters, bindings and events."""
 
 import uuid
 from datetime import datetime
+from typing import Any
 
-from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
-from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func, true
+from sqlalchemy.dialects.postgresql import ARRAY, CIDR, JSONB, UUID
 from sqlalchemy.orm import Mapped, mapped_column
 
 from dewpoint.core.models.base import Base
@@ -21,3 +22,96 @@ class TenantEventKey(Base):
     public_key: Mapped[bytes] = mapped_column(LargeBinary)
     private_sealed: Mapped[bytes] = mapped_column(LargeBinary)
     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class WebhookEndpoint(Base):
+    """An endpoint (`/hooks/<id>`): its authentication, its limits, where its events' ids are, its rate buckets, its
+    pending and retained counters and their quotas. Its secrets are sealed under the ingress key, never a tenant's."""
+
+    __tablename__ = "webhook_endpoints"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    name: Mapped[str] = mapped_column(Text)
+    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
+    auth_kind: Mapped[str] = mapped_column(String(16))
+    bearer_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
+    hmac_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
+    signature_header: Mapped[str | None] = mapped_column(Text)
+    timestamp_header: Mapped[str | None] = mapped_column(Text)
+    tolerance_s: Mapped[int] = mapped_column(Integer, server_default="300")
+    allowlist: Mapped[list[Any]] = mapped_column(ARRAY(CIDR), server_default="{}")
+    body_limit: Mapped[int] = mapped_column(Integer, server_default=str(1024 * 1024))
+    id_source: Mapped[str] = mapped_column(String(16), server_default="none")
+    id_pointer: Mapped[str | None] = mapped_column(Text)
+    id_header: Mapped[str | None] = mapped_column(Text)
+    events_pointer: Mapped[str | None] = mapped_column(Text)
+    dedupe_key: Mapped[bytes] = mapped_column(LargeBinary)
+    request_per_s: Mapped[float] = mapped_column(Float, server_default="20")
+    request_burst: Mapped[int] = mapped_column(BigInteger, server_default="100")
+    event_per_s: Mapped[float] = mapped_column(Float, server_default="200")
+    event_burst: Mapped[int] = mapped_column(BigInteger, server_default="1000")
+    byte_per_s: Mapped[float] = mapped_column(Float, server_default=str(2 * 1024 * 1024))
+    byte_burst: Mapped[int] = mapped_column(BigInteger, server_default=str(10 * 1024 * 1024))
+    pending_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    pending_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    retained_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    retained_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    pending_events_max: Mapped[int] = mapped_column(BigInteger, server_default="10000")
+    pending_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(64 * 1024 * 1024))
+    retained_events_max: Mapped[int] = mapped_column(BigInteger, server_default="100000")
+    retained_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(512 * 1024 * 1024))
+    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class TenantEventCounters(Base):
+    """A tenant's event and byte buckets, its pending and retained counters and their quotas, across its endpoints."""
+
+    __tablename__ = "tenant_event_counters"
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
+    pending_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    pending_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    retained_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    retained_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
+    pending_events_max: Mapped[int] = mapped_column(BigInteger, server_default="50000")
+    pending_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(256 * 1024 * 1024))
+    retained_events_max: Mapped[int] = mapped_column(BigInteger, server_default="250000")
+    retained_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(1024 * 1024 * 1024))
+    recounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+
+
+class TriggerBinding(Base):
+    """An endpoint's events to a workflow of the same tenant, when every typed JSON-pointer equality of its filter
+    holds (at most 8; none: every event)."""
+
+    __tablename__ = "trigger_bindings"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    filter: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
+    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
+    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class InboundEvent(Base):
+    """An event as ingress recorded it, sealed to its tenant's keypair `key_version`, and what became of it."""
+
+    __tablename__ = "inbound_events"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    dedupe_key: Mapped[bytes | None] = mapped_column(LargeBinary)
+    content_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
+    key_version: Mapped[int] = mapped_column(Integer)
+    sealed: Mapped[bytes] = mapped_column(LargeBinary)
+    size_bytes: Mapped[int] = mapped_column(Integer)
+    status: Mapped[str] = mapped_column(String(16), server_default="pending")
+    reason: Mapped[str | None] = mapped_column(String(64))
+    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
+    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    request_count: Mapped[int | None] = mapped_column(Integer)
+    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
diff --git a/backend/tests/apps/dispatcher/inbound.py b/backend/tests/apps/dispatcher/inbound.py
new file mode 100644
index 0000000..26977a5
--- /dev/null
+++ b/backend/tests/apps/dispatcher/inbound.py
@@ -0,0 +1,167 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Inbound events for the matcher's tests: a published workflow's tenant with its inbound keypair (sealed with the
+fixture keys the dispatcher reads), an endpoint, bindings, and events recorded through ingress's own function."""
+
+import hashlib
+import uuid
+from dataclasses import dataclass
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto import events
+from dewpoint.core.ingress.identity import canonical
+from dewpoint.core.ingress.keys import PURPOSE
+from tests.apps.test_admission import KEYS, OPEN_GRAPH, current, published
+from tests.core.ingress.support import record
+
+
+@dataclass
+class Inbound:
+    ctx: Any  # the publishing actor's TenantContext
+    tenant_id: uuid.UUID
+    user_id: uuid.UUID
+    workflow_id: uuid.UUID
+    endpoint_id: uuid.UUID
+    public_key: bytes
+
+
+async def keypair(owner: Any, tenant_id: uuid.UUID, version: int = 1) -> bytes:
+    """The tenant's inbound keypair `version`, its private key sealed with the fixture keys; its public key."""
+    private, public = events.generate_keypair()
+    sealed = await ClaimCipher(KEYS, purpose=PURPOSE).seal(str(tenant_id), str(version), private)
+    async with owner() as s, s.begin():
+        await s.execute(
+            text(
+                "insert into tenant_event_keys (tenant_id, version, public_key, private_sealed) values (:t, :v, :p, :s)"
+            ),
+            {"t": tenant_id, "v": version, "p": public, "s": sealed},
+        )
+    return public
+
+
+async def endpoint(owner: Any, tenant_id: uuid.UUID, user_id: uuid.UUID, **columns: Any) -> uuid.UUID:
+    endpoint_id = uuid.uuid4()
+    values = {"auth_kind": "bearer", "bearer_digest": b"\x00" * 32, "dedupe_key": b"sealed"} | columns
+    names = ", ".join(values)
+    async with owner() as s, s.begin():
+        await s.execute(
+            text(f"insert into webhook_endpoints (id, tenant_id, name, created_by, {names}) "  # noqa: S608
+                 f"values (:id, :t, 'hooks', :u, {', '.join(':' + k for k in values)})"),
+            {"id": endpoint_id, "t": tenant_id, "u": user_id} | values,
+        )  # fmt: skip
+    return endpoint_id
+
+
+async def bind(
+    owner: Any, inbound: Inbound, workflow_id: uuid.UUID | None = None, *, filter: list[dict[str, Any]] | None = None,
+    enabled: bool = True, endpoint_id: uuid.UUID | None = None,
+) -> uuid.UUID:  # fmt: skip
+    binding_id = uuid.uuid4()
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, filter, enabled, created_by) "
+                 "values (:id, :t, :e, :w, cast(:f as jsonb), :on, :u)"),
+            {"id": binding_id, "t": inbound.tenant_id, "e": endpoint_id or inbound.endpoint_id,
+             "w": workflow_id or inbound.workflow_id, "f": _json(filter or []), "on": enabled, "u": inbound.user_id},
+        )  # fmt: skip
+    return binding_id
+
+
+def _json(value: object) -> str:
+    return canonical(value).decode()
+
+
+async def inbound(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, graph: Any = OPEN_GRAPH) -> Inbound:
+    """A published workflow (its input any object), the current build recorded, the tenant's keypair, an endpoint."""
+    ctx, workflow_id = await published(owner, api, admin, settings, graph)
+    await current(dispatch)
+    public = await keypair(owner, ctx.tenant_id)
+    endpoint_id = await endpoint(owner, ctx.tenant_id, ctx.user.id)
+    return Inbound(ctx, ctx.tenant_id, ctx.user.id, workflow_id, endpoint_id, public)
+
+
+def sealed(inbound: Inbound, event_id: uuid.UUID, payload: object, *, endpoint_id: uuid.UUID | None = None) -> bytes:
+    return events.seal(
+        inbound.public_key, 1, tenant_id=inbound.tenant_id, endpoint_id=endpoint_id or inbound.endpoint_id,
+        event_id=event_id, plaintext=canonical(payload),
+    )  # fmt: skip
+
+
+async def send(ingress: Any, inbound: Inbound, *payloads: object, dedupe: list[bytes | None] | None = None,
+               endpoint_id: uuid.UUID | None = None) -> list[uuid.UUID]:  # fmt: skip
+    """Events recorded through ingress's function, committed: their ids."""
+    ids = [uuid.uuid4() for _ in payloads]
+    keys = dedupe or [None] * len(payloads)
+    given = [
+        (key, None if key is None else hashlib.sha256(canonical(payload)).digest(),
+         sealed(inbound, i, payload, endpoint_id=endpoint_id))
+        for i, payload, key in zip(ids, payloads, keys, strict=True)
+    ]  # fmt: skip
+    outcome = await record(ingress, endpoint_id or inbound.endpoint_id, given, ids=ids)
+    assert outcome["outcome"] == "recorded", outcome
+    return ids
+
+
+async def event_state(owner: Any, event_id: uuid.UUID) -> dict[str, Any]:
+    async with owner() as s:
+        found = await s.execute(text("select * from inbound_events where id = :e"), {"e": event_id})
+        return dict(found.mappings().one())
+
+
+async def requests_of(owner: Any, event_id: uuid.UUID) -> list[dict[str, Any]]:
+    async with owner() as s:
+        found = await s.execute(
+            text("select idempotency_key, workflow_id, source, mode, status, reason from run_requests "
+                 "where idempotency_key like :k order by idempotency_key"), {"k": f"evt:{event_id}:%"},
+        )  # fmt: skip
+        return [dict(r) for r in found.mappings()]
+
+
+async def counters(owner: Any, inbound: Inbound) -> tuple[tuple[int, int], tuple[int, int]]:
+    """(the endpoint's pending events and bytes, the tenant's)."""
+    endpoint = text("select pending_events, pending_bytes from webhook_endpoints where id = :e")
+    tenant = text("select pending_events, pending_bytes from tenant_event_counters where tenant_id = :t")
+    async with owner() as s:
+        e = (await s.execute(endpoint, {"e": inbound.endpoint_id})).one()
+        t = (await s.execute(tenant, {"t": inbound.tenant_id})).one()
+    return (e[0], e[1]), (t[0], t[1])
+
+
+async def lock_waiters(owner: Any) -> int:
+    async with owner() as s:
+        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
+                    ).scalar_one())  # fmt: skip
+
+
+async def stored(owner: Any, inbound: Inbound, payload: object) -> uuid.UUID:
+    """An event written straight to the table, as ingress would have recorded it, with its counters: for a test whose
+    deployment ingress wouldn't record in (a production one)."""
+    event_id = uuid.uuid4()
+    blob = sealed(inbound, event_id, payload)
+    async with owner() as s, s.begin():
+        await s.execute(
+            text(
+                "insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes) "
+                "values (:i, :t, :e, 1, :b, :n)"
+            ),
+            {"i": event_id, "t": inbound.tenant_id, "e": inbound.endpoint_id, "b": blob, "n": len(blob)},
+        )
+        await s.execute(
+            text(
+                "update webhook_endpoints set pending_events = pending_events + 1, pending_bytes = "
+                "pending_bytes + :n where id = :e"
+            ),
+            {"n": len(blob), "e": inbound.endpoint_id},
+        )
+        await s.execute(
+            text(
+                "insert into tenant_event_counters (tenant_id, pending_events, pending_bytes) values "
+                "(:t, 1, :n) on conflict (tenant_id) do update set pending_events = "
+                "tenant_event_counters.pending_events + 1, pending_bytes = "
+                "tenant_event_counters.pending_bytes + :n"
+            ),
+            {"t": inbound.tenant_id, "n": len(blob)},
+        )
+    return event_id
diff --git a/backend/tests/apps/dispatcher/test_main.py b/backend/tests/apps/dispatcher/test_main.py
index 8208b35..4df0795 100644
--- a/backend/tests/apps/dispatcher/test_main.py
+++ b/backend/tests/apps/dispatcher/test_main.py
@@ -75,3 +75,30 @@ async def test_the_loop_outlives_a_cycle_that_fails(monkeypatch) -> None:
 
     await main.serve(cycle, cycles=3)
     assert calls == [0, 1, 2]
+
+
+async def test_a_cycle_matches_events_only_when_it_observed_the_current_build(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
+    api_settings,
+) -> None:  # fmt: skip
+    """Admission refuses a durable request for want of a fresh build record, for good: a cycle that couldn't observe
+    the build leaves events pending, and the next one matches them (2b-3b, M3)."""
+    from tests.apps.dispatcher.inbound import bind, event_state, inbound, send
+
+    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
+                          api_settings)  # fmt: skip
+    await bind(owner_sessionmaker, ready)
+    [event_id] = await send(ingress_sessionmaker, ready, {"type": "ap_down"})
+    client = FakeClient()
+    client.workflow_service = Flaky(failures=1)
+    instance, rotation = uuid.uuid4(), dispatch.Rotation()
+
+    async def cycle() -> None:
+        await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=instance, reconciler=uuid.uuid4(),
+                         leader=NotLeading(), rotation=rotation)  # type: ignore[arg-type]  # fmt: skip
+
+    await cycle()
+    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"
+    await cycle()
+    assert (await event_state(owner_sessionmaker, event_id))["status"] == "matched"
+    assert (await reported(owner_sessionmaker, instance)) == {"current_build": True, "event_matched": 1}
diff --git a/backend/tests/apps/dispatcher/test_matching.py b/backend/tests/apps/dispatcher/test_matching.py
new file mode 100644
index 0000000..1ab4a66
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_matching.py
@@ -0,0 +1,336 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Matching (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b outline): every dispatcher, only while the
+gate is on, one transaction per event. It takes the gate's and the tenant's lifecycle locks shared and rechecks the
+gate and the tenant; locks the event's endpoint row, the tenant's counter row, then the event row with SKIP LOCKED,
+rechecking it's still pending; opens it; admits one request per matching binding (source `webhook`, key
+`evt:<event id>:<workflow id>`, the event as the trigger), in workflow-id order; records `matched` with its request
+count, or `unmatched`; and releases the pending counters. A recheck that fails changes nothing."""
+
+import asyncio
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission
+from dewpoint.apps.dispatcher import matching
+from dewpoint.core.platform.service import PRODUCTION, record_environment
+from tests.apps.dispatcher.inbound import (
+    bind,
+    counters,
+    event_state,
+    inbound,
+    lock_waiters,
+    requests_of,
+    send,
+    stored,
+)
+from tests.apps.test_admission import KEYS
+from tests.core.ingress.support import RECORD
+
+ALARM = {"id": "a-1", "type": "ap_down", "site": "s-1", "count": 2}
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    return await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
+
+
+@pytest.fixture
+async def dev(development_deployment, ready):  # type: ignore[no-untyped-def]
+    return ready
+
+
+async def matched(dispatch: Any, inbound: Any, event_id: uuid.UUID, verified: Any = None) -> str:
+    return await matching.match_event(
+        dispatch,
+        KEYS,
+        verified if verified is not None else matching.Verified(),
+        tenant_id=inbound.tenant_id,
+        event_id=event_id,
+        endpoint_id=inbound.endpoint_id,
+    )
+
+
+async def other_workflow(owner: Any, inbound: Any) -> uuid.UUID:
+    workflow_id = uuid.uuid4()
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
+            {"w": workflow_id, "t": inbound.tenant_id, "n": f"w-{workflow_id.hex[:8]}"},
+        )
+    return workflow_id
+
+
+async def test_an_event_admits_one_request_per_matching_binding_in_workflow_order(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, admin_sessionmaker,
+    api_settings, monkeypatch,
+) -> None:  # fmt: skip
+    from tests.apps.test_admission import OPEN_GRAPH
+    from tests.apps.test_workflow_ops import create, publish
+
+    second = await create(api_sessionmaker, dev.ctx, OPEN_GRAPH, name="W2")
+    assert (await publish(api_sessionmaker, dev.ctx, second, api_settings)).version is not None
+    await bind(owner_sessionmaker, dev)
+    await bind(owner_sessionmaker, dev, second)
+    order: list[uuid.UUID] = []
+    admit = admission.admit_request
+
+    async def recorded(*args: Any, **kwargs: Any) -> Any:
+        order.append(kwargs["workflow_id"])
+        return await admit(*args, **kwargs)
+
+    monkeypatch.setattr(admission, "admit_request", recorded)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "matched"
+    assert order == sorted([dev.workflow_id, second])
+    found = await requests_of(owner_sessionmaker, event_id)
+    assert [(r["idempotency_key"], r["source"], r["mode"], r["status"]) for r in found] == sorted(
+        (f"evt:{event_id}:{w}", "webhook", "live", "queued") for w in (dev.workflow_id, second)
+    )
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["request_count"], state["attempts"]) == ("matched", 2, 0)
+    assert state["ended_at"] is not None
+    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
+
+
+async def test_a_filter_selects_by_typed_equality_and_no_match_is_unmatched(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    await bind(owner_sessionmaker, dev, filter=[{"pointer": "/type", "value": "ap_down"}, {"pointer": "/count",
+                                                                                         "value": 2}])  # fmt: skip
+    hit, typed, miss = await send(ingress_sessionmaker, dev, ALARM, ALARM | {"count": "2"}, ALARM | {"type": "ap_up"})
+    assert await matched(dispatch_sessionmaker, dev, hit) == "matched"
+    for event_id in (typed, miss):  # "2" isn't 2
+        assert await matched(dispatch_sessionmaker, dev, event_id) == "unmatched"
+        state = await event_state(owner_sessionmaker, event_id)
+        assert (state["status"], state["request_count"]) == ("unmatched", 0)
+        assert await requests_of(owner_sessionmaker, event_id) == []
+    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
+
+
+async def test_without_an_enabled_binding_an_event_is_unmatched(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    await bind(owner_sessionmaker, dev, enabled=False)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "unmatched"
+
+
+async def test_a_refused_admission_is_a_request_too(dev, owner_sessionmaker, ingress_sessionmaker,
+                                                   dispatch_sessionmaker) -> None:  # fmt: skip
+    await bind(owner_sessionmaker, dev)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update workflows set enabled = false where id = :w"), {"w": dev.workflow_id})
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "matched"
+    [request] = await requests_of(owner_sessionmaker, event_id)
+    assert (request["status"], request["reason"]) == ("refused", admission.WORKFLOW_DISABLED)
+    assert (await event_state(owner_sessionmaker, event_id))["request_count"] == 1
+
+
+async def test_with_the_gate_off_nothing_is_matched(ready, owner_sessionmaker, dispatch_sessionmaker) -> None:
+    async with owner_sessionmaker() as s, s.begin():  # a production deployment, its runs off by default (the gate)
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    await bind(owner_sessionmaker, ready)
+    event_id = await stored(owner_sessionmaker, ready, ALARM)
+    assert await matched(dispatch_sessionmaker, ready, event_id) == "gate_off"
+    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"gate_off": 1}
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["attempts"], state["next_attempt_at"]) == ("pending", 0, None)
+    assert await requests_of(owner_sessionmaker, event_id) == []
+
+
+async def test_an_erasing_tenants_events_wait(dev, owner_sessionmaker, ingress_sessionmaker,
+                                              dispatch_sessionmaker) -> None:  # fmt: skip
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "tenant_erasing"
+    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"
+
+
+async def test_more_bindings_than_the_cap_wait_with_an_alert_and_admit_nothing(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    for _ in range(matching.MAX_BINDINGS + 1):
+        await bind(owner_sessionmaker, dev, await other_workflow(owner_sessionmaker, dev))
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "fan_out_exceeded"
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["attempts"]) == ("pending", 0)
+    assert state["next_attempt_at"] is not None  # it backs off, untouched otherwise
+    assert await requests_of(owner_sessionmaker, event_id) == []
+
+
+async def test_a_cycle_matches_the_due_events(dev, owner_sessionmaker, ingress_sessionmaker,
+                                              dispatch_sessionmaker) -> None:  # fmt: skip
+    await bind(owner_sessionmaker, dev, filter=[{"pointer": "/type", "value": "ap_down"}])
+    await send(ingress_sessionmaker, dev, ALARM, ALARM | {"type": "x"}, ALARM | {"id": "a-2"})
+    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 2,
+                                                                                            "unmatched": 1}  # fmt: skip
+    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {}
+
+
+# Races (the owner's M3 check), each in both orders where order is a question.
+
+
+_RELEASES: list[asyncio.Event] = []
+
+
+@pytest.fixture(autouse=True)
+async def _released() -> Any:
+    """A race test that fails while a match is held releases it before the teardown's truncate, which would otherwise
+    wait for that match's locks for ever: a regression fails the test, never hangs the suite."""
+    yield
+    while _RELEASES:
+        _RELEASES.pop().set()
+    await asyncio.sleep(0)
+
+
+async def _held(monkeypatch: Any) -> tuple[asyncio.Event, asyncio.Event]:
+    """A matcher that, holding its event's row, waits until released (at the latest when the test ends)."""
+    reached, release = asyncio.Event(), asyncio.Event()
+    _RELEASES.append(release)
+
+    async def hold() -> None:
+        reached.set()
+        await release.wait()
+
+    monkeypatch.setattr(matching, "_after_event_locked", hold)
+    return reached, release
+
+
+async def _waiting(owner: Any, n: int = 1) -> None:
+    for _ in range(300):
+        if await lock_waiters(owner) >= n:
+            return
+        await asyncio.sleep(0.01)
+    raise AssertionError("nothing waited for a lock")
+
+
+async def test_two_dispatchers_match_an_event_once(dev, owner_sessionmaker, ingress_sessionmaker,
+                                                   dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    reached, release = await _held(monkeypatch)
+    first = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+    await reached.wait()
+    monkeypatch.setattr(matching, "_after_event_locked", matching_noop)
+    second = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+    await _waiting(owner_sessionmaker)  # on the endpoint's row
+    release.set()
+    assert sorted([await first, await second]) == ["matched", "skipped"]
+    assert len(await requests_of(owner_sessionmaker, event_id)) == 1
+
+
+async def matching_noop() -> None:
+    return None
+
+
+async def test_two_events_of_one_endpoint_are_matched_one_after_the_other(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    await bind(owner_sessionmaker, dev)
+    one, two = await send(ingress_sessionmaker, dev, ALARM, ALARM | {"id": "a-2"})
+    reached, release = await _held(monkeypatch)
+    first = asyncio.create_task(matched(dispatch_sessionmaker, dev, one))
+    await reached.wait()
+    monkeypatch.setattr(matching, "_after_event_locked", matching_noop)
+    second = asyncio.create_task(matched(dispatch_sessionmaker, dev, two))
+    await _waiting(owner_sessionmaker)
+    release.set()
+    assert [await first, await second] == ["matched", "matched"]
+    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
+
+
+async def test_a_duplicate_recorded_while_its_event_is_matched_is_acknowledged_after(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    """The matcher first: ingress's duplicate waits for the endpoint's row, then finds the event, matched."""
+    await bind(owner_sessionmaker, dev)
+    key = b"k" * 32
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM, dedupe=[key])
+    reached, release = await _held(monkeypatch)
+    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+    await reached.wait()
+    duplicate = asyncio.create_task(send_raw(ingress_sessionmaker, dev, ALARM, key))
+    await _waiting(owner_sessionmaker)
+    release.set()
+    assert await matcher == "matched"
+    assert await duplicate == {"outcome": "recorded", "accepted": 0, "duplicates": 1}
+    assert len(await requests_of(owner_sessionmaker, event_id)) == 1
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from inbound_events"))).scalar_one() == 1
+
+
+async def test_a_duplicate_recorded_first_holds_the_matcher_until_it_commits(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """Ingress first: the matcher waits for the endpoint's row, then matches the one event once."""
+    await bind(owner_sessionmaker, dev)
+    key = b"k" * 32
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM, dedupe=[key])
+    async with ingress_sessionmaker() as s, s.begin():
+        outcome = await s.execute(RECORD, _params(dev, ALARM, key))
+        assert dict(outcome.scalar_one())["duplicates"] == 1
+        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+        await _waiting(owner_sessionmaker)
+    assert await matcher == "matched"
+    assert len(await requests_of(owner_sessionmaker, event_id)) == 1
+
+
+async def test_a_tenant_marked_erasing_first_is_never_matched(dev, owner_sessionmaker, ingress_sessionmaker,
+                                                              dispatch_sessionmaker) -> None:  # fmt: skip
+    """2b-4's erasure takes the tenant's lifecycle lock exclusively: the matcher waits for it, then sees `erasing`."""
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
+                        {"k": f"dewpoint:tenant:{dev.tenant_id}"})  # fmt: skip
+        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})
+        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+        await _waiting(owner_sessionmaker)
+    assert await matcher == "tenant_erasing"
+    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"
+
+
+async def test_an_erasure_waits_for_a_match_in_flight(dev, owner_sessionmaker, ingress_sessionmaker,
+                                                      dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    reached, release = await _held(monkeypatch)
+    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+    await reached.wait()
+
+    async def erase() -> None:
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
+                            {"k": f"dewpoint:tenant:{dev.tenant_id}"})  # fmt: skip
+            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})
+
+    erasure = asyncio.create_task(erase())
+    await _waiting(owner_sessionmaker)
+    assert not erasure.done()
+    release.set()
+    assert await matcher == "matched"
+    await erasure
+
+
+async def send_raw(ingress: Any, inbound: Any, payload: object, key: bytes) -> dict[str, Any]:
+    async with ingress() as s, s.begin():
+        return dict((await s.execute(RECORD, _params(inbound, payload, key))).scalar_one())
+
+
+def _params(inbound: Any, payload: object, key: bytes) -> dict[str, Any]:
+    import hashlib
+
+    from dewpoint.core.ingress.identity import canonical
+    from tests.apps.dispatcher.inbound import sealed
+
+    event_id = uuid.uuid4()
+    return {"e": inbound.endpoint_id, "refusal": None, "read": 0, "ids": [event_id],
+            "sealed": [sealed(inbound, event_id, payload)], "versions": [1], "dedupe": [key],
+            "digests": [hashlib.sha256(canonical(payload)).digest()]}  # fmt: skip
diff --git a/backend/tests/core/ingress/test_filters.py b/backend/tests/core/ingress/test_filters.py
new file mode 100644
index 0000000..a79c287
--- /dev/null
+++ b/backend/tests/core/ingress/test_filters.py
@@ -0,0 +1,63 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A binding's filter (engine 2b spec §8.3): at most 8 typed JSON-pointer equalities on the event, all of which must
+hold; none matches every event. No CEL. Typed: `1`, `1.0`, `true` and `"1"` are four values. A filter is checked when
+it's written: a pointer (RFC 6901, at most 256 characters) and a scalar value (a string of at most 1,024 characters,
+an integer, a boolean or null; never a float, whose equality is a formatting question)."""
+
+import pytest
+
+from dewpoint.core.ingress.filters import FilterError, matches, validated
+
+EVENT = {"type": "ap_down", "count": 1, "up": True, "site": {"id": "s-1", "name": None}, "tags": ["a", "b"]}
+
+
+def test_no_clause_matches_every_event() -> None:
+    assert matches([], EVENT)
+
+
+def test_every_clause_must_hold() -> None:
+    assert matches([{"pointer": "/type", "value": "ap_down"}, {"pointer": "/site/id", "value": "s-1"}], EVENT)
+    assert not matches([{"pointer": "/type", "value": "ap_down"}, {"pointer": "/site/id", "value": "s-2"}], EVENT)
+
+
+def test_equality_is_typed() -> None:
+    assert matches([{"pointer": "/count", "value": 1}], EVENT)
+    assert matches([{"pointer": "/up", "value": True}], EVENT)
+    assert matches([{"pointer": "/site/name", "value": None}], EVENT)
+    assert matches([{"pointer": "/tags/1", "value": "b"}], EVENT)
+    for pointer, value in (("/count", True), ("/count", "1"), ("/up", 1), ("/site/name", False), ("/type", "AP_DOWN")):
+        assert not matches([{"pointer": pointer, "value": value}], EVENT), (pointer, value)
+    assert not matches([{"pointer": "/count", "value": 1}], {"count": 1.0})
+
+
+def test_a_pointer_that_doesnt_resolve_doesnt_match() -> None:
+    assert not matches([{"pointer": "/missing", "value": None}], EVENT)
+    assert not matches([{"pointer": "/tags/5", "value": "a"}], EVENT)
+
+
+def test_a_valid_filter_is_kept_as_given() -> None:
+    given = [{"pointer": "/type", "value": "ap_down"}, {"pointer": "/n", "value": -3}, {"pointer": "/x", "value": None}]
+    assert validated(given) == given
+    assert validated([]) == []
+
+
+@pytest.mark.parametrize(
+    "given",
+    [
+        "not a list",
+        [{"pointer": "/a", "value": 1}] * 9,
+        [{"pointer": "a", "value": 1}],  # not a pointer
+        [{"pointer": "/" + "a" * 256, "value": 1}],
+        [{"pointer": "/a", "value": 1.5}],
+        [{"pointer": "/a", "value": {"b": 1}}],
+        [{"pointer": "/a", "value": [1]}],
+        [{"pointer": "/a", "value": "x" * 1025}],
+        [{"pointer": "/a", "value": 10**30}],  # past a 64-bit integer
+        [{"pointer": "/a"}],
+        [{"pointer": "/a", "value": 1, "op": "ne"}],
+        ["/a"],
+    ],
+)
+def test_an_invalid_filter_is_refused_with_a_reason(given) -> None:
+    with pytest.raises(FilterError):
+        validated(given)
diff --git a/backend/tests/core/ingress/test_matching_schema.py b/backend/tests/core/ingress/test_matching_schema.py
new file mode 100644
index 0000000..4e01de2
--- /dev/null
+++ b/backend/tests/core/ingress/test_matching_schema.py
@@ -0,0 +1,118 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What matching, cancelling and the recount need from the schema (engine 2b spec §8.3; "Functions and lock order" in
+the 2b-3b outline): the dispatcher picks pending events through `event_candidates(n)`, ids only, fairly across tenants
+(every tenant's oldest due event before any tenant's second, FIFO within one); the recount's tenants through
+`recount_candidates(n)`, each at most every 10 minutes; the API cancels within its tenant, releasing the pending
+counters. Both functions are the dispatcher's alone, definers with a pinned path."""
+
+import uuid
+from datetime import UTC, datetime
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.core.db import tenant_scope
+from tests.core.ingress.support import endpoint
+
+FUNCTIONS = ("event_candidates(integer)", "recount_candidates(integer)")
+FUTURE, PAST = datetime(2999, 1, 1, tzinfo=UTC), datetime(2000, 1, 1, tzinfo=UTC)
+ROLES = ("dewpoint_api", "dewpoint_ingress", "dewpoint_worker", "dewpoint_admin", "dewpoint_auditor")
+
+
+async def event(owner, tenant: uuid.UUID, endpoint_id: uuid.UUID, ago_s: int, **columns: object) -> uuid.UUID:
+    """An event received `ago_s` seconds ago, pending unless `columns` say otherwise."""
+    event_id = uuid.uuid4()
+    values = {"status": "pending", "next_attempt_at": None, "ended_at": None} | columns
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes, status, "
+                 "next_attempt_at, ended_at, received_at) values (:id, :t, :e, 1, '\\x01', 1, :status, "
+                 ":next_attempt_at, :ended_at, now() - make_interval(secs => :ago))"),
+            {"id": event_id, "t": tenant, "e": endpoint_id, "ago": ago_s} | values,
+        )  # fmt: skip
+    return event_id
+
+
+async def candidates(dispatch, n: int = 50) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
+    async with dispatch() as s:
+        found = await s.execute(text("select tenant_id, event_id, endpoint_id from event_candidates(:n)"), {"n": n})
+        return [tuple(row) for row in found.all()]
+
+
+async def test_every_tenants_oldest_due_event_comes_before_any_tenants_second(
+    owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    a, a_endpoint = await endpoint(owner_sessionmaker)
+    b, b_endpoint = await endpoint(owner_sessionmaker)
+    a1 = await event(owner_sessionmaker, a, a_endpoint, 50)
+    a2 = await event(owner_sessionmaker, a, a_endpoint, 40)
+    a3 = await event(owner_sessionmaker, a, a_endpoint, 30)
+    b1 = await event(owner_sessionmaker, b, b_endpoint, 10)
+    assert await candidates(dispatch_sessionmaker) == [
+        (a, a1, a_endpoint), (b, b1, b_endpoint), (a, a2, a_endpoint), (a, a3, a_endpoint),
+    ]  # fmt: skip
+    assert [c[1] for c in await candidates(dispatch_sessionmaker, 2)] == [a1, b1]
+
+
+async def test_only_due_pending_events_are_candidates(owner_sessionmaker, dispatch_sessionmaker) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    due = await event(owner_sessionmaker, tenant, endpoint_id, 60)
+    await event(owner_sessionmaker, tenant, endpoint_id, 50, next_attempt_at=FUTURE)  # backing off
+    await event(owner_sessionmaker, tenant, endpoint_id, 40, status="matched", ended_at=PAST)
+    await event(owner_sessionmaker, tenant, endpoint_id, 30, status="dead", ended_at=PAST)
+    again = await event(owner_sessionmaker, tenant, endpoint_id, 20, next_attempt_at=PAST)
+    assert [c[1] for c in await candidates(dispatch_sessionmaker)] == [due, again]
+
+
+async def test_a_tenant_is_recounted_at_most_every_ten_minutes(owner_sessionmaker, dispatch_sessionmaker) -> None:
+    tenant, _ = await endpoint(owner_sessionmaker)
+    other, _ = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into tenant_event_counters (tenant_id, recounted_at) values "
+                             "(:t, null), (:o, now() - interval '9 minutes')"), {"t": tenant, "o": other})  # fmt: skip
+    async with dispatch_sessionmaker() as s:
+        found = (await s.execute(text("select tenant_id from recount_candidates(10)"))).scalars().all()
+    assert found == [tenant]
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenant_event_counters set recounted_at = now() - interval '11 minutes' "
+                             "where tenant_id = :o"), {"o": other})  # fmt: skip
+    async with dispatch_sessionmaker() as s:
+        found = (await s.execute(text("select tenant_id from recount_candidates(10)"))).scalars().all()
+    assert found == [tenant, other]  # never recounted first, then the longest ago
+
+
+async def test_the_candidate_functions_are_the_dispatchers_alone(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        for function in FUNCTIONS:
+            allowed = text("select has_function_privilege(:r, :f, 'EXECUTE')")
+            assert (await s.execute(allowed, {"r": "dewpoint_dispatch", "f": function})).scalar_one() is True
+            for role in ROLES:
+                assert (await s.execute(allowed, {"r": role, "f": function})).scalar_one() is False, (role, function)
+            query = text("select prosecdef, proconfig, proacl::text from pg_proc where oid = cast(:f as regprocedure)")
+            definer, config, acl = (await s.execute(query, {"f": function})).one()
+            assert (definer, config) == (True, ["search_path=public, pg_temp"])
+            assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))
+
+
+async def test_the_api_cancels_within_its_tenant_and_releases_the_pending_counters(
+    owner_sessionmaker, api_sessionmaker
+) -> None:
+    tenant, endpoint_id = await endpoint(owner_sessionmaker)
+    other, other_endpoint = await endpoint(owner_sessionmaker)
+    mine = await event(owner_sessionmaker, tenant, endpoint_id, 10)
+    theirs = await event(owner_sessionmaker, other, other_endpoint, 10)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        changed = await s.execute(text("update inbound_events set status = 'cancelled', reason = 'cancelled', "
+                                       "ended_at = now() where id = any(:ids)"), {"ids": [mine, theirs]})  # fmt: skip
+        assert changed.rowcount == 1  # row-level security: its own tenant's only
+        await s.execute(text("update webhook_endpoints set pending_events = 0, pending_bytes = 0 where id = :e"),
+                        {"e": endpoint_id})  # fmt: skip
+        await s.execute(text("update tenant_event_counters set pending_events = 0, pending_bytes = 0 "
+                             "where tenant_id = :t"), {"t": tenant})  # fmt: skip
+    with pytest.raises(Exception, match="permission denied"):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text("update inbound_events set attempts = 9 where id = :e"), {"e": mine})
```

### Task 6: An event that can't match is dead only when that's confirmed; the leader recounts the counters

**Commit:** `30e9333` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/src/dewpoint/apps/dispatcher/recount.py`,
`backend/tests/apps/dispatcher/test_matching_outcomes.py`, `backend/tests/apps/dispatcher/test_recount.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/apps/dispatcher/matching.py`,
`backend/tests/apps/dispatcher/test_main.py`

**What it does:**

A ciphertext that fails under a key version that has opened another event in this process, or a payload that isn't a
JSON object, is dead at once; an unconfirmed failure backs off (30 s, doubling) and is dead after 5 attempts. Dead
events release their pending counters and are audited. A platform-wide failure (a key version missing or not pairing,
the tenant's data key unreadable) waits a minute, its attempts untouched; the database itself failing writes nothing.
A match's alerts (a death, a key unavailable, a fan-out over the cap) are logged only once its transaction commits.

The recount (the leader, per tenant, at most every 10 minutes) takes the tenant's lifecycle lock shared, its endpoint
rows in id order and its counter row before it counts, then corrects every pending and retained counter that drifted,
warning only once its correction commits. Races: the recount against an insert and against a match, each way. A race
test that fails while holding releases at teardown.

**A later task refines this.** Task 7 moves the counter release to `core.ingress.counters` and the binding cap to
`core.ingress.filters`, which the API shares.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/dispatcher/test_main.py tests/apps/dispatcher/test_matching_outcomes.py
  tests/apps/dispatcher/test_recount.py`. Replay result (exit 1), shortened:

```
<replay>/t6/backend/src/dewpoint/core/ingress/keys.py:66: dewpoint.core.ingress.keys.NoEventKeyError: tenant d52a3e07-f199-42ca-b541-c2f6eb00db6b has no inbound keypair 7
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_main.py::test_the_leader_recounts_inbound_event_counters_and_reports_it
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_ciphertext_that_fails_under_a_key_that_opened_others_is_dead_at_once
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_an_unconfirmed_failure_backs_off_and_is_dead_after_five_attempts
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_payload_that_isnt_a_json_object_is_dead[not json-event_not_json]
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_payload_that_isnt_a_json_object_is_dead[[1, 2]-event_not_object]
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_missing_key_version_waits_with_an_alert_and_its_attempts_untouched
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_an_unreadable_data_key_waits_too
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_verified_version_rewrapped_with_another_key_keeps_its_events_pending
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_death_rolled_back_is_never_alerted_nor_audited
FAILED tests/apps/dispatcher/test_matching_outcomes.py::test_a_wait_rolled_back_is_never_alerted
ERROR tests/apps/dispatcher/test_recount.py - ImportError while importing tes...
10 failed, 3 passed, 1 error in 16.94s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
....................                                                     [100%]
20 passed in 25.04s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 30e9333 && git commit -C 30e9333`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 634a3f0..4ccceba 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -20,6 +20,7 @@ from dewpoint.apps.dispatcher.dispatch import Rotation, dispatch_once
 from dewpoint.apps.dispatcher.matching import Verified, match_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
+from dewpoint.apps.dispatcher.recount import recount_once
 from dewpoint.apps.dispatcher.schedule_sync import check_misses, sync_schedules
 from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, Ticker
 from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
@@ -51,7 +52,8 @@ async def cycle(
     instance: uuid.UUID, reconciler: uuid.UUID, leader: Leader, rotation: Rotation, verified: Verified | None = None,
 ) -> None:  # fmt: skip
     """One cycle: observe the current build, dispatch what's due, match inbound events, report; the leader also
-    reconciles, sends cancels, keeps the Temporal Schedules in step with their rows and reads their missed firings. An
+    reconciles, sends cancels, keeps the Temporal Schedules in step with their rows, reads their missed firings and
+    recounts the inbound-event counters due a recount. An
     observation that fails (Temporal, or the database, briefly unavailable) dispatches and matches nothing this cycle,
     and the next one asks again: admission would refuse a matched event's requests for good without a fresh record of
     the build (§7.2), which ages out meanwhile."""
@@ -71,6 +73,7 @@ async def cycle(
         settled.update({f"cancel_{k}": v for k, v in (await send_cancels(sessionmaker, client)).items()})
         settled.update({f"schedule_{k}": v for k, v in (await sync_schedules(sessionmaker, client, leader)).items()})
         settled.update({f"misses_{k}": v for k, v in (await check_misses(sessionmaker, client)).items()})
+        settled.update({f"recount_{k}": v for k, v in (await recount_once(sessionmaker)).items()})
         await report(sessionmaker, reconciler, build_id, {**settled}, kind="reconciler")
 
 
diff --git a/backend/src/dewpoint/apps/dispatcher/matching.py b/backend/src/dewpoint/apps/dispatcher/matching.py
index 6446f1c..5977253 100644
--- a/backend/src/dewpoint/apps/dispatcher/matching.py
+++ b/backend/src/dewpoint/apps/dispatcher/matching.py
@@ -13,7 +13,13 @@ The event is opened with the tenant's private key and, for each enabled binding
 workflow-id order (§7.2), one request is admitted: source `webhook`, key `evt:<event id>:<workflow id>`, the event as
 the trigger. Admission freezes it or records it `refused`; either is a request. The event is recorded `matched` with
 its request count, or `unmatched`, and its pending counters are released, together. A recheck that fails changes
-nothing; more enabled bindings than the cap (refused when they're written) wait, with an alert."""
+nothing; more enabled bindings than the cap (refused when they're written) wait, with an alert.
+
+An event is `dead` (audited, alerted on, its counters released) only for a confirmed event-specific failure: its
+ciphertext fails under a key version that has opened another event in this process, or its payload isn't a JSON
+object; or after `EVENT_ATTEMPTS` unconfirmed failures, backing off from `BACKOFF`, doubling. A platform-wide failure
+(a key version missing, the tenant's data key unreadable) waits `WAIT` with an alert, its attempts untouched; the
+database itself failing writes nothing (§8.3, §10.5)."""
 
 import json
 import uuid
@@ -21,14 +27,16 @@ from collections import Counter
 from datetime import timedelta
 
 import structlog
+from cryptography.exceptions import InvalidTag
 from sqlalchemy import func, or_, select, text, update
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 
 from dewpoint.apps import admission
 from dewpoint.apps.dispatcher.dispatch import GATE_LOCK, tenant_lock
+from dewpoint.core.audit import service as audit
 from dewpoint.core.crypto import events
-from dewpoint.core.crypto.keys import KeySource
-from dewpoint.core.db import tenant_scope
+from dewpoint.core.crypto.keys import KeySource, key_unreadable
+from dewpoint.core.db import tenant_scope, unavailable
 from dewpoint.core.ingress import keys as event_keys
 from dewpoint.core.ingress.filters import matches
 from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
@@ -48,7 +56,16 @@ ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
 TENANT_ERASING = "tenant_erasing"
 SKIPPED = "skipped"
 FAN_OUT_EXCEEDED = "fan_out_exceeded"
+KEY_UNAVAILABLE = "key_unavailable"
+RETRYING = "retrying"
+DEAD = "dead"
+EVENT_UNREADABLE = "event_unreadable"
+EVENT_NOT_JSON = "event_not_json"
+EVENT_NOT_OBJECT = "event_not_object"
+EVENT_ATTEMPTS = 5  # event-specific attempts before an unconfirmed failure is dead (§8.3)
+BACKOFF = timedelta(seconds=30)  # after the first event-specific failure, doubling (§15, provisional)
 ROLLED_BACK = (GATE_OFF, ENVIRONMENT_NOT_RECORDED, TENANT_ERASING, SKIPPED)
+ALERTS = "dewpoint.matching.alerts"  # in the session's `info`: alerts logged once its transaction commits
 
 
 class Verified:
@@ -68,6 +85,15 @@ async def _after_event_locked() -> None:
     """Runs once a match holds its event's row. A no-op; the race tests hold a match here."""
 
 
+async def _before_commit() -> None:
+    """Runs as a match is about to commit what it decided. A no-op; the tests fail a transaction here."""
+
+
+def _alert(s: AsyncSession, event: str, **fields: object) -> None:
+    """An alert to log once the transaction has committed, never for one rolled back."""
+    s.info.setdefault(ALERTS, []).append((event, fields))
+
+
 def gate_off(platform: PlatformSettings | None) -> str | None:
     """Why nothing is matched now, or None: no recorded environment, or a production deployment's runs off."""
     if platform is None:
@@ -107,11 +133,17 @@ async def match_event(
     sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, tenant_id: uuid.UUID,
     event_id: uuid.UUID, endpoint_id: uuid.UUID,
 ) -> str:  # fmt: skip
-    """One event's matching transaction: `matched`, `unmatched`, or why it waits or was passed by."""
-    async with sessionmaker() as s, s.begin():
-        outcome = await _match(s, keys, verified, tenant_id, event_id, endpoint_id)
-        if outcome in ROLLED_BACK:
-            await s.rollback()
+    """One event's matching transaction: `matched`, `unmatched`, or why it waits or was passed by. Its alerts are
+    logged once it has committed: a transaction rolled back alerts on nothing (the owner's M3 review)."""
+    async with sessionmaker() as s:
+        async with s.begin():
+            outcome = await _match(s, keys, verified, tenant_id, event_id, endpoint_id)
+            if outcome in ROLLED_BACK:
+                await s.rollback()
+            else:
+                await _before_commit()
+        for event, fields in s.info.pop(ALERTS, []):  # committed
+            log.error(event, **fields)
         return outcome
 
 
@@ -155,11 +187,30 @@ async def _match(
     if event is None:
         return SKIPPED
     await _after_event_locked()
-    private = await event_keys.private_key(s, keys, tenant_id, event.key_version)
-    plaintext = events.open_sealed(private, tenant_id=tenant_id, endpoint_id=endpoint_id, event_id=event.id,
-                                   blob=event.sealed)  # fmt: skip
+    try:
+        private = await event_keys.private_key(s, keys, tenant_id, event.key_version)
+    except Exception as e:  # no fault of the event's: a version missing, or the tenant's data key unreadable
+        if unavailable(e) or not (isinstance(e, event_keys.NoEventKeyError) or key_unreadable(e)):
+            raise  # the database itself, or a bug: nothing written, the event as it was
+        _alert(s, "event_key_unavailable", tenant_id=str(tenant_id), version=event.key_version,
+               error=type(e).__name__)  # fmt: skip
+        event.next_attempt_at = func.statement_timestamp() + WAIT
+        await s.flush()
+        return KEY_UNAVAILABLE
+    try:
+        plaintext = events.open_sealed(private, tenant_id=tenant_id, endpoint_id=endpoint_id, event_id=event.id,
+                                       blob=event.sealed)  # fmt: skip
+    except (InvalidTag, ValueError):
+        if (tenant_id, event.key_version) in verified:  # confirmed: the key is good, the event isn't
+            return await _dead(s, event, EVENT_UNREADABLE)
+        return await _retry(s, event, EVENT_UNREADABLE)
     verified.add(tenant_id, event.key_version)
-    payload = json.loads(plaintext)
+    try:
+        payload = json.loads(plaintext)
+    except ValueError:
+        return await _dead(s, event, EVENT_NOT_JSON)
+    if not isinstance(payload, dict):
+        return await _dead(s, event, EVENT_NOT_OBJECT)
     bindings = (
         await s.execute(
             select(TriggerBinding)
@@ -169,7 +220,7 @@ async def _match(
         )
     ).scalars().all()  # fmt: skip
     if len(bindings) > MAX_BINDINGS:
-        log.error("event_fan_out_exceeded", endpoint_id=str(endpoint_id), event_id=str(event.id))
+        _alert(s, "event_fan_out_exceeded", endpoint_id=str(endpoint_id), event_id=str(event.id))
         event.next_attempt_at = func.statement_timestamp() + WAIT
         await s.flush()
         return FAN_OUT_EXCEEDED
@@ -191,6 +242,28 @@ async def _match(
     return event.status
 
 
+async def _retry(s: AsyncSession, event: InboundEvent, reason: str) -> str:
+    """An event-specific failure not yet confirmed: another attempt later, backing off, dead after the last."""
+    event.attempts += 1
+    if event.attempts >= EVENT_ATTEMPTS:
+        return await _dead(s, event, reason)
+    event.next_attempt_at = func.statement_timestamp() + BACKOFF * 2 ** (event.attempts - 1)
+    await s.flush()
+    return RETRYING
+
+
+async def _dead(s: AsyncSession, event: InboundEvent, reason: str) -> str:
+    """An event that will never match: dead, its pending counters released, audited and alerted on."""
+    event.status, event.reason, event.ended_at = DEAD, reason, func.statement_timestamp()
+    await release(s, event.tenant_id, event.endpoint_id, event.size_bytes)
+    details: dict[str, object] = {"endpoint_id": str(event.endpoint_id), "reason": reason, "attempts": event.attempts}
+    await audit.record(s, tenant_id=event.tenant_id, actor_id=None, action="inbound_event.dead",
+                       target_type="inbound_event", target_id=str(event.id), details=details)  # fmt: skip
+    _alert(s, "inbound_event_dead", tenant_id=str(event.tenant_id), event_id=str(event.id), reason=reason)
+    await s.flush()
+    return DEAD
+
+
 async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
     """An event's pending counters released, on its endpoint and its tenant, whose rows the caller holds. Never below
     zero: a drift the recount corrects doesn't block an event's end."""
diff --git a/backend/src/dewpoint/apps/dispatcher/recount.py b/backend/src/dewpoint/apps/dispatcher/recount.py
new file mode 100644
index 0000000..4924a1f
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/recount.py
@@ -0,0 +1,119 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The recount of inbound-event counters (engine 2b spec §8.3; "Retained storage" in the 2b-3b outline), by the
+leader. Each tenant `recount_candidates()` picks (at most every 10 minutes) is recounted in one transaction, under the
+one lock order: the tenant's lifecycle lock shared, its endpoint rows in id order, its counter row, all held **before**
+it counts, so no insert or match in flight is overwritten by a stale total. Every pending and retained counter that
+drifted from what the events say is corrected and warned about."""
+
+import uuid
+from collections import Counter
+
+import structlog
+from sqlalchemy import func, select, text, update
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps.dispatcher.dispatch import tenant_lock
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, WebhookEndpoint
+
+log = structlog.get_logger("dewpoint.dispatcher.recount")
+BATCH = 20  # tenants a leader's cycle
+FIELDS = ("pending_events", "pending_bytes", "retained_events", "retained_bytes")
+
+
+async def _after_recount_locked() -> None:
+    """Runs once a recount holds its tenant's rows, before it counts. A no-op; the race tests hold a recount here."""
+
+
+async def _before_recount_commit() -> None:
+    """Runs as a recount is about to commit its corrections. A no-op; the tests fail a transaction here."""
+
+
+async def recount_once(sessionmaker: async_sessionmaker[AsyncSession], *, batch: int = BATCH) -> dict[str, int]:
+    """The tenants due a recount, each recounted: how many, and how many rows were corrected. A recount that fails is
+    logged by type and leaves its tenant for a later cycle."""
+    async with sessionmaker() as s:
+        query = text("select tenant_id from recount_candidates(:n)")
+        picked: list[uuid.UUID] = list((await s.execute(query, {"n": batch})).scalars().all())
+    counts: Counter[str] = Counter()
+    for tenant_id in picked:
+        try:
+            counts["drifted"] += await recount_tenant(sessionmaker, tenant_id)
+            counts["recounted"] += 1
+        except Exception as e:
+            log.error("event_recount_failed", tenant_id=str(tenant_id), error=type(e).__name__)
+            counts["error"] += 1
+    return dict(counts)
+
+
+async def recount_tenant(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID) -> int:
+    """One tenant's counters recounted under its locks: the rows corrected. Each correction is warned about once it
+    has committed, never for one rolled back (the owner's M3 review)."""
+    drifts: list[dict[str, object]] = []
+    async with sessionmaker() as s:
+        async with s.begin():
+            corrected = await _recount(s, tenant_id, drifts)
+            await _before_recount_commit()
+    for drift in drifts:  # committed
+        log.warning("event_counters_drifted", **drift)
+    return corrected
+
+
+async def _recount(s: AsyncSession, tenant_id: uuid.UUID, drifts: list[dict[str, object]]) -> int:
+    await tenant_scope(s, tenant_id)
+    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"),
+                    {"k": tenant_lock(tenant_id)})  # fmt: skip
+    endpoints = (
+        await s.execute(
+            select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id).order_by(WebhookEndpoint.id)
+            .with_for_update().execution_options(populate_existing=True)
+        )
+    ).scalars().all()  # fmt: skip
+    counter = (
+        await s.execute(
+            select(TenantEventCounters).where(TenantEventCounters.tenant_id == tenant_id).with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()  # fmt: skip
+    if counter is None:
+        return 0
+    await _after_recount_locked()
+    pending = InboundEvent.status == "pending"
+    rows = await s.execute(
+        select(
+            InboundEvent.endpoint_id,
+            func.count().filter(pending),
+            func.coalesce(func.sum(InboundEvent.size_bytes).filter(pending), 0),
+            func.count(),
+            func.coalesce(func.sum(InboundEvent.size_bytes), 0),
+        )
+        .where(InboundEvent.tenant_id == tenant_id)
+        .group_by(InboundEvent.endpoint_id)
+    )
+    by_endpoint = {row[0]: tuple(int(v) for v in row[1:]) for row in rows.all()}
+    corrected = 0
+    for endpoint in endpoints:
+        truth = by_endpoint.get(endpoint.id, (0, 0, 0, 0))
+        if await _correct(s, WebhookEndpoint, WebhookEndpoint.id == endpoint.id, endpoint, truth, drifts,
+                          tenant_id=str(tenant_id), endpoint_id=str(endpoint.id)):  # fmt: skip
+            corrected += 1
+    totals = tuple(sum(values[i] for values in by_endpoint.values()) for i in range(len(FIELDS)))
+    if await _correct(s, TenantEventCounters, TenantEventCounters.tenant_id == tenant_id, counter, totals, drifts,
+                      tenant_id=str(tenant_id)):  # fmt: skip
+        corrected += 1
+    await s.execute(
+        update(TenantEventCounters).where(TenantEventCounters.tenant_id == tenant_id)
+        .values(recounted_at=func.now())
+    )  # fmt: skip
+    return corrected
+
+
+async def _correct(s: AsyncSession, model: type, where: object, row: object, truth: tuple[int, ...],
+                   drifts: list[dict[str, object]], **named: str) -> bool:  # fmt: skip
+    stored = tuple(getattr(row, field) for field in FIELDS)
+    if stored == truth:
+        return False
+    drifts.append({**named, "stored": dict(zip(FIELDS, stored, strict=True)),
+                   "counted": dict(zip(FIELDS, truth, strict=True))})  # fmt: skip
+    await s.execute(update(model).where(where).values(dict(zip(FIELDS, truth, strict=True))))  # type: ignore[arg-type]
+    return True
diff --git a/backend/tests/apps/dispatcher/test_main.py b/backend/tests/apps/dispatcher/test_main.py
index 4df0795..404ee7a 100644
--- a/backend/tests/apps/dispatcher/test_main.py
+++ b/backend/tests/apps/dispatcher/test_main.py
@@ -102,3 +102,36 @@ async def test_a_cycle_matches_events_only_when_it_observed_the_current_build(
     await cycle()
     assert (await event_state(owner_sessionmaker, event_id))["status"] == "matched"
     assert (await reported(owner_sessionmaker, instance)) == {"current_build": True, "event_matched": 1}
+
+
+async def test_the_leader_recounts_inbound_event_counters_and_reports_it(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
+    api_settings, monkeypatch,
+) -> None:  # fmt: skip
+    from tests.apps.dispatcher.inbound import inbound, send
+
+    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
+                          api_settings)  # fmt: skip
+    await send(ingress_sessionmaker, ready, {"type": "ap_down"})
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update webhook_endpoints set pending_events = 5 where id = :e"), {"e": ready.endpoint_id})
+
+    async def nothing(*args: Any, **kwargs: Any) -> dict[str, int]:
+        return {}
+
+    for step in ("reconcile_once", "send_cancels", "sync_schedules", "check_misses"):
+        monkeypatch.setattr(main, step, nothing)
+
+    class Leading:
+        async def leading(self) -> bool:
+            return True
+
+    client = FakeClient()
+    client.workflow_service = Flaky(failures=0)
+    reconciler = uuid.uuid4()
+    await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=uuid.uuid4(), reconciler=reconciler,
+                     leader=Leading(), rotation=dispatch.Rotation())  # type: ignore[arg-type]  # fmt: skip
+    assert await reported(owner_sessionmaker, reconciler) == {"recount_recounted": 1, "recount_drifted": 1}
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
+                                {"e": ready.endpoint_id})).scalar_one() == 0  # fmt: skip
diff --git a/backend/tests/apps/dispatcher/test_matching_outcomes.py b/backend/tests/apps/dispatcher/test_matching_outcomes.py
new file mode 100644
index 0000000..07533d3
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_matching_outcomes.py
@@ -0,0 +1,203 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What becomes of an event that can't be matched (engine 2b spec §8.3, §10.5): `dead` only for a confirmed
+event-specific, unrecoverable failure (its ciphertext doesn't authenticate while its key version is present and opens
+other events; its payload isn't a JSON object) or after 5 event-specific attempts, backing off. A platform-wide
+failure (a key version missing, the tenant's data key unreadable) keeps it pending, backing off with an alert, its
+attempts untouched. A dead event's pending counters are released, and its death audited."""
+
+import uuid
+from datetime import UTC, datetime, timedelta
+from typing import Any
+
+import pytest
+import structlog
+from sqlalchemy import text
+
+from dewpoint.apps.dispatcher import matching
+from dewpoint.core.crypto import events
+from tests.apps.dispatcher.inbound import bind, counters, event_state, inbound, send
+from tests.apps.test_admission import KEYS
+from tests.support.keys import FixtureKeys
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+ALARM = {"type": "ap_down"}
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    found = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
+    await bind(owner_sessionmaker, found)
+    return found
+
+
+async def matched(dispatch: Any, inbound: Any, event_id: uuid.UUID, verified: Any, keys: Any = KEYS) -> str:
+    return await matching.match_event(
+        dispatch, keys, verified, tenant_id=inbound.tenant_id, event_id=event_id, endpoint_id=inbound.endpoint_id
+    )
+
+
+async def tampered(owner: Any, event_id: uuid.UUID) -> None:
+    """The event's ciphertext with its last byte flipped (its tag): the same size, no longer authentic."""
+    async with owner() as s, s.begin():
+        await s.execute(text("update inbound_events set sealed = overlay(sealed placing set_byte('\\x00', 0, "
+                             "get_byte(sealed, length(sealed) - 1) # 1) from length(sealed)) where id = :e"),
+                        {"e": event_id})  # fmt: skip
+
+
+async def resealed(owner: Any, inbound: Any, event_id: uuid.UUID, plaintext: bytes, version: int = 1) -> None:
+    """The event's payload replaced by `plaintext`, authentically sealed (what a bug before sealing could store)."""
+    blob = events.seal(inbound.public_key, version, tenant_id=inbound.tenant_id, endpoint_id=inbound.endpoint_id,
+                       event_id=event_id, plaintext=plaintext)  # fmt: skip
+    async with owner() as s, s.begin():
+        await s.execute(text("update inbound_events set sealed = :b, size_bytes = :n, key_version = :v where id = :e"),
+                        {"b": blob, "n": len(blob), "v": version, "e": event_id})  # fmt: skip
+
+
+async def due(owner: Any, event_id: uuid.UUID) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text("update inbound_events set next_attempt_at = null where id = :e"), {"e": event_id})
+
+
+async def deaths(owner: Any) -> list[dict[str, Any]]:
+    async with owner() as s:
+        found = await s.execute(text("select target_id, details from audit_log where action = 'inbound_event.dead'"))
+        return [dict(r) for r in found.mappings()]
+
+
+async def test_a_ciphertext_that_fails_under_a_key_that_opened_others_is_dead_at_once(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    good, bad = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
+    await tampered(owner_sessionmaker, bad)
+    verified = matching.Verified()
+    assert await matched(dispatch_sessionmaker, ready, good, verified) == "matched"
+    with structlog.testing.capture_logs() as logs:
+        assert await matched(dispatch_sessionmaker, ready, bad, verified) == "dead"
+    state = await event_state(owner_sessionmaker, bad)
+    assert (state["status"], state["reason"], state["request_count"]) == ("dead", "event_unreadable", None)
+    assert state["ended_at"] is not None
+    assert await counters(owner_sessionmaker, ready) == ((0, 0), (0, 0))
+    assert [d["target_id"] for d in await deaths(owner_sessionmaker)] == [str(bad)]
+    assert any(e["event"] == "inbound_event_dead" and e["log_level"] == "error" for e in logs)
+
+
+async def test_an_unconfirmed_failure_backs_off_and_is_dead_after_five_attempts(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    await tampered(owner_sessionmaker, event_id)
+    waits = []
+    for attempt in range(1, matching.EVENT_ATTEMPTS):
+        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "retrying"
+        state = await event_state(owner_sessionmaker, event_id)
+        assert (state["status"], state["attempts"]) == ("pending", attempt)
+        waits.append(state["next_attempt_at"] - datetime.now(UTC))
+        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "skipped"  # not due
+        await due(owner_sessionmaker, event_id)
+    assert [round(w / timedelta(seconds=30)) for w in waits] == [1, 2, 4, 8]  # doubling from 30 s
+    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "dead"
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["reason"], state["attempts"]) == (
+        "dead",
+        "event_unreadable",
+        matching.EVENT_ATTEMPTS,
+    )
+
+
+@pytest.mark.parametrize(("plaintext", "reason"), [(b"not json", "event_not_json"), (b"[1, 2]", "event_not_object")])
+async def test_a_payload_that_isnt_a_json_object_is_dead(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                         dispatch_sessionmaker, plaintext, reason) -> None:  # fmt: skip
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    await resealed(owner_sessionmaker, ready, event_id, plaintext)
+    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "dead"
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["reason"]) == ("dead", reason)
+    async with owner_sessionmaker() as s:  # the endpoint's counter only: resealing changed the size the tenant's saw
+        assert (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
+                                {"e": ready.endpoint_id})).scalar_one() == 0  # fmt: skip
+
+
+async def test_a_missing_key_version_waits_with_an_alert_and_its_attempts_untouched(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update inbound_events set key_version = 7 where id = :e"), {"e": event_id})
+    with structlog.testing.capture_logs() as logs:
+        assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "key_unavailable"
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["attempts"]) == ("pending", 0)
+    assert state["next_attempt_at"] - datetime.now(UTC) == pytest.approx(matching.WAIT, abs=timedelta(seconds=5))
+    assert [e for e in logs if e["event"] == "event_key_unavailable"][0]["log_level"] == "error"
+
+
+async def test_an_unreadable_data_key_waits_too(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                dispatch_sessionmaker) -> None:  # fmt: skip
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    keys = FixtureKeys(missing={str(ready.tenant_id)})
+    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified(), keys) == "key_unavailable"
+    state = await event_state(owner_sessionmaker, event_id)
+    assert (state["status"], state["attempts"]) == ("pending", 0)
+    await due(owner_sessionmaker, event_id)
+    assert await matched(dispatch_sessionmaker, ready, event_id, matching.Verified()) == "matched"  # the key back
+
+
+async def test_a_verified_version_rewrapped_with_another_key_keeps_its_events_pending(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """The owner's M3 review: a keypair whose private key no longer pairs with its public one is the keypair's failure.
+    Its events wait, alerted on, attempts untouched; none is dead, though the version opened an event before."""
+    from dewpoint.core.claims.cipher import ClaimCipher
+    from dewpoint.core.ingress.keys import PURPOSE
+
+    first, second = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
+    verified = matching.Verified()
+    assert await matched(dispatch_sessionmaker, ready, first, verified) == "matched"
+    other, _ = events.generate_keypair()
+    rewrapped = await ClaimCipher(KEYS, purpose=PURPOSE).seal(str(ready.tenant_id), "1", other)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenant_event_keys set private_sealed = :p where tenant_id = :t"),
+                        {"p": rewrapped, "t": ready.tenant_id})  # fmt: skip
+    with structlog.testing.capture_logs() as logs:
+        assert await matched(dispatch_sessionmaker, ready, second, verified) == "key_unavailable"
+    state = await event_state(owner_sessionmaker, second)
+    assert (state["status"], state["attempts"], state["reason"]) == ("pending", 0, None)
+    assert [e["error"] for e in logs if e["event"] == "event_key_unavailable"] == ["EventKeyMismatchError"]
+    assert await deaths(owner_sessionmaker) == []
+
+
+async def test_a_death_rolled_back_is_never_alerted_nor_audited(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    """The owner's M3 review: an outcome's alert is logged once its transaction has committed, never before. A death
+    whose transaction fails before its commit leaves no alert, no audit entry and the event pending."""
+    good, bad = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
+    await tampered(owner_sessionmaker, bad)
+    verified = matching.Verified()
+    assert await matched(dispatch_sessionmaker, ready, good, verified) == "matched"
+
+    async def fail() -> None:
+        raise RuntimeError("the commit never happens")
+
+    monkeypatch.setattr(matching, "_before_commit", fail, raising=False)
+    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
+        await matched(dispatch_sessionmaker, ready, bad, verified)
+    assert [e for e in logs if e["event"] == "inbound_event_dead"] == []
+    assert (await event_state(owner_sessionmaker, bad))["status"] == "pending"
+    assert await deaths(owner_sessionmaker) == []
+
+
+async def test_a_wait_rolled_back_is_never_alerted(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                   dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update inbound_events set key_version = 7 where id = :e"), {"e": event_id})
+
+    async def fail() -> None:
+        raise RuntimeError("the commit never happens")
+
+    monkeypatch.setattr(matching, "_before_commit", fail, raising=False)
+    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
+        await matched(dispatch_sessionmaker, ready, event_id, matching.Verified())
+    assert [e for e in logs if e["event"] == "event_key_unavailable"] == []
+    assert (await event_state(owner_sessionmaker, event_id))["next_attempt_at"] is None
diff --git a/backend/tests/apps/dispatcher/test_recount.py b/backend/tests/apps/dispatcher/test_recount.py
new file mode 100644
index 0000000..f8b2ad0
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_recount.py
@@ -0,0 +1,214 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The recount (engine 2b spec §8.3; "Retained storage" and "Functions and lock order" in the 2b-3b outline): the
+leader, per tenant, at most every 10 minutes, takes the tenant's lifecycle lock shared, its endpoint rows in id order
+and its counter row **first**, then counts the events and corrects every pending and retained counter that drifted, in
+that transaction, so no insert or match in flight is overwritten by a stale total."""
+
+import asyncio
+from typing import Any
+
+import pytest
+import structlog
+from sqlalchemy import text
+
+from dewpoint.apps.dispatcher import matching, recount
+from tests.apps.dispatcher.inbound import bind, inbound, lock_waiters, send
+from tests.apps.test_admission import KEYS
+from tests.core.ingress.support import RECORD
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+ALARM = {"type": "ap_down"}
+COUNTERS = "pending_events, pending_bytes, retained_events, retained_bytes"
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    found = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
+    await bind(owner_sessionmaker, found)
+    return found
+
+
+async def counted(owner: Any, inbound: Any) -> tuple[tuple[int, ...], tuple[int, ...]]:
+    """(the endpoint's counters, the tenant's), as stored."""
+    async with owner() as s:
+        e = (await s.execute(text(f"select {COUNTERS} from webhook_endpoints where id = :e"),  # noqa: S608
+                             {"e": inbound.endpoint_id})).one()  # fmt: skip
+        t = (await s.execute(text(f"select {COUNTERS} from tenant_event_counters where tenant_id = :t"),  # noqa: S608
+                             {"t": inbound.tenant_id})).one()  # fmt: skip
+    return tuple(e), tuple(t)
+
+
+async def truth(owner: Any, inbound: Any) -> tuple[int, ...]:
+    """The counters the events themselves say."""
+    async with owner() as s:
+        row = await s.execute(
+            text("select count(*) filter (where status = 'pending'), coalesce(sum(size_bytes) filter (where status = "
+                 "'pending'), 0), count(*), coalesce(sum(size_bytes), 0) from inbound_events where endpoint_id = :e"),
+            {"e": inbound.endpoint_id},
+        )  # fmt: skip
+        return tuple(int(v) for v in row.one())
+
+
+async def drifted(owner: Any, inbound: Any) -> None:
+    async with owner() as s, s.begin():
+        for table, where in (("webhook_endpoints", "id = :e"), ("tenant_event_counters", "tenant_id = :t")):
+            await s.execute(
+                text(
+                    f"update {table} set pending_events = 99, pending_bytes = 7, retained_events = 0, "  # noqa: S608
+                    f"retained_bytes = 1 where {where}"
+                ),
+                {"e": inbound.endpoint_id, "t": inbound.tenant_id},
+            )
+
+
+async def test_drifted_counters_are_corrected_and_the_tenant_isnt_recounted_again_soon(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
+) -> None:
+    one, _ = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
+    assert await matching.match_event(dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id,
+                                      event_id=one, endpoint_id=ready.endpoint_id) == "matched"  # fmt: skip
+    right = await truth(owner_sessionmaker, ready)
+    await drifted(owner_sessionmaker, ready)
+    with structlog.testing.capture_logs() as logs:
+        assert await recount.recount_once(dispatch_sessionmaker) == {"recounted": 1, "drifted": 2}
+    assert await counted(owner_sessionmaker, ready) == (right, right)
+    assert {e["event"] for e in logs} == {"event_counters_drifted"}
+    assert await recount.recount_once(dispatch_sessionmaker) == {}  # recounted within the last 10 minutes
+
+
+async def test_counters_that_agree_are_left_alone(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                  dispatch_sessionmaker) -> None:  # fmt: skip
+    await send(ingress_sessionmaker, ready, ALARM)
+    before = await counted(owner_sessionmaker, ready)
+    assert await recount.recount_once(dispatch_sessionmaker) == {"recounted": 1, "drifted": 0}
+    assert await counted(owner_sessionmaker, ready) == before
+
+
+_RELEASES: list[asyncio.Event] = []
+
+
+@pytest.fixture(autouse=True)
+async def _released() -> Any:
+    """A race test that fails while a recount or a match is held releases it before the teardown's truncate, which
+    would otherwise wait for its locks for ever: a regression fails the test, never hangs the suite."""
+    yield
+    while _RELEASES:
+        _RELEASES.pop().set()
+    await asyncio.sleep(0)
+
+
+async def _held(monkeypatch: Any, module: Any, hook: str) -> tuple[asyncio.Event, asyncio.Event]:
+    """A recount or a match that, holding its rows, waits until released (at the latest when the test ends)."""
+    reached, release = asyncio.Event(), asyncio.Event()
+    _RELEASES.append(release)
+
+    async def hold() -> None:
+        reached.set()
+        await release.wait()
+
+    monkeypatch.setattr(module, hook, hold)
+    return reached, release
+
+
+async def _waiting(owner: Any) -> None:
+    for _ in range(300):
+        if await lock_waiters(owner):
+            return
+        await asyncio.sleep(0.01)
+    raise AssertionError("nothing waited for a lock")
+
+
+async def _insert(ingress: Any, inbound: Any) -> Any:
+    from tests.apps.dispatcher.test_matching import _params
+
+    async with ingress() as s, s.begin():
+        return dict((await s.execute(RECORD, _params(inbound, ALARM | {"late": True}, b"z" * 32))).scalar_one())
+
+
+async def test_an_insert_waits_for_a_recount_and_is_counted_after_it(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    await send(ingress_sessionmaker, ready, ALARM)
+    await drifted(owner_sessionmaker, ready)
+    reached, release = await _held(monkeypatch, recount, "_after_recount_locked")
+    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
+    await reached.wait()
+    inserting = asyncio.create_task(_insert(ingress_sessionmaker, ready))
+    await _waiting(owner_sessionmaker)  # on the endpoint's row
+    release.set()
+    await counting
+    assert (await inserting)["accepted"] == 1
+    right = await truth(owner_sessionmaker, ready)
+    assert right[0] == 2 and await counted(owner_sessionmaker, ready) == (right, right)
+
+
+async def test_a_recount_waits_for_an_insert_and_counts_it(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                           dispatch_sessionmaker) -> None:  # fmt: skip
+    from tests.apps.dispatcher.test_matching import _params
+
+    await send(ingress_sessionmaker, ready, ALARM)
+    await drifted(owner_sessionmaker, ready)
+    async with ingress_sessionmaker() as s, s.begin():
+        await s.execute(RECORD, _params(ready, ALARM | {"late": True}, b"z" * 32))
+        counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
+        await _waiting(owner_sessionmaker)
+    await counting
+    right = await truth(owner_sessionmaker, ready)
+    assert right[0] == 2 and await counted(owner_sessionmaker, ready) == (right, right)
+
+
+async def test_a_match_waits_for_a_recount_and_releases_after_it(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    await drifted(owner_sessionmaker, ready)
+    reached, release = await _held(monkeypatch, recount, "_after_recount_locked")
+    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
+    await reached.wait()
+    matcher = asyncio.create_task(matching.match_event(
+        dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id, event_id=event_id,
+        endpoint_id=ready.endpoint_id,
+    ))  # fmt: skip
+    await _waiting(owner_sessionmaker)
+    release.set()
+    await counting
+    assert await matcher == "matched"
+    right = await truth(owner_sessionmaker, ready)
+    assert right[0] == 0 and await counted(owner_sessionmaker, ready) == (right, right)
+
+
+async def test_a_recount_waits_for_a_match_and_counts_after_it(
+    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
+    await drifted(owner_sessionmaker, ready)
+    reached, release = await _held(monkeypatch, matching, "_after_event_locked")
+    matcher = asyncio.create_task(matching.match_event(
+        dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id, event_id=event_id,
+        endpoint_id=ready.endpoint_id,
+    ))  # fmt: skip
+    await reached.wait()
+    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
+    await _waiting(owner_sessionmaker)
+    release.set()
+    assert await matcher == "matched"
+    await counting
+    right = await truth(owner_sessionmaker, ready)
+    assert right[0] == 0 and await counted(owner_sessionmaker, ready) == (right, right)
+
+
+async def test_a_correction_rolled_back_is_never_warned(ready, owner_sessionmaker, ingress_sessionmaker,
+                                                        dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
+    """The owner's M3 review: drift is warned about once its correction has committed, never before."""
+    await send(ingress_sessionmaker, ready, ALARM)
+    await drifted(owner_sessionmaker, ready)
+    before = await counted(owner_sessionmaker, ready)
+
+    async def fail() -> None:
+        raise RuntimeError("the commit never happens")
+
+    monkeypatch.setattr(recount, "_before_recount_commit", fail, raising=False)
+    with structlog.testing.capture_logs() as logs:
+        assert await recount.recount_once(dispatch_sessionmaker) == {"error": 1}
+    assert [e for e in logs if e["event"] == "event_counters_drifted"] == []
+    assert await counted(owner_sessionmaker, ready) == before
```

### Task 7: Webhook endpoints, bindings and inbound events, their secrets shown once and their cancels admins'

**Commit:** `6e97235` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/src/dewpoint/apps/api/routes/webhooks.py`, `backend/src/dewpoint/apps/webhooks.py`,
`backend/src/dewpoint/core/ingress/counters.py`, `backend/tests/apps/api/test_webhooks_api.py`

**Modify:** `backend/src/dewpoint/apps/api/main.py`, `backend/src/dewpoint/apps/dispatcher/matching.py`,
`backend/src/dewpoint/core/ingress/filters.py`, `backend/src/dewpoint/core/models/ingress.py`,
`backend/tests/apps/dispatcher/test_matching.py`, `backend/tests/core/ingress/test_filters.py`

**What it does:**

`trigger.manage` makes, updates and rotates endpoints and writes bindings; `workflow.view` reads them. A secret is
made by Dewpoint and shown once: a bearer token kept as its digest, or an HMAC secret sealed under the ingress key with
the endpoint's id as context (ingress authenticates a request signed with it); the dedupe-digest key survives
rotation. Making an endpoint makes the tenant's inbound keypair if it lacks one and gives it a byte burst that covers
its largest charge; its identity never changes. Pointers, header names and allowlists are checked; a binding's
workflow must be its tenant's, once per endpoint, at most 20 (counted under the endpoint's row lock), its filter
checked. Events' metadata is read with `workflow.view`, never a payload, dead events only by admins; dead events are
listed, and pending or dead events cancelled (singly or an endpoint's pending ones), with `tenant.manage`, under the
lock order, audited, their pending counters released (the release and the tenant's lock shared from
`core.ingress.counters`). The tenant's backlog and retained usage. Without the ingress key, nothing that seals a secret
is written. Races: two bindings at the cap; a cancel against a match, each way.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/api/test_webhooks_api.py tests/apps/dispatcher/test_matching.py tests/core/ingress/test_filters.py`. Replay
  result (exit 1), shortened:

```
FAILED tests/apps/api/test_webhooks_api.py::test_writing_an_endpoint_needs_trigger_manage_and_the_ingress_key
FAILED tests/apps/api/test_webhooks_api.py::test_an_endpoint_that_isnt_one_is_refused_with_what_to_change[given4-allowlist]
FAILED tests/apps/api/test_webhooks_api.py::test_rotating_a_secret_shows_the_new_one_once_and_keeps_deduplication
FAILED tests/apps/api/test_webhooks_api.py::test_an_endpoint_is_updated_and_disabled_but_never_its_identity
FAILED tests/apps/api/test_webhooks_api.py::test_bindings_are_checked_capped_and_unique
FAILED tests/apps/api/test_webhooks_api.py::test_events_are_listed_as_metadata_only
FAILED tests/apps/api/test_webhooks_api.py::test_an_admin_lists_dead_events_and_cancels_pending_or_dead_ones
FAILED tests/apps/api/test_webhooks_api.py::test_an_admin_cancels_an_endpoints_pending_events_at_once
FAILED tests/apps/api/test_webhooks_api.py::test_two_bindings_made_at_once_never_pass_the_cap_together
FAILED tests/apps/api/test_webhooks_api.py::test_an_endpoints_event_list_shows_dead_events_to_admins_only
FAILED tests/apps/dispatcher/test_matching.py::test_a_cancel_waits_for_a_match_in_flight_and_finds_it_matched
FAILED tests/apps/dispatcher/test_matching.py::test_a_match_waits_for_a_cancel_and_passes_the_cancelled_event_by
FAILED tests/core/ingress/test_filters.py::test_the_tenant_lock_is_the_one_the_dispatchers_starts_take
25 failed, 31 passed in 39.32s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........................................................                 [100%]
56 passed in 23.55s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 6e97235 && git commit -C 6e97235`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/api/main.py b/backend/src/dewpoint/apps/api/main.py
index 18f9cc4..ad100d1 100644
--- a/backend/src/dewpoint/apps/api/main.py
+++ b/backend/src/dewpoint/apps/api/main.py
@@ -22,9 +22,11 @@ from dewpoint.apps.api.routes import (
     runs,
     schedules,
     tenants,
+    webhooks,
     workflows,
 )
 from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.crypto.ingress import IngressKey
 from dewpoint.core.crypto.kek import KekSet
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.crypto.keys import KeyringKeys
@@ -49,6 +51,8 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.state.sessionmaker = make_sessionmaker(app.state.engine)
     app.state.keyring = Keyring(KekSet.from_settings(settings))
     app.state.keys = KeyringKeys(app.state.sessionmaker, app.state.keyring)  # admission's: claims, envelopes, digests
+    # Webhook endpoints' secrets (engine 2b spec §8.3): without the ingress key, nothing that seals one is written.
+    app.state.ingress_key = IngressKey.from_settings(settings) if settings.ingress_key_b64 else None
     # Created eagerly (not in the lifespan) so ASGI test transports, which skip lifespan, get it too.
     app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)
     app.add_middleware(
@@ -76,6 +80,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
         csv_uploads.router,
         runs.router,
         schedules.router,
+        webhooks.router,
     ):
         app.include_router(router)
     return app
diff --git a/backend/src/dewpoint/apps/api/routes/webhooks.py b/backend/src/dewpoint/apps/api/routes/webhooks.py
new file mode 100644
index 0000000..86af8a1
--- /dev/null
+++ b/backend/src/dewpoint/apps/api/routes/webhooks.py
@@ -0,0 +1,264 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook endpoints, bindings and inbound events (engine 2b spec §8.3; the owner's ruling 10 on the 2b-3b outline):
+endpoints and bindings written with `trigger.manage` and read with `workflow.view`, a secret shown once; events'
+metadata read with `workflow.view`, never a payload, dead ones left out; dead events listed, and pending or dead ones
+cancelled, with `tenant.manage`. The endpoints' secrets are sealed under the ingress key, which the API holds beside
+ingress: without it, nothing that seals one is written."""
+
+import uuid
+from typing import Any, Literal
+
+from fastapi import APIRouter, Depends, HTTPException, Request, Response
+from pydantic import BaseModel, ConfigDict, Field
+from sqlalchemy import select
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps import webhooks
+from dewpoint.apps.api.routes.run_requests import key_unusable
+from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
+from dewpoint.core.crypto.ingress import IngressKey
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.ingress import TriggerBinding, WebhookEndpoint
+
+router = APIRouter(prefix="/api/v1", tags=["webhooks"])
+STATUSES = Literal["pending", "matched", "unmatched", "cancelled", "dead"]
+
+
+class EndpointIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    name: str = Field(min_length=1, max_length=120)
+    enabled: bool = True
+    auth: Literal["bearer", "hmac"] = "bearer"
+    signature_header: str | None = Field(default=None, max_length=64)
+    timestamp_header: str | None = Field(default=None, max_length=64)
+    tolerance_s: int = Field(default=300, ge=60, le=900)
+    allowlist: list[str] = Field(default_factory=list)
+    body_limit: int = Field(default=webhooks.MIB, ge=1, le=webhooks.MAX_BODY)
+    id_source: Literal["pointer", "header", "none"] = "none"
+    id_pointer: str | None = None
+    id_header: str | None = Field(default=None, max_length=64)
+    events_pointer: str | None = None
+
+
+class EndpointPatch(BaseModel):
+    """Only the fields given change, never an endpoint's identity (how it authenticates, where its ids are)."""
+
+    model_config = ConfigDict(extra="forbid")
+    name: str | None = Field(default=None, min_length=1, max_length=120)
+    enabled: bool | None = None
+    signature_header: str | None = Field(default=None, max_length=64)
+    timestamp_header: str | None = Field(default=None, max_length=64)
+    tolerance_s: int | None = Field(default=None, ge=60, le=900)
+    allowlist: list[str] | None = None
+    body_limit: int | None = Field(default=None, ge=1, le=webhooks.MAX_BODY)
+    events_pointer: str | None = None
+
+
+class BindingIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    workflow_id: uuid.UUID
+    filter: list[Any] = Field(default_factory=list)
+    enabled: bool = True
+
+
+class BindingPatch(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    filter: list[Any] | None = None
+    enabled: bool | None = None
+
+
+def get_ingress_key(request: Request) -> IngressKey:
+    key: IngressKey | None = getattr(request.app.state, "ingress_key", None)
+    if key is None:
+        raise HTTPException(503, detail={"error": "ingress_key_missing"})
+    return key
+
+
+def get_keyring(request: Request) -> Keyring:
+    return request.app.state.keyring  # type: ignore[no-any-return]
+
+
+def _refused(e: webhooks.WebhookRefusedError) -> HTTPException:
+    return HTTPException(e.status, detail=e.detail)
+
+
+@router.post("/t/{tenant_id}/webhook-endpoints", status_code=201)
+async def create_endpoint(
+    given: EndpointIn,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    key: IngressKey = Depends(get_ingress_key),
+    keyring: Keyring = Depends(get_keyring),
+) -> dict[str, object]:
+    try:
+        endpoint, secret = await webhooks.create_endpoint(db, keyring, key, tenant_id=ctx.tenant_id,
+                                                          actor_id=ctx.user.id, given=given.model_dump())  # fmt: skip
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    return webhooks.endpoint_body(endpoint) | {"secret": secret}  # shown this once
+
+
+@router.get("/t/{tenant_id}/webhook-endpoints")
+async def list_endpoints(
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    found = await db.execute(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at, WebhookEndpoint.id))
+    return {"endpoints": [webhooks.endpoint_body(e) for e in found.scalars()]}
+
+
+@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}")
+async def get_endpoint(
+    endpoint_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    try:
+        return webhooks.endpoint_body(await webhooks.found_endpoint(db, endpoint_id))
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+
+
+@router.patch("/t/{tenant_id}/webhook-endpoints/{endpoint_id}")
+async def update_endpoint(
+    endpoint_id: uuid.UUID,
+    given: EndpointPatch,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    changes = {k: getattr(given, k) for k in given.model_fields_set}
+    try:
+        endpoint = await webhooks.found_endpoint(db, endpoint_id, lock=True)
+        updated = await webhooks.update_endpoint(db, endpoint=endpoint, actor_id=ctx.user.id, changes=changes)
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return webhooks.endpoint_body(updated)
+
+
+@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret")
+async def rotate_secret(
+    endpoint_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    key: IngressKey = Depends(get_ingress_key),
+) -> dict[str, object]:
+    try:
+        endpoint = await webhooks.found_endpoint(db, endpoint_id, lock=True)
+        secret = await webhooks.rotate_secret(db, key, endpoint=endpoint, actor_id=ctx.user.id)
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return {"id": str(endpoint.id), "secret": secret}  # shown this once
+
+
+@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", status_code=201)
+async def create_binding(
+    endpoint_id: uuid.UUID,
+    given: BindingIn,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    try:
+        binding = await webhooks.create_binding(db, endpoint_id=endpoint_id, actor_id=ctx.user.id,
+                                                workflow_id=given.workflow_id, filter=given.filter,
+                                                enabled=given.enabled)  # fmt: skip
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return webhooks.binding_body(binding)
+
+
+@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings")
+async def list_bindings(
+    endpoint_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    found = await db.execute(select(TriggerBinding).where(TriggerBinding.endpoint_id == endpoint_id)
+                             .order_by(TriggerBinding.workflow_id))  # fmt: skip
+    return {"bindings": [webhooks.binding_body(b) for b in found.scalars()]}
+
+
+@router.patch("/t/{tenant_id}/webhook-bindings/{binding_id}")
+async def update_binding(
+    binding_id: uuid.UUID,
+    given: BindingPatch,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    changes = {k: getattr(given, k) for k in given.model_fields_set if getattr(given, k) is not None}
+    try:
+        binding = await webhooks.found_binding(db, binding_id)
+        updated = await webhooks.update_binding(db, binding=binding, actor_id=ctx.user.id, changes=changes)
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return webhooks.binding_body(updated)
+
+
+@router.delete("/t/{tenant_id}/webhook-bindings/{binding_id}", status_code=204)
+async def delete_binding(
+    binding_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> Response:
+    try:
+        await webhooks.delete_binding(db, binding=await webhooks.found_binding(db, binding_id), actor_id=ctx.user.id)
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return Response(status_code=204)
+
+
+@router.get("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/events")
+async def list_events(
+    endpoint_id: uuid.UUID,
+    status: STATUSES | None = None,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    admin = P.TENANT_MANAGE in ROLE_PERMISSIONS[ctx.role]  # dead events are listed to admins only
+    found = await webhooks.events_of(db, endpoint_id, status, dead=admin)
+    return {"events": [webhooks.event_body(e) for e in found]}
+
+
+@router.get("/t/{tenant_id}/inbound-events/dead")
+async def list_dead_events(
+    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    return {"events": [webhooks.event_body(e) for e in await webhooks.dead_events(db)]}
+
+
+@router.post("/t/{tenant_id}/inbound-events/{event_id}/cancel")
+async def cancel_event(
+    event_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    try:
+        event = await webhooks.cancel_event(db, tenant_id=ctx.tenant_id, event_id=event_id, actor_id=ctx.user.id)
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return webhooks.event_body(event)
+
+
+@router.post("/t/{tenant_id}/webhook-endpoints/{endpoint_id}/cancel-pending")
+async def cancel_pending(
+    endpoint_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    try:
+        cancelled = await webhooks.cancel_pending(db, tenant_id=ctx.tenant_id, endpoint_id=endpoint_id,
+                                                  actor_id=ctx.user.id)  # fmt: skip
+    except webhooks.WebhookRefusedError as e:
+        raise _refused(e) from None
+    return {"cancelled": cancelled}
+
+
+@router.get("/t/{tenant_id}/inbound-usage")
+async def inbound_usage(
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    return dict(await webhooks.usage(db, ctx.tenant_id))
diff --git a/backend/src/dewpoint/apps/dispatcher/matching.py b/backend/src/dewpoint/apps/dispatcher/matching.py
index 5977253..02e3e03 100644
--- a/backend/src/dewpoint/apps/dispatcher/matching.py
+++ b/backend/src/dewpoint/apps/dispatcher/matching.py
@@ -28,7 +28,7 @@ from datetime import timedelta
 
 import structlog
 from cryptography.exceptions import InvalidTag
-from sqlalchemy import func, or_, select, text, update
+from sqlalchemy import func, or_, select, text
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 
 from dewpoint.apps import admission
@@ -38,7 +38,8 @@ from dewpoint.core.crypto import events
 from dewpoint.core.crypto.keys import KeySource, key_unreadable
 from dewpoint.core.db import tenant_scope, unavailable
 from dewpoint.core.ingress import keys as event_keys
-from dewpoint.core.ingress.filters import matches
+from dewpoint.core.ingress.counters import release
+from dewpoint.core.ingress.filters import MAX_BINDINGS, matches
 from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
 from dewpoint.core.models.platform import PlatformSettings
 from dewpoint.core.models.tenancy import Tenant
@@ -48,7 +49,6 @@ from dewpoint.engine.runtime.activities import LIVE
 
 log = structlog.get_logger("dewpoint.dispatcher.matching")
 BATCH = 50  # events a cycle (§15, provisional)
-MAX_BINDINGS = 20  # an endpoint's enabled bindings, refused past it when written, rechecked here
 WAIT = timedelta(minutes=1)  # a wait that's no fault of the event's: retried after it, its attempts untouched
 SOURCE = "webhook"
 GATE_OFF = "gate_off"
@@ -262,16 +262,3 @@ async def _dead(s: AsyncSession, event: InboundEvent, reason: str) -> str:
     _alert(s, "inbound_event_dead", tenant_id=str(event.tenant_id), event_id=str(event.id), reason=reason)
     await s.flush()
     return DEAD
-
-
-async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
-    """An event's pending counters released, on its endpoint and its tenant, whose rows the caller holds. Never below
-    zero: a drift the recount corrects doesn't block an event's end."""
-    for model, where in ((WebhookEndpoint, WebhookEndpoint.id == endpoint_id),
-                         (TenantEventCounters, TenantEventCounters.tenant_id == tenant_id)):  # fmt: skip
-        await s.execute(
-            update(model).where(where).values(
-                pending_events=func.greatest(model.pending_events - events_n, 0),
-                pending_bytes=func.greatest(model.pending_bytes - size, 0),
-            )
-        )  # fmt: skip
diff --git a/backend/src/dewpoint/apps/webhooks.py b/backend/src/dewpoint/apps/webhooks.py
new file mode 100644
index 0000000..c4c6ab5
--- /dev/null
+++ b/backend/src/dewpoint/apps/webhooks.py
@@ -0,0 +1,371 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook endpoints, bindings and inbound events, as the API writes and reads them (engine 2b spec §8.3; the owner's
+ruling 10 on the 2b-3b outline).
+
+An endpoint's secret is made by Dewpoint and shown once, when it's made or rotated: a bearer token, kept as its SHA-256
+digest, or an HMAC secret, sealed under the ingress key with the endpoint's id as its context (ingress opens it so).
+Its dedupe-digest key is sealed the same way and never changes, so rotating the secret keeps deduplication. Making an
+endpoint makes the tenant's inbound keypair if it has none. Its identity (how it authenticates, where its ids are) is
+fixed once it's made; its byte burst always covers the largest charge it permits.
+
+A binding names a workflow of the endpoint's tenant, at most once per endpoint and at most `MAX_BINDINGS` per endpoint
+(counted under the endpoint's row lock), with a filter checked when written. An admin cancels a pending or dead event,
+or an endpoint's pending events, under the lock order (the tenant's lifecycle lock shared, the endpoint's row, the
+tenant's counter row, the events), releasing what was pending; every write is audited."""
+
+import ipaddress
+import re
+import uuid
+from collections.abc import Mapping
+from typing import Any
+
+from sqlalchemy import func, select
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.audit import service as audit
+from dewpoint.core.crypto.ingress import (
+    DEDUPE_KEY,
+    HMAC_SECRET,
+    IngressKey,
+    bearer_digest,
+    new_bearer_token,
+    new_dedupe_key,
+    new_hmac_secret,
+)
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.ingress.counters import lock_tenant_shared, release
+from dewpoint.core.ingress.filters import MAX_BINDINGS, FilterError, validated
+from dewpoint.core.ingress.keys import ensure_event_key
+from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
+from dewpoint.core.models.workflows import Workflow
+
+MIB = 1024 * 1024
+MAX_BODY = 5 * MIB  # the largest body limit, and ingress's global cap
+DEFAULT_BYTE_BURST = 10 * MIB
+SIGNATURE_HEADER, TIMESTAMP_HEADER = "x-dewpoint-signature", "x-dewpoint-timestamp"
+HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]{1,64}")  # an HTTP token, lower case
+# Headers a sender can't be asked to put an id or a signature in: the transport's, or what a proxy rewrites.
+RESERVED_HEADERS = frozenset({
+    "authorization", "connection", "content-length", "content-type", "cookie", "forwarded", "host",
+    "transfer-encoding", "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
+})  # fmt: skip
+MAX_POINTER = 256
+MAX_ALLOWLIST = 32
+LISTED = 100  # events a listing shows at most
+CANCELLED = "cancelled"
+UPDATABLE = frozenset({"name", "enabled", "allowlist", "tolerance_s", "body_limit", "events_pointer",
+                       "signature_header", "timestamp_header"})  # fmt: skip
+
+
+class WebhookRefusedError(Exception):
+    """A write the API refuses: the HTTP status and the fixed detail to answer with."""
+
+    def __init__(self, status: int, detail: dict[str, Any]) -> None:
+        super().__init__(detail["error"])
+        self.status, self.detail = status, detail
+
+
+def byte_burst(body_limit: int) -> int:
+    """A byte burst that covers the largest charge an endpoint permits: its largest sealed batch, and the largest body
+    ingress reads before it authenticates (the schema's `webhook_endpoints_bursts`)."""
+    return max(DEFAULT_BYTE_BURST, 5 * body_limit + 128 * 500, MAX_BODY)
+
+
+def _header_ok(name: object) -> bool:
+    return isinstance(name, str) and bool(HEADER.fullmatch(name)) and name not in RESERVED_HEADERS
+
+
+def _networks(given: object) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
+    """An allowlist's networks, or None when it isn't one: strict, a host's bits never set past its prefix."""
+    if not isinstance(given, list) or len(given) > MAX_ALLOWLIST or not all(isinstance(e, str) for e in given):
+        return None
+    try:
+        return [ipaddress.ip_network(entry) for entry in given]
+    except ValueError:
+        return None
+
+
+def _problems(given: Mapping[str, Any], *, auth: str, id_source: str) -> list[str]:
+    """The fields of an endpoint that aren't valid: a pointer that isn't one, a header a sender can't use, an
+    allowlist entry that isn't a network, a field its kind doesn't take."""
+    problems = []
+    if id_source == "pointer":
+        pointer = given.get("id_pointer")
+        if not (isinstance(pointer, str) and pointer.startswith("/") and len(pointer) <= MAX_POINTER):
+            problems.append("id_pointer")
+    elif given.get("id_pointer") is not None:
+        problems.append("id_pointer")
+    if id_source == "header":
+        if not _header_ok(given.get("id_header")):
+            problems.append("id_header")
+    elif given.get("id_header") is not None:
+        problems.append("id_header")
+    events_pointer = given.get("events_pointer")
+    if events_pointer is not None and not (
+        isinstance(events_pointer, str) and (events_pointer == "" or events_pointer.startswith("/"))
+        and len(events_pointer) <= MAX_POINTER
+    ):  # fmt: skip
+        problems.append("events_pointer")
+    for field in ("signature_header", "timestamp_header"):
+        value = given.get(field)
+        if value is not None and (auth != "hmac" or not _header_ok(value)):
+            problems.append(field)
+    if "allowlist" in given and _networks(given["allowlist"]) is None:
+        problems.append("allowlist")
+    return problems
+
+
+def _secret(key: IngressKey, endpoint_id: uuid.UUID, auth: str) -> tuple[str, dict[str, bytes | None]]:
+    """A new secret for the endpoint, and what's stored of it."""
+    if auth == "bearer":
+        token = new_bearer_token()
+        return token, {"bearer_digest": bearer_digest(token), "hmac_secret": None}
+    secret = new_hmac_secret()
+    return secret, {"bearer_digest": None, "hmac_secret": key.seal(HMAC_SECRET, str(endpoint_id), secret.encode())}
+
+
+async def _audit(s: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None, action: str, target_type: str,
+                 target_id: uuid.UUID, details: dict[str, object]) -> None:  # fmt: skip
+    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action=action, target_type=target_type,
+                       target_id=str(target_id), details=details)  # fmt: skip
+
+
+async def create_endpoint(
+    s: AsyncSession, keyring: Keyring, key: IngressKey, *, tenant_id: uuid.UUID, actor_id: uuid.UUID,
+    given: Mapping[str, Any],
+) -> tuple[WebhookEndpoint, str]:  # fmt: skip
+    """The endpoint and its secret, to show once. Raises WebhookRefusedError."""
+    auth, id_source = given["auth"], given["id_source"]
+    problems = _problems(given, auth=auth, id_source=id_source)
+    if problems:
+        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": problems})
+    await ensure_event_key(s, keyring, tenant_id)
+    endpoint_id = uuid.uuid4()
+    secret, stored = _secret(key, endpoint_id, auth)
+    burst = byte_burst(given["body_limit"])
+    endpoint = WebhookEndpoint(
+        id=endpoint_id, tenant_id=tenant_id, name=given["name"], enabled=given["enabled"], auth_kind=auth, **stored,
+        signature_header=(given.get("signature_header") or SIGNATURE_HEADER) if auth == "hmac" else None,
+        timestamp_header=(given.get("timestamp_header") or TIMESTAMP_HEADER) if auth == "hmac" else None,
+        tolerance_s=given["tolerance_s"], allowlist=_networks(given.get("allowlist") or []),
+        body_limit=given["body_limit"], id_source=id_source, id_pointer=given.get("id_pointer"),
+        id_header=given.get("id_header"), events_pointer=given.get("events_pointer"),
+        dedupe_key=key.seal(DEDUPE_KEY, str(endpoint_id), new_dedupe_key()), byte_burst=burst, byte_tokens=burst,
+        created_by=actor_id,
+    )  # fmt: skip
+    s.add(endpoint)
+    await s.flush()
+    await s.refresh(endpoint)  # the defaults the database set, read now (never lazily)
+    await _audit(s, tenant_id, actor_id, "webhook_endpoint.create", "webhook_endpoint", endpoint_id,
+                 {"name": endpoint.name, "auth": auth, "id_source": id_source})  # fmt: skip
+    return endpoint, secret
+
+
+async def found_endpoint(s: AsyncSession, endpoint_id: uuid.UUID, *, lock: bool = False) -> WebhookEndpoint:
+    """The caller's tenant's endpoint (row-level security), locked when asked. Raises WebhookRefusedError."""
+    query = select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).execution_options(populate_existing=True)
+    endpoint = (await s.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
+    if endpoint is None:
+        raise WebhookRefusedError(404, {"error": "not_found"})
+    return endpoint
+
+
+async def rotate_secret(s: AsyncSession, key: IngressKey, *, endpoint: WebhookEndpoint, actor_id: uuid.UUID) -> str:
+    """A new secret, to show once; the dedupe-digest key kept."""
+    secret, stored = _secret(key, endpoint.id, endpoint.auth_kind)
+    endpoint.bearer_digest, endpoint.hmac_secret = stored["bearer_digest"], stored["hmac_secret"]
+    endpoint.updated_at = func.now()
+    await s.flush()
+    await _audit(s, endpoint.tenant_id, actor_id, "webhook_endpoint.rotate_secret", "webhook_endpoint", endpoint.id,
+                 {"auth": endpoint.auth_kind})  # fmt: skip
+    return secret
+
+
+async def update_endpoint(
+    s: AsyncSession, *, endpoint: WebhookEndpoint, actor_id: uuid.UUID, changes: Mapping[str, Any]
+) -> WebhookEndpoint:
+    """Only what `UPDATABLE` names changes; an endpoint's identity never does. Raises WebhookRefusedError."""
+    fixed = sorted(set(changes) - UPDATABLE)
+    nulled = sorted(k for k in set(changes) - {"events_pointer"} if changes[k] is None)
+    problems = fixed + nulled + _problems(changes, auth=endpoint.auth_kind, id_source=endpoint.id_source)
+    if problems:
+        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": sorted(set(problems))})
+    for field, value in changes.items():
+        setattr(endpoint, field, _networks(value) if field == "allowlist" else value)
+    if "body_limit" in changes:
+        endpoint.byte_burst = max(endpoint.byte_burst, byte_burst(changes["body_limit"]))
+    endpoint.updated_at = func.now()
+    await s.flush()
+    await s.refresh(endpoint)
+    await _audit(s, endpoint.tenant_id, actor_id, "webhook_endpoint.update", "webhook_endpoint", endpoint.id,
+                 {"fields": sorted(changes)})  # fmt: skip
+    return endpoint
+
+
+async def create_binding(
+    s: AsyncSession, *, endpoint_id: uuid.UUID, actor_id: uuid.UUID, workflow_id: uuid.UUID, filter: object,
+    enabled: bool,
+) -> TriggerBinding:  # fmt: skip
+    try:
+        clauses = validated(filter)
+    except FilterError as e:
+        raise WebhookRefusedError(422, {"error": "filter_invalid", "message": str(e)}) from None
+    endpoint = await found_endpoint(s, endpoint_id, lock=True)  # serializes the cap's count
+    if await s.get(Workflow, workflow_id) is None:  # row-level security: the endpoint's tenant's only
+        raise WebhookRefusedError(404, {"error": "workflow_not_found"})
+    bound = (await s.execute(select(TriggerBinding.workflow_id).where(TriggerBinding.endpoint_id == endpoint.id))
+             ).scalars().all()  # fmt: skip
+    if workflow_id in bound:
+        raise WebhookRefusedError(409, {"error": "binding_exists"})
+    if len(bound) >= MAX_BINDINGS:
+        raise WebhookRefusedError(409, {"error": "binding_cap", "max": MAX_BINDINGS})
+    binding = TriggerBinding(id=uuid.uuid4(), tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id,
+                             workflow_id=workflow_id, filter=clauses, enabled=enabled, created_by=actor_id)  # fmt: skip
+    s.add(binding)
+    await s.flush()
+    await _audit(s, endpoint.tenant_id, actor_id, "webhook_binding.create", "webhook_binding", binding.id,
+                 {"endpoint_id": str(endpoint.id), "workflow_id": str(workflow_id)})  # fmt: skip
+    return binding
+
+
+async def found_binding(s: AsyncSession, binding_id: uuid.UUID) -> TriggerBinding:
+    binding = await s.get(TriggerBinding, binding_id, populate_existing=True)
+    if binding is None:
+        raise WebhookRefusedError(404, {"error": "not_found"})
+    return binding
+
+
+async def update_binding(
+    s: AsyncSession, *, binding: TriggerBinding, actor_id: uuid.UUID, changes: Mapping[str, Any]
+) -> TriggerBinding:
+    if "filter" in changes:
+        try:
+            binding.filter = validated(changes["filter"])
+        except FilterError as e:
+            raise WebhookRefusedError(422, {"error": "filter_invalid", "message": str(e)}) from None
+    if "enabled" in changes:
+        binding.enabled = changes["enabled"]
+    await s.flush()
+    await _audit(s, binding.tenant_id, actor_id, "webhook_binding.update", "webhook_binding", binding.id,
+                 {"fields": sorted(changes)})  # fmt: skip
+    return binding
+
+
+async def delete_binding(s: AsyncSession, *, binding: TriggerBinding, actor_id: uuid.UUID) -> None:
+    await s.delete(binding)
+    await s.flush()
+    await _audit(s, binding.tenant_id, actor_id, "webhook_binding.delete", "webhook_binding", binding.id,
+                 {"endpoint_id": str(binding.endpoint_id), "workflow_id": str(binding.workflow_id)})  # fmt: skip
+
+
+async def events_of(s: AsyncSession, endpoint_id: uuid.UUID, status: str | None, *, dead: bool) -> list[InboundEvent]:
+    """The endpoint's newest events; dead ones only when `dead` (the caller has `tenant.manage`: the owner's M3
+    review), filtered by status or not."""
+    query = select(InboundEvent).where(InboundEvent.endpoint_id == endpoint_id)
+    if status is not None:
+        query = query.where(InboundEvent.status == status)
+    if not dead:
+        query = query.where(InboundEvent.status != "dead")
+    order = (InboundEvent.received_at.desc(), InboundEvent.id.desc())
+    return list((await s.execute(query.order_by(*order).limit(LISTED))).scalars())
+
+
+async def dead_events(s: AsyncSession) -> list[InboundEvent]:
+    query = select(InboundEvent).where(InboundEvent.status == "dead")
+    return list((await s.execute(query.order_by(InboundEvent.ended_at.desc()).limit(LISTED))).scalars())
+
+
+async def _locked(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> None:
+    """The lock order's first steps for a cancel: the tenant's lifecycle lock shared, the endpoint's row, the
+    tenant's counter row."""
+    await lock_tenant_shared(s, tenant_id)
+    await found_endpoint(s, endpoint_id, lock=True)
+    await s.execute(select(TenantEventCounters.tenant_id).where(TenantEventCounters.tenant_id == tenant_id)
+                    .with_for_update())  # fmt: skip
+
+
+async def cancel_event(s: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID,
+                       actor_id: uuid.UUID) -> InboundEvent:  # fmt: skip
+    """A pending or dead event cancelled; what was pending released. Raises WebhookRefusedError."""
+    seen = await s.get(InboundEvent, event_id)
+    if seen is None:
+        raise WebhookRefusedError(404, {"error": "not_found"})
+    await _locked(s, tenant_id, seen.endpoint_id)
+    event = (await s.execute(select(InboundEvent).where(InboundEvent.id == event_id).with_for_update()
+                             .execution_options(populate_existing=True))).scalar_one()  # fmt: skip
+    if event.status not in ("pending", "dead"):
+        raise WebhookRefusedError(409, {"error": "not_cancellable", "status": event.status})
+    was = event.status
+    if was == "pending":
+        await release(s, tenant_id, event.endpoint_id, event.size_bytes)
+        event.ended_at = func.now()
+    event.status, event.reason = CANCELLED, CANCELLED
+    await s.flush()
+    await s.refresh(event)
+    await _audit(s, tenant_id, actor_id, "inbound_event.cancel", "inbound_event", event.id,
+                 {"endpoint_id": str(event.endpoint_id), "was": was})  # fmt: skip
+    return event
+
+
+async def cancel_pending(s: AsyncSession, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID,
+                         actor_id: uuid.UUID) -> int:  # fmt: skip
+    """Every pending event of the endpoint cancelled at once, its counters released: how many."""
+    await _locked(s, tenant_id, endpoint_id)
+    events = (
+        await s.execute(
+            select(InboundEvent).where(InboundEvent.endpoint_id == endpoint_id, InboundEvent.status == "pending")
+            .order_by(InboundEvent.id).with_for_update().execution_options(populate_existing=True)
+        )
+    ).scalars().all()  # fmt: skip
+    for event in events:
+        event.status, event.reason, event.ended_at = CANCELLED, CANCELLED, func.now()
+    if events:
+        await release(s, tenant_id, endpoint_id, sum(e.size_bytes for e in events), events_n=len(events))
+    await s.flush()
+    await _audit(s, tenant_id, actor_id, "webhook_endpoint.cancel_pending", "webhook_endpoint", endpoint_id,
+                 {"cancelled": len(events)})  # fmt: skip
+    return len(events)
+
+
+async def usage(s: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
+    """The tenant's pending backlog and retained storage, against their quotas."""
+    counters = await s.get(TenantEventCounters, tenant_id, populate_existing=True)
+    fields = ("pending_events", "pending_bytes", "retained_events", "retained_bytes")
+    quotas = {"pending_events_max": 50_000, "pending_bytes_max": 256 * MIB, "retained_events_max": 250_000,
+              "retained_bytes_max": 1024 * MIB}  # the schema's defaults, before the tenant's first event  # fmt: skip
+    if counters is None:
+        return dict.fromkeys(fields, 0) | quotas
+    return {f: getattr(counters, f) for f in (*fields, *quotas)}
+
+
+def endpoint_body(endpoint: WebhookEndpoint) -> dict[str, object]:
+    """An endpoint as the API shows it: never its secret, its digest or its dedupe key."""
+    return {
+        "id": str(endpoint.id), "name": endpoint.name, "enabled": endpoint.enabled, "auth": endpoint.auth_kind,
+        "signature_header": endpoint.signature_header, "timestamp_header": endpoint.timestamp_header,
+        "tolerance_s": endpoint.tolerance_s, "allowlist": [str(n) for n in endpoint.allowlist or []],
+        "body_limit": endpoint.body_limit, "id_source": endpoint.id_source, "id_pointer": endpoint.id_pointer,
+        "id_header": endpoint.id_header, "events_pointer": endpoint.events_pointer, "path": f"/hooks/{endpoint.id}",
+        "pending_events": endpoint.pending_events, "pending_bytes": endpoint.pending_bytes,
+        "retained_events": endpoint.retained_events, "retained_bytes": endpoint.retained_bytes,
+        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
+    }  # fmt: skip
+
+
+def binding_body(binding: TriggerBinding) -> dict[str, object]:
+    return {"id": str(binding.id), "endpoint_id": str(binding.endpoint_id), "workflow_id": str(binding.workflow_id),
+            "filter": binding.filter, "enabled": binding.enabled}  # fmt: skip
+
+
+def event_body(event: InboundEvent) -> dict[str, object]:
+    """An event's metadata: never its payload, its dedupe key or its digest."""
+
+    def when(value: Any) -> str | None:
+        return value.isoformat() if value is not None else None
+
+    return {
+        "id": str(event.id), "endpoint_id": str(event.endpoint_id), "status": event.status, "reason": event.reason,
+        "attempts": event.attempts, "next_attempt_at": when(event.next_attempt_at),
+        "request_count": event.request_count, "size_bytes": event.size_bytes, "key_version": event.key_version,
+        "received_at": when(event.received_at), "ended_at": when(event.ended_at),
+    }  # fmt: skip
diff --git a/backend/src/dewpoint/core/ingress/counters.py b/backend/src/dewpoint/core/ingress/counters.py
new file mode 100644
index 0000000..23494ef
--- /dev/null
+++ b/backend/src/dewpoint/core/ingress/counters.py
@@ -0,0 +1,34 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What every writer of inbound events and their counters shares (engine 2b spec §8.3; "Functions and lock order" in
+the 2b-3b outline): the tenant's lifecycle lock, taken shared (2b-4's erasure takes it exclusively), the first lock
+any of them takes after the gate's; and releasing an event's pending counters, on its endpoint's row and its tenant's,
+which the caller holds by then."""
+
+import uuid
+
+from sqlalchemy import func, text, update
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.models.ingress import TenantEventCounters, WebhookEndpoint
+
+
+def tenant_lock(tenant_id: uuid.UUID) -> str:
+    """The tenant's lifecycle lock: the dispatcher's starting transaction takes the same one."""
+    return f"dewpoint:tenant:{tenant_id}"
+
+
+async def lock_tenant_shared(s: AsyncSession, tenant_id: uuid.UUID) -> None:
+    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": tenant_lock(tenant_id)})
+
+
+async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
+    """`events_n` events' pending counters (`size` bytes in all) released, on their endpoint and their tenant. Never
+    below zero: a drift the recount corrects doesn't block an event's end."""
+    for model, where in ((WebhookEndpoint, WebhookEndpoint.id == endpoint_id),
+                         (TenantEventCounters, TenantEventCounters.tenant_id == tenant_id)):  # fmt: skip
+        await s.execute(
+            update(model).where(where).values(
+                pending_events=func.greatest(model.pending_events - events_n, 0),
+                pending_bytes=func.greatest(model.pending_bytes - size, 0),
+            )
+        )  # fmt: skip
diff --git a/backend/src/dewpoint/core/ingress/filters.py b/backend/src/dewpoint/core/ingress/filters.py
index 92aac07..133ecc7 100644
--- a/backend/src/dewpoint/core/ingress/filters.py
+++ b/backend/src/dewpoint/core/ingress/filters.py
@@ -11,6 +11,7 @@ from dewpoint.core.ingress.identity import canonical
 from dewpoint.core.ingress.pointer import PointerError, resolve
 
 MAX_CLAUSES = 8
+MAX_BINDINGS = 20  # an endpoint's bindings: refused past it when written, rechecked when matching (§15, provisional)
 MAX_POINTER_CHARS = 256
 MAX_VALUE_CHARS = 1024
 INT_RANGE = (-(2**63), 2**63 - 1)
diff --git a/backend/src/dewpoint/core/models/ingress.py b/backend/src/dewpoint/core/models/ingress.py
index 9305e39..df1c1aa 100644
--- a/backend/src/dewpoint/core/models/ingress.py
+++ b/backend/src/dewpoint/core/models/ingress.py
@@ -52,6 +52,10 @@ class WebhookEndpoint(Base):
     event_burst: Mapped[int] = mapped_column(BigInteger, server_default="1000")
     byte_per_s: Mapped[float] = mapped_column(Float, server_default=str(2 * 1024 * 1024))
     byte_burst: Mapped[int] = mapped_column(BigInteger, server_default=str(10 * 1024 * 1024))
+    request_tokens: Mapped[float] = mapped_column(Float, server_default="100")
+    event_tokens: Mapped[float] = mapped_column(Float, server_default="1000")
+    byte_tokens: Mapped[float] = mapped_column(Float, server_default=str(10 * 1024 * 1024))
+    refilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
     pending_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
     pending_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
     retained_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
diff --git a/backend/tests/apps/api/test_webhooks_api.py b/backend/tests/apps/api/test_webhooks_api.py
new file mode 100644
index 0000000..aafe592
--- /dev/null
+++ b/backend/tests/apps/api/test_webhooks_api.py
@@ -0,0 +1,384 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook endpoints, bindings and events through the API (engine 2b spec §8.3; the owner's ruling 10 on the 2b-3b
+outline): `trigger.manage` writes endpoints and bindings and `workflow.view` reads them; an endpoint's secret (a bearer
+token, or an HMAC secret sealed under the ingress key with the endpoint's id as context) is shown once, when it's made
+or rotated, and never again; filters and the binding cap are checked when written. Events' metadata is read with
+`workflow.view`, never a payload; dead events are listed, and pending or dead ones cancelled, with `tenant.manage`
+(admins), audited, their pending counters released."""
+
+import hashlib
+import hmac
+import json
+import time
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.ingress.main import create_app
+from dewpoint.core.crypto import events
+from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET
+from dewpoint.core.ingress.identity import canonical
+from tests.apps.api.test_run_requests_api import as_role
+from tests.apps.dispatcher.inbound import keypair
+from tests.apps.ingress.support import KEY
+from tests.apps.ingress.support import client as ingress_client
+from tests.apps.ingress.support import settings as ingress_settings
+from tests.apps.test_admission import KEYS, OPEN_GRAPH, published
+from tests.core.ingress.support import record
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+MIB = 1024 * 1024
+CANARY = "canary-payload-7f3a"
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    app.state.keys = KEYS
+    app.state.ingress_key = KEY
+    return app
+
+
+@pytest.fixture
+async def tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, OPEN_GRAPH)
+    await keypair(owner_sessionmaker, ctx.tenant_id)
+    return ctx, wf
+
+
+def url(ctx: Any, path: str = "") -> str:
+    return f"/api/v1/t/{ctx.tenant_id}{path}"
+
+
+async def row(owner: Any, table: str, row_id: Any) -> dict[str, Any]:
+    async with owner() as s:
+        found = await s.execute(text(f"select * from {table} where id = :i"), {"i": row_id})  # noqa: S608
+        return dict(found.mappings().one())
+
+
+async def audited(owner: Any, action: str) -> list[dict[str, Any]]:
+    async with owner() as s:
+        found = await s.execute(text("select target_id, details from audit_log where action = :a order by seq"),
+                                {"a": action})  # fmt: skip
+        return [dict(r) for r in found.mappings()]
+
+
+async def made(keyed_app: Any, owner: Any, settings: Any, ctx: Any, **body: Any) -> dict[str, Any]:
+    editor = await as_role(keyed_app, owner, settings, ctx, "editor")
+    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "alarms"} | body)
+    assert answer.status_code == 201, answer.text
+    return dict(answer.json())
+
+
+async def test_an_editor_makes_a_bearer_endpoint_whose_token_is_shown_once(
+    keyed_app, tenant, owner_sessionmaker, api_settings
+) -> None:
+    ctx, _ = tenant
+    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    token = body.pop("secret")
+    assert token.startswith("dwp_") and len(token) > 40
+    assert {k: body[k] for k in ("name", "enabled", "auth", "id_source", "body_limit", "path")} == {
+        "name": "alarms", "enabled": True, "auth": "bearer", "id_source": "none", "body_limit": MIB,
+        "path": f"/hooks/{body['id']}",
+    }  # fmt: skip
+    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
+    assert stored["bearer_digest"] == hashlib.sha256(token.encode()).digest() and stored["hmac_secret"] is None
+    assert KEY.open(DEDUPE_KEY, body["id"], stored["dedupe_key"])  # sealed under the ingress key, its id the context
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    listed = (await viewer.get(url(ctx, "/webhook-endpoints"))).json()["endpoints"]
+    shown = (await viewer.get(url(ctx, f"/webhook-endpoints/{body['id']}"))).json()
+    assert [e["id"] for e in listed] == [body["id"]] and shown["id"] == body["id"]
+    for seen in (listed, shown):
+        assert token not in json.dumps(seen) and "secret" not in json.dumps(seen) and "digest" not in json.dumps(seen)
+    [entry] = await audited(owner_sessionmaker, "webhook_endpoint.create")
+    assert entry["target_id"] == body["id"] and token not in json.dumps(entry["details"])
+
+
+async def test_an_hmac_endpoints_secret_is_the_one_ingress_authenticates_with(
+    keyed_app, tenant, owner_sessionmaker, api_settings, pg_url
+) -> None:
+    ctx, _ = tenant
+    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, auth="hmac", id_source="pointer",
+                      id_pointer="/id")  # fmt: skip
+    secret = body["secret"]
+    assert (body["signature_header"], body["timestamp_header"]) == ("x-dewpoint-signature", "x-dewpoint-timestamp")
+    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
+    assert KEY.open(HMAC_SECRET, body["id"], stored["hmac_secret"]) == secret.encode()
+    ingress = create_app(ingress_settings(pg_url))
+    event = json.dumps({"id": "e-1", "note": CANARY}).encode()
+    stamp = str(int(time.time()))
+    signed = hmac.new(secret.encode(), stamp.encode() + b"." + event, hashlib.sha256).hexdigest()
+    async with ingress_client(ingress) as c:
+        answer = await c.post(body["path"], content=event,
+                              headers={"x-dewpoint-timestamp": stamp, "x-dewpoint-signature": signed})  # fmt: skip
+    await ingress.state.engine.dispose()
+    assert (answer.status_code, answer.json()) == (200, {"accepted": 1, "duplicates": 0})
+
+
+@pytest.mark.parametrize(
+    ("given", "problem"),
+    [
+        ({"id_source": "pointer"}, "id_pointer"),
+        ({"id_source": "header"}, "id_header"),
+        ({"id_source": "pointer", "id_pointer": "id"}, "id_pointer"),
+        ({"events_pointer": "events"}, "events_pointer"),
+        ({"allowlist": ["10.0.0.1/8"]}, "allowlist"),
+        ({"allowlist": ["not-an-address"]}, "allowlist"),
+        ({"auth": "hmac", "signature_header": "authorization"}, "signature_header"),
+        ({"auth": "hmac", "timestamp_header": "bad header"}, "timestamp_header"),
+        ({"id_source": "header", "id_header": "x-forwarded-for"}, "id_header"),
+        ({"auth": "bearer", "signature_header": "x-sig"}, "signature_header"),
+    ],
+)
+async def test_an_endpoint_that_isnt_one_is_refused_with_what_to_change(
+    keyed_app, tenant, owner_sessionmaker, api_settings, given, problem
+) -> None:
+    ctx, _ = tenant
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x"} | given)
+    assert answer.status_code == 422, answer.text
+    assert answer.json()["error"] == "endpoint_invalid"
+    assert problem in answer.json()["fields"]
+
+
+async def test_a_large_body_limit_gets_the_burst_that_covers_it(keyed_app, tenant, owner_sessionmaker,
+                                                                api_settings) -> None:  # fmt: skip
+    ctx, _ = tenant
+    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, body_limit=5 * MIB)
+    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
+    assert stored["byte_burst"] >= 5 * 5 * MIB + 64_000 and stored["byte_tokens"] >= 0
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    assert (await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x", "body_limit": 5 * MIB + 1})
+            ).status_code == 422  # fmt: skip
+
+
+async def test_writing_an_endpoint_needs_trigger_manage_and_the_ingress_key(
+    keyed_app, tenant, owner_sessionmaker, api_settings
+) -> None:
+    ctx, _ = tenant
+    for role in ("viewer", "operator"):
+        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+        assert (await client.post(url(ctx, "/webhook-endpoints"), json={"name": "x"})).status_code == 403
+    keyed_app.state.ingress_key = None
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x"})
+    assert (answer.status_code, answer.json()) == (503, {"error": "ingress_key_missing"})
+
+
+async def test_rotating_a_secret_shows_the_new_one_once_and_keeps_deduplication(
+    keyed_app, tenant, owner_sessionmaker, api_settings
+) -> None:
+    ctx, _ = tenant
+    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    before = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    rotated = await editor.post(url(ctx, f"/webhook-endpoints/{body['id']}/secret"))
+    assert rotated.status_code == 200, rotated.text
+    new = rotated.json()["secret"]
+    after = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
+    assert new != body["secret"] and after["bearer_digest"] == hashlib.sha256(new.encode()).digest()
+    assert after["dedupe_key"] == before["dedupe_key"]
+    assert [e["target_id"] for e in await audited(owner_sessionmaker, "webhook_endpoint.rotate_secret")] == [body["id"]]
+
+
+async def test_an_endpoint_is_updated_and_disabled_but_never_its_identity(
+    keyed_app, tenant, owner_sessionmaker, api_settings
+) -> None:
+    ctx, _ = tenant
+    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    patched = await editor.patch(
+        url(ctx, f"/webhook-endpoints/{body['id']}"),
+        json={"name": "renamed", "enabled": False, "allowlist": ["203.0.113.0/24"]},
+    )
+    assert patched.status_code == 200, patched.text
+    assert {k: patched.json()[k] for k in ("name", "enabled", "allowlist")} == {
+        "name": "renamed", "enabled": False, "allowlist": ["203.0.113.0/24"],
+    }  # fmt: skip
+    for refused in ({"id_source": "pointer", "id_pointer": "/id"}, {"auth": "hmac"}, {"name": None}):
+        assert (await editor.patch(url(ctx, f"/webhook-endpoints/{body['id']}"), json=refused)).status_code == 422
+    other = uuid.uuid4()
+    assert (await editor.patch(url(ctx, f"/webhook-endpoints/{other}"), json={"name": "x"})).status_code == 404
+
+
+async def test_bindings_are_checked_capped_and_unique(keyed_app, tenant, owner_sessionmaker, api_settings,
+                                                      api_sessionmaker, admin_sessionmaker) -> None:  # fmt: skip
+    ctx, wf = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    bindings = url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings")
+    created = await editor.post(bindings, json={"workflow_id": str(wf),
+                                                "filter": [{"pointer": "/type", "value": "ap_down"}]})  # fmt: skip
+    assert created.status_code == 201, created.text
+    assert created.json()["filter"] == [{"pointer": "/type", "value": "ap_down"}]
+    assert (await editor.post(bindings, json={"workflow_id": str(wf)})).status_code == 409  # one per workflow
+    bad = await editor.post(bindings, json={"workflow_id": str(wf), "filter": [{"pointer": "/a", "value": 1.5}]})
+    assert (bad.status_code, bad.json()["error"]) == (422, "filter_invalid")
+    theirs, their_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
+                                       OPEN_GRAPH)  # fmt: skip
+    assert (await editor.post(bindings, json={"workflow_id": str(their_wf)})).status_code == 404
+    async with owner_sessionmaker() as s, s.begin():
+        for n in range(20):
+            await s.execute(
+                text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
+                {"w": uuid.uuid4(), "t": ctx.tenant_id, "n": f"extra-{n}"},
+            )
+        extra = (await s.execute(text("select id from workflows where tenant_id = :t and name like 'extra-%' "
+                                      "order by name"), {"t": ctx.tenant_id})).scalars().all()  # fmt: skip
+    for workflow_id in extra[:19]:
+        assert (await editor.post(bindings, json={"workflow_id": str(workflow_id)})).status_code == 201
+    capped = await editor.post(bindings, json={"workflow_id": str(extra[19])})
+    assert (capped.status_code, capped.json()["error"]) == (409, "binding_cap")
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert len((await viewer.get(bindings)).json()["bindings"]) == 20
+    binding = created.json()["id"]
+    patched = await editor.patch(url(ctx, f"/webhook-bindings/{binding}"), json={"enabled": False, "filter": []})
+    assert {k: patched.json()[k] for k in ("enabled", "filter")} == {"enabled": False, "filter": []}
+    assert (await editor.delete(url(ctx, f"/webhook-bindings/{binding}"))).status_code == 204
+    assert (await viewer.post(bindings, json={"workflow_id": str(wf)})).status_code == 403
+    assert len(await audited(owner_sessionmaker, "webhook_binding.create")) == 20
+
+
+async def _events(ingress: Any, ctx: Any, endpoint_id: str, n: int) -> list[uuid.UUID]:
+    """`n` events recorded through ingress's function, sealed to the tenant's key, carrying the canary."""
+    async with ingress() as s:
+        public = (await s.execute(text("select public_key from resolve_webhook_endpoint(:e)"),
+                                  {"e": endpoint_id})).scalar_one()  # fmt: skip
+    ids = [uuid.uuid4() for _ in range(n)]
+    sealed = [(None, None, events.seal(public, 1, tenant_id=ctx.tenant_id, endpoint_id=uuid.UUID(endpoint_id),
+                                       event_id=i, plaintext=canonical({"note": CANARY, "n": k})))
+              for k, i in enumerate(ids)]  # fmt: skip
+    assert (await record(ingress, uuid.UUID(endpoint_id), sealed, ids=ids))["outcome"] == "recorded"
+    return ids
+
+
+async def pending(owner: Any, ctx: Any, endpoint_id: str) -> tuple[int, int]:
+    async with owner() as s:
+        e = (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
+                             {"e": endpoint_id})).scalar_one()  # fmt: skip
+        t = (await s.execute(text("select pending_events from tenant_event_counters where tenant_id = :t"),
+                             {"t": ctx.tenant_id})).scalar_one()  # fmt: skip
+    return e, t
+
+
+async def test_events_are_listed_as_metadata_only(keyed_app, tenant, owner_sessionmaker, api_settings,
+                                                  ingress_sessionmaker) -> None:  # fmt: skip
+    ctx, _ = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    ids = await _events(ingress_sessionmaker, ctx, endpoint["id"], 2)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    answer = await viewer.get(url(ctx, f"/webhook-endpoints/{endpoint['id']}/events"))
+    assert answer.status_code == 200, answer.text
+    listed = answer.json()["events"]
+    assert sorted(e["id"] for e in listed) == sorted(str(i) for i in ids)
+    assert set(listed[0]) == {"id", "endpoint_id", "status", "reason", "attempts", "next_attempt_at",
+                              "request_count", "size_bytes", "key_version", "received_at", "ended_at"}  # fmt: skip
+    assert CANARY not in answer.text
+    matched = await viewer.get(url(ctx, f"/webhook-endpoints/{endpoint['id']}/events?status=matched"))
+    assert matched.json()["events"] == []
+    usage = (await viewer.get(url(ctx, "/inbound-usage"))).json()
+    assert {k: usage[k] for k in ("pending_events", "retained_events")} == {"pending_events": 2, "retained_events": 2}
+    assert usage["pending_events_max"] == 50_000 and usage["retained_bytes"] > 0
+
+
+async def test_an_admin_lists_dead_events_and_cancels_pending_or_dead_ones(
+    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
+) -> None:
+    ctx, _ = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    dead, waiting, done = await _events(ingress_sessionmaker, ctx, endpoint["id"], 3)
+    async with owner_sessionmaker() as s, s.begin():  # one dead (its counters released), one matched
+        await s.execute(text("update inbound_events set status = 'dead', reason = 'event_unreadable', ended_at = now() "
+                             "where id = :e"), {"e": dead})  # fmt: skip
+        await s.execute(text("update inbound_events set status = 'matched', request_count = 0, ended_at = now() "
+                             "where id = :e"), {"e": done})  # fmt: skip
+        for table, where in (("webhook_endpoints", "id = :i"), ("tenant_event_counters", "tenant_id = :t")):
+            await s.execute(text(f"update {table} set pending_events = 1 where {where}"),  # noqa: S608
+                            {"i": endpoint["id"], "t": ctx.tenant_id})  # fmt: skip
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    assert (await editor.get(url(ctx, "/inbound-events/dead"))).status_code == 403
+    assert (await editor.post(url(ctx, f"/inbound-events/{waiting}/cancel"))).status_code == 403
+    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
+    listed = (await admin.get(url(ctx, "/inbound-events/dead"))).json()["events"]
+    assert [e["id"] for e in listed] == [str(dead)] and CANARY not in json.dumps(listed)
+    for event_id in (dead, waiting):
+        answer = await admin.post(url(ctx, f"/inbound-events/{event_id}/cancel"))
+        assert (answer.status_code, answer.json()["status"]) == (200, "cancelled"), answer.text
+    assert await pending(owner_sessionmaker, ctx, endpoint["id"]) == (0, 0)  # the dead one had released its own
+    assert (await admin.post(url(ctx, f"/inbound-events/{done}/cancel"))).json()["error"] == "not_cancellable"
+    assert (await admin.post(url(ctx, f"/inbound-events/{uuid.uuid4()}/cancel"))).status_code == 404
+    assert sorted(e["target_id"] for e in await audited(owner_sessionmaker, "inbound_event.cancel")) == sorted(
+        [str(dead), str(waiting)]
+    )
+
+
+async def test_an_admin_cancels_an_endpoints_pending_events_at_once(
+    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
+) -> None:
+    ctx, _ = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    await _events(ingress_sessionmaker, ctx, endpoint["id"], 3)
+    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
+    answer = await admin.post(url(ctx, f"/webhook-endpoints/{endpoint['id']}/cancel-pending"))
+    assert (answer.status_code, answer.json()) == (200, {"cancelled": 3})
+    assert await pending(owner_sessionmaker, ctx, endpoint["id"]) == (0, 0)
+    async with owner_sessionmaker() as s:
+        bytes_left = (await s.execute(text("select pending_bytes from webhook_endpoints where id = :e"),
+                                      {"e": endpoint["id"]})).scalar_one()  # fmt: skip
+    assert bytes_left == 0
+    [entry] = await audited(owner_sessionmaker, "webhook_endpoint.cancel_pending")
+    assert entry["details"]["cancelled"] == 3
+
+
+async def test_two_bindings_made_at_once_never_pass_the_cap_together(
+    keyed_app, tenant, owner_sessionmaker, api_settings
+) -> None:
+    """The cap is counted under the endpoint's row lock: two writers at 19 bindings are serialized, one refused."""
+    import asyncio
+
+    ctx, wf = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    bindings = url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings")
+    async with owner_sessionmaker() as s, s.begin():
+        for n in range(20):
+            await s.execute(
+                text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
+                {"w": uuid.uuid4(), "t": ctx.tenant_id, "n": f"extra-{n:02}"},
+            )
+        extra = (await s.execute(text("select id from workflows where tenant_id = :t and name like 'extra-%' "
+                                      "order by name"), {"t": ctx.tenant_id})).scalars().all()  # fmt: skip
+    assert (await editor.post(bindings, json={"workflow_id": str(wf)})).status_code == 201
+    for workflow_id in extra[:18]:
+        assert (await editor.post(bindings, json={"workflow_id": str(workflow_id)})).status_code == 201
+    async with owner_sessionmaker() as s, s.begin():  # both writers wait on the endpoint's row, then go one by one
+        await s.execute(text("select 1 from webhook_endpoints where id = :e for update"), {"e": endpoint["id"]})
+        racing = [asyncio.create_task(editor.post(bindings, json={"workflow_id": str(w)})) for w in extra[18:]]
+        await asyncio.sleep(0.3)
+    answers = sorted([(await r).status_code for r in racing])
+    assert answers == [201, 409]
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from trigger_bindings where endpoint_id = :e"),
+                                {"e": endpoint["id"]})).scalar_one() == 20  # fmt: skip
+
+
+async def test_an_endpoints_event_list_shows_dead_events_to_admins_only(
+    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
+) -> None:
+    """The owner's M3 review: dead events are listed with `tenant.manage` only, so an endpoint's event list (read with
+    `workflow.view`) leaves them out for anyone else, filtered or not."""
+    ctx, _ = tenant
+    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
+    dead, alive = await _events(ingress_sessionmaker, ctx, endpoint["id"], 2)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update inbound_events set status = 'dead', reason = 'event_unreadable', ended_at = now() "
+                             "where id = :e"), {"e": dead})  # fmt: skip
+    events = url(ctx, f"/webhook-endpoints/{endpoint['id']}/events")
+    for role in ("viewer", "operator", "editor"):
+        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+        assert [e["id"] for e in (await client.get(events)).json()["events"]] == [str(alive)], role
+        assert (await client.get(f"{events}?status=dead")).json()["events"] == [], role
+    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
+    assert sorted(e["id"] for e in (await admin.get(events)).json()["events"]) == sorted([str(dead), str(alive)])
+    assert [e["id"] for e in (await admin.get(f"{events}?status=dead")).json()["events"]] == [str(dead)]
diff --git a/backend/tests/apps/dispatcher/test_matching.py b/backend/tests/apps/dispatcher/test_matching.py
index 1ab4a66..318f0f7 100644
--- a/backend/tests/apps/dispatcher/test_matching.py
+++ b/backend/tests/apps/dispatcher/test_matching.py
@@ -334,3 +334,50 @@ def _params(inbound: Any, payload: object, key: bytes) -> dict[str, Any]:
     return {"e": inbound.endpoint_id, "refusal": None, "read": 0, "ids": [event_id],
             "sealed": [sealed(inbound, event_id, payload)], "versions": [1], "dedupe": [key],
             "digests": [hashlib.sha256(canonical(payload)).digest()]}  # fmt: skip
+
+
+async def _cancel(api: Any, inbound: Any, event_id: uuid.UUID) -> str:
+    from dewpoint.apps import webhooks
+    from dewpoint.core.db import tenant_scope
+
+    try:
+        async with api() as s, s.begin():
+            await tenant_scope(s, inbound.tenant_id)
+            event = await webhooks.cancel_event(s, tenant_id=inbound.tenant_id, event_id=event_id,
+                                                actor_id=inbound.user_id)  # fmt: skip
+            return event.status
+    except webhooks.WebhookRefusedError as e:
+        return str(e)
+
+
+async def test_a_cancel_waits_for_a_match_in_flight_and_finds_it_matched(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, monkeypatch
+) -> None:
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    reached, release = await _held(monkeypatch)
+    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+    await reached.wait()
+    cancel = asyncio.create_task(_cancel(api_sessionmaker, dev, event_id))
+    await _waiting(owner_sessionmaker)  # on the endpoint's row
+    release.set()
+    assert (await matcher, await cancel) == ("matched", "not_cancellable")
+    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
+
+
+async def test_a_match_waits_for_a_cancel_and_passes_the_cancelled_event_by(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker
+) -> None:
+    from dewpoint.apps import webhooks
+    from dewpoint.core.db import tenant_scope
+
+    await bind(owner_sessionmaker, dev)
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, dev.tenant_id)
+        await webhooks.cancel_event(s, tenant_id=dev.tenant_id, event_id=event_id, actor_id=dev.user_id)
+        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
+        await _waiting(owner_sessionmaker)
+    assert await matcher == "skipped"
+    assert await requests_of(owner_sessionmaker, event_id) == []
+    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
diff --git a/backend/tests/core/ingress/test_filters.py b/backend/tests/core/ingress/test_filters.py
index a79c287..f9a3aa5 100644
--- a/backend/tests/core/ingress/test_filters.py
+++ b/backend/tests/core/ingress/test_filters.py
@@ -61,3 +61,13 @@ def test_a_valid_filter_is_kept_as_given() -> None:
 def test_an_invalid_filter_is_refused_with_a_reason(given) -> None:
     with pytest.raises(FilterError):
         validated(given)
+
+
+def test_the_tenant_lock_is_the_one_the_dispatchers_starts_take() -> None:
+    import uuid
+
+    from dewpoint.apps.dispatcher.dispatch import tenant_lock as dispatchers
+    from dewpoint.core.ingress.counters import tenant_lock
+
+    tenant = uuid.uuid4()
+    assert tenant_lock(tenant) == dispatchers(tenant)
```

**Checkpoint (milestone 3).** Focused: `tests/apps/api`, `tests/apps/cli`, `tests/apps/dispatcher`,
`tests/apps/ingress`, `tests/core/crypto`, `tests/core/ingress`, `tests/core/tenancy`, `tests/deploy` (647 passed); the
migrations 0030 → 0033 → 0030 → 0033 and 0033 → 0032 → 0033 over existing rows. The owner held it once (milestone ruling
3) and approved it as a prototype checkpoint, not production ingress sign-off (2026-10-04).

## Milestone 4 — Proofs, the load probe, Compose and docs

### Task 8: A signed webhook becomes a run end to end with the keyring's real keys, leaking nothing

**Commit:** `527013c` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/tests/apps/dispatcher/test_ingress_end_to_end.py`

**What it does:**

On Temporal's CLI dev server: the API makes an HMAC endpoint and a bearer one (secrets shown once) and a binding;
ingress refuses a replay outside the tolerance and records a signed event carrying a canary in a sensitive field; a
match whose transaction fails before its commit leaves it pending; the matcher then admits it once; the dispatcher
starts it on a versioned engine worker and it succeeds, its input (decrypted with the real keys) the event. The canary,
the HMAC secret and the bearer token appear in no raw history, stored row in plain, log line, audit entry or
projection. Limits, quotas and the retained cap are proven through ingress's app; the gate off on events recorded
before (ingress records nothing in production).

**Proven elsewhere.** The limits, the quotas and the retained cap are proven through ingress's own app (Task 4's
`tests/apps/ingress/test_hooks_recording.py`), and the gate off on events recorded before by Task 5's
`test_with_the_gate_off_nothing_is_matched`; this task adds the one proof above.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/apps/dispatcher/test_ingress_end_to_end.py`. Replay result (exit 0), shortened:

```
.                                                                        [100%]
1 passed in 22.19s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.                                                                        [100%]
1 passed in 17.62s
```

Evidence beyond the replay: a proof of what Tasks 1 to 7 built, so it passes before any code of its own. Its scan reads
real data: the request's input, decrypted with the real keys, is the event with its canary, and every history scanned
names the tenant; neither the canary nor a secret is in any of them.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 527013c && git commit -C 527013c`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_ingress_end_to_end.py b/backend/tests/apps/dispatcher/test_ingress_end_to_end.py
new file mode 100644
index 0000000..1731e03
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_ingress_end_to_end.py
@@ -0,0 +1,187 @@
+# SPDX-License-Identifier: Apache-2.0
+"""2b-3b's proof on Temporal's CLI dev server (engine 2b spec §8.3, §12): a webhook becomes a run end to end with the
+keyring's real keys everywhere. The API makes an HMAC endpoint and a bearer one (their secrets shown once) and a
+binding; ingress records a signed event carrying a canary in a sensitive field, sealed to the tenant's keypair; a
+match whose transaction fails before its commit leaves it pending; the matcher then admits it once; the dispatcher
+starts it on a versioned engine worker, and it succeeds. The event's canary, the HMAC secret and the bearer token
+appear in no execution's whole raw history, no projection, no stored row in plain, no log line and no audit entry. A
+replay outside the tolerance is refused.
+
+The limits, the quotas and the retained cap are proven through ingress's own app (`tests/apps/ingress`); the gate
+off, on events recorded before (`test_matching.py`): ingress itself records nothing in a production deployment."""
+
+import hashlib
+import hmac
+import json
+import time
+import uuid
+from collections.abc import AsyncIterator
+from typing import Any
+
+import pytest
+import structlog
+from sqlalchemy import text
+from temporalio.client import Client
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps.codec import data_converter
+from dewpoint.apps.dispatcher import dispatch, matching
+from dewpoint.apps.ingress.main import create_app as create_ingress
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.tenancy.service import ensure_tenant_keys
+from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.dispatcher.test_dev_server import until_ended
+from tests.apps.dispatcher.test_triggers_end_to_end import decrypted_input, raw_histories
+from tests.apps.ingress.support import KEY
+from tests.apps.ingress.support import client as ingress_client
+from tests.apps.ingress.support import settings as ingress_settings
+from tests.apps.test_admission import current, published
+from tests.apps.worker.test_real_server import serving
+from tests.support.graphs import G, ref
+from tests.support.keys import FIXTURE_CONVERTER
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+CANARY = "Hook-c4n4ry-W8q"
+EVENT_SCHEMA = {  # an event as a sender sends it: its id, a sensitive field, and the rest
+    "type": "object",
+    "properties": {
+        "id": {"type": "string"},
+        "token": {"type": "string", "x-sensitive": True},
+        "site": {"type": "string"},
+    },
+    "required": ["id", "token"],
+    "additionalProperties": False,
+}
+ECHO_GRAPH = G().node("a", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
+    "settings": {"input_schema": EVENT_SCHEMA}
+}
+
+
+@pytest.fixture(scope="module")
+async def server() -> AsyncIterator[WorkflowEnvironment]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
+        yield environment
+
+
+async def plain_rows(owner: Any) -> str:
+    """Every row 2b-3b writes or a run it starts writes, as text (their ciphertexts included, which must hold no
+    canary or secret in plain)."""
+    tables = (
+        "webhook_endpoints",
+        "trigger_bindings",
+        "inbound_events",
+        "tenant_event_counters",
+        "tenant_event_keys",
+        "run_requests",
+        "runs",
+        "run_steps",
+        "audit_log",
+        "run_inputs",
+        "step_outputs",
+        "run_secret_index",
+    )
+    async with owner() as s:
+        return "\n".join([str((await s.execute(text(f"select * from {t}"))).all()) for t in tables])  # noqa: S608
+
+
+def signed(secret: str, body: bytes, stamp: int) -> dict[str, str]:
+    signature = hmac.new(secret.encode(), str(stamp).encode() + b"." + body, hashlib.sha256).hexdigest()
+    return {"x-dewpoint-timestamp": str(stamp), "x-dewpoint-signature": signature}
+
+
+async def test_a_signed_webhook_becomes_a_run_end_to_end_with_the_keyrings_real_keys_leaking_nothing(
+    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
+    api_settings, pg_url, monkeypatch,
+) -> None:  # fmt: skip
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, ECHO_GRAPH)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    async with admin_sessionmaker() as s, s.begin():
+        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
+    app.state.ingress_key = KEY  # the API seals endpoint secrets under the key ingress opens them with
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    target, namespace = server.client.service_client.config.target_host, server.client.namespace
+    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
+    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
+    editor, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "editor")
+    base = f"/api/v1/t/{ctx.tenant_id}"
+    ingress = create_ingress(ingress_settings(pg_url))
+    with structlog.testing.capture_logs() as logs:
+        made = await editor.post(
+            f"{base}/webhook-endpoints",
+            json={"name": "alarms", "auth": "hmac", "id_source": "pointer", "id_pointer": "/id"},
+        )
+        assert made.status_code == 201, made.text
+        endpoint, secret = made.json(), made.json()["secret"]
+        bearer = await editor.post(f"{base}/webhook-endpoints", json={"name": "other"})
+        token = bearer.json()["secret"]
+        bound = await editor.post(f"{base}/webhook-endpoints/{endpoint['id']}/bindings", json={"workflow_id": str(wf)})
+        assert bound.status_code == 201, bound.text
+        body = json.dumps({"id": "evt-1", "token": CANARY, "site": "lyon"}).encode()
+        now = int(time.time())
+        async with ingress_client(ingress) as hooks:
+            replayed = await hooks.post(endpoint["path"], content=body, headers=signed(secret, body, now - 301))
+            assert (replayed.status_code, replayed.content) == (401, b"")  # outside the tolerance
+            recorded = await hooks.post(endpoint["path"], content=body, headers=signed(secret, body, now))
+            assert (recorded.status_code, recorded.json()) == (200, {"accepted": 1, "duplicates": 0})
+            other = await hooks.post(bearer.json()["path"], content=b'{"n": 1}',
+                                     headers={"authorization": f"Bearer {token}"})  # fmt: skip
+            assert other.status_code == 200
+        [event_id] = await owner_rows(owner_sessionmaker, endpoint["id"])
+
+        async def crash() -> None:
+            raise RuntimeError("the dispatcher dies before its commit")
+
+        monkeypatch.setattr(matching, "_before_commit", crash)
+        assert (await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified())).get("error")
+        assert await status_of(owner_sessionmaker, event_id) == ("pending", None)  # nothing it decided stayed
+        monkeypatch.undo()
+        counts = await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified())
+        assert counts.get("matched") == 1, counts
+        assert await status_of(owner_sessionmaker, event_id) == ("matched", 1)
+        request_id = await request_of(owner_sessionmaker, event_id, wf)
+        async with serving(worker, DbRunStore(worker_sessionmaker, worker_keys)):  # type: ignore[arg-type]
+            for _ in range(20):
+                if not await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings,
+                                                    BUILD):  # fmt: skip
+                    break
+            run = await until_ended(editor, f"{base}/runs/{request_id}")
+        audited = (await editor.get(f"{base}/runs/{request_id}")).json()
+    await ingress.state.engine.dispose()
+    assert (run["status"], run["request"]["source"], run["request"]["reason"]) == ("succeeded", "webhook", None)
+    # The canary was in the data: the request's input, decrypted with the real keys, is the event.
+    assert (await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, request_id))["token"] == CANARY
+    secrets = (CANARY, secret, token)
+    raws = await raw_histories(server.client)
+    assert raws and all(str(ctx.tenant_id).encode() in raw for raw in raws)  # this tenant's real histories, whole
+    assert not [c for c in secrets for raw in raws if c.encode() in raw]
+    rows = await plain_rows(owner_sessionmaker)
+    assert not [c for c in secrets if c in rows]
+    assert not [c for c in secrets for entry in logs if c in str(entry)]
+    assert not [c for c in secrets if c in json.dumps(audited)]
+    steps = audited["steps"]
+    assert steps and CANARY not in str(steps)
+
+
+async def owner_rows(owner: Any, endpoint_id: str) -> list[uuid.UUID]:
+    async with owner() as s:
+        return list((await s.execute(text("select id from inbound_events where endpoint_id = :e"),
+                                     {"e": endpoint_id})).scalars())  # fmt: skip
+
+
+async def status_of(owner: Any, event_id: uuid.UUID) -> tuple[str, int | None]:
+    async with owner() as s:
+        row = (await s.execute(text("select status, request_count from inbound_events where id = :e"),
+                               {"e": event_id})).one()  # fmt: skip
+    return row[0], row[1]
+
+
+async def request_of(owner: Any, event_id: uuid.UUID, workflow_id: uuid.UUID) -> str:
+    async with owner() as s:
+        return str((await s.execute(text("select id from run_requests where idempotency_key = :k"),
+                                    {"k": f"evt:{event_id}:{workflow_id}"})).scalar_one())  # fmt: skip
```

### Task 9: The load probe, and event rates set below what it measured the dispatcher drains

**Commit:** `e473aae` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/tests/probes/__init__.py`, `backend/tests/probes/ingress_load.py`

**Modify:** `backend/migrations/versions/0032_webhook_ingress.py`, `backend/src/dewpoint/core/models/ingress.py`,
`backend/tests/core/ingress/test_ingress_schema.py`

**What it does:**

`tests/probes/ingress_load.py`, run by hand on a disposable Postgres 16 container, never collected by the suite or run
in CI, measures each limit on its own: an authenticated body's cost on ingress's event loop; the failure limiter at
saturation; the candidates' ranking against the backlog; one ingress process's latency, throughput and memory; how long
a match holds its endpoint's row; each rate bucket and each pending and retained quota at its default; and the drain
through the dispatcher's own loop (a cycle, then its sleep), at a fan-out of 1, 3 and 5 and across one tenant's
endpoints. It drained 23.0, 16.6 and 13.0 events/s at a fan-out of 1, 3 and 5, and one tenant's four endpoints no
faster than one (every match holds the tenant's counter row). The default event rates, an endpoint's and a tenant's,
are therefore 10/s (their bursts, 1,000 and 5,000, unchanged), below the five-binding drain.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/core/ingress/test_ingress_schema.py`. Replay result (exit 1), shortened:

```
[gw0] darwin -- Python 3.14.7 <venv>/bin/python
E   assert (200.0, 1000) == (10, 1000)
      At index 0 diff: 200.0 != 10
      Use -v to get more diff
<replay>/t9/backend/tests/core/ingress/test_ingress_schema.py:158: assert (200.0, 1000) == (10, 1000)
[gw1] darwin -- Python 3.14.7 <venv>/bin/python
E   assert (1000.0, 5000) == (10, 5000)
      At index 0 diff: 1000.0 != 10
      Use -v to get more diff
<replay>/t9/backend/tests/core/ingress/test_ingress_schema.py:172: assert (1000.0, 5000) == (10, 5000)
=========================== short test summary info ============================
FAILED tests/core/ingress/test_ingress_schema.py::test_an_endpoints_default_event_rate_is_below_one_dispatchers_measured_drain
FAILED tests/core/ingress/test_ingress_schema.py::test_a_tenants_default_event_rate_is_below_what_its_endpoints_drain_together
2 failed, 10 passed in 21.42s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
............                                                             [100%]
12 passed in 13.98s
```

Evidence beyond the replay: the probe's parts ran by hand, each on a disposable database, and gave the measurements this
commit and the guide record; its `buckets` part ran again at the tenant's 10/s default (5,000 of 5,030 events accepted
in 100-event calls, the refusals waiting 8 to 10 s).

- [ ] **Step 3: commit.** `git cherry-pick --no-commit e473aae && git commit -C e473aae`

The diff:

```diff
diff --git a/backend/migrations/versions/0032_webhook_ingress.py b/backend/migrations/versions/0032_webhook_ingress.py
index 076e15c..c9d4381 100644
--- a/backend/migrations/versions/0032_webhook_ingress.py
+++ b/backend/migrations/versions/0032_webhook_ingress.py
@@ -259,7 +259,8 @@ def upgrade() -> None:
         sa.Column("events_pointer", sa.Text, nullable=True),  # none: the body is one event
         sa.Column("dedupe_key", sa.LargeBinary, nullable=False),  # sealed under the ingress key
         *_bucket("request", 20, 100),
-        *_bucket("event", 200, 1000),
+        # 10 events/s, below one dispatcher's measured drain (tests/probes/ingress_load.py drain); a burst for a batch.
+        *_bucket("event", 10, 1000),
         *_bucket("byte", 2 * MIB, 10 * MIB),
         sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
         *_counters(),
@@ -300,7 +301,9 @@ def upgrade() -> None:
     op.create_table(
         "tenant_event_counters",
         sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
-        *_bucket("event", 1000, 5000),
+        # 10 events/s: a tenant's endpoints are matched one at a time (each match holds this row), and drain no faster
+        # than one (tests/probes/ingress_load.py tenant-drain); the burst is a spike's budget.
+        *_bucket("event", 10, 5000),
         *_bucket("byte", 10 * MIB, 50 * MIB),
         sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
         *_counters(),
diff --git a/backend/src/dewpoint/core/models/ingress.py b/backend/src/dewpoint/core/models/ingress.py
index df1c1aa..4046d06 100644
--- a/backend/src/dewpoint/core/models/ingress.py
+++ b/backend/src/dewpoint/core/models/ingress.py
@@ -48,7 +48,7 @@ class WebhookEndpoint(Base):
     dedupe_key: Mapped[bytes] = mapped_column(LargeBinary)
     request_per_s: Mapped[float] = mapped_column(Float, server_default="20")
     request_burst: Mapped[int] = mapped_column(BigInteger, server_default="100")
-    event_per_s: Mapped[float] = mapped_column(Float, server_default="200")
+    event_per_s: Mapped[float] = mapped_column(Float, server_default="10")
     event_burst: Mapped[int] = mapped_column(BigInteger, server_default="1000")
     byte_per_s: Mapped[float] = mapped_column(Float, server_default=str(2 * 1024 * 1024))
     byte_burst: Mapped[int] = mapped_column(BigInteger, server_default=str(10 * 1024 * 1024))
diff --git a/backend/tests/core/ingress/test_ingress_schema.py b/backend/tests/core/ingress/test_ingress_schema.py
index ed8e772..a6e8415 100644
--- a/backend/tests/core/ingress/test_ingress_schema.py
+++ b/backend/tests/core/ingress/test_ingress_schema.py
@@ -144,3 +144,29 @@ async def test_a_binding_cant_point_to_another_tenants_workflow(owner_sessionmak
                      "values (:i, :t, :e, :w, :u)"),
                 {"i": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": foreign, "u": user},
             )  # fmt: skip
+
+
+async def test_an_endpoints_default_event_rate_is_below_one_dispatchers_measured_drain(owner_sessionmaker) -> None:
+    """The owner's M4 review: an endpoint's default event rate stays below what one dispatcher's own loop drains
+    (`tests/probes/ingress_load.py drain`: 12.6 events/s at a fan-out of 5, 15.9 at 3, 22.9 at 1), so a sender keeping
+    to it isn't refused for a backlog the platform can't clear. Its burst still admits a whole 500-event batch. A
+    pending quota's 429 is backpressure, never a throughput promise."""
+    _, endpoint_id = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s:
+        rate, burst = (await s.execute(text("select event_per_s, event_burst from webhook_endpoints where id = :e"),
+                                       {"e": endpoint_id})).one()  # fmt: skip
+    assert (rate, burst) == (10, 1000)
+
+
+async def test_a_tenants_default_event_rate_is_below_what_its_endpoints_drain_together(owner_sessionmaker) -> None:
+    """The owner's M4 review: every match holds the tenant's counter row, so a tenant's endpoints are matched one at a
+    time. `tests/probes/ingress_load.py tenant-drain` measured one tenant's four endpoints draining no faster than one
+    (23.8 events/s against 22.9, 24.7 with two dispatchers), and `drain` 13.0 events/s at a fan-out of 5: the tenant's
+    rate stays below that, whatever its number of endpoints. Its burst (5,000) is the abuse budget for a spike, which
+    the pending quota then holds back; a 429 there is backpressure, never a throughput promise."""
+    tenant, _ = await endpoint(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
+        rate, burst = (await s.execute(text("select event_per_s, event_burst from tenant_event_counters "
+                                            "where tenant_id = :t"), {"t": tenant})).one()  # fmt: skip
+    assert (rate, burst) == (10, 5000)
diff --git a/backend/tests/probes/__init__.py b/backend/tests/probes/__init__.py
new file mode 100644
index 0000000..94f7b86
--- /dev/null
+++ b/backend/tests/probes/__init__.py
@@ -0,0 +1,2 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Probes run by hand, never by the test suite or CI: each bounded, each on a disposable database of its own."""
diff --git a/backend/tests/probes/ingress_load.py b/backend/tests/probes/ingress_load.py
new file mode 100644
index 0000000..b3f5966
--- /dev/null
+++ b/backend/tests/probes/ingress_load.py
@@ -0,0 +1,625 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Webhook ingress's load probe (engine 2b spec §8.3, §15; the owner's ruling 12 on the 2b-3b outline): what its
+provisional limits are measured against, reproducible for the rate decision and production sign-off. Run by hand,
+never in CI; each part is bounded (a minute or two) and runs on a disposable Postgres 16 container (testcontainers),
+with synthetic data only. From `backend/`:
+
+    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.ingress_load <part>
+
+- `cost`: an authenticated body's parsing, splitting and sealing, on ingress's event loop;
+- `limiter`: the failure limiter's table at saturation, and what eviction makes of its limit;
+- `candidates`: `event_candidates()`, which ranks the whole pending backlog, against its size;
+- `ingress`: latency, throughput and memory of one `dewpoint ingress` process (uvicorn, a process of its own), and a
+  rate bucket's behavior;
+- `lock`: how long a match transaction holds its endpoint's row, and what that costs ingress on that endpoint;
+- `drain`: events matched per second through the dispatcher's own loop (a cycle, then its sleep), at a fan-out of 1, 3
+  and 5 bindings: the per-endpoint event rate's default stays below it;
+- `buckets`: each rate bucket (an endpoint's events and bytes, a tenant's events and bytes) at its default, on its own;
+- `quotas`: each pending and retained quota (events and bytes, an endpoint's and a tenant's) at its default, on its own;
+- `tenant-drain`: one tenant's endpoints drained together by one dispatcher or two (processes of their own), with two
+  tenants as the control: a tenant's default event rate stays below it.
+
+Numbers depend on the machine; record them with it."""
+
+import asyncio
+import base64
+import hashlib
+import json
+import os
+import statistics
+import subprocess
+import sys
+import time
+import tracemalloc
+import uuid
+from collections.abc import Callable, Coroutine
+from dataclasses import replace
+from pathlib import Path
+from typing import Any
+
+BACKEND = Path(__file__).resolve().parents[2]
+MIB = 1024 * 1024
+ROLES = ("dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin",
+         "dewpoint_auditor")  # fmt: skip
+FAST = {  # an endpoint whose buckets never refuse, for parts that measure something else
+    "request_per_s": 1e6, "request_burst": 10**6, "request_tokens": 1e6, "event_per_s": 1e6, "event_burst": 10**7,
+    "event_tokens": 1e7, "byte_per_s": 1e9, "byte_burst": 10**10, "byte_tokens": 1e10, "pending_events_max": 10**7,
+    "retained_events_max": 10**7, "pending_bytes_max": 10**11, "retained_bytes_max": 10**11,
+}  # fmt: skip
+
+
+def pct(values: list[float], p: float) -> float:
+    ordered = sorted(values)
+    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]
+
+
+def ms(seconds: float) -> str:
+    return f"{seconds * 1000:.2f} ms"
+
+
+def cost() -> None:
+    from dewpoint.apps.ingress.batch import prepare
+    from dewpoint.apps.ingress.endpoints import Endpoint
+    from dewpoint.core.crypto import events
+
+    _, public = events.generate_keypair()
+    base = Endpoint(id=uuid.uuid4(), tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="bearer",
+                    bearer_digest=b"", hmac_secret=None, signature_header=None, timestamp_header=None, tolerance_s=300,
+                    allowlist=(), body_limit=5 * MIB, id_source="none", id_pointer=None, id_header=None,
+                    events_pointer=None, dedupe_key=b"", key_version=1, public_key=public)  # fmt: skip
+    batch = replace(base, id_source="pointer", id_pointer="/id", events_pointer="/events")
+    secret = os.urandom(32)
+    pads = lambda size: json.dumps({"events": [{"id": f"e-{i}", "pad": "x" * size} for i in range(500)]}).encode()  # noqa: E731
+    cases: dict[str, tuple[Any, bytes, bytes | None]] = {
+        "1 event, 1 KiB": (base, json.dumps({"type": "ap_down", "pad": "x" * 1000}).encode(), None),
+        "500 events, ~1 MiB, ids": (batch, pads(2000), secret),
+        "500 events, ~5 MiB, ids": (batch, pads(10400), secret),
+        "1 event, 5 MiB string": (base, json.dumps({"pad": "x" * (5 * MIB - 20)}).encode(), None),
+        "1 event, ~5 MiB of small integers": (base, json.dumps({"a": [0] * (5 * MIB // 3 - 10)}).encode(), None),
+        "1 event, ~1.1 MiB of 1e15 (canonical x4.5)": (base, ('{"a":[' + ",".join(["1e15"] * 230_000) + "]}").encode(),
+                                                       None),
+    }  # fmt: skip
+    print("| body | bytes | prepare (median) | MiB/s | peak memory |\n|---|---|---|---|---|")
+    for name, (endpoint, body, key) in cases.items():
+        times = []
+        for _ in range(3 if len(body) > MIB else 20):
+            start = time.perf_counter()
+            prepare(endpoint, body, None, key)
+            times.append(time.perf_counter() - start)
+        tracemalloc.start()
+        prepare(endpoint, body, None, key)
+        _, peak = tracemalloc.get_traced_memory()
+        tracemalloc.stop()
+        median = statistics.median(times)
+        print(f"| {name} | {len(body):,} | {ms(median)} | {len(body) / MIB / median:.1f} | {peak / MIB:.1f} MiB |")
+
+
+def limiter() -> None:
+    from dewpoint.apps.ingress.limits import FailureLimiter
+
+    address = lambda prefix, i: f"{prefix}:{i // 65536:x}:{i % 65536:x}::/64"  # noqa: E731
+    table = FailureLimiter(failures=30, window_s=60)
+    tracemalloc.start()
+    start = time.perf_counter()
+    for i in range(65_536):
+        table.fail(address("2001:db8", i), 0.0)
+    filled = time.perf_counter() - start
+    _, peak = tracemalloc.get_traced_memory()
+    tracemalloc.stop()
+    start = time.perf_counter()
+    for i in range(100_000):
+        table.fail(address("2001:db9", i), 1.0)
+    full = time.perf_counter() - start
+    print(f"fill 65,536 entries: {ms(filled)} ({filled / 65_536 * 1e6:.2f} us each); peak ~{peak / MIB:.1f} MiB")
+    print(f"a failure on a full table (evicting): {full / 100_000 * 1e6:.2f} us")
+    victim = FailureLimiter(failures=30, window_s=60)
+    for _ in range(29):
+        victim.fail("203.0.113.9", 0.0)
+    for i in range(65_536):
+        victim.fail(address("2001:dba", i), 1.0)
+    for _ in range(29):
+        victim.fail("203.0.113.9", 2.0)
+    blocked = victim.blocked("203.0.113.9", 2.0) is not None
+    print("29 failures, then 65,536 other /64s in the same minute: the address is evicted and fails 29 more "
+          f"(blocked: {blocked}): best-effort past the table's size")  # fmt: skip
+
+
+class Database:
+    """A disposable Postgres 16, migrated, with the roles the tests use and a `development` deployment."""
+
+    def __enter__(self) -> "Database":
+        from testcontainers.community.postgres import PostgresContainer
+
+        self._container = PostgresContainer("postgres:16-alpine", driver="asyncpg").__enter__()
+        self.url = self._container.get_connection_url()
+        env = {**os.environ, "DEWPOINT_DATABASE_URL": self.url, "UV_NO_SYNC": "1"}
+        subprocess.run([".venv/bin/alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
+        return self
+
+    def __exit__(self, *exc: object) -> None:
+        self._container.__exit__(*exc)
+
+    def role_url(self, role: str) -> str:
+        return f"postgresql+asyncpg://t_{role}:pw@{self.url.split('@', 1)[1]}"
+
+    def sessions(self, role: str | None = None) -> Any:
+        from dewpoint.core.db import make_engine, make_sessionmaker
+
+        return make_sessionmaker(make_engine(self.role_url(role) if role else self.url))
+
+    async def prepared(self) -> None:
+        from sqlalchemy import text
+
+        from dewpoint.core.db import make_engine, make_sessionmaker
+        from dewpoint.core.platform.service import DEVELOPMENT, record_environment
+
+        engine = make_engine(self.url)
+        async with engine.begin() as c:
+            for role in ROLES:
+                await c.execute(text(f"CREATE ROLE t_{role} LOGIN PASSWORD 'pw' IN ROLE {role}"))
+        async with make_sessionmaker(engine)() as s, s.begin():
+            await record_environment(s, environment=DEVELOPMENT, namespace="default")
+        await engine.dispose()
+
+
+async def candidates(db: Database) -> None:
+    from sqlalchemy import text
+
+    from tests.core.ingress.support import endpoint
+
+    owner, dispatch = db.sessions(), db.sessions("dewpoint_dispatch")
+    endpoints = [await endpoint(owner) for _ in range(10)]
+    total = 0
+    print("| pending events (10 tenants) | event_candidates(50), median of 5 | max |\n|---|---|---|")
+    for target in (1_000, 10_000, 50_000, 200_000):
+        per_tenant = (target - total) // len(endpoints)
+        async with owner() as s, s.begin():
+            for tenant, endpoint_id in endpoints:
+                await s.execute(text(
+                    "insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes, "
+                    "received_at) select gen_random_uuid(), :t, :e, 1, '\\x01', 1, now() - make_interval(secs => g) "
+                    "from generate_series(1, :n) g"), {"t": tenant, "e": endpoint_id, "n": per_tenant})  # fmt: skip
+            await s.execute(text("analyze inbound_events"))
+        total += per_tenant * len(endpoints)
+        times = []
+        for _ in range(5):
+            async with dispatch() as s:
+                start = time.perf_counter()
+                await s.execute(text("select * from event_candidates(50)"))
+                times.append(time.perf_counter() - start)
+        print(f"| {total:,} | {ms(statistics.median(times))} | {ms(max(times))} |")
+
+
+async def ingress(db: Database) -> None:
+    import httpx
+    from sqlalchemy import text
+
+    from tests.core.ingress.support import endpoint
+
+    owner = db.sessions()
+    token = "dwp_probe-token"  # noqa: S105 - the probe's own
+    digest = hashlib.sha256(token.encode()).digest()
+    tenant, fast = await endpoint(owner, bearer_digest=digest, **FAST)
+    async with owner() as s, s.begin():
+        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
+                             "byte_per_s, byte_burst, byte_tokens, pending_events_max, retained_events_max, "
+                             "pending_bytes_max, retained_bytes_max) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
+                             "1e10, 10000000, 10000000, 100000000000, 100000000000)"), {"t": tenant})  # fmt: skip
+    _, limited = await endpoint(owner, bearer_digest=digest)  # the defaults
+    env = {k: v for k, v in os.environ.items() if not k.startswith("DEWPOINT_KEK")} | {
+        "DEWPOINT_DATABASE_URL": db.role_url("dewpoint_ingress"), "PYTHONPATH": f"{BACKEND}/src",
+        "DEWPOINT_INGRESS_KEY_B64": base64.b64encode(os.urandom(32)).decode(),
+    }  # fmt: skip
+    server = subprocess.Popen([".venv/bin/python", "-c", "from dewpoint.apps.cli.main import app; app()", "ingress",  # noqa: ASYNC220 - started once, before the measuring
+                               "--port", "18099"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL,
+                              stderr=subprocess.DEVNULL)  # fmt: skip
+
+    def rss() -> float:
+        out = subprocess.run(["ps", "-o", "rss=", "-p", str(server.pid)], capture_output=True, text=True).stdout
+        return int(out.strip() or 0) / 1024
+
+    try:
+        async with httpx.AsyncClient(base_url="http://127.0.0.1:18099", timeout=30,
+                                     limits=httpx.Limits(max_connections=64)) as c:  # fmt: skip
+            for _ in range(100):
+                try:
+                    if (await c.get("/health/ready")).status_code == 200:
+                        break
+                except httpx.HTTPError:
+                    pass
+                await asyncio.sleep(0.1)
+            headers = {"authorization": f"Bearer {token}"}
+            body = json.dumps({"type": "ap_down", "pad": "x" * 1000}).encode()
+            print(f"ingress RSS idle: {rss():.0f} MiB")
+            print("| concurrency | requests | throughput | p50 | p95 | p99 | RSS |\n|---|---|---|---|---|---|---|")
+
+            async def one(n: int, latencies: list[float]) -> None:
+                for _ in range(n):
+                    start = time.perf_counter()
+                    answer = await c.post(f"/hooks/{fast}", content=body, headers=headers)
+                    latencies.append(time.perf_counter() - start)
+                    assert answer.status_code == 200, answer.text
+
+            for concurrency in (1, 8, 32):
+                latencies: list[float] = []
+                start = time.perf_counter()
+                await asyncio.gather(*(one(400 // concurrency, latencies) for _ in range(concurrency)))
+                elapsed = time.perf_counter() - start
+                print(f"| {concurrency} | {len(latencies)} | {len(latencies) / elapsed:.0f}/s | "
+                      f"{ms(pct(latencies, .5))} | {ms(pct(latencies, .95))} | {ms(pct(latencies, .99))} | "
+                      f"{rss():.0f} MiB |")  # fmt: skip
+            statuses: list[int] = []
+            start = time.perf_counter()
+
+            async def hammer() -> None:
+                for _ in range(40):
+                    answer = await c.post(f"/hooks/{limited}", content=b'{"n": 1}', headers=headers)
+                    statuses.append(answer.status_code)
+
+            await asyncio.gather(*(hammer() for _ in range(8)))
+            elapsed = time.perf_counter() - start
+            print(
+                f"the default request bucket (20/s, burst 100): 320 requests in {elapsed:.2f} s, "
+                f"{statuses.count(200)} accepted, {statuses.count(429)} refused; it allows {100 + 20 * elapsed:.0f}"
+            )
+    finally:
+        server.terminate()
+        server.wait(10)
+
+
+def _settings(db: Database) -> Any:
+    from dewpoint.core.config import Settings
+
+    return Settings(database_url=db.role_url("dewpoint_api"), kek_b64=base64.b64encode(b"k" * 32).decode(),
+                    public_origin="https://probe", rp_id="probe")  # fmt: skip
+
+
+async def _inbound(db: Database, fan_out: int) -> Any:
+    """A tenant with `fan_out` published workflows, all bound to one endpoint whose buckets never refuse."""
+    from sqlalchemy import text
+
+    from tests.apps.dispatcher.inbound import bind, inbound
+    from tests.apps.test_admission import OPEN_GRAPH
+    from tests.apps.test_workflow_ops import create, publish
+
+    owner, api = db.sessions(), db.sessions("dewpoint_api")
+    settings = _settings(db)
+    ready = await inbound(owner, api, db.sessions("dewpoint_admin"), db.sessions("dewpoint_dispatch"), settings)
+    await bind(owner, ready)
+    for n in range(fan_out - 1):
+        workflow = await create(api, ready.ctx, OPEN_GRAPH, name=f"fan-{n}")
+        assert (await publish(api, ready.ctx, workflow, settings)).version is not None
+        await bind(owner, ready, workflow)
+    async with owner() as s, s.begin():
+        await s.execute(text("update webhook_endpoints set " + ", ".join(f"{k} = :{k}" for k in FAST)  # noqa: S608
+                             + " where id = :e"), FAST | {"e": ready.endpoint_id})  # fmt: skip
+        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
+                             "byte_per_s, byte_burst, byte_tokens) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
+                             "1e10) on conflict (tenant_id) do update set event_per_s = 1e6, event_burst = 10000000, "
+                             "event_tokens = 1e7, byte_per_s = 1e9, byte_burst = 10000000000, byte_tokens = 1e10"),
+                        {"t": ready.tenant_id})  # fmt: skip
+    return ready
+
+
+async def _record(db: Database, ready: Any, n: int, *, batch: int = 1) -> list[float]:
+    """`n` events recorded through ingress's function, `batch` a call: each call's time."""
+    from tests.apps.dispatcher.inbound import sealed
+    from tests.core.ingress.support import RECORD
+
+    ingress_ = db.sessions("dewpoint_ingress")
+    times = []
+    for _ in range(n // batch):
+        ids = [uuid.uuid4() for _ in range(batch)]
+        params = {"e": ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
+                  "sealed": [sealed(ready, i, {"type": "ap_down", "pad": "x" * 500}) for i in ids],
+                  "versions": [1] * batch, "dedupe": [None] * batch, "digests": [None] * batch}  # fmt: skip
+        start = time.perf_counter()
+        async with ingress_() as s, s.begin():
+            await s.execute(RECORD, params)
+        times.append(time.perf_counter() - start)
+    return times
+
+
+async def lock(db: Database) -> None:
+    from sqlalchemy import text
+
+    from dewpoint.apps.dispatcher import matching
+    from tests.apps.test_admission import KEYS
+
+    ready = await _inbound(db, 1)
+    dispatch = db.sessions("dewpoint_dispatch")
+    idle = await _record(db, ready, 300)
+    print(f"recording on an idle endpoint: p50 {ms(pct(idle, 0.5))}, p95 {ms(pct(idle, 0.95))}")
+    await _record(db, ready, 200)
+    async with dispatch() as s:
+        picked = (await s.execute(text("select tenant_id, event_id, endpoint_id from event_candidates(200)"))).all()
+    verified, held = matching.Verified(), []
+    for tenant_id, event_id, endpoint_id in picked:
+        start = time.perf_counter()
+        await matching.match_event(dispatch, KEYS, verified, tenant_id=tenant_id, event_id=event_id,
+                                   endpoint_id=endpoint_id)  # fmt: skip
+        held.append(time.perf_counter() - start)
+    print(f"a match transaction, which holds its endpoint's row (an upper bound): p50 {ms(pct(held, .5))}, "
+          f"p95 {ms(pct(held, .95))}, max {ms(max(held))}")  # fmt: skip
+    await _record(db, ready, 1000)
+
+    async def matched_without_pause() -> None:  # the endpoint's row held as much as matching can
+        while await matching.match_once(dispatch, KEYS, verified):
+            pass
+
+    task = asyncio.create_task(matched_without_pause())
+    contended = await _record(db, ready, 300)
+    await task
+    print(f"recording while that endpoint is matched back to back: p50 {ms(pct(contended, .5))}, "
+          f"p95 {ms(pct(contended, .95))}, max {ms(max(contended))}")  # fmt: skip
+
+
+async def drain(db: Database) -> None:
+    """Events matched per second through `dewpoint dispatcher`'s own loop: `main.cycle` (it observes the build,
+    dispatches what's due, then matches), then the loop's `CYCLE_S` sleep, one dispatcher, not the leader (whose
+    reconciling only adds to a cycle). Temporal is a fake that accepts each start at once, so a real one's latency only
+    lowers this."""
+    from tests.apps.dispatcher.support import workers
+
+    owner, dispatch, settings = db.sessions(), db.sessions("dewpoint_dispatch"), _settings(db)
+    await workers(owner)
+
+    class NotLeading:
+        async def leading(self) -> bool:
+            return False
+
+    print("| fan-out | events | elapsed | events/s sustained | requests admitted | cycle time, median |")
+    print("|---|---|---|---|---|---|")
+    for fan_out in (1, 3, 5):
+        ready = await _inbound(db, fan_out)
+        await _record(db, ready, 500, batch=100)
+        await _drained(owner, dispatch, settings, ready, fan_out, 500, NotLeading())
+
+
+async def _drained(owner: Any, dispatch: Any, settings: Any, ready: Any, fan_out: int, events: int,
+                   leader: Any) -> None:  # fmt: skip
+    """The endpoint's pending events drained through the dispatcher's loop, timed, and a row printed."""
+    from sqlalchemy import text
+
+    from dewpoint.apps.dispatcher import dispatch as dispatching
+    from dewpoint.apps.dispatcher import main
+    from tests.apps.test_admission import KEYS
+    from tests.apps.test_runs import FakeClient
+
+    client, rotation, verified = FakeClient(), dispatching.Rotation(), main.Verified()
+    cycles: list[float] = []
+
+    async def one() -> None:
+        start = time.perf_counter()
+        await main.cycle(dispatch, client, KEYS, settings, instance=uuid.uuid4(), reconciler=uuid.uuid4(),  # type: ignore[arg-type]
+                         leader=leader, rotation=rotation, verified=verified)  # fmt: skip
+        cycles.append(time.perf_counter() - start)
+
+    query = text("select count(*) from inbound_events where endpoint_id = :e and status = 'pending'")
+    start = time.perf_counter()
+    while True:
+        async with owner() as s:
+            if not (await s.execute(query, {"e": ready.endpoint_id})).scalar_one():
+                break
+        await main.serve(one, cycles=1)  # a cycle, then the loop's own sleep
+    elapsed = time.perf_counter() - start
+    admitted_query = text("select count(*) from run_requests where idempotency_key like 'evt:%' and workflow_id in "
+                          "(select workflow_id from trigger_bindings where endpoint_id = :e)")  # fmt: skip
+    async with owner() as s:
+        admitted = (await s.execute(admitted_query, {"e": ready.endpoint_id})).scalar_one()
+    print(f"| {fan_out} | {events} | {elapsed:.1f} s | {events / elapsed:.1f} | {admitted} | "
+          f"{ms(statistics.median(cycles))} |")  # fmt: skip
+
+
+# Each limit measured on its own (the owner's M4 review): a fresh tenant and endpoint for each, every other limit
+# relaxed, the one measured at its default, through `record_inbound_events` itself.
+TENANT_FAST = {
+    "event_per_s": 1e6, "event_burst": 10**7, "event_tokens": 1e7, "byte_per_s": 1e9, "byte_burst": 10**10,
+    "byte_tokens": 1e10, "pending_events_max": 10**7, "pending_bytes_max": 10**11, "retained_events_max": 10**7,
+    "retained_bytes_max": 10**11,
+}  # fmt: skip
+ENDPOINT_FAST = FAST | {"body_limit": 5 * MIB, "byte_burst": 10**10}
+
+
+async def _measured(db: Database, endpoint_limits: tuple[str, ...], tenant_limits: tuple[str, ...]) -> uuid.UUID:
+    """A fresh endpoint whose limits are relaxed but those named (left at their defaults), of a fresh tenant
+    likewise."""
+    from sqlalchemy import text
+
+    from tests.core.ingress.support import endpoint
+
+    owner = db.sessions()
+    columns = {k: v for k, v in ENDPOINT_FAST.items() if not any(k.startswith(limit) for limit in endpoint_limits)}
+    tenant, endpoint_id = await endpoint(owner, **columns)
+    relaxed = {k: v for k, v in TENANT_FAST.items() if not any(k.startswith(limit) for limit in tenant_limits)}
+    async with owner() as s, s.begin():
+        await s.execute(text(f"insert into tenant_event_counters (tenant_id, {', '.join(relaxed)}) values "  # noqa: S608
+                             f"(:t, {', '.join(':' + k for k in relaxed)})"), {"t": tenant} | relaxed)  # fmt: skip
+    return endpoint_id
+
+
+async def _call(
+    ingress_: Any, endpoint_id: uuid.UUID, events: int, size: int, keyed: bool = False
+) -> tuple[Any, float]:
+    """One recording of `events` events of `size` sealed bytes each (keyed: with dedupe keys): its outcome and time."""
+    from tests.core.ingress.support import RECORD
+
+    ids = [uuid.uuid4() for _ in range(events)]
+    keys = [os.urandom(32) if keyed else None for _ in ids]
+    params = {"e": endpoint_id, "refusal": None, "read": 0, "ids": ids, "sealed": [os.urandom(size) for _ in ids],
+              "versions": [1] * events, "dedupe": keys, "digests": [k and os.urandom(32) for k in keys]}  # fmt: skip
+    start = time.perf_counter()
+    async with ingress_() as s, s.begin():
+        outcome = dict((await s.execute(RECORD, params)).scalar_one())
+    return outcome | {"params": params}, time.perf_counter() - start
+
+
+async def buckets(db: Database) -> None:
+    """Each rate bucket at its default, sent to as fast as one caller can for 3 s: what it accepted against what it
+    allows (its burst, and its rate over the time taken), and the wait a refusal names."""
+    ingress_ = db.sessions("dewpoint_ingress")
+    cases = (  # (bucket, endpoint limits kept, tenant limits kept, events a call, bytes an event, unit, burst, rate)
+        ("endpoint events (10/s, burst 1,000)", ("event_",), (), 1, 100, "events", 1000, 10),
+        ("endpoint bytes (2 MiB/s, burst 10 MiB)", ("byte_", "body_limit"), (), 1, MIB // 2,
+         "bytes", 10 * MIB, 2 * MIB),
+        ("tenant events (10/s, burst 5,000)", (), ("event_",), 100, 100, "events", 5000, 10),
+        ("tenant bytes (10 MiB/s, burst 50 MiB)", (), ("byte_",), 1, 4 * MIB, "bytes", 50 * MIB, 10 * MIB),
+    )  # fmt: skip
+    print("| bucket | accepted | it allows | refused calls | a refusal's Retry-After | a call, median |")
+    print("|---|---|---|---|---|---|")
+    for name, kept_endpoint, kept_tenant, events, size, unit, burst, rate in cases:
+        endpoint_id = await _measured(db, kept_endpoint, kept_tenant)
+        accepted, refused, waits, times = 0, 0, [], []
+        start = time.perf_counter()
+        while time.perf_counter() - start < 3:
+            outcome, took = await _call(ingress_, endpoint_id, events, size)
+            times.append(took)
+            if outcome["outcome"] == "recorded":
+                accepted += events * (1 if unit == "events" else size)
+            else:
+                refused += 1
+                waits.append(outcome.get("retry_after"))
+        elapsed = time.perf_counter() - start
+        shown = (lambda v: f"{v:,}") if unit == "events" else (lambda v: f"{v / MIB:.1f} MiB")  # noqa: E731
+        print(f"| {name} | {shown(accepted)} | {shown(int(burst + rate * elapsed))} | {refused} | "
+              f"{sorted(set(waits))[:3]} | {ms(statistics.median(times))} |")  # fmt: skip
+
+
+async def quotas(db: Database) -> None:
+    """Each pending and retained quota at its default, filled until refused: what it took, the refusal, a duplicate's
+    acknowledgment at the quota, and a call's time empty and full."""
+    ingress_ = db.sessions("dewpoint_ingress")
+    pending, retained = ("pending_",), ("retained_",)
+    cases = (  # (quota, endpoint limits kept, tenant limits kept, events a call, bytes an event)
+        ("endpoint pending events (10,000)", pending, (), 500, 64),
+        ("endpoint pending bytes (64 MiB)", pending, (), 1, 4 * MIB),
+        ("tenant pending events (50,000)", (), pending, 500, 64),
+        ("tenant pending bytes (256 MiB)", (), pending, 1, 4 * MIB),
+        ("endpoint retained events (100,000)", retained, (), 500, 64),
+        ("endpoint retained bytes (512 MiB)", retained, (), 1, 4 * MIB),
+        ("tenant retained events (250,000)", (), retained, 500, 64),
+        ("tenant retained bytes (1 GiB)", (), retained, 1, 4 * MIB),
+    )
+    print("| quota | taken before refusal | refusal | Retry-After | a duplicate at it | a call, first / last |")
+    print("|---|---|---|---|---|---|")
+    for name, kept_endpoint, kept_tenant, events, size in cases:
+        endpoint_id = await _measured(db, kept_endpoint, kept_tenant)
+        taken, first, times = 0, None, []
+        while True:
+            outcome, took = await _call(ingress_, endpoint_id, events, size, keyed=True)
+            times.append(took)
+            if outcome["outcome"] != "recorded":
+                break
+            first = first or outcome["params"]
+            taken += events
+        from tests.core.ingress.support import RECORD
+
+        again = {**first, "ids": [uuid.uuid4() for _ in first["ids"]]}  # the first call's events, a sender's retry
+        async with ingress_() as s, s.begin():
+            duplicate = dict((await s.execute(RECORD, again)).scalar_one())
+        amount = f"{taken:,} events" if size < 1024 else f"{taken * size / MIB:.0f} MiB"
+        print(f"| {name} | {amount} | {outcome['outcome']} | {outcome.get('retry_after', 'none')} | "
+              f"{duplicate.get('duplicates', duplicate['outcome'])} acknowledged | "
+              f"{ms(statistics.median(times[:5]))} / {ms(statistics.median(times[-5:]))} |")  # fmt: skip
+
+
+async def tenant_drain(db: Database) -> None:
+    """One tenant's endpoints drained together, by one dispatcher or two (each a process of its own, its own loop):
+    every match holds the tenant's counter row, so a tenant's endpoints are matched one at a time whatever the
+    dispatchers. Two tenants by two dispatchers is the control. Fan-out 1; a fake Temporal, as `drain`."""
+    from tests.apps.dispatcher.inbound import bind, endpoint
+    from tests.apps.dispatcher.support import workers
+
+    owner = db.sessions()
+    await workers(owner)
+    scenarios = (  # (name, tenants, endpoints a tenant, dispatchers)
+        ("1 tenant, 1 endpoint, 1 dispatcher", 1, 1, 1),
+        ("1 tenant, 4 endpoints, 1 dispatcher", 1, 4, 1),
+        ("1 tenant, 4 endpoints, 2 dispatchers", 1, 4, 2),
+        ("2 tenants, 2 endpoints each, 2 dispatchers (control)", 2, 2, 2),
+    )
+    print("| scenario | events | elapsed | events/s sustained |\n|---|---|---|---|")
+    for name, tenants, per_tenant, dispatchers in scenarios:
+        total = 400
+        for _ in range(tenants):
+            ready = await _inbound(db, 1)
+            endpoints = [ready.endpoint_id]
+            for _ in range(per_tenant - 1):
+                extra = await endpoint(owner, ready.tenant_id, ready.user_id, **FAST)
+                await bind(owner, ready, endpoint_id=extra)
+                endpoints.append(extra)
+            for endpoint_id in endpoints:
+                await _record(db, replace_endpoint(ready, endpoint_id), total // (tenants * per_tenant), batch=50)
+        env = os.environ | {"PYTHONPATH": f"{BACKEND}/src:{BACKEND}"}
+        children = [subprocess.Popen([".venv/bin/python", "-m", "tests.probes.ingress_load", "dispatcher-loop",  # noqa: ASYNC220
+                                      db.role_url("dewpoint_dispatch")], cwd=BACKEND, env=env,
+                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
+                    for _ in range(dispatchers)]  # fmt: skip
+        spans = [tuple(float(v) for v in child.communicate()[0].split()[-2:]) for child in children]
+        elapsed = max(end for _, end in spans) - min(begin for begin, _ in spans)
+        print(f"| {name} | {total} | {elapsed:.1f} s | {total / elapsed:.1f} |")
+
+
+def replace_endpoint(ready: Any, endpoint_id: uuid.UUID) -> Any:
+    return replace(ready, endpoint_id=endpoint_id)
+
+
+async def dispatcher_loop(dispatch_url: str) -> None:
+    """A dispatcher of `tenant-drain`'s, in a process of its own: its loop until nothing is pending, then the times its
+    first cycle began and its last ended."""
+    from sqlalchemy import text
+
+    from dewpoint.apps.dispatcher import dispatch as dispatching
+    from dewpoint.apps.dispatcher import main
+    from dewpoint.core.config import Settings
+    from dewpoint.core.db import make_engine, make_sessionmaker
+    from tests.apps.test_admission import KEYS
+    from tests.apps.test_runs import FakeClient
+
+    class NotLeading:
+        async def leading(self) -> bool:
+            return False
+
+    sessions = make_sessionmaker(make_engine(dispatch_url))
+    settings = Settings(database_url=dispatch_url, kek_b64=base64.b64encode(b"k" * 32).decode(),
+                        public_origin="https://probe", rp_id="probe")  # fmt: skip
+    client, rotation, verified = FakeClient(), dispatching.Rotation(), main.Verified()
+
+    async def one() -> None:
+        await main.cycle(sessions, client, KEYS, settings, instance=uuid.uuid4(), reconciler=uuid.uuid4(),  # type: ignore[arg-type]
+                         leader=NotLeading(), rotation=rotation, verified=verified)  # fmt: skip
+
+    begin = time.time()
+    while True:
+        async with sessions() as s:
+            if not (await s.execute(text("select 1 from event_candidates(1)"))).first():
+                break
+        await main.serve(one, cycles=1)
+    print(begin, time.time())
+
+
+PARTS: dict[str, Callable[[Database], Coroutine[Any, Any, None]]] = {
+    "candidates": candidates, "ingress": ingress, "lock": lock, "drain": drain, "buckets": buckets, "quotas": quotas,
+    "tenant-drain": tenant_drain,
+}  # fmt: skip
+
+
+def run(part: str, *args: str) -> None:
+    if part == "dispatcher-loop":  # a child of `tenant-drain`
+        asyncio.run(dispatcher_loop(args[0]))
+    elif part == "cost":
+        cost()
+    elif part == "limiter":
+        limiter()
+    else:
+        with Database() as db:
+
+            async def go() -> None:
+                await db.prepared()
+                await PARTS[part](db)
+
+            asyncio.run(go())
+
+
+if __name__ == "__main__":
+    run(*sys.argv[1:])
```

### Task 10: Webhook ingress under its own Compose profile behind nginx, CI's proof through it, and its guide

**Commit:** `aa8efc3` (prototype `proto/2b3b-v2`), whose tree the replay reproduced: yes.

**Create:** `backend/tests/deploy/test_compose_ingress_proof.py`, `deploy/compose/ci/ingress-proof.py`,
`docs/operations/ingress.md`

**Modify:** `.github/workflows/ci.yml`, `backend/tests/deploy/test_compose.py`, `deploy/compose/.env.example`,
`deploy/compose/docker-compose.yml`, `deploy/docker/nginx.conf`, `docs/operations/deployment.md`,
`docs/operations/runs.md`

**What it does:**

Compose's `ingress` service runs only with the `ingress` profile (still refusing outside a development deployment):
its own environment (no key-encryption key), its login, no published port, reached by `web` on a network of their own,
`hooks`, whose range is the one it believes X-Forwarded-For from. nginx's `/hooks/` route streams each body to ingress
as it arrives (chunked too, over HTTP/1.1), so ingress's whole-body deadline and its in-flight limit hold through it,
and writes the client it recovered into X-Forwarded-For. The API holds the ingress key when one is set.

CI's e2e job runs the profile and one bounded step: `ci/ingress-proof.py` makes an HMAC endpoint and its binding; a
signed event goes through nginx to ingress, then again as a retry (acknowledged once); a body trickled through nginx
gets its 408 within the deadline; the Compose dispatcher matches the event and the worker runs it, within 120 s. The
script is proven against the test database.

`docs/operations/ingress.md`: running it, endpoints and signing, Mist's bearer path (unverified until a real delivery
confirms the Authorization header), ids and at-least-once, responses, bindings, outcomes, limits as backpressure, the
load probe's measurements (one machine's), and matching's scaling with dispatchers, a required decision of 2b-4.

- [ ] **Step 1: its tests alone, before its code.** Run (in `backend/`): `uv run pytest -q -n 2
  tests/deploy/test_compose.py tests/deploy/test_compose_ingress_proof.py`. Replay result (exit 1), shortened:

```
<replay>/t10/backend/tests/deploy/test_compose.py:165: KeyError: 'DEWPOINT_INGRESS_KEY_B64'
[gw0] darwin -- Python 3.14.7 <venv>/bin/python
E   KeyError: 'COMPOSE_PROFILES'
<replay>/t10/backend/tests/deploy/test_compose.py:170: KeyError: 'COMPOSE_PROFILES'
[gw1] darwin -- Python 3.14.7 <venv>/bin/python
E   FileNotFoundError: [Errno 2] No such file or directory: '<replay>/t10/deploy/compose/ci/ingress-proof.py'
<frozen importlib._bootstrap_external>:950: FileNotFoundError: [Errno 2] No such file or directory: '<replay>/t10/deploy/compose/ci/ingress-proof.py'
=========================== short test summary info ============================
FAILED tests/deploy/test_compose.py::test_ingress_runs_behind_its_profile_as_its_own_login_without_a_key_encryption_key
FAILED tests/deploy/test_compose.py::test_web_reaches_ingress_on_a_network_of_their_own_whose_addresses_ingress_trusts
FAILED tests/deploy/test_compose.py::test_the_api_holds_the_ingress_key_only_when_one_is_set
FAILED tests/deploy/test_compose.py::test_ci_runs_the_ingress_profile_and_proves_a_webhook_through_nginx
FAILED tests/deploy/test_compose_ingress_proof.py::test_the_ingress_proof_waits_for_the_webhooks_run_to_succeed
5 failed, 8 passed in 21.18s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.............                                                            [100%]
13 passed in 19.77s
```

Evidence beyond the replay: the repo's `nginx.conf` in the local `dewpoint-web:dev` image (which the owner approved for
this proof), pointed at an ingress on the host: buffering, a trickled body got no answer in 25 s, by length and chunked;
streaming, each got its 408 at 10.0 s, and a whole body its 200. The Compose stack and its CI step haven't run here:
this branch's pull request runs them.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit aa8efc3 && git commit -C aa8efc3`

The diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index c085e9d..2799bb2 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -73,7 +73,8 @@ jobs:
     runs-on: ubuntu-latest
     needs: [backend, frontend]
     # A development deployment (engine 2b spec §2.1): every compose command below uses the override.
-    env: { COMPOSE_FILE: "docker-compose.yml:docker-compose.dev.yml" }
+    # Webhook ingress runs only under its profile (a gated prototype until 2b-4, engine 2b spec §8.3).
+    env: { COMPOSE_FILE: "docker-compose.yml:docker-compose.dev.yml", COMPOSE_PROFILES: ingress }
     steps:
       - uses: actions/checkout@v4
       - name: Write CI env
@@ -88,6 +89,7 @@ jobs:
             echo "DEWPOINT_DISPATCH_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_INGRESS_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_KEK_B64=$(openssl rand -base64 32)"
+            echo "DEWPOINT_INGRESS_KEY_B64=$(openssl rand -base64 32)"
             echo "DEWPOINT_AUDIT_SIGNING_KEY_B64=$(openssl rand -base64 32)"
           } > .env
       - working-directory: deploy/compose
@@ -130,6 +132,34 @@ jobs:
           # only once the first scheduled run succeeded, within 150 s.
           schedule=$(docker compose run --rm -T api python - create "$tenant" "$workflow" < ci/schedule-proof.py | tail -n 1)
           docker compose run --rm -T api python - wait "$tenant" "$schedule" 150 < ci/schedule-proof.py
+      - name: A webhook through nginx and ingress (engine 2b spec §8.3, §12)
+        working-directory: deploy/compose
+        timeout-minutes: 5
+        run: |
+          set -a; . ./.env; set +a
+          read -r tenant workflow < <(docker compose run --rm -T api python - < ci/seed-workflow.py | tail -n 1)
+          # An HMAC endpoint and its binding, as the API's login; the secret, shown once, only ever in this shell.
+          read -r endpoint secret < <(docker compose run --rm -T api python - create "$tenant" "$workflow" \
+            < ci/ingress-proof.py | tail -n 1)
+          body='{"id":"ci-proof-1","type":"ci_proof"}'
+          stamp=$(date +%s)
+          signature=$(printf '%s.%s' "$stamp" "$body" | openssl dgst -sha256 -hmac "$secret" -r | cut -d' ' -f1)
+          post() {
+            curl -sS -o response.json -w '%{http_code}' -X POST "http://127.0.0.1:8080/hooks/$endpoint" \
+              -H "content-type: application/json" -H "x-dewpoint-timestamp: $stamp" \
+              -H "x-dewpoint-signature: $signature" --data-binary "$body"
+          }
+          # Signed, through nginx to ingress: recorded; the same event again (a sender's retry): acknowledged once.
+          test "$(post)" = 200 && grep -q '"accepted":1' response.json
+          test "$(post)" = 200 && grep -q '"duplicates":1' response.json
+          # A body trickled through nginx, a byte every 2 s (under nginx's own gap timeout), streamed to ingress: its
+          # 408 within the 10 s whole-body deadline, never minutes later.
+          start=$(date +%s)
+          trickled=$( (printf '{'; for _ in $(seq 30); do sleep 2; printf ' '; done; printf '}') | curl -sS \
+            -o /dev/null -w '%{http_code}' --max-time 40 -X POST -T - -H 'Expect:' "http://127.0.0.1:8080/hooks/$endpoint")
+          test "$trickled" = 408 && test $(( $(date +%s) - start )) -le 14
+          # Matched by the Compose dispatcher, started and run: exit 0 only once its run succeeded, within 120 s.
+          docker compose run --rm -T api python - wait "$tenant" "$endpoint" 120 < ci/ingress-proof.py
       - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
         with: { package_json_file: frontend/package.json }
       - uses: actions/setup-node@v4
diff --git a/backend/tests/deploy/test_compose.py b/backend/tests/deploy/test_compose.py
index 914dde2..597b596 100644
--- a/backend/tests/deploy/test_compose.py
+++ b/backend/tests/deploy/test_compose.py
@@ -117,3 +117,61 @@ def test_the_database_init_makes_an_ingress_login_from_its_password() -> None:
     ci = (COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml").read_text()
     assert 'echo "DEWPOINT_INGRESS_DB_PASSWORD=$(openssl rand -hex 16)"' in ci
     assert "DEWPOINT_INGRESS_DB_PASSWORD=" in (COMPOSE.parent / ".env.example").read_text()
+
+
+NGINX = Path(__file__).parents[3] / "deploy" / "docker" / "nginx.conf"
+HOOKS_SUBNET = "172.31.255.248/29"
+
+
+def test_ingress_runs_behind_its_profile_as_its_own_login_without_a_key_encryption_key() -> None:
+    """2b-3b (engine 2b spec §8.3): ingress is a gated prototype until 2b-4, so plain Compose never starts it; the
+    `ingress` profile does, and it still refuses to start unless the deployment is `development`. Its environment is its
+    own (it refuses one holding the key-encryption key), its database login has no table privilege, and it publishes no
+    port: it's reached through `web` only."""
+    ingress = service("ingress")
+    assert ingress["profiles"] == ["ingress"]
+    assert ingress["command"] == ["dewpoint", "ingress", "--host", "0.0.0.0", "--port", "8001"]  # noqa: S104 - no port published
+    env = environment("ingress")
+    assert not [name for name in env if "KEK" in name]
+    assert env["DEWPOINT_DATABASE_URL"] == "postgresql+asyncpg://dewpoint_ingress_login:ingress-pw@postgres/dewpoint"
+    assert env["DEWPOINT_INGRESS_TRUSTED_PROXIES"] == HOOKS_SUBNET
+    assert "ports" not in ingress and ingress["read_only"] is True and ingress["cap_drop"] == ["ALL"]
+    assert ingress["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}
+
+
+def test_web_reaches_ingress_on_a_network_of_their_own_whose_addresses_ingress_trusts() -> None:
+    """Ruling 11: X-Forwarded-For is believed only from configured proxies. `web` and ingress share a small network
+    (`hooks`), on which ingress is `hooks-ingress`; nginx proxies there, so the peer ingress sees is `web` on that
+    network, the one range it trusts. nginx writes the client it recovered into X-Forwarded-For, never a client's own,
+    and streams a body to ingress as it arrives (chunked ones too, over HTTP/1.1), so ingress's whole-body deadline and
+    its requests-in-flight limit hold through it (the owner's M4 review); its own gap timeout matches."""
+    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
+    assert rendered(compose["networks"]["hooks"]["ipam"]["config"][0]["subnet"]) == HOOKS_SUBNET
+    assert service("ingress")["networks"] == {"default": None, "hooks": {"aliases": ["hooks-ingress"]}}
+    assert service("web")["networks"] == ["default", "hooks"]
+    conf = NGINX.read_text()
+    hooks = conf[conf.index("location /hooks/") :].split("}", 1)[0]
+    assert "set $ingress http://hooks-ingress:8001;" in conf
+    assert "proxy_pass $ingress;" in hooks
+    assert "proxy_set_header X-Forwarded-For $remote_addr;" in hooks
+    assert "client_body_timeout 10s;" in hooks
+    assert "proxy_request_buffering off;" in hooks and "proxy_http_version 1.1;" in hooks
+
+
+def test_the_api_holds_the_ingress_key_only_when_one_is_set() -> None:
+    """The API seals endpoints' secrets under the ingress key: without one it writes none (503), and plain Compose
+    needs none."""
+    env = environment("api")
+    assert env["DEWPOINT_INGRESS_KEY_B64"] == "" and env["DEWPOINT_INGRESS_KEY_ID"] == "ingress-1"
+
+
+def test_ci_runs_the_ingress_profile_and_proves_a_webhook_through_nginx() -> None:
+    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
+    assert e2e["env"]["COMPOSE_PROFILES"] == "ingress"
+    steps = {step.get("name", ""): step for step in e2e["steps"]}
+    assert "DEWPOINT_INGRESS_KEY_B64=$(openssl rand -base64 32)" in steps["Write CI env"]["run"]
+    proof = steps["A webhook through nginx and ingress (engine 2b spec §8.3, §12)"]
+    assert proof["timeout-minutes"] == 5
+    assert "http://127.0.0.1:8080/hooks/$endpoint" in proof["run"]
+    assert "ci/ingress-proof.py" in proof["run"]
+    assert 'test "$trickled" = 408' in proof["run"]  # a slow body's deadline holds through nginx
diff --git a/backend/tests/deploy/test_compose_ingress_proof.py b/backend/tests/deploy/test_compose_ingress_proof.py
new file mode 100644
index 0000000..aaf90d9
--- /dev/null
+++ b/backend/tests/deploy/test_compose_ingress_proof.py
@@ -0,0 +1,72 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's ingress proof (engine 2b spec §8.3, §12; 2b-3b task 10): `deploy/compose/ci/ingress-proof.py` makes an HMAC
+endpoint and its binding to the seeded workflow, as the API's login, and prints the endpoint's id and its secret; CI
+posts a signed event through nginx to ingress, twice (the second a retry, acknowledged once); then the script waits for
+the event's run to succeed through the Compose dispatcher's matcher, the dispatcher and the worker. Here the posting
+goes through ingress's own app against the test database; CI does the same through the Compose stack."""
+
+import base64
+import hashlib
+import hmac
+import importlib.util
+import time
+from typing import Any
+
+import pytest
+
+from dewpoint.apps.dispatcher import matching
+from dewpoint.apps.dispatcher.dispatch import dispatch_once
+from dewpoint.apps.ingress.main import create_app as create_ingress
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.ingress.support import KEY_BYTES
+from tests.apps.ingress.support import client as ingress_client
+from tests.apps.ingress.support import settings as ingress_settings
+from tests.apps.test_admission import current
+from tests.apps.worker.harness import workers as engine_workers
+from tests.deploy.test_compose_seed import ROOT, seeding
+from tests.support.registry import sync_test_plugins
+
+PROOF = ROOT / "deploy" / "compose" / "ci" / "ingress-proof.py"
+
+
+def proving() -> Any:
+    spec = importlib.util.spec_from_file_location("ingress_proof", PROOF)
+    assert spec is not None and spec.loader is not None
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_the_ingress_proof_waits_for_the_webhooks_run_to_succeed(
+    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, pg_url
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)
+    tenant_id, workflow_id = await seeding().seed(api_settings)
+    settings = api_settings.model_copy(update={"ingress_key_b64": base64.b64encode(KEY_BYTES).decode()})
+    proof = proving()
+    endpoint_id, secret = await proof.create(settings, tenant_id, workflow_id)
+    assert await proof.state(settings, tenant_id, endpoint_id) == (None, None)
+    body, stamp = b'{"id":"ci-proof-1","type":"ci_proof"}', str(int(time.time()))
+    signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
+    headers = {"x-dewpoint-timestamp": stamp, "x-dewpoint-signature": signature, "content-type": "application/json"}
+    ingress = create_ingress(ingress_settings(pg_url))
+    async with ingress_client(ingress) as hooks:
+        assert (await hooks.post(f"/hooks/{endpoint_id}", content=body, headers=headers)).json()["accepted"] == 1
+        assert (await hooks.post(f"/hooks/{endpoint_id}", content=body, headers=headers)).json()["duplicates"] == 1
+    await ingress.state.engine.dispose()
+    assert await proof.state(settings, tenant_id, endpoint_id) == ("pending", None)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    assert await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified()) == {"matched": 1}
+    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
+        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
+            "started": 1
+        }
+        assert await proof.wait(settings, tenant_id, endpoint_id, 30)
diff --git a/deploy/compose/.env.example b/deploy/compose/.env.example
index 9782536..1f4b8f8 100644
--- a/deploy/compose/.env.example
+++ b/deploy/compose/.env.example
@@ -15,3 +15,8 @@ DEWPOINT_TEMPORAL_NAMESPACE=
 # IPs/CIDRs of the TLS proxy in front of `web`, space- or comma-separated. Leave empty without a proxy;
 # otherwise every client shares the proxy's per-IP rate limits.
 DEWPOINT_TRUSTED_PROXIES=
+# Webhook ingress (engine 2b spec §8.3; docs/operations/ingress.md), a development-only prototype until engine 2b-4:
+# started only with COMPOSE_PROFILES=ingress and the development override. The API seals endpoints' secrets with it.
+DEWPOINT_INGRESS_KEY_B64=     # openssl rand -base64 32
+# The network `web` reaches ingress on, the one range ingress believes X-Forwarded-For from (empty: 172.31.255.248/29).
+DEWPOINT_HOOKS_SUBNET=
diff --git a/deploy/compose/ci/ingress-proof.py b/deploy/compose/ci/ingress-proof.py
new file mode 100644
index 0000000..667de83
--- /dev/null
+++ b/deploy/compose/ci/ingress-proof.py
@@ -0,0 +1,91 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's ingress proof (engine 2b spec §8.3, §12; 2b-3b): an HMAC endpoint of the synthetic tenant `seed-workflow.py`
+made, its events' ids at `/id`, bound to the seeded workflow; CI posts a signed event through nginx to ingress; the
+Compose dispatcher matches it, starts it and the worker runs it. Run in the API's image, as the API's database login
+(which holds the ingress key and the KEK):
+
+    docker compose run --rm -T api python - create <tenant> <workflow> < ci/ingress-proof.py   # prints id and secret
+    docker compose run --rm -T api python - wait <tenant> <endpoint> <seconds> < ci/ingress-proof.py
+
+`create` prints the endpoint's id and its secret on its last line, for the caller's shell only. `wait` exits 0 once the
+endpoint's first event's run succeeded, and 1 when the time is up, printing only states. Nothing here is real data."""
+
+import asyncio
+import sys
+import uuid
+
+from sqlalchemy import text
+
+from dewpoint.apps import webhooks
+from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.crypto.ingress import IngressKey
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
+
+ENDPOINT = {
+    "name": "CI proof", "enabled": True, "auth": "hmac", "tolerance_s": 300, "allowlist": [], "body_limit": 1024 * 1024,
+    "id_source": "pointer", "id_pointer": "/id",
+}  # fmt: skip
+
+
+async def create(settings: Settings, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> tuple[uuid.UUID, str]:
+    """The endpoint's id and its secret: made by the tenant's owner, bound to the workflow."""
+    engine = make_engine(settings.database_url)
+    try:
+        sessionmaker = make_sessionmaker(engine)
+        async with sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant_id)
+            owner = (
+                await s.execute(text("select user_id from memberships where tenant_id = :t and role = 'owner'"),
+                                {"t": tenant_id})
+            ).scalar_one()  # fmt: skip
+            endpoint, secret = await webhooks.create_endpoint(
+                s, Keyring(KekSet.from_settings(settings)), IngressKey.from_settings(settings), tenant_id=tenant_id,
+                actor_id=owner, given=ENDPOINT,
+            )  # fmt: skip
+            await webhooks.create_binding(s, endpoint_id=endpoint.id, actor_id=owner, workflow_id=workflow_id,
+                                          filter=[], enabled=True)  # fmt: skip
+        return endpoint.id, secret
+    finally:
+        await engine.dispose()
+
+
+async def state(settings: Settings, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> tuple[str | None, str | None]:
+    """The endpoint's first event's status, and its request's state (its run's status once it started)."""
+    engine = make_engine(settings.database_url)
+    try:
+        async with make_sessionmaker(engine)() as s:
+            await tenant_scope(s, tenant_id)
+            found = (
+                await s.execute(
+                    text("select e.status, coalesce(r.status, q.status) from inbound_events e "
+                         "left join run_requests q on q.idempotency_key like 'evt:' || e.id || ':%' "
+                         "left join runs r on r.id = q.id and q.status = 'started' "
+                         "where e.endpoint_id = :e order by e.received_at limit 1"),
+                    {"e": endpoint_id},
+                )
+            ).first()  # fmt: skip
+        return (found[0], found[1]) if found else (None, None)
+    finally:
+        await engine.dispose()
+
+
+async def wait(settings: Settings, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, seconds: int) -> bool:
+    event, run = None, None
+    for _ in range(seconds):
+        event, run = await state(settings, tenant_id, endpoint_id)
+        if run in ("succeeded", "failed", "cancelled", "refused", "dead") or event in ("unmatched", "dead"):
+            break
+        await asyncio.sleep(1)
+    print(f"first event: {event}; its run: {run}")
+    return run == "succeeded"
+
+
+if __name__ == "__main__":
+    command, tenant, *rest = sys.argv[1:]
+    if command == "create":
+        endpoint_id, secret = asyncio.run(create(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0])))
+        print(endpoint_id, secret)
+    else:
+        sys.exit(0 if asyncio.run(wait(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]), int(rest[1]))) else 1)
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
index f991bb9..5bfd603 100644
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -59,6 +59,9 @@ services:
     environment:
       <<: *appenv
       DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint
+      # Webhook endpoints' secrets are sealed under it (engine 2b spec §8.3): without it, the API makes none (503).
+      DEWPOINT_INGRESS_KEY_B64: ${DEWPOINT_INGRESS_KEY_B64:-}
+      DEWPOINT_INGRESS_KEY_ID: ${DEWPOINT_INGRESS_KEY_ID:-ingress-1}
     depends_on: { migrate: { condition: service_completed_successfully } }
     healthcheck:
       test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready').status==200 else 1)"]
@@ -158,6 +161,30 @@ services:
       interval: 5s
       retries: 20
 
+  ingress:
+    <<: *app
+    # Webhook ingress (engine 2b spec §8.3; docs/operations/ingress.md): a gated prototype until engine 2b-4, so only
+    # the `ingress` profile starts it, and it refuses to start unless the deployment is `development` (the development
+    # override). Its environment is its own, never the KEK: it refuses to start with one. It publishes no port: `web`
+    # proxies /hooks/ to it on the `hooks` network.
+    profiles: [ingress]
+    command: ["dewpoint", "ingress", "--host", "0.0.0.0", "--port", "8001"]
+    environment:
+      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_ingress_login:${DEWPOINT_INGRESS_DB_PASSWORD}@postgres/dewpoint
+      DEWPOINT_INGRESS_KEY_B64: ${DEWPOINT_INGRESS_KEY_B64:-}
+      DEWPOINT_INGRESS_KEY_ID: ${DEWPOINT_INGRESS_KEY_ID:-ingress-1}
+      # X-Forwarded-For is believed from `web` only: the `hooks` network, where it's ingress's one peer (ruling 11).
+      DEWPOINT_INGRESS_TRUSTED_PROXIES: ${DEWPOINT_HOOKS_SUBNET:-172.31.255.248/29}
+    networks:
+      default:
+      hooks: { aliases: [hooks-ingress] }
+    depends_on: { migrate: { condition: service_completed_successfully } }
+    healthcheck:
+      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health/ready').status==200 else 1)"]
+      interval: 5s
+      retries: 20
+    restart: unless-stopped
+
   web:
     image: ${DEWPOINT_WEB_IMAGE:-dewpoint-web:dev}
     build: { context: ../.., dockerfile: deploy/docker/web.Dockerfile }
@@ -168,6 +195,13 @@ services:
     environment:
       # IPs/CIDRs of the TLS proxy / load balancer in front of `web` (see README). Empty = no proxy.
       DEWPOINT_TRUSTED_PROXIES: ${DEWPOINT_TRUSTED_PROXIES:-}
+    networks: [default, hooks]
     depends_on: { api: { condition: service_healthy } }
 
+networks:
+  # `web` and ingress only: ingress believes X-Forwarded-For from this range, where `web` is its only peer. Change it
+  # (DEWPOINT_HOOKS_SUBNET) if it overlaps a network of this host's.
+  hooks:
+    ipam: { config: [{ subnet: "${DEWPOINT_HOOKS_SUBNET:-172.31.255.248/29}" }] }
+
 volumes: { pgdata: {}, anchors: {}, cel-socket: {}, temporal-data: {} }
diff --git a/deploy/docker/nginx.conf b/deploy/docker/nginx.conf
index 191b667..7cbfbc2 100644
--- a/deploy/docker/nginx.conf
+++ b/deploy/docker/nginx.conf
@@ -9,6 +9,9 @@ server {
   # is restarted or redeployed (502 until web restarts). A variable in proxy_pass forces per-TTL resolution.
   resolver 127.0.0.11 valid=10s ipv6=off;
   set $api http://api:8000;
+  # Webhook ingress (engine 2b spec §8.3): only where the `ingress` profile runs it (a gated prototype until 2b-4);
+  # elsewhere /hooks/ answers 502. Reached on the `hooks` network, where ingress trusts `web` as its proxy.
+  set $ingress http://hooks-ingress:8001;
 
   location /api/ {
     proxy_pass $api;
@@ -16,6 +19,17 @@ server {
     proxy_set_header X-Forwarded-For $remote_addr;   # the recovered client IP; never forward client-supplied values
     proxy_set_header X-Forwarded-Proto $scheme;
   }
+  location /hooks/ {
+    proxy_pass $ingress;
+    # Each body streamed to ingress as it arrives (a chunked one too, which needs HTTP/1.1 upstream), never buffered
+    # here first: ingress's 10 s whole-body deadline and its limit on requests in flight then hold through nginx.
+    proxy_http_version 1.1;
+    proxy_request_buffering off;
+    proxy_set_header Host $host;
+    proxy_set_header X-Forwarded-For $remote_addr;   # the recovered client IP; never forward client-supplied values
+    proxy_set_header X-Forwarded-Proto $scheme;
+    client_body_timeout 10s;   # a gap between reads; the whole body's deadline is ingress's
+  }
   location /health/ { proxy_pass $api; }
   location /assets/ {
     include /etc/nginx/snippets/security-headers.conf;
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index 2d2c89e..b58fffc 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -240,6 +240,10 @@ docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
 
 It records `development` (`DEWPOINT_ENVIRONMENT`); CI sets `COMPOSE_FILE` to both files.
 
+Webhook ingress, a development-only prototype until engine 2b-4, runs only with the `ingress` profile
+(`COMPOSE_PROFILES=ingress`, as CI sets it) and the development override; it needs `DEWPOINT_INGRESS_KEY_B64` in
+`.env`, which the API holds too ([webhook ingress](ingress.md)).
+
 Compose runs one build at a time, so its worker makes its own build current as it starts
 (`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
 worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. When the new
diff --git a/docs/operations/ingress.md b/docs/operations/ingress.md
new file mode 100644
index 0000000..eec0444
--- /dev/null
+++ b/docs/operations/ingress.md
@@ -0,0 +1,205 @@
+# Webhook ingress: endpoints, events and their runs
+
+Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §8.3 (with §2.5, §6.4 and §10.5).
+
+A sender posts a webhook to `/hooks/<endpoint id>`. `dewpoint ingress` authenticates it, splits it into events and
+records each, sealed to its tenant; the dispatcher matches each event to the endpoint's bindings and admits one run
+request per matching workflow; the run starts as any other does ([runs](runs.md)).
+
+> **A development-only prototype.** Until engine sub-project 2b-4 adds key rotation, retention and erasure,
+> `dewpoint ingress` refuses to start unless the deployment's recorded environment is `development`, and its
+> database function records nothing otherwise. Nothing here is for production data.
+
+## Running it
+
+`dewpoint ingress` is its own process with its own database login, `dewpoint_ingress_login`
+([deployment](deployment.md#docker-compose-evaluation)), which has no table privilege: it resolves an endpoint and
+records events only through three database functions. Its settings come from its environment only, never a `.env`
+file:
+
+| Setting | |
+|---|---|
+| `DEWPOINT_DATABASE_URL` | the ingress login's |
+| `DEWPOINT_INGRESS_KEY_B64`, `DEWPOINT_INGRESS_KEY_ID` | the ingress key, 32 bytes (`openssl rand -base64 32`), which the API holds too |
+| `DEWPOINT_INGRESS_TRUSTED_PROXIES` | the proxies whose `X-Forwarded-For` it believes, as addresses or networks; none by default |
+
+It never holds a tenant's key: it refuses to start with `DEWPOINT_KEK_B64` (or `DEWPOINT_KEK_PREVIOUS_B64`) in its
+environment. It seals each event to the tenant's public key; only the dispatcher opens events.
+
+In Docker Compose it runs only with the `ingress` profile and the development override:
+
+```
+COMPOSE_PROFILES=ingress docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --wait
+```
+
+`web` (nginx) proxies `/hooks/` to it on a network of their own, `hooks` (`DEWPOINT_HOOKS_SUBNET`, by default
+`172.31.255.248/29`), the one range ingress believes `X-Forwarded-For` from. nginx writes the client it recovered into
+that header, never a client's own, and streams each body to ingress as it arrives (a chunked one too), so ingress's
+10 s whole-body deadline and its limit on requests in flight hold through it: a body trickled slower is a 408. Without
+the profile, `/hooks/` answers 502.
+
+### Behind a proxy
+
+An address is believed from `X-Forwarded-For` only when the request comes from a configured proxy, and only from the
+header's trusted end: right to left, past the proxies listed. Set `DEWPOINT_INGRESS_TRUSTED_PROXIES` to exactly the
+proxies in front of ingress; anything wider lets a client choose its address, which the allowlist and the failure limit
+below rely on. An IPv6 client is limited by its /64.
+
+## Endpoints
+
+With `trigger.manage` (editors and up), under `/api/v1/t/{tenant}`; read with `workflow.view`:
+
+| | |
+|---|---|
+| `POST /webhook-endpoints` | make one; answers 201 with its `path` and its `secret`, shown this once |
+| `GET /webhook-endpoints`, `GET /webhook-endpoints/{id}` | its settings and its counters, never a secret |
+| `PATCH /webhook-endpoints/{id}` | its name, `enabled`, allowlist, tolerance, body limit, events pointer, HMAC header names |
+| `POST /webhook-endpoints/{id}/secret` | a new secret, shown this once; deduplication carries on |
+
+How an endpoint authenticates and where its events' ids are never change: make another endpoint instead. The API needs
+the ingress key to make or rotate one (503 `ingress_key_missing` without it), and makes the tenant's inbound keypair if
+it has none.
+
+### Authentication
+
+- **HMAC** (`"auth": "hmac"`): the sender signs `<timestamp>.<the exact raw body>` with HMAC-SHA256 under the secret,
+  and sends the timestamp (Unix seconds) in `x-dewpoint-timestamp` and the hex signature (optionally prefixed
+  `sha256=`) in `x-dewpoint-signature` (both names configurable). A timestamp more than the tolerance (300 s by
+  default, 60 to 900) from ingress's clock is refused, which bounds a replay. Reformatting the body breaks the
+  signature: it's the bytes that are signed.
+- **Bearer** (the default): `Authorization: Bearer <token>`, the token high-entropy and made by Dewpoint; only its
+  SHA-256 digest is kept.
+
+Every failure before an attempt is recorded (an unknown or disabled endpoint, an address outside the allowlist, a bad
+signature, an `erasing` tenant) is the same bodiless 401.
+
+**Mist.** A Mist webhook signs only the body (`X-Mist-Signature-v2`, HMAC-SHA256 with no timestamp), so it can't use
+the HMAC scheme above. Juniper's documentation says an `http-post` webhook can carry custom headers (names and values
+together under 1,000 bytes) and names token-based authentication among their uses, so a bearer endpoint with the
+header `Authorization: Bearer <token>` should serve. **This is unverified**: the documentation doesn't say whether
+Mist allows the `Authorization` header name, and no real Mist delivery has confirmed it yet.
+
+### Events and their ids
+
+The body is one JSON object, or, with an events pointer (RFC 6901, such as `/events`), the array of objects there: 1 to
+500 events. A body is refused whole (400 `malformed`) for invalid UTF-8, a duplicate key anywhere, `NaN` or an infinity,
+a number past binary64's range, an escaped unpaired surrogate, an integer of more than 4,300 digits, nesting deeper than
+64 levels, or any event that isn't an object or lacks a valid id.
+
+Deduplication follows the endpoint's id source:
+- **`pointer`**: each event's own id at a JSON pointer (`id_pointer`), a string or an integer, typed (`1` and `"1"` are
+  two ids);
+- **`header`**: one id for the request, in a header (`id_header`), the item's index qualifying it;
+- **`none`**: no id, and **nothing is deduplicated**: a sender that retries after losing a 200 records its events
+  twice (at-least-once). Use `pointer` or `header` when that matters.
+
+A repeated id with the same content (compared as canonical JSON, so key order and spacing don't matter) is
+acknowledged and recorded once; with other content, the whole request is refused, 409 `event_id_reused`. Ids are never
+stored: only keyed digests of them.
+
+### Responses
+
+| Status | When |
+|---|---|
+| 200 `{"accepted": n, "duplicates": d}` | recorded, once committed |
+| 400 `malformed` | the body, as above |
+| 401, no body | any failure before recording |
+| 408 | the body took longer than 10 s |
+| 409 `event_id_reused` | an id reused for other content |
+| 413 `too_large` | past the endpoint's body limit (1 MiB by default, at most 5 MiB) or the global 5 MiB |
+| 429 `rate_limited`, `Retry-After` | short of a rate budget, or too many failures from this address |
+| 429 `quota_exceeded`, `Retry-After: 30` | the endpoint's or the tenant's pending backlog is full |
+| 429 `retained_full`, no `Retry-After` | the stored events are at their cap: nothing frees it before 2b-4 |
+| 503 | too many requests in flight (`busy`, `Retry-After`), outside a development deployment, the database unavailable, or the tenant without an inbound key |
+
+A refused attempt pays its rate budget as an accepted one does.
+
+## Bindings
+
+With `trigger.manage`: `POST /webhook-endpoints/{id}/bindings` `{"workflow_id": ..., "filter": [...], "enabled": true}`,
+`GET` the same path (with `workflow.view`), `PATCH` and `DELETE /webhook-bindings/{id}`. A binding names a workflow of
+the endpoint's tenant, once per endpoint, at most 20 per endpoint. Its filter is at most 8 clauses
+`{"pointer": "/type", "value": "ap_down"}`, every one of which must hold: typed equality on the event (a string, an
+integer, a boolean or null; never a float). No filter matches every event.
+
+Each matching binding admits one request, source `webhook`, key `evt:<event id>:<workflow id>`, the event as the
+run's trigger input (`trigger`), checked against the workflow's input schema like any input: an event the schema
+refuses is a `refused` request.
+
+## What becomes of an event
+
+The dispatcher matches events only while the production gate is on (always, in development), every tenant's oldest
+first. An event is then:
+
+- **`matched`**, with the number of requests it admitted, or **`unmatched`** when no binding's filter held;
+- **`dead`**, only when it can never be matched: its ciphertext fails under a keypair version proven on another event,
+  or its payload isn't a JSON object; or after 5 failed attempts, backing off from 30 s. Each death is audited and
+  alerted on (`inbound_event_dead`);
+- **`cancelled`**, by an admin.
+
+A failure that isn't the event's (a keypair version missing or not pairing with its public key, the tenant's data key
+unreadable) leaves it pending, retried after a minute, alerted on (`event_key_unavailable`), its attempts untouched. A
+dispatcher that stops before its commit leaves the event pending: matching is all or nothing.
+
+`GET /webhook-endpoints/{id}/events` (with `workflow.view`) lists an endpoint's events' metadata, never a payload; dead
+events only to admins. With `tenant.manage` (admins): `GET /inbound-events/dead`, `POST /inbound-events/{id}/cancel`
+(a pending or dead event) and `POST /webhook-endpoints/{id}/cancel-pending`, each audited. `GET /inbound-usage` shows
+the tenant's pending backlog and stored events against their quotas.
+
+## Limits
+
+Provisional (spec §15):
+
+| Limit | Value |
+|---|---|
+| Requests in flight, per ingress process | 32 (503 past it) |
+| Failed requests per address (an IPv6 /64) per minute, per process | 30 |
+| Global body cap; endpoint body limit; body deadline | 5 MiB; 1 MiB by default; 10 s |
+| Events per request | 500 |
+| Per endpoint: requests; events; bytes | 20/s, burst 100; 10/s, burst 1,000; 2 MiB/s, burst 10 MiB or more |
+| Per tenant: events; bytes | 10/s, burst 5,000; 10 MiB/s, burst 50 MiB |
+| Pending, per endpoint; per tenant | 10,000 events, 64 MiB; 50,000 events, 256 MiB |
+| Stored, per endpoint; per tenant | 100,000 events, 512 MiB; 250,000 events, 1 GiB |
+| Matcher | 50 events a cycle per dispatcher; 20 bindings per endpoint |
+
+The failure limit is each process's own, in a table of 65,536 addresses that drops the one that failed least recently
+when full: past that many failing addresses in a minute, it's best-effort.
+
+The event rates are set below what the dispatcher drains (below), for an endpoint and for a tenant alike: every match
+holds its tenant's counter row, so a tenant's endpoints are matched one at a time and together drain no faster than
+one does. The bursts are budgets for a spike, which the pending quotas then hold back. Those quotas are backpressure:
+past one, ingress answers 429 `quota_exceeded` and the sender retries later. They promise no throughput: matching
+drains what it can, and a sender faster than that is held back by the 429s, not served. These values are provisional,
+for development: they aren't a promise with a real Temporal or with more bindings than measured.
+
+### Measured
+
+`tests/probes/ingress_load.py` measures these, by hand and never in CI, each part on a disposable Postgres 16
+container (`PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.ingress_load <part>`, from `backend/`). On one
+development machine, **not production capacity**:
+
+- **drain** (one dispatcher's own loop: a cycle, then its one-second sleep, at most 50 events a cycle, not the leader,
+  with a Temporal that accepts each start at once): 23 events a second with one binding per event, 16.6 with three,
+  13.0 with five. A real Temporal, the leader's own work and more bindings only lower it;
+- **one tenant's endpoints together** (`tenant-drain`, each dispatcher a process of its own): four endpoints drained
+  23.8 events a second against one endpoint's 22.9, and 24.7 with two dispatchers; two tenants with two dispatchers,
+  25.6. **A second dispatcher adds almost nothing today**: both take the same candidates in the same order, and the
+  second waits for each endpoint's row the first holds, to find its event matched. Making matching scale with
+  dispatchers is a required decision of engine 2b-4, before production, after which this control is measured again;
+- **each limit on its own** (`buckets`, `quotas`), at its default: every rate bucket accepted what its burst and rate
+  allow over the time taken, within one call (an endpoint's events 1,029 of 1,030; its bytes 15.5 of 16.0 MiB; a
+  tenant's events 5,000 of 5,030, in calls of 100 events, so the 30 refilled never made a whole one; its bytes 76 of
+  80 MiB), each refusal naming its wait (1 s, and 8 to 10 s for a 100-event call on a tenant's 10/s); every pending
+  and retained quota refused exactly at its value (10,000 and 50,000 events, 64 and 256 MiB pending; 100,000 and
+  250,000 events, 512 MiB and 1 GiB stored), a pending one with `Retry-After: 30`, a stored one with none, and a
+  sender's retry was still acknowledged at each; a recording took about as long at a quota (22 to 41 ms for a
+  500-event or 4 MiB call) as on an empty endpoint;
+- a match transaction holds its endpoint's row about 16 ms (20 ms at the 95th percentile); recording on that endpoint
+  while it's matched back to back takes about 13 ms instead of 2;
+- one ingress process recorded 1 KiB events at about 160 a second one at a time (median 6 ms) and 540 to 600 a second
+  with 8 to 32 in flight (median 11 to 47 ms; the 95th percentile reached 164 ms at 32, its database pool's limit), in
+  about 155 MiB;
+- parsing and sealing run on its event loop: 0.3 ms for a 1 KiB event, about 150 ms for 500 events in 1 MiB (the
+  sealing, 0.3 ms an event, dominates), about 195 ms for 5 MiB of small numbers;
+- picking the candidates ranks every pending event: 6.5 ms at 10,000 pending, 61 ms at 200,000;
+- the failure limiter's 65,536 addresses take about 12.6 MiB.
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 9e9a0b7..944f8d6 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -10,8 +10,8 @@ never shown.
 
 A run starts as a **request**: the run API and `dewpoint dev run` admit it, in their own transaction, and
 `dewpoint dispatcher` starts it on Temporal within its tenant's slots. Nothing else starts a run: a CSV start and a
-schedule's tick are admitted the same way ([below](#starting-a-run-from-a-csv), [schedules](#schedules)); webhooks
-arrive with sub-project 2b-3b.
+schedule's tick are admitted the same way ([below](#starting-a-run-from-a-csv), [schedules](#schedules)), and so is a
+webhook's event, by the dispatcher ([webhook ingress](ingress.md)).
 
 ## Starting a run
```

**Checkpoint (milestone 4).** Focused: as milestone 3 (655 passed); the migrations as there (Task 9 changes only 0032's
defaults). The load probe and the slow-upload probe by hand (the evidence of Tasks 9 and 10). The owner held it three
times (milestone ruling 4) and approved it as a prototype checkpoint (2026-10-04), which doesn't claim the Compose proof
has passed CI: this branch's pull request runs it. Then the whole suite and the static checks once, and a fresh
whole-branch review.
