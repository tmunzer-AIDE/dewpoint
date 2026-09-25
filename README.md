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

## Keys

- `DEWPOINT_KEK_B64` — the key-encryption key (`openssl rand -base64 32`). Losing it makes stored secrets unreadable;
  keep it in a secret manager. Rotation: [`docs/operations/key-rotation.md`](docs/operations/key-rotation.md).
- `DEWPOINT_AUDIT_SIGNING_KEY_B64` — Ed25519 key that signs audit anchors.

## Audit integrity

The `audit-anchor` service writes signed chain heads every 15 minutes. **In production, anchors must live off this
host** (object storage with object lock, or your SIEM): an anchor file next to the database proves little.
Verify at any time, as the auditor database role:

```bash
docker compose run --rm -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_auditor_login:${DEWPOINT_AUDITOR_DB_PASSWORD}@postgres/dewpoint" \
  -e DEWPOINT_AUDIT_ANCHOR_PATH=/anchors/anchors.jsonl audit-anchor dewpoint audit verify
```

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Architecture: [`docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md`](docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md).
Security reports: [`SECURITY.md`](SECURITY.md).

Licensed under the Apache License 2.0.
