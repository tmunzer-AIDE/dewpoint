# Key rotation

Dewpoint uses envelope encryption:

- **Data keys** (one per tenant, plus one platform key for user TOTP secrets) encrypt secrets such as Mist API tokens.
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

Existing ciphertext stays readable (old data-key versions are kept); new encryptions use the new version. This is
independent of KEK rotation.

## Backups

A database backup is only restorable with the KEKs that wrapped its rows **at backup time**. Keep retired KEKs in
escrow (your secret manager) for at least the backup retention period.
