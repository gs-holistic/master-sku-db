# Schema

Postgres 16. Migrations are in `migrations/` and applied in order by `python -m msku migrate`.

| Schema | Who can read it | Purpose |
|---|---|---|
| `core` | `msku_editor` | Master data |
| `cost` | `msku_cost_reader`, `msku_cost_editor` only | Confidential unit and landed costs |
| `staging` | owner | Raw imported rows |
| `ops` | `msku_editor` | Import runs, conflicts, decisions, exclusions, audit log |
| `api` | `msku_api_reader` | Read-only views for other systems (no costs) |

Every `core` table has `updated_at` and `version`. Both only change when a value actually changes. Every insert, update and delete is written to `ops.audit_log` with who made it (`msku.actor`), when, and the row before and after.

## core

| Table | What it holds |
|---|---|
| `brand` | G Pen, Stündenglass, Vapium |
| `family` | Product line within a brand (Micro II, Dash II, Gravity Infuser, Modül…), taken from the price-list category heading. Has `help_url` and `asset_portal_url` for links. |
| `producer` | Factory / supplier (Dongguan Medica Tech, WEEKE, BUDDY…) |
| `sku` | One row per SKU code. `id` is a **stable UUID** for other systems. Fields: name, brand, family, category, product class, variant (brand & colour) code, pack type and quantity, `base_sku_id` (pack → its single unit), UPC/GTIN, HTS code, country of origin, producer, NEW flag, `code_check` (why a code breaks our conventions, or empty), `master_active` (the master sheet's Active column, reference only), `review_flags` from the last import. |
| `sku_tier` | Current tier (1 Active, 2 Falling, 3 Discontinued / out of stock), the date it took effect, and the reason |
| `sku_tier_history` | Every tier move: old → new, date, reason, import run |
| `sku_packaging_level` | Unit / inner pack / master case / pallet: dimensions in mm, weight in g, units per level, plus the original text (`raw`) and source |
| `price` | Region (US/CA/EU) × tier (MSRP/wholesale/distribution/retail), currency, amount, `effective_from` / `effective_to`. A change closes the old row and opens a new one; history is never overwritten. |
| `sku_component` | What's inside a POP display or kit (parent → child × qty) |
| `sku_compatibility` | Which accessories and parts fit which device or family |
| `collateral_link` | Marketing collateral SKU ↔ family |
| `sku_supply` | Producer, MOQ and lead time per SKU |
| `sku_link` | Store page, asset portal, manual, packaging files, die lines, barcode files |
| `external_id` | Links a SKU to other systems: `cin7`, `gnln`, `mpn`, later `shopify_product`, `shopify_variant`, `asset_portal` |
| `stock_location` | Cin7 locations and whether each **counts** for tiering (the 13 Ken listed) |
| `stock_snapshot` | Cin7 Available / On hand / On order per SKU × location × report date |
| `field_source` | Every value from every source, with sheet / tab / row and the date read, so any number can be traced |

## cost (confidential)

| Table / view | What it holds |
|---|---|
| `unit_cost` | One dated record per cost. Costs change order to order, so records are added, never overwritten. Each has a source (`manual` / PO, `ex_factory` tab, `master` sheet), a priority, `order_ref` and `entered_by`. |
| `current_unit_cost` (view) | The cost in force. Master-sheet costs are a fallback only. Otherwise the latest effective record wins, ties broken by priority (manual > ex-factory). |
| `setting` | `landed_uplift` = 0.24 |
| `landed_cost` (view) | Approximate landed cost = unit × (1 + uplift) for every SKU, with `cost_missing` = true where there is no unit cost |
| `sheet_landed_cost` | The master sheet's old "Landed Cost" column (about 35%), kept for reference only |

To enter a new cost for an order:
```sql
SET msku.actor = 'ken';
INSERT INTO cost.unit_cost (sku_id, amount, effective_from, source, source_priority, order_ref)
SELECT id, 11.50, '2026-11-01', 'manual', 1, 'PO-1234' FROM core.sku WHERE code = 'GPM-001-APZZ';
```

## staging and ops

| Table | What it holds |
|---|---|
| `staging.raw_row` | Every imported row as read, with spreadsheet, tab and row number (cost cells blanked) |
| `ops.import_run` | Each run: who, when, dry run or not, sources and their read dates, and a summary of changes |
| `ops.exclusion` | Codes left out and why (Grenco Goods, Route, Printful, -10/-20 packs, dropped duplicate rows…) |
| `ops.conflict` | Sources that disagree about a SKU field. Status: open, resolved, reopened (sources changed after a decision) or cleared (sources now agree). Costs never appear here. |
| `ops.conflict_resolution` | Ken's decision for each conflict, reapplied on every import |
| `ops.audit_log` | Who changed what, when, and the row before and after |
