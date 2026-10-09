# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4: a namespace boundary recorded through the platform admin's API (a provisional slot, on the
lineage-reconciliation list with 0049 and 0050).

The owner's ruling on the M4 design: the local namespace boundary (D3g) is recorded in M4 through the D11
platform-admin path, tied to the actual proof and to the server's and the namespace's identity; production's only
after real-target qualification. So `namespace_boundaries` gets what each row rests on: the namespace's name and
Temporal's id for it, the server binary's SHA-256, the D12 proof record's SHA-256, the attestation and the platform
admin who recorded it (all null on any row from before, which none of 0040's paths wrote). The API's role writes it
only through `record_namespace_boundary()`, which refuses a deployment whose environment isn't recorded (DPN01), any
but a development deployment (DPN02: production's boundary waits for real-target qualification), a namespace other than
the recorded one (DPN03) and evidence that isn't whole (DPN04). The key admin's role loses 0040's insert (the review's
I4: a direct insert would skip every refusal and the platform admin's second factor) and keeps reading the table and
marking a boundary lost (`lost_at`). The API's role lists them through `namespace_boundaries_listed()`, no grant on
the table. Adding nullable columns and functions: no table rewrite, no long lock (D15)."""

from alembic import op

from migrations.online import exists, grants, online, step, ungranted

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

COLUMNS = ("namespace text", "namespace_id text", "server_build text", "proof_digest text", "attestation text",
           "recorded_by uuid")  # fmt: skip
SIGNATURE = "record_namespace_boundary(text, text, text, text, text, text, uuid)"
RECORD = [  # the API's, for a platform admin (D11): the CLI asks the API
    """CREATE FUNCTION record_namespace_boundary(p_name text, p_namespace text, p_namespace_id text,
    p_server_build text, p_proof_digest text, p_attestation text, p_actor uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    p platform_settings%ROWTYPE;
    v_id bigint;
BEGIN
    SELECT * INTO p FROM platform_settings WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the deployment''s environment is not recorded' USING ERRCODE = 'DPN01';
    END IF;
    IF p.environment <> 'development' THEN
        RAISE EXCEPTION 'a production boundary is recorded only after real-target qualification'
            USING ERRCODE = 'DPN02';
    END IF;
    IF p_namespace IS DISTINCT FROM p.temporal_namespace THEN
        RAISE EXCEPTION 'not the deployment''s recorded namespace' USING ERRCODE = 'DPN03';
    END IF;
    IF coalesce(btrim(p_name), '') = '' OR coalesce(btrim(p_namespace_id), '') = ''
        OR coalesce(btrim(p_attestation), '') = '' OR p_actor IS NULL
        OR coalesce(p_server_build, '') !~ '^sha256:[0-9a-f]{64}$'
        OR coalesce(p_proof_digest, '') !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'a boundary needs its name, the namespace''s id, the server''s and the proof''s SHA-256, '
            'an attestation and its admin' USING ERRCODE = 'DPN04';
    END IF;
    INSERT INTO namespace_boundaries (name, namespace, namespace_id, server_build, proof_digest, attestation,
                                      recorded_by)
    VALUES (p_name, p_namespace, p_namespace_id, p_server_build, p_proof_digest, p_attestation, p_actor)
    RETURNING id INTO v_id;
    RETURN v_id;
END
$$""",
    f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO dewpoint_api",
    # what the admin's GET shows, newest first: through a function, not a grant on the table (the owner's M3 ruling:
    # no broadening of the API's role)
    """CREATE FUNCTION namespace_boundaries_listed() RETURNS TABLE (id bigint, name text, verified_at timestamptz,
    lost_at timestamptz, namespace text, namespace_id text, server_build text, proof_digest text, recorded_by uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT b.id, b.name, b.verified_at, b.lost_at, b.namespace, b.namespace_id, b.server_build, b.proof_digest,
         b.recorded_by
  FROM namespace_boundaries b ORDER BY b.id DESC
$$""",
    "REVOKE ALL ON FUNCTION namespace_boundaries_listed() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION namespace_boundaries_listed() TO dewpoint_api",
]


REVOKED = [  # 0040's, kept: SELECT and UPDATE (lost_at)
    "REVOKE INSERT ON namespace_boundaries FROM dewpoint_admin",
    "REVOKE USAGE ON SEQUENCE namespace_boundaries_id_seq FROM dewpoint_admin",
]


def upgrade() -> None:
    with online() as conn:
        added = f"ALTER TABLE namespace_boundaries {', '.join(f'ADD COLUMN {c}' for c in COLUMNS)}"
        step(conn, "0051 a boundary's evidence", added, done=exists("column", "recorded_by", "namespace_boundaries"))
        step(conn, "0051 record_namespace_boundary", *ungranted(*RECORD),
             done=exists("function", "namespace_boundaries_listed()"))  # fmt: skip
        step(conn, "0051 the admin's insert revoked", *REVOKED)
        step(conn, "0051 grants", *grants(*RECORD))


def downgrade() -> None:
    op.execute("GRANT INSERT ON namespace_boundaries TO dewpoint_admin")
    op.execute("GRANT USAGE ON SEQUENCE namespace_boundaries_id_seq TO dewpoint_admin")
    op.execute("DROP FUNCTION namespace_boundaries_listed()")
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(f"ALTER TABLE namespace_boundaries {', '.join(f'DROP COLUMN {c.split()[0]}' for c in COLUMNS)}")
