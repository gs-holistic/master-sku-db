-- G Pen Hub API (msku/hub_api.py). Additive only: nothing existing moves.

-- SKUs the Hub creates aren't in any sheet, so the importer mustn't push them to Tier 3 as "gone".
ALTER TABLE core.sku ADD COLUMN origin text NOT NULL DEFAULT 'import' CHECK (origin IN ('import', 'hub'));

-- Fields only the Hub writes. NULL means "not set by the Hub"; the API then shows what the sheets give.
CREATE TABLE core.sku_spec (
  sku_id          uuid PRIMARY KEY REFERENCES core.sku ON DELETE CASCADE,
  status          text CHECK (status IN ('draft', 'active', 'deprecated', 'obsolete')),
  notes           text,
  pack_size       int CHECK (pack_size >= 0),
  product_dims    text, product_weight  text,
  packaging_dims  text, packaged_weight text,
  case_pack       int CHECK (case_pack >= 0),
  case_dims       text, case_weight     text,
  pallet_qty      int CHECK (pallet_qty >= 0),
  pallet_dims     text, pallet_weight   text,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

-- A sheet-fed field the Hub has set. The importer keeps the Hub's value and, if the sheet says
-- something else, raises a conflict for Ken instead of overwriting it.
CREATE TABLE core.hub_lock (
  sku_id  uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  field   text NOT NULL,     -- name, brand, upc, msrp, wholesale, distro, distro_eu, distro_ca
  value   text,              -- NULL = the Hub cleared it
  set_by  text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (sku_id, field));

SELECT ops.track('core.sku_spec', 'sku_id'), ops.track('core.hub_lock', 'sku_id');

-- Which SKU an audit row is about, so "who changed this SKU last" and /changes are one index lookup.
ALTER TABLE ops.audit_log ADD COLUMN sku_key text GENERATED ALWAYS AS (
  CASE WHEN table_name = 'core.sku' THEN row_pk ELSE coalesce(after->>'sku_id', before->>'sku_id') END) STORED;
CREATE INDEX ON ops.audit_log (sku_key, id);
CREATE INDEX ON ops.audit_log (at);

-- The API's database login gets this role: SKU master data and the audit trail, never the cost schema.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'msku_hub_api') THEN CREATE ROLE msku_hub_api NOLOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA core, ops TO msku_hub_api;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO msku_hub_api;
GRANT INSERT, UPDATE ON core.sku, core.sku_spec, core.hub_lock, core.price TO msku_hub_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core TO msku_hub_api;
GRANT SELECT ON ops.audit_log TO msku_hub_api;
GRANT INSERT ON ops.audit_log TO msku_hub_api;
GRANT USAGE ON SEQUENCE ops.audit_log_id_seq TO msku_hub_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON core.sku_spec, core.hub_lock TO msku_editor;
