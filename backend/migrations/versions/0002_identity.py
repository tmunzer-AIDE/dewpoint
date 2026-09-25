# SPDX-License-Identifier: Apache-2.0
"""identity: users, MFA, passkeys, sessions, throttle"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = [
    "users",
    "user_mfa",
    "recovery_codes",
    "webauthn_credentials",
    "sessions",
    "auth_throttle",
    "webauthn_challenges",
]


def _uuid_pk() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _user_fk(nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_platform_admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "user_mfa",
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("totp_secret_ct", sa.LargeBinary),
        sa.Column("totp_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("last_totp_step", sa.Integer),
        # A new secret awaiting confirmation; the confirmed factor above stays in force until it verifies.
        sa.Column("totp_pending_ct", sa.LargeBinary),
        sa.Column("totp_pending_expires_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "recovery_codes",
        _uuid_pk(),
        _user_fk(),
        sa.Column("code_hash", sa.Text, nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "webauthn_credentials",
        _uuid_pk(),
        _user_fk(),
        sa.Column("credential_id", sa.LargeBinary, nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary, nullable=False),
        sa.Column("sign_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transports", pg.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "sessions",
        _uuid_pk(),
        sa.Column("token_hash", sa.LargeBinary, nullable=False, unique=True),
        _user_fk(),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("auth_methods", pg.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("reauth_at", sa.DateTime(timezone=True)),  # last time this session proved a second factor
        sa.Column("ip", pg.INET),
        sa.Column("user_agent", sa.String(400)),
    )
    op.create_index("ix_sessions_user", "sessions", ["user_id"])
    op.create_table(
        "auth_throttle",
        sa.Column("kind", sa.String(20), primary_key=True),
        sa.Column("key", sa.String(320), primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "webauthn_challenges",
        _uuid_pk(),
        sa.Column("challenge", sa.LargeBinary, nullable=False),
        _user_fk(nullable=True),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webauthn_challenges_expires", "webauthn_challenges", ["expires_at"])
    op.create_index("ix_auth_throttle_window", "auth_throttle", ["window_start"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO dewpoint_api, dewpoint_admin")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
