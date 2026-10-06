# SPDX-License-Identifier: Apache-2.0
"""Where an endpoint's events are is fixed when it's made (engine 2b-4 ruling D10): an events pointer decides how a
delivery splits into events, so changing it would change how later deliveries are deduplicated against earlier ones.
The API's role loses its grant to update `events_pointer`, as it has none for where the events' ids are; it still
sets it on a new endpoint."""

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE (events_pointer) ON webhook_endpoints FROM dewpoint_api")


def downgrade() -> None:
    op.execute("GRANT UPDATE (events_pointer) ON webhook_endpoints TO dewpoint_api")
