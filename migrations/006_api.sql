-- Read-only interface for other systems (Sales Hub, CS portal, B2B portal, website, core DB).
-- Join on sku_id (stable UUID) or sku_code. Sync with: WHERE updated_at > :last_sync.
-- No costs here, ever.
CREATE VIEW api.skus AS
SELECT s.id AS sku_id, s.code AS sku_code, s.name, b.name AS brand, f.name AS family, s.category,
       s.product_class, s.variant_code, s.pack_type::text, s.pack_qty, base.code AS base_sku_code,
       s.upc, s.hts_code, s.country_of_origin, p.name AS producer, s.is_new,
       t.tier, t.since AS tier_since, t.reason AS tier_reason,
       greatest(s.updated_at, t.updated_at) AS updated_at, s.version
FROM core.sku s
LEFT JOIN core.brand b ON b.id = s.brand_id
LEFT JOIN core.family f ON f.id = s.family_id
LEFT JOIN core.sku base ON base.id = s.base_sku_id
LEFT JOIN core.producer p ON p.id = s.producer_id
LEFT JOIN core.sku_tier t ON t.sku_id = s.id;

CREATE VIEW api.prices AS
SELECT p.sku_id, s.code AS sku_code, p.region::text, p.tier::text AS price_tier, p.currency, p.amount,
       p.effective_from, p.source, p.updated_at, p.version
FROM core.price p JOIN core.sku s ON s.id = p.sku_id
WHERE p.effective_to IS NULL;

CREATE VIEW api.price_history AS
SELECT p.sku_id, s.code AS sku_code, p.region::text, p.tier::text AS price_tier, p.currency, p.amount,
       p.effective_from, p.effective_to, p.source, p.updated_at, p.version
FROM core.price p JOIN core.sku s ON s.id = p.sku_id;

CREATE VIEW api.tier_history AS
SELECT h.sku_id, s.code AS sku_code, h.old_tier, h.new_tier, h.effective_date, h.reason, h.recorded_at AS updated_at
FROM core.sku_tier_history h JOIN core.sku s ON s.id = h.sku_id;

CREATE VIEW api.packaging AS
SELECT l.sku_id, s.code AS sku_code, l.level::text, l.length_mm, l.width_mm, l.height_mm, l.weight_g,
       l.units_per_level, l.source, l.updated_at, l.version
FROM core.sku_packaging_level l JOIN core.sku s ON s.id = l.sku_id;

CREATE VIEW api.external_ids AS
SELECT e.sku_id, s.code AS sku_code, e.system, e.external_key, e.updated_at, e.version
FROM core.external_id e JOIN core.sku s ON s.id = e.sku_id;

CREATE VIEW api.links AS
SELECT k.sku_id, s.code AS sku_code, k.kind, k.url, k.source, k.updated_at, k.version
FROM core.sku_link k JOIN core.sku s ON s.id = k.sku_id;

CREATE VIEW api.stock AS
SELECT st.sku_id, s.code AS sku_code, st.as_of, sum(st.available) FILTER (WHERE l.counted) AS available_counted,
       sum(st.available) AS available_all_locations
FROM core.stock_snapshot st JOIN core.sku s ON s.id = st.sku_id JOIN core.stock_location l ON l.name = st.location
WHERE st.as_of = (SELECT max(as_of) FROM core.stock_snapshot)
GROUP BY st.sku_id, s.code, st.as_of;

GRANT SELECT ON ALL TABLES IN SCHEMA api TO msku_api_reader;
-- Views run with the owner's rights, so the reader needs nothing in core.
