-- Confidential. Only msku_cost_reader / msku_cost_editor can see this schema.
-- Costs change order to order: every cost is its own dated record, never overwritten.
CREATE TABLE cost.setting (
  key text PRIMARY KEY, value numeric NOT NULL, note text,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);
INSERT INTO cost.setting VALUES ('landed_uplift', 0.24, 'Approx. landed = unit cost x (1 + uplift). Ken, 2026-10-22');

-- source_priority: lower wins on the same effective date. 1 = manual / PO entry, 2 = ex-factory tab, 3 = master sheet.
CREATE TABLE cost.unit_cost (
  id bigserial PRIMARY KEY,
  sku_id uuid NOT NULL REFERENCES core.sku ON DELETE CASCADE,
  amount numeric(12,4) NOT NULL CHECK (amount >= 0),
  currency char(3) NOT NULL DEFAULT 'USD',
  effective_from date NOT NULL,
  source text NOT NULL, source_priority smallint NOT NULL, source_ref text,
  order_ref text,                -- PO / order number when entered per order
  entered_by text NOT NULL DEFAULT coalesce(nullif(current_setting('msku.actor', true), ''), current_user),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);
CREATE INDEX ON cost.unit_cost (sku_id, effective_from DESC);

-- Reference only (the 24% calculation replaces it): landed cost as written in the master sheet.
CREATE TABLE cost.sheet_landed_cost (
  sku_id uuid PRIMARY KEY REFERENCES core.sku ON DELETE CASCADE,
  amount numeric(12,4) NOT NULL, source_ref text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), version int NOT NULL DEFAULT 1);

SELECT ops.track('cost.setting','key'), ops.track('cost.unit_cost','id'), ops.track('cost.sheet_landed_cost','sku_id');

-- Current unit cost: master-sheet costs are a fallback, used only when no manual / PO / ex-factory record exists.
-- Otherwise the latest effective record wins, ties broken by source_priority.
CREATE VIEW cost.current_unit_cost AS
SELECT DISTINCT ON (sku_id) sku_id, amount, currency, effective_from, source, source_ref, order_ref, entered_by
FROM cost.unit_cost
ORDER BY sku_id, (source_priority = 3), effective_from DESC, source_priority, id DESC;

CREATE VIEW cost.landed_cost AS
SELECT s.id AS sku_id, s.code, c.amount AS unit_cost, c.currency, c.source AS unit_cost_source, c.effective_from,
       round(c.amount * (1 + u.value), 2) AS approx_landed_cost, u.value AS uplift,
       (c.sku_id IS NULL) AS cost_missing
FROM core.sku s
LEFT JOIN cost.current_unit_cost c ON c.sku_id = s.id
CROSS JOIN (SELECT value FROM cost.setting WHERE key = 'landed_uplift') u;

GRANT SELECT ON ALL TABLES IN SCHEMA cost TO msku_cost_reader;
GRANT INSERT, UPDATE ON cost.unit_cost, cost.setting TO msku_cost_editor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA cost TO msku_cost_editor;
