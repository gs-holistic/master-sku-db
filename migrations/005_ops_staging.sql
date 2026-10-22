CREATE TABLE ops.import_run (
  id bigserial PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  dry_run boolean NOT NULL, actor text NOT NULL,
  sources jsonb NOT NULL DEFAULT '[]', stats jsonb NOT NULL DEFAULT '{}');

-- Raw rows exactly as read, with sheet / tab / row on every record.
CREATE TABLE staging.raw_row (
  import_run_id bigint NOT NULL REFERENCES ops.import_run ON DELETE CASCADE,
  spreadsheet_id text NOT NULL, spreadsheet text NOT NULL, tab text NOT NULL, row_num int NOT NULL,
  data jsonb NOT NULL,
  PRIMARY KEY (import_run_id, spreadsheet_id, tab, row_num));

CREATE TABLE ops.exclusion (
  code text PRIMARY KEY, reason text NOT NULL, seen_in text[] NOT NULL,
  first_seen date NOT NULL DEFAULT current_date, last_seen date NOT NULL DEFAULT current_date);

-- A conflict is identified by its fingerprint (sku + field). values_hash changes if any source changes.
CREATE TABLE ops.conflict (
  fingerprint text PRIMARY KEY,
  sku_code text NOT NULL, kind text NOT NULL, detail text NOT NULL,
  candidates jsonb NOT NULL, values_hash text NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','reopened','cleared')),  -- cleared = sources now agree
  first_seen date NOT NULL DEFAULT current_date, last_seen date NOT NULL DEFAULT current_date,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

-- Ken's decisions, remembered across imports. If the sources change, the conflict reopens.
CREATE TABLE ops.conflict_resolution (
  fingerprint text PRIMARY KEY REFERENCES ops.conflict ON DELETE CASCADE,
  chosen_value text NOT NULL, chosen_source text, note text,
  values_hash text NOT NULL, decided_by text NOT NULL, decided_at timestamptz NOT NULL DEFAULT now());

SELECT ops.track('ops.conflict','fingerprint');
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO msku_editor;
GRANT INSERT, UPDATE ON ops.conflict_resolution TO msku_editor;
