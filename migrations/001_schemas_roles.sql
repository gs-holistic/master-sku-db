-- Schemas and roles. Roles are NOLOGIN groups; real logins are granted membership.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS core;     -- master data
CREATE SCHEMA IF NOT EXISTS cost;     -- confidential costs (cost_reader only)
CREATE SCHEMA IF NOT EXISTS staging;  -- raw imported rows
CREATE SCHEMA IF NOT EXISTS ops;      -- import runs, conflicts, exclusions, audit
CREATE SCHEMA IF NOT EXISTS api;      -- read-only views for other systems

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'msku_api_reader') THEN CREATE ROLE msku_api_reader NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'msku_editor')     THEN CREATE ROLE msku_editor NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'msku_cost_reader') THEN CREATE ROLE msku_cost_reader NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'msku_cost_editor') THEN CREATE ROLE msku_cost_editor NOLOGIN; END IF;
END $$;

REVOKE ALL ON SCHEMA cost FROM PUBLIC;
REVOKE ALL ON SCHEMA core, staging, ops FROM PUBLIC;
GRANT USAGE ON SCHEMA api TO msku_api_reader;
GRANT USAGE ON SCHEMA core, ops TO msku_editor;
GRANT USAGE ON SCHEMA cost TO msku_cost_reader, msku_cost_editor;
GRANT msku_cost_reader TO msku_cost_editor;
