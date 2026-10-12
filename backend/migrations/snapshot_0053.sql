-- The normalized ACL snapshot (gate A, revision 3). One text, read by the reference inventory now, and embedded
-- verbatim in 0053 later for its drift check, so both compare the same thing.
--
-- Run in a session with `SET search_path = pg_catalog, pg_temp` (the caller sets it; every identity below is also
-- built explicitly from schema and object names, so neither depends on the session's search_path).
-- Normalized names: the role running it (current_user, the migration role) is written <migrator>; the current
-- database is <current>. An ACL's state is 'default' (NULL), 'empty' ({}) or 'explicit', so an object with no grants
-- still appears in `objects`; `grants` lists aclexplode's rows, with the hard-wired default exploded for a NULL ACL.
-- Sections are separated by `-- name: <section>` lines.

-- name: objects
WITH s AS (SELECT oid, nspname FROM pg_namespace
           WHERE nspname NOT IN ('pg_catalog', 'information_schema') AND nspname !~ '^pg_(toast|temp)'),
o AS (
  SELECT 'schema' AS kind, quote_ident(s.nspname) AS identity, n.nspowner AS owner, n.nspacl::text AS acl, '' AS detail
    FROM pg_namespace n JOIN s ON s.oid = n.oid
  UNION ALL
  SELECT 'relation:'::text || c.relkind::text, quote_ident(s.nspname) || '.' || quote_ident(c.relname), c.relowner, c.relacl::text, ''
    FROM pg_class c JOIN s ON s.oid = c.relnamespace WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  UNION ALL
  SELECT 'column', quote_ident(s.nspname) || '.' || quote_ident(c.relname) || '.' || quote_ident(a.attname), c.relowner,
         a.attacl::text, ''
    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN s ON s.oid = c.relnamespace
   WHERE a.attnum > 0 AND NOT a.attisdropped AND a.attacl IS NOT NULL
  UNION ALL
  SELECT 'function:'::text || p.prokind::text,
         quote_ident(s.nspname) || '.' || quote_ident(p.proname) || '(' || pg_get_function_identity_arguments(p.oid) || ')',
         p.proowner, p.proacl::text,
         CASE WHEN p.prosecdef THEN 'definer' ELSE 'invoker' END || coalesce(' extension=' || quote_ident(e.extname), '')
    FROM pg_proc p JOIN s ON s.oid = p.pronamespace
    LEFT JOIN pg_depend d ON d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
    LEFT JOIN pg_extension e ON e.oid = d.refobjid
  UNION ALL
  SELECT 'type:'::text || t.typtype::text, quote_ident(s.nspname) || '.' || quote_ident(t.typname), t.typowner, t.typacl::text, ''
    FROM pg_type t JOIN s ON s.oid = t.typnamespace
   WHERE t.typcategory <> 'A'
     AND (t.typrelid = 0 OR (SELECT c.relkind FROM pg_class c WHERE c.oid = t.typrelid) = 'c')
  UNION ALL
  SELECT 'language', quote_ident(l.lanname), l.lanowner, l.lanacl::text, '' FROM pg_language l
  UNION ALL
  SELECT 'fdw', quote_ident(w.fdwname), w.fdwowner, w.fdwacl::text, '' FROM pg_foreign_data_wrapper w
  UNION ALL
  SELECT 'server', quote_ident(v.srvname), v.srvowner, v.srvacl::text, '' FROM pg_foreign_server v
  UNION ALL
  SELECT 'large_object', m.oid::text, m.lomowner, m.lomacl::text, '' FROM pg_largeobject_metadata m
  UNION ALL
  SELECT 'database', '<current>', d.datdba, d.datacl::text, '' FROM pg_database d WHERE d.datname = current_database()
  UNION ALL
  SELECT 'default_acl',
         CASE WHEN d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user) THEN '<migrator>'
              ELSE quote_ident(pg_get_userbyid(d.defaclrole)) END
         || ':' || coalesce(quote_ident(n.nspname), '*') || ':' || d.defaclobjtype::text,
         d.defaclrole, d.defaclacl::text, ''
    FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
  UNION ALL
  SELECT 'extension', quote_ident(e.extname), e.extowner, NULL, e.extversion || ' schema=' || quote_ident(n.nspname)
    FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
)
SELECT kind, identity,
       CASE WHEN pg_get_userbyid(owner) = current_user THEN '<migrator>' ELSE pg_get_userbyid(owner) END AS owner,
       CASE WHEN kind = 'extension' THEN 'n/a' WHEN acl IS NULL THEN 'default' WHEN acl = '{}' THEN 'empty'
            ELSE 'explicit' END AS acl_state,
       detail
  FROM o ORDER BY 1, 2;

-- name: grants
WITH s AS (SELECT oid, nspname FROM pg_namespace
           WHERE nspname NOT IN ('pg_catalog', 'information_schema') AND nspname !~ '^pg_(toast|temp)'),
