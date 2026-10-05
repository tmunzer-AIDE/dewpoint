# SPDX-License-Identifier: Apache-2.0
"""The API's role reads no ciphertext (engine 2b spec §8.3, §14; the owner's ruling on 2b-3b's final review): it keeps
SELECT on every column of inbound_events and tenant_event_keys but an event's sealed payload (`sealed`) and a keypair's
sealed private key (`private_sealed`), which only the dispatcher opens. Read-access hardening: the role still inserts
keypairs, and the API process holds the tenants' keyring."""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

READABLE = {  # every column but the ciphertext
    "inbound_events": (
        "id, tenant_id, endpoint_id, dedupe_key, content_digest, key_version, size_bytes, status, reason, attempts, "
        "next_attempt_at, request_count, received_at, ended_at"
    ),
    "tenant_event_keys": "tenant_id, version, public_key, created_at",
}


def upgrade() -> None:
    for table, columns in READABLE.items():
        op.execute(f"REVOKE SELECT ON {table} FROM dewpoint_api")
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO dewpoint_api")


def downgrade() -> None:
    for table, columns in READABLE.items():
        op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM dewpoint_api")
        op.execute(f"GRANT SELECT ON {table} TO dewpoint_api")
