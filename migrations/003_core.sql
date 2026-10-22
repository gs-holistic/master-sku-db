-- Master data. Every table has updated_at + version so consumers can sync changes.
CREATE TYPE core.pack_type AS ENUM ('single_unit','inner_pack','pop_display','master_case','multi_pack','kit');
CREATE TYPE core.region    AS ENUM ('US','CA','EU');
CREATE TYPE core.price_tier AS ENUM ('msrp','wholesale','distribution','retail');
CREATE TYPE core.pack_level AS ENUM ('unit','inner_pack','master_case','pallet');

CREATE TABLE core.brand (
  id serial PRIMARY KEY, name text NOT NULL UNIQUE,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

CREATE TABLE core.family (
  id serial PRIMARY KEY, brand_id int REFERENCES core.brand, name text NOT NULL,
  help_url text, asset_portal_url text,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  UNIQUE (brand_id, name));

CREATE TABLE core.producer (
  id serial PRIMARY KEY, name text NOT NULL UNIQUE,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

CREATE TABLE core.sku (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- stable ID for other systems
  code              text NOT NULL UNIQUE,
  name              text,
  brand_id          int REFERENCES core.brand,
  family_id         int REFERENCES core.family,
  category          text,
  product_class     text,
  variant_code      text,                 -- brand & colour code, e.g. STBK
  pack_type         core.pack_type NOT NULL DEFAULT 'single_unit',
  pack_qty          int,
  base_sku_id       uuid REFERENCES core.sku,  -- pack -> its single unit
  upc               text,
  hts_code          text,
  country_of_origin text,
  producer_id       int REFERENCES core.producer,
  is_new            boolean NOT NULL DEFAULT false,
  code_check        text,                 -- NULL = matches our conventions, else why not
  master_active     text,                 -- master sheet "Active" column, reference only
  updated_at        timestamptz NOT NULL DEFAULT now(),
  version           int NOT NULL DEFAULT 1);

CREATE TABLE core.sku_tier (
  sku_id     uuid PRIMARY KEY REFERENCES core.sku ON DELETE CASCADE,
  tier       smallint NOT NULL CHECK (tier IN (1,2,3)),
  since      date NOT NULL,
  reason     text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

CREATE TABLE core.sku_tier_history (
  id bigserial PRIMARY KEY,
  sku_id uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  old_tier smallint, new_tier smallint NOT NULL,
  effective_date date NOT NULL, reason text NOT NULL, import_run_id bigint,
  recorded_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE core.sku_packaging_level (
  sku_id          uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  level           core.pack_level NOT NULL,
  length_mm numeric, width_mm numeric, height_mm numeric, weight_g numeric,
  units_per_level int,
  raw             jsonb NOT NULL DEFAULT '{}',   -- original text, e.g. {"weight": "15.7 Kg"}
  source          text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (sku_id, level));

-- Prices are effective-dated: a change closes the old row (effective_to) and inserts a new one.
CREATE TABLE core.price (
  id bigserial PRIMARY KEY,
  sku_id uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  region core.region NOT NULL, tier core.price_tier NOT NULL,
  currency char(3) NOT NULL, amount numeric(12,2) NOT NULL,
  effective_from date NOT NULL, effective_to date,
  source text NOT NULL, source_ref text,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX price_one_current ON core.price (sku_id, region, tier) WHERE effective_to IS NULL;

CREATE TABLE core.sku_component (            -- what's inside a POP display / kit
  parent_sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  child_sku_id  uuid REFERENCES core.sku ON DELETE CASCADE,
  qty int NOT NULL CHECK (qty > 0),
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (parent_sku_id, child_sku_id));

CREATE TABLE core.sku_compatibility (         -- accessory / part fits device or family
  sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  fits_family_id int REFERENCES core.family,
  fits_sku_id uuid REFERENCES core.sku,
  note text,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  CHECK (fits_family_id IS NOT NULL OR fits_sku_id IS NOT NULL));

CREATE TABLE core.collateral_link (           -- marketing collateral SKU <-> family
  collateral_sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  family_id int REFERENCES core.family,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (collateral_sku_id, family_id));

CREATE TABLE core.sku_supply (
  sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  producer_id int REFERENCES core.producer,
  moq int, lead_time_days int,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (sku_id, producer_id));

CREATE TABLE core.sku_link (
  sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  kind text NOT NULL,            -- store_page, asset_portal, manual, packaging_files, die_line, barcode_file
  url text NOT NULL, source text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (sku_id, kind, url));

CREATE TABLE core.external_id (
  sku_id uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  system text NOT NULL,          -- cin7, shopify_product, shopify_variant, gnln, mpn, asset_portal
  external_key text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1,
  PRIMARY KEY (sku_id, system, external_key));
CREATE INDEX ON core.external_id (system, external_key);

CREATE TABLE core.stock_location (
  name text PRIMARY KEY, counted boolean NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

CREATE TABLE core.stock_snapshot (
  sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  location text REFERENCES core.stock_location,
  as_of date NOT NULL,
  available numeric NOT NULL, on_hand numeric, on_order numeric,
  PRIMARY KEY (sku_id, location, as_of));

-- Where each value came from and when it was read.
CREATE TABLE core.field_source (
  sku_id uuid REFERENCES core.sku ON DELETE CASCADE,
  field text NOT NULL, value text NOT NULL,
  source text NOT NULL, source_ref text NOT NULL,
  read_at date NOT NULL,
  PRIMARY KEY (sku_id, field, source, source_ref));

SELECT ops.track('core.brand','id'), ops.track('core.family','id'), ops.track('core.producer','id'),
       ops.track('core.sku','id'), ops.track('core.sku_tier','sku_id'),
       ops.track('core.sku_packaging_level','sku_id'), ops.track('core.price','id'),
       ops.track('core.sku_component','parent_sku_id'), ops.track('core.sku_compatibility','sku_id'),
       ops.track('core.collateral_link','collateral_sku_id'), ops.track('core.sku_supply','sku_id'),
       ops.track('core.sku_link','sku_id'), ops.track('core.external_id','sku_id'),
       ops.track('core.stock_location','name');

GRANT SELECT ON ALL TABLES IN SCHEMA core TO msku_editor;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO msku_editor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core TO msku_editor;
