# SPDX-License-Identifier: Apache-2.0
"""An endpoint records the trigger it's for (4c-3a ruling 1): the key of a trigger type a synced plugin declares
(`mist.webhook`), its settings taken from that trigger when it's made; null for another sender. Like where its events
and their ids are (2b-4 ruling D10), it never changes: the API's role has no grant to update it, and still sets it on a
new endpoint (its INSERT is table-wide). A nullable column with no default: a catalog change, no rewrite.

Slot 0070 is 4c-3a's (the owner, 2026-10-11): it was 0054, which 2b-4b's work also names (its plan holds 0048-0063,
with room left after it). Slot numbers name ownership, not order, so it is chained after main's head when it was
written, 0045."""

import sqlalchemy as sa
from alembic import op

revision = "0070"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_endpoints", sa.Column("trigger_key", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_endpoints", "trigger_key")
