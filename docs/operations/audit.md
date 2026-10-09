# The audit trail's anchors: setup and runbook

Spec: `docs/superpowers/specs/2026-09-29-engine-2b-design.md` §10.2, and D6 of the 2b-4 outline (#3). Status: the
sink, the verifier and the monitor are built and tested against an in-memory bucket; D6's proof on the pinned MinIO
and the acceptance on your own bucket are still to run. Audit pruning stays off in production until then.

The audit log is a hash chain per scope (the platform's, and each tenant's). Its heads are signed and written outside
the database, so a database rewritten by someone who controls it can't hide what it removed: the anchors don't move.
Production writes them to an S3 bucket with Object Lock in compliance mode; development may use a file
(`DEWPOINT_AUDIT_ANCHOR_PATH`).

## The bucket

- Object Lock enabled at creation, with a **default retention in compliance mode** of at least the audit retention plus
  the backup period: `DEWPOINT_AUDIT_RETENTION_DAYS` (400 unless set) + `DEWPOINT_BACKUP_RETENTION_DAYS` (35 unless
  set) = 435 days. `dewpoint audit verify` checks it against the settings in force and fails below them. Nobody,
  the bucket's owner included, can shorten a compliance-mode lock: choose the period before the first write.
- Anchors go under `<prefix>anchors/<scope>/<sequence>.json` (`DEWPOINT_AUDIT_S3_PREFIX`, `dewpoint/` unless set).
  Temporal's authorizer writes its records under `<prefix>temporal-authorizer/<day>/<id>.json` in the same bucket.
- Settings: `DEWPOINT_AUDIT_S3_BUCKET`, and for a server other than AWS, `DEWPOINT_AUDIT_S3_ENDPOINT_URL` and
  `DEWPOINT_AUDIT_S3_REGION`. Credentials come from the standard AWS settings (the environment, or a shared
  credentials file), never Dewpoint's own.

### Three credential sets, kept apart

| Who | May | Holds it |
|---|---|---|
| The anchor job (`dewpoint audit anchor`) | `s3:PutObject` under `<prefix>anchors/` only | the anchor host, with the signing key |
| The verifier and the monitor (`audit verify`, `audit monitor`) | list versions, read objects and their retention, read the bucket's lock configuration; nothing else | the monitor's host |
| Temporal's authorizer | `s3:PutObject` under `<prefix>temporal-authorizer/` only | the Temporal server |

None of them may delete or change a retention; the bucket's root or admin credentials stay with whoever owns the
bucket, used by no Dewpoint process.

## The anchor job

```bash
dewpoint audit anchor
```

Run it as the `dewpoint_auditor` database login, **off the database host**, every 15 minutes (a timer or cron). It
signs each scope's newest entry with `DEWPOINT_AUDIT_SIGNING_KEY_B64` (an Ed25519 key, raw 32 bytes, base64) and its id
`DEWPOINT_AUDIT_SIGNING_KEY_ID` (`audit-1` unless set), and writes one object per anchor, once: a retry after a crash
between the write and the database's record of it is refused as already there, so no second version appears. The
signing key and the put-only credentials live on that host and nowhere else.

## Verifying

```bash
dewpoint audit verify
```

With the verifier's credentials and the public keys alone (`DEWPOINT_AUDIT_PUBLIC_KEYS`, JSON: each key id with its
base64 raw public key), never the signing key. It reads every version and delete marker under the anchors' prefix,
across every page of the listing, and exits 1 on any of:

| It says | What happened | What to do |
|---|---|---|
| `…: deleted (a delete marker)` | someone deleted the anchor's key (the version itself is locked and still there) | treat as tampering: find who held delete rights; the locked version remains the record |
| `…: rewritten (n versions)` | something wrote the key again | the first version is the anchor of record; find the second writer |
| `…: not locked`, `…: not in compliance mode`, `…: kept until …` | a version the default retention didn't cover | check the bucket's configuration; it isn't the anchor job's doing |
| `the bucket's default retention, n days, is less than m` | the bucket keeps anchors shorter than the settings require | raise the default (new writes only) and review what was written meanwhile |
| `…: bad anchor signature`, `…: anchor signed with an unknown key` | a forged anchor, or a key id missing from `DEWPOINT_AUDIT_PUBLIC_KEYS` | add the retired key's id if it's yours; otherwise, tampering |
| `…: hash mismatch with external anchor`, `…: chain broken at seq n` | the database's audit log was changed after it was anchored | incident: the anchors are the evidence; restore from backup and compare |
| `…: checkpoint not among the external anchors` | the database records an anchor the bucket doesn't hold | an anchor withheld or written elsewhere: check the anchor job's bucket and prefix |
| `no external anchors found` | nothing anchored yet, or the wrong bucket or prefix | check the settings; a fresh deployment anchors on its first run |

## The monitor

```bash
dewpoint audit monitor --roster /etc/dewpoint/audit-roster.json --state /var/lib/dewpoint/audit-monitor.json
```

Object Lock protects an anchor once written, not the writing of the next one: a compromised database could drop a
scope, or stop its anchors. The monitor runs **on its own host, off the database's**, with the verifier's credentials
and the `dewpoint_auditor` login, and keeps two files there:

- **the roster,** which you maintain: each scope you expect and its anchor cadence,
  `{"default_cadence_minutes": 30, "scopes": {"platform": 15}}`. A tenant's new scope is adopted as it appears.
- **its state:** each scope's high-water mark, the newest anchor it has seen. Set it up once with `--init`; after that,
  a missing state file is an alert.

It runs verify, then prints one line per alert and exits 1 when there's any:

| Alert | Meaning |
|---|---|
| `ALERT audit_verify_failed: …` | verify's problem, as above |
| `ALERT audit_scope_missing <scope>: …` | a scope the roster names, or one seen before, is gone from the database |
| `ALERT audit_anchor_overdue <scope>: …` | the scope's oldest unanchored entry is older than its cadence: the anchor job stopped, or anchors are withheld |
| `ALERT audit_high_water_rolled_back <scope>: …` | the bucket's newest anchor is below the mark already seen; the mark stays, so the alert stays until explained |
| `ALERT audit_monitor_state_lost: …` | the state file is gone: restore it from the monitor's own backup, never re-`--init` without knowing why |

Run it every few minutes. Locally, its exit code and lines are the alert. **Before readiness,** its output goes to an
alert destination you choose and test, from a host independent of the database's.

## Rotating the signing key

1. Make a new key pair and give it a new id (`audit-2`).
2. Add the new public key to `DEWPOINT_AUDIT_PUBLIC_KEYS` wherever verify and the monitor run, **keeping the old one**:
   every anchor names the key that signed it, and old anchors stay signed by the old key.
3. On the anchor host, set `DEWPOINT_AUDIT_SIGNING_KEY_B64` and `DEWPOINT_AUDIT_SIGNING_KEY_ID` to the new pair.
4. Run `dewpoint audit verify`: it passes with both ids. Destroy the old private key; never remove its public key while
   anchors it signed are kept.

## Rotating the S3 credentials

Each credential set is replaced on its own host, the new one issued with the same rights before the old one is
revoked: the anchor job's (the anchor host), the verifier's (the monitor's host), the authorizer's (the Temporal
server, which reads them at startup: restart it). After each, run the job that uses them once (`audit anchor`,
`audit verify`, or a namespace change through Temporal's authorizer) and check it succeeded. A namespace change made
while the authorizer's credentials don't work is refused, not let through.
