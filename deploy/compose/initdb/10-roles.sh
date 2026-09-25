#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_pw="$DEWPOINT_API_DB_PASSWORD" -v admin_pw="$DEWPOINT_ADMIN_DB_PASSWORD" \
  -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_api') THEN CREATE ROLE dewpoint_api NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_admin') THEN CREATE ROLE dewpoint_admin NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
END $$;
CREATE ROLE dewpoint_api_login LOGIN PASSWORD :'api_pw' IN ROLE dewpoint_api;
CREATE ROLE dewpoint_admin_login LOGIN PASSWORD :'admin_pw' IN ROLE dewpoint_admin;
CREATE ROLE dewpoint_auditor_login LOGIN PASSWORD :'auditor_pw' IN ROLE dewpoint_auditor;
SQL
