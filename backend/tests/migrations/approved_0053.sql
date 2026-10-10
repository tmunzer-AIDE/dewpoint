-- Proposed literal statements for migration 0053: gate A, revision 3. Nothing here is approved or applied.
-- From run 2's accepted inventory: PostgreSQL 16.15, alembic 0052, database dewpoint. Functions are named schema-qualified.

-- ================= upgrade =================
-- Phase 0, checks only: each failure raises before any change, and nothing below runs.
--  0.1 guard: :expected_database (alembic -x, from DEWPOINT_EXPECTED_DATABASE; none given -> refuse)
--             = current_database();
--             to_regclass('public.alembic_version') and to_regclass('public.platform_settings') exist
--             (gate A rev 5: the table, not its row, which a fresh installation records after migrating);
--             (SELECT version_num FROM public.alembic_version) = '0052'      -- upgrade enters from 0052
--  0.2 drift: with search_path pinned to pg_catalog, pg_temp, snapshot.sql's `objects` and `grants`
--             sections, run on the target, equal EXPECTED_OBJECTS and EXPECTED_GRANTS (literals in the
--             migration, from the reference build) exactly, as sets; and `recovery_presence` is (0, 0).
--             Else raise, listing up to 20 missing or extra rows (inventory.md, section 4).
--  0.3 role:  no role named dewpoint_recovery exists, whatever its attributes or comment. One that does is
--             a collision: raise. There's no reuse path (inventory.md, section 3).

-- Phase 1, changes:
CREATE ROLE dewpoint_recovery NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE dewpoint_recovery IS 'dewpoint:recovery-group:created-by-0053';
CREATE SCHEMA recovery;
REVOKE ALL ON SCHEMA recovery FROM PUBLIC;
GRANT USAGE ON SCHEMA recovery TO dewpoint_recovery;

-- Functions: PUBLIC loses EXECUTE on all 44; 18 explicit grants replace the uses found.
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_admin;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_api;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_auditor;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_dispatch;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_retention;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_worker;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_admin;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_api;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_dispatch;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_retention;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_worker;
REVOKE EXECUTE ON FUNCTION public.armor(bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.armor(bytea,text[],text[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_admin;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_api;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_auditor;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_dispatch;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_ingress;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_retention;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_worker;
REVOKE EXECUTE ON FUNCTION public.audit_reject() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.crypt(text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.dearmor(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.decrypt(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.decrypt_iv(bytea,bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.digest(bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.digest(text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.encrypt(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.encrypt_iv(bytea,bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.gen_random_bytes(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.gen_salt(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.gen_salt(text,integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hmac(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hmac(text,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_armor_headers(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_key_id(bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.platform_settings_recorded_once() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.gen_random_uuid() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.runs_set_root() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.runs_tree_fixed() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.workflow_versions_immutable() FROM PUBLIC;

-- Schema public: PUBLIC's USAGE replaced; every service role but one already holds it explicitly.
REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO dewpoint_start_check;

-- TEMPORARY on this database (option A): the one current_database() exception, after the guard of 0.1.
-- No service role creates temporary tables, so none is granted it.
DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$;

-- Default privileges: functions created later BY THE ROLE RUNNING THIS MIGRATION start without PUBLIC
-- EXECUTE. It governs that role only, not other future owners (an extension update run by another role, an
-- administrator's own objects); the exhaustive privilege test is what catches those.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Languages (gate A revision 6, the owner's amendment): PUBLIC's USAGE on the trusted ones only. PostgreSQL refuses
-- GRANT and REVOKE on the untrusted c and internal; their inherited USAGE is a named, inert allow-list exception
-- (a function or DO block in an untrusted language needs a superuser whatever its ACL).
REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC;
REVOKE USAGE ON LANGUAGE sql FROM PUBLIC;

-- ================= downgrade =================
-- Phase 0, checks only:
--  0.1 guard: as the upgrade's, but (SELECT version_num FROM public.alembic_version) = '0053'  -- leaves 0053
--  0.2 drift: the rows this downgrade touches are exactly as the upgrade left them: EXPECTED_AFTER, a literal
--             derived from EXPECTED_OBJECTS/EXPECTED_GRANTS and the upgrade's statements. Else raise.
--  0.3 role:  dewpoint_recovery exists with NOT rolcanlogin NOT rolsuper NOT rolcreatedb NOT rolcreaterole NOT rolreplication NOT rolbypassrls,
--             its comment exactly 'dewpoint:recovery-group:created-by-0053', no members, and a member of nothing.
--             Else raise: a provisioned recovery login stops the downgrade (revoke it first).
-- Phase 1, changes (reverse order):
GRANT USAGE ON LANGUAGE sql TO PUBLIC;
GRANT USAGE ON LANGUAGE plpgsql TO PUBLIC;
ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
DO $$ BEGIN EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database()); END $$;
REVOKE USAGE ON SCHEMA public FROM dewpoint_start_check;
GRANT USAGE ON SCHEMA public TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.workflow_versions_immutable() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.runs_tree_fixed() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.runs_set_root() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.gen_random_uuid() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.platform_settings_recorded_once() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_key_id(bytea) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.pgp_armor_headers(text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.hmac(text,text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.hmac(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.gen_salt(text,integer) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.gen_salt(text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.gen_random_bytes(integer) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.encrypt_iv(bytea,bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.encrypt(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.digest(text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.digest(bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.decrypt_iv(bytea,bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.decrypt(bytea,bytea,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.dearmor(text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.crypt(text,text) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.audit_reject() TO PUBLIC;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_admin;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_api;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_auditor;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_dispatch;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_ingress;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_retention;
REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_worker;
GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.armor(bytea,text[],text[]) TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.armor(bytea) TO PUBLIC;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_admin;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_api;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_dispatch;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_retention;
REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_worker;
GRANT EXECUTE ON FUNCTION public.app_user_id() TO PUBLIC;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_admin;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_api;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_auditor;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_dispatch;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_retention;
REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_worker;
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO PUBLIC;
DROP SCHEMA recovery;
DROP ROLE dewpoint_recovery;  -- this migration's own role (0.3); it fails, and the downgrade with it, on any
                              -- dependent in any database
