# Read-only interface (for Tim and other systems)

Connect with a login that is a member of `msku_api_reader`. It can read the `api` schema only. Costs are never exposed.

```sql
CREATE ROLE core_db_sync LOGIN PASSWORD '…' IN ROLE msku_api_reader;
```

## Keys and syncing

- **`sku_id`** (UUID) is stable and never reused. Join on it. `sku_code` is unique too, but codes can be corrected.
- Every view has **`updated_at`**. Incremental sync: `WHERE updated_at > :last_sync`, then store `max(updated_at)`.
- `version` goes up by one on every real change to the row.

## Views

| View | One row per | Columns |
|---|---|---|
| `api.skus` | SKU | sku_id, sku_code, name, brand, family, category, product_class, variant_code, pack_type, pack_qty, base_sku_code, upc, hts_code, country_of_origin, producer, is_new, **tier**, tier_since, tier_reason, updated_at, version |
| `api.prices` | SKU × region × price tier (current only) | region (US/CA/EU), price_tier (msrp/wholesale/distribution/retail), currency, amount, effective_from, source |
| `api.price_history` | every price ever | as above plus effective_to |
| `api.tier_history` | tier move | old_tier, new_tier, effective_date, reason |
| `api.packaging` | SKU × level | level (unit/inner_pack/master_case/pallet), length_mm, width_mm, height_mm, weight_g, units_per_level |
| `api.external_ids` | SKU × system × key | system (cin7, gnln, mpn, later shopify_*), external_key |
| `api.links` | SKU × link | kind, url |
| `api.stock` | SKU (latest Cin7 report) | available_counted (the 13 counted locations), available_all_locations, as_of |

## Tiers

- **1, Active:** on the "G Pen / Stündenglass Price Lists + Order Form + Ex-Factory Unit Costs" price tabs (or in development)
- **2, Falling:** not on the price list, but Available > 0 in the counted locations
- **3, Discontinued / out of stock:** not on the price list and no Available stock in the counted locations

## Example

```sql
SELECT s.sku_code, s.name, s.tier, p.amount AS us_msrp
FROM api.skus s
LEFT JOIN api.prices p ON p.sku_id = s.sku_id AND p.region = 'US' AND p.price_tier = 'msrp'
WHERE s.tier = 1 AND s.brand = 'G Pen';
```
