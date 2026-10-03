# SPDX-License-Identifier: Apache-2.0
"""disabling production runs (engine 2b spec §2.2, §2.4): the admin role turns the gate off, and only off

`disable_production_runs()` takes `dewpoint:production-gate` exclusively, so it waits for every starting transaction
holding it shared; once its caller commits, no request becomes `starting`. It returns whether the gate was on. No role
updates `platform_settings` itself: enabling is 2b-4's audited command, with its readiness checks."""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

DISABLE = """
CREATE FUNCTION disable_production_runs() RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE was boolean;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('dewpoint:production-gate', 0));
  SELECT production_runs INTO was FROM platform_settings WHERE id = 1 FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'the deployment''s environment is not recorded';
  END IF;
  UPDATE platform_settings SET production_runs = false WHERE id = 1;
  RETURN was;
END $$"""


def upgrade() -> None:
    op.execute(DISABLE)
    op.execute("REVOKE ALL ON FUNCTION disable_production_runs() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION disable_production_runs() TO dewpoint_admin")


def downgrade() -> None:
    op.execute("DROP FUNCTION disable_production_runs()")
