# Key rotation

Dewpoint uses envelope encryption:

- **Data keys** (one per tenant, plus one platform key for user TOTP secrets) encrypt secrets such as Mist API tokens,
  every payload a tenant's runs exchange with Temporal, and the claims and secret indexes stored for its runs
  ([`deployment.md`](deployment.md#encrypted-payloads)). A tenant gets its key when it's created; `dewpoint keys
  ensure-tenants`, as a `dewpoint_admin` login, gives one to tenants created before (Compose's migrate step runs it).
- The **key-encryption key (KEK)** wraps every data key. It is supplied through `DEWPOINT_KEK_B64` (with its id in
  `DEWPOINT_KEK_ID`) and is never stored in the database.

Key commands run as a `dewpoint_admin` database login (`DEWPOINT_DATABASE_URL`).

## Rotating the KEK

**No phase may start before the previous one is fully rolled out to every process that reads secrets**
(`api`, workers, and any host running the CLI). Verify each rollout before moving on.

| Phase | Configuration on every process | Why |
|---|---|---|
| **A. Distribute** | `KEK=old` (current), `KEK_PREVIOUS=new` | Every process can *read* data wrapped by the new key before anyone *writes* with it. |
| **B. Switch** | `KEK=new` (current), `KEK_PREVIOUS=old` | New data keys are wrapped with `new`; old rows stay readable. |
| **C. Rewrap** | unchanged from B; run `dewpoint keys rewrap` | Moves every data key to `new`, in short committed batches. Re-run until it prints `rewrapped 0`. |
| **D. Retire** | `KEK=new` only | Only after `dewpoint keys status` shows no `old=` line **and** exits 0. |

In environment variables, "`KEK=x`" means `DEWPOINT_KEK_B64` + `DEWPOINT_KEK_ID`, and "`KEK_PREVIOUS=y`" means
`DEWPOINT_KEK_PREVIOUS_B64` + `DEWPOINT_KEK_PREVIOUS_ID`.

```bash
# generate the new key; ids must be unique and never reused
openssl rand -base64 32
dewpoint keys status                  # before: e.g. env-1=42
dewpoint keys rewrap --batch-size 100 # phase C
dewpoint keys status                  # after: env-2=42, exit 0 — now safe to retire env-1
```

`dewpoint keys status` exits **3** when any data key is wrapped by a KEK the current configuration lacks. That is
exactly the situation phase D must never create; treat it as an outage signal.

### Rollback

- During A or B: revert the configuration of all processes to the previous phase.
- After C: rollback means running phases A–C again in reverse (old key becomes "new").

## Rotating a data key

```bash
dewpoint keys rotate-dek --tenant <tenant-uuid>
dewpoint keys rotate-dek --platform
```

Existing ciphertext stays readable (old data-key versions are kept); new encryptions use the new version. A claim keeps
the version it was sealed with until `keys reencrypt` seals it again (below); a run tree's secret index is sealed again
with the current version each time it grows. This is independent of KEK rotation. Workers and the CLI cache a tenant's
key for up to 5 minutes, and never longer, even while the database doesn't answer, so their Temporal payloads switch to
the new version within that time. (The cost: a database outage longer than that fails the steps whose payloads need the
key, [`deployment.md`](deployment.md).)

### Re-encrypting and retiring an older version

An older version stays until nothing needs it. Two commands, as `dewpoint_admin`, take it there:

```bash
dewpoint keys reencrypt --tenant <tenant-uuid>   # or --all, or --platform; re-run until every count is 0
dewpoint keys retire --tenant <tenant-uuid> --version 1             # a dry run: every check, and why one fails
dewpoint keys retire --tenant <tenant-uuid> --version 1 --confirm   # deletes it, audited, only if all pass
```

Run `keys reencrypt` once 5 minutes have passed since the rotation: until then, processes still seal with the older
version, and what they seal is left for a later run (`keys retire` won't pass its `records` check meanwhile). It
seals every record stored under an older version again under the active one: claims, envelopes and
CSV records, step outputs, secret indexes, staged uploads, saved CSV mappings, schedule inputs, connection secrets and
the inbound keypairs' private keys (`--platform`: users' TOTP secrets). The command keeps each record's plaintext,
purpose and context, and leaves a record the application rewrote meanwhile as it is. This is the command's behaviour,
not a guarantee from the database: the key admin's grants let it rewrite these columns, and can't check what it
writes. A schedule's Temporal action is sealed by the
dispatcher's sync, which records the version its action's payload names; `reencrypt` queues every schedule whose
recorded version isn't the active one, and the sync seals it again within a cycle or two.

`keys retire` deletes a version only when every check passes:

| Check | Passes when |
|---|---|
| `not_active` | it isn't the active version |
| `payload_floor` | its successor's creation + 5 minutes (the key cache) + twice the longest maximum run duration ever recorded + the Temporal namespace's retention has passed |
| `open_runs` | no run that started before its successor reached every cache is still running |
| `records` | no stored record names it (`reencrypt` is done) |
| `digests` | no request's or upload's idempotency digest was made with it: digests can't be re-encrypted, so these wait for retention |
| `schedule_actions` | every live schedule's Temporal action is synced under the active version, and every deleted schedule's absence settled |

The longest maximum run duration is what the dispatcher records as it starts (`DEWPOINT_MAX_RUN_DURATION_DAYS`, kept
for good: a later, shorter setting never lowers it); the namespace's retention is read from Temporal. Either one
unknown fails the floor: nothing retires on a guess. Exit codes: 1 when a dry run finds a check failing, 4 when
`--confirm` does. A platform key version (users' TOTP secrets, never a payload) checks `not_active` and `records`
only.

## Rotating a tenant's inbound keypair

Webhook events are sealed to the tenant's X25519 keypair ([webhook ingress](ingress.md)), its private key sealed
under the tenant's data key (so `keys reencrypt` re-wraps it).

```bash
dewpoint keys rotate-event-key --tenant <tenant-uuid>   # the next version: new events are sealed to it
dewpoint keys retire-event-keys --all                   # older versions no stored event names
```

An older keypair is retired only once no stored event names it (retention deletes ended events past the tenant's
cutoff), and only after a newer one has existed for a 10-minute settling period. The newest is never retired. Ingress
reads the newest public key for each delivery once it has the body, and nothing bounds the rest of the request, so the
settling period only makes a refusal rare; it isn't the safety mechanism. Recording and retiring take the same
database lock, so no stored event names a keypair that's gone:
- an event being recorded keeps its keypair, because the retirement waits for it and then finds it;
- an event sealed to a keypair that a retirement removed is refused with a retryable 503 `key_retired`
  (`Retry-After: 1`), and nothing is stored; the sender's retry is sealed to the newest keypair.

## Rotating the ingress key

The ingress key seals endpoints' HMAC and dedupe secrets; ingress and the API hold it. Its rollout follows the KEK's,
with `DEWPOINT_INGRESS_KEY_B64`/`_ID` and `DEWPOINT_INGRESS_KEY_PREVIOUS_B64`/`_ID` on both:

| Phase | Configuration on ingress and the API | |
|---|---|---|
| **A. Distribute** | current old, previous new | every process opens secrets sealed under the new key |
| **B. Switch** | current new, previous old | new secrets are sealed under the new key |
| **C. Reseal** | unchanged; `dewpoint keys reseal-ingress` (as `dewpoint_admin`, with the same two keys) | every endpoint's secrets sealed again under the new key, the command keeping their plaintext: signatures still verify and deduplication carries on; re-run until it reports 0 |
| **D. Retire** | current new only | only after `dewpoint keys ingress-status` shows no old id **and** exits 0 |

`keys ingress-status` exits 3 while any secret is sealed under a key the configuration lacks.

## Backups

A database backup is only restorable with the KEKs that wrapped its rows **at backup time**. Keep retired KEKs in
escrow (your secret manager) for at least the backup retention period.
