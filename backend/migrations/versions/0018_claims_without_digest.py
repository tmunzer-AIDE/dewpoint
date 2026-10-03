# SPDX-License-Identifier: Apache-2.0
"""claims keep no digest of their value (#28; engine 2b spec §3.1, revision 7)

`content_hash` was an unkeyed SHA-256 of each claim's plaintext, sensitive claims included: anyone who could read the
claim tables could test guesses for a low-entropy secret offline. A rewrite of a claim's id is now checked by decrypting
the existing claim. Dropping the column removes the hashes from the live database only: a backup taken before this
migration still holds them, so it's handled as sensitive until it expires (docs/operations/deployment.md)."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("run_inputs_hash", "run_inputs")
    op.drop_constraint("step_outputs_hash", "step_outputs")
    op.drop_column("run_inputs", "content_hash")
    op.drop_column("step_outputs", "content_hash")


def downgrade() -> None:
    # The hashes can't be recomputed without the plaintext: the column comes back empty for every row (its check
    # passes on an empty value).
    op.add_column("step_outputs", sa.Column("content_hash", sa.LargeBinary))
    op.add_column("run_inputs", sa.Column("content_hash", sa.LargeBinary))
    op.create_check_constraint("step_outputs_hash", "step_outputs", "octet_length(content_hash) = 32")
    op.create_check_constraint("run_inputs_hash", "run_inputs", "octet_length(content_hash) = 32")
