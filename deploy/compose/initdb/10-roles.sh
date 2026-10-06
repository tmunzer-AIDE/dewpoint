#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_pw="$DEWPOINT_API_DB_PASSWORD" -v admin_pw="$DEWPOINT_ADMIN_DB_PASSWORD" \
  -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" -v worker_pw="$DEWPOINT_WORKER_DB_PASSWORD" \
  -v dispatch_pw="$DEWPOINT_DISPATCH_DB_PASSWORD" -v ingress_pw="$DEWPOINT_INGRESS_DB_PASSWORD" \
  -v retention_pw="$DEWPOINT_RETENTION_DB_PASSWORD" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_api') THEN CREATE ROLE dewpoint_api NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_admin') THEN CREATE ROLE dewpoint_admin NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_worker') THEN CREATE ROLE dewpoint_worker NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_dispatch') THEN CREATE ROLE dewpoint_dispatch NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_ingress') THEN CREATE ROLE dewpoint_ingress NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_retention') THEN CREATE ROLE dewpoint_retention NOLOGIN; END IF;
END $$;
CREATE ROLE dewpoint_api_login LOGIN PASSWORD :'api_pw' IN ROLE dewpoint_api;
CREATE ROLE dewpoint_admin_login LOGIN PASSWORD :'admin_pw' IN ROLE dewpoint_admin;
CREATE ROLE dewpoint_auditor_login LOGIN PASSWORD :'auditor_pw' IN ROLE dewpoint_auditor;
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD :'worker_pw' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD :'dispatch_pw' IN ROLE dewpoint_dispatch;
CREATE ROLE dewpoint_ingress_login LOGIN PASSWORD :'ingress_pw' IN ROLE dewpoint_ingress;
CREATE ROLE dewpoint_retention_login LOGIN PASSWORD :'retention_pw' IN ROLE dewpoint_retention;
SQL