g AS (
  SELECT 'schema' AS kind, quote_ident(s.nspname) AS identity, a.*
    FROM pg_namespace n JOIN s ON s.oid = n.oid, aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a
  UNION ALL
  SELECT 'relation:'::text || c.relkind::text, quote_ident(s.nspname) || '.' || quote_ident(c.relname), a.*
    FROM pg_class c JOIN s ON s.oid = c.relnamespace,
         aclexplode(coalesce(c.relacl, acldefault((CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char",
                                                   c.relowner))) a
   WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  UNION ALL
  SELECT 'column', quote_ident(s.nspname) || '.' || quote_ident(c.relname) || '.' || quote_ident(att.attname), a.*
    FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid JOIN s ON s.oid = c.relnamespace,
         aclexplode(att.attacl) a
   WHERE att.attnum > 0 AND NOT att.attisdropped AND att.attacl IS NOT NULL
  UNION ALL
  SELECT 'function:'::text || p.prokind::text,
         quote_ident(s.nspname) || '.' || quote_ident(p.proname) || '(' || pg_get_function_identity_arguments(p.oid) || ')',
         a.*
    FROM pg_proc p JOIN s ON s.oid = p.pronamespace, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
  UNION ALL
  SELECT 'type:'::text || t.typtype::text, quote_ident(s.nspname) || '.' || quote_ident(t.typname), a.*
    FROM pg_type t JOIN s ON s.oid = t.typnamespace, aclexplode(coalesce(t.typacl, acldefault('T', t.typowner))) a
   WHERE t.typcategory <> 'A'
     AND (t.typrelid = 0 OR (SELECT c.relkind FROM pg_class c WHERE c.oid = t.typrelid) = 'c')
  UNION ALL
  SELECT 'language', quote_ident(l.lanname), a.*
    FROM pg_language l, aclexplode(coalesce(l.lanacl, acldefault('l', l.lanowner))) a
  UNION ALL
  SELECT 'fdw', quote_ident(w.fdwname), a.*
    FROM pg_foreign_data_wrapper w, aclexplode(coalesce(w.fdwacl, acldefault('F', w.fdwowner))) a
  UNION ALL
  SELECT 'server', quote_ident(v.srvname), a.*
    FROM pg_foreign_server v, aclexplode(coalesce(v.srvacl, acldefault('S', v.srvowner))) a
  UNION ALL
  SELECT 'large_object', m.oid::text, a.*
    FROM pg_largeobject_metadata m, aclexplode(coalesce(m.lomacl, acldefault('L', m.lomowner))) a
  UNION ALL
  SELECT 'database', '<current>', a.*
    FROM pg_database d, aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
   WHERE d.datname = current_database()
  UNION ALL
  SELECT 'default_acl',
         CASE WHEN d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user) THEN '<migrator>'
              ELSE quote_ident(pg_get_userbyid(d.defaclrole)) END
         || ':' || coalesce(quote_ident(n.nspname), '*') || ':' || d.defaclobjtype::text,
         a.*
    FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace, aclexplode(d.defaclacl) a
)
SELECT kind, identity, privilege_type,
       CASE grantee WHEN 0 THEN 'PUBLIC'
            ELSE CASE WHEN pg_get_userbyid(grantee) = current_user THEN '<migrator>' ELSE pg_get_userbyid(grantee) END
       END AS grantee,
       CASE WHEN pg_get_userbyid(grantor) = current_user THEN '<migrator>' ELSE pg_get_userbyid(grantor) END AS grantor,
       is_grantable
  FROM g ORDER BY 1, 2, 3, 4, 5;

-- name: recovery_presence
SELECT (SELECT count(*) FROM pg_roles WHERE rolname = 'dewpoint_recovery') AS role,
       (SELECT count(*) FROM pg_namespace WHERE nspname = 'recovery') AS schema;

-- name: roles
SELECT CASE WHEN rolname = current_user THEN '<migrator>' ELSE rolname END AS role, rolsuper, rolinherit,
       rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls, rolconnlimit,
       coalesce(rolvaliduntil::text, '') AS valid_until, coalesce(shobj_description(oid, 'pg_authid'), '') AS comment
  FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1;

-- name: memberships
SELECT CASE WHEN r.rolname = current_user THEN '<migrator>' ELSE r.rolname END AS role,
       CASE WHEN m.rolname = current_user THEN '<migrator>' ELSE m.rolname END AS member,
       CASE WHEN g.rolname = current_user THEN '<migrator>' ELSE coalesce(g.rolname, '') END AS grantor,
       am.admin_option, am.inherit_option, am.set_option
  FROM pg_auth_members am JOIN pg_roles r ON r.oid = am.roleid JOIN pg_roles m ON m.oid = am.member
  LEFT JOIN pg_roles g ON g.oid = am.grantor
 ORDER BY 1, 2, 3;

-- name: databases
SELECT CASE WHEN d.datname = current_database() THEN '<current>' ELSE quote_ident(d.datname) END AS database,
       CASE WHEN pg_get_userbyid(d.datdba) = current_user THEN '<migrator>' ELSE pg_get_userbyid(d.datdba) END AS owner,
       CASE WHEN d.datacl IS NULL THEN 'default' WHEN d.datacl::text = '{}' THEN 'empty' ELSE 'explicit' END AS acl_state,
       a.privilege_type,
       CASE a.grantee WHEN 0 THEN 'PUBLIC'
            ELSE CASE WHEN pg_get_userbyid(a.grantee) = current_user THEN '<migrator>' ELSE pg_get_userbyid(a.grantee) END
       END AS grantee,
       CASE WHEN pg_get_userbyid(a.grantor) = current_user THEN '<migrator>' ELSE pg_get_userbyid(a.grantor) END AS grantor,
       a.is_grantable
  FROM pg_database d LEFT JOIN LATERAL aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a ON true
 ORDER BY 1, 4, 5, 6;
