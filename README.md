# Dewpoint

Self-hosted, multi-tenant, no-code automation for Juniper Mist: visual workflows triggered by webhooks,
schedules or manual runs, with Mist API actions, notifications, ITSM integrations and AI agents.

**Status:** Foundations — sign-in (password + TOTP/passkeys), tenants and members, encrypted Mist connections,
tamper-evident audit log. Workflows arrive in the next milestone.

## Quick start (single host, evaluation)

Requirements: Docker with Compose v2.

```bash
cd deploy/compose
cp .env.example .env        # then fill every value (see the generation hints in the file)
set -a; . ./.env; set +a
docker compose up -d --build --wait
docker compose run --rm \
  -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint" \
  api dewpoint admin init --email admin@example.com
```

Open <http://localhost:8080>, sign in, and enroll a passkey or authenticator app (MFA is mandatory).

**Beyond localhost you must use HTTPS.** `__Host-` session cookies and WebAuthn require a secure origin: terminate TLS
in front of the `web` service and set `DEWPOINT_PUBLIC_ORIGIN=https://<host>` and `DEWPOINT_RP_ID=<host>`.
Also set `DEWPOINT_TRUSTED_PROXIES` to that proxy's IP or CIDR: nginx then takes the client address from
`X-Forwarded-For`, skipping only trusted hops. Without it, every user appears to come from the proxy and shares its
per-IP rate limits; without a proxy, leave it empty so clients cannot spoof their address.

## Keys

- `DEWPOINT_KEK_B64` — the key-encryption key (`openssl rand -base64 32`). Losing it makes stored secrets unreadable;
  keep it in a secret manager. Rotation: [`docs/operations/key-rotation.md`](docs/operations/key-rotation.md).
- `DEWPOINT_AUDIT_SIGNING_KEY_B64` — Ed25519 key that signs audit anchors.

## Node types and CEL profiles

Run `dewpoint plugins sync` with the `dewpoint_admin` database credentials on every deploy, before the new build
serves traffic. Deprecation, retirement and code removal:
[`docs/operations/plugin-lifecycle.md`](docs/operations/plugin-lifecycle.md).

CEL expressions that can't run inline go to the `cel-evaluator` service: no secrets, no network, one Unix socket
(Docker Compose; Kubernetes support comes with the Helm chart). Sizing, refusals and health:
[`docs/operations/cel-evaluator.md`](docs/operations/cel-evaluator.md).

## Runs

Runs are admitted through the run API (`POST /api/v1/t/{tenant}/workflows/{workflow}/runs`) or `dewpoint dev run`;
`dewpoint dispatcher` starts them within each tenant's slots, and `dewpoint worker` executes them on Temporal.
Settings, how a run ends, and this build's limits:
[`docs/operations/runs.md`](docs/operations/runs.md). Compose runs Temporal's dev server (Web UI at
<http://127.0.0.1:8233>), one worker and one dispatcher; rolling out a new build, and upgrading Compose:
[`docs/operations/deployment.md`](docs/operations/deployment.md).

## Audit integrity

The `audit-anchor` service writes signed chain heads every 15 minutes. **In production, anchors must live off this
host** (object storage with object lock, or your SIEM): an anchor file next to the database proves little.
The `audit-anchor` container exits nonzero if an anchor run fails, and its healthcheck (`dewpoint audit freshness
--max-age-minutes 30`) turns it `unhealthy` when audit rows older than 30 minutes have no anchor. Alert on both:
a stopped or unhealthy anchor job means new audit entries are not being protected.

The healthcheck measures anchors **recorded in the database**; it is a liveness check, not an integrity check. It
does not notice if the external anchor file or sink is deleted, unwritable or unreachable. In production, also
monitor the external sink itself and run `dewpoint audit verify` on a schedule (it exits nonzero on any mismatch or
missing anchor).

Verify at any time, as the auditor database role:

```bash
docker compose run --rm -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_auditor_login:${DEWPOINT_AUDITOR_DB_PASSWORD}@postgres/dewpoint" \
  -e DEWPOINT_AUDIT_ANCHOR_PATH=/anchors/anchors.jsonl audit-anchor dewpoint audit verify
```

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Architecture: [`docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md`](docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md).
Security reports: [`SECURITY.md`](SECURITY.md).

Licensed under the Apache License 2.0.
