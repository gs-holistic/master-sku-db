# Master SKU database: decisions log

## 2026-10-22: SKU lifecycle tiers (from Ken)

| Tier | Meaning | Rule |
|---|---|---|
| 1, Active | Currently sold, or in development | On **"G Pen / Stündenglass Price Lists + Order Form + Ex-Factory Unit Costs"**, OR in development. Stays Tier 1 even at zero stock (backordered). |
| 2, Falling | Holds inventory, not actively sold | Not on the price list AND total Available > 0 across the counted locations |
| 3, Discontinued / out of stock | Gone | Not on the price list AND total Available ≤ 0 across the counted locations |

### Stock rule
- Use only the **"Available"** quantity (column L of the stock report).
- Sum across exactly these locations, and no others:
  - Anlerr
  - DMT GPEN
  - DMT STG
  - In Transit - STG
  - In Transit- GPEN
  - Retail North LTD (Franklins 3PL)
  - South Reed
  - Vandeventer GPEN B2B
  - Vandeventer GPEN B2C
  - Vandeventer STG B2C
  - WeFill GPEN B2B
  - WeFill GPEN B2C
  - WeFill STG B2C
- Location names are matched exactly as written (spacing included, e.g. "In Transit - STG" vs "In Transit- GPEN"). Any location not on the list is reported, never silently counted.

### Tier history
- Every tier change is recorded with its effective date, the old tier, the new tier and the reason (price-list change / stock change / manual).

### Costs
- Ex-factory unit costs from the price-list sheet go only into the role-restricted cost tables. Prices and active status are imported separately.

## 2026-10-22: Inventory follow-ups (from Ken)

- **Locations:** only the 13 listed count. Vandeventer STG B2B, In Transit 2- STG, BYRD EU ×3, Grenco Goods, Quarantine, Tradeshow, Empire, HongKong Buddy, SMISS, Stache, WWC and Yuebang stay excluded on purpose.
- **Non-product Cin7 codes** (GG00-…, ROUTEINS…, Printful numeric IDs, fees/tests, CS-ONLY-…, 6-digit legacy IDs) are excluded from the database and listed in an exclusions report.
- **Pack SKUs:** exclude every `-10` / `-20` SKU **except `GHO-007-AOZZ-10`**. Currently excluded: GHK-001-AOSL-20, GHK-001-AOZZ-20, GHK-001-APHC-20, GHK-001-APST-20, GHK-002-APST-20, GHO-001-AOZZ-10, GPD-001-APZZ-10, GSB-001-AOZZ-20. This applies even when the code is on the price list.
- **Pack tiers:** each pack SKU gets its tier from its own row (price list / stock), never inherited from its single unit.
- **Master duplicates:** these are resolved in the database only; Ken's sheet is never edited.
  - `SG4-KIT-STBK-02`: keep both rows (69 "(2025)", 408 "V3") for now.
  - `GPD-002-AMGD`: keep row 77, drop the BLU row 84.
  - `SG2-UPL-GLPR-02`: keep row 20, drop row 67.
  - `SGM-DFK-GDAO-02`: keep row 285, drop row 400.
  - `GPD-001-AMGD`: the SKU is **blue**. Keep row 83 (name BLU, colour code BLU), drop row 76 (name BLU, colour code RED).
  - Dropped rows are matched on tab + row + SKU code. If the sheet is edited and the row moves, the import warns instead of dropping the wrong row.
- **-10 / -20 fix (2026-10-22):** Ken corrected the price list. No -10/-20 codes remain on it except `GHO-007-AOZZ-10`. The rest appear only in Cin7 and stay excluded.
- **GP EU WS:** `$` values on that tab are euros with the wrong symbol and are imported as EUR.
- **In-development SKUs:** list to come from Ken later.

## 2026-10-22: Unit and landed costs (from Ken)

- **Unit costs change from order to order**, so every unit cost is kept as its own dated record and never overwritten. Each record holds: SKU, cost type (ex-factory unit cost), amount, currency, effective date, source (sheet / PO / order number), and who entered it. "Current cost" means the latest effective record. Older ones stay as history.
- Costs can be updated in the database directly (role-restricted) and by re-importing the sheets. Either way a new dated record is added and the audit log records the change.
- **Approximate landed cost = unit cost × 1.24** (24% above unit cost), calculated for every SKU that has a unit cost. The 24% is stored as a setting, not hard-coded, so it can be changed later. Changing it recalculates; it doesn't rewrite history.
- Costs stay in the restricted cost schema (`cost_reader` role only) and are not shown on the preview page or in the `api.*` views.

## 2026-10-22: Cost sources, names, schema (from Ken)

- **Unit cost source:** when both the ex-factory tab and the master sheet have a unit cost, the **ex-factory tab wins**. The master value is kept as history in the restricted cost schema. Cost disagreements are deliberately kept out of the shared conflict report so costs are never exposed there.
- **Landed cost:** the 24% calculation (unit × 1.24) **replaces** the master sheet's "Landed Cost" column (which was ~35%). The sheet value is kept as a reference only.
- **Missing costs:** SKUs with no unit cost in any source are **flagged as missing**. Nothing is estimated.
- `GPD-002-AMGD`: **RED** is correct. The master colour code "BLU" on row 77 is wrong and is overridden to RED.
- `SGM-DFK-GDAO-02`: the name is **"Grateful Dead x Modül + Dok Deluxe Travel Set - Legacy Patchwork"** (as on the price list).
- **Cin7 PriceTier1/2/3 = US MSRP / Wholesale / Distribution** (confirmed).
- **Schema proposal: approved.**

## 2026-10-22: Price precedence and conflict workflow (from Ken)

- **The price list always beats Cin7 and the master sheet's MSRP.** Those mismatches are no longer conflicts. They go on a **fix list** (`ops.source_fix`, and the "Fix list (other systems)" tab) for whoever maintains Cin7 / the master sheet. This cleared 56 of the 73 conflicts.
- Only disagreements **inside** the price-list workbook (WS tab vs D tab vs order form), UPC disagreements and status disagreements remain conflicts for Ken.
- **Conflicts are decided in Google Sheets:** a separate spreadsheet, "Master SKU Database – Outputs" (created by Ken, shared with the service account as Editor), has a Conflicts tab with a "Your decision" column. Each sync reads the decisions first, then imports, then rewrites the tabs.

## 2026-10-23: MSRP vs MAP (from Ken)

- For `SG4-KIT-STBK-02`, `SG4-KIT-STBU-02`, `SG4-KIT-STDR-02`, `SG4-KIT-STGR-02`, `SG4-KIT-STPU-02` (US), the price list's "MSRP" column ($449.95) is the **B2B MAP**. The **B2C MSRP is $499.95** (matches stundenglass.com and Cin7 PriceTier1).
- The database stores them as two price tiers: `map` = 449.95 (source: price list) and `msrp` = 499.95 (source: Ken's decision). Cin7 / master sheet values of 499.95 are therefore correct and no longer on the fix list.
- Applies to US only for now. Rule lives in `MAP_ON_PRICE_LIST` in `msku/mapping_rules.py`.
- Ken updated Cin7 and the master sheet per the fix list. Master-sheet fixes confirmed on 2026-10-23; Cin7 fixes will show once a new Cin7 inventory export is shared.

## 2026-10-23: MSRP vs MAP follow-up (from Ken)

- The MSRP/MAP split for the five Gravity Infuser V3 SKUs applies in **US, Canada and the EU**. The price list "MSRP" column is loaded as **MAP** in all three (US 449.95 USD, CA 599.95 CAD, EU 449.95 EUR).
- B2C MSRP: US 499.95. **CA and EU B2C MSRP not given yet**, so they are left empty and flagged rather than guessed.
- **Every other product:** keep the price list's "MSRP" column labelled as MSRP ("keep things simple").
- **SKUs that drop out of every source** (e.g. `GHO-002-APST`, only in the 10/22 Cin7 export) are kept, moved to Tier 3 by the normal rule (not on the price list, no stock), recorded in tier history and flagged "No longer in any source".

## 2026-10-23: Manual tier override (from Ken)

- **`GPM-001-APZZ` (G Pen Micro II Vaporizer) is Tier 1.** By the normal rule it was Tier 2 (only its 10-pack POP `GPM-001-APZZ-Inner Pack` is on the price list; 5,886 units available). Overrides live in `TIER_OVERRIDES` in `msku/mapping_rules.py`, win over the rule on every import, and are recorded in tier history with their reason.
- Open question: other single units are in the same position (their POP is on the price list, the unit isn't) — `GHK-001-AOZZ`, `GHO-001-AOZZ`, `GPA-001-APSC`, `GPD-001-APZZ`, `GSB-001-AOZZ` (Tier 2) and `GPD-001-APGR`, `GPD-001-APPU` (Tier 3).

## 2026-10-26: G Pen Hub API (from Ken)

- The G Pen Hub (gpen-crm.vercel.app) reads and writes SKUs through an HTTP API: `msku/hub_api.py`, documented in `docs/HUB_API.md`. It uses the existing tables; migration 010 only adds things (`core.sku_spec`, `core.hub_lock`, `core.sku.origin`, an audit index and the `msku_hub_api` role).
- **When the Hub and a sheet disagree, the Hub wins, and the difference is flagged (Ken's choice).** A field the Hub sets (name, brand, UPC, the five prices) is no longer overwritten by the sync. A sheet that says otherwise raises a "Changed in the G Pen Hub" conflict. Deciding it for the sheet's value hands the field back to the sheets.
- SKUs created in the Hub (`origin = 'hub'`) aren't treated as "gone" by the sync. They have no tier until they appear on the price list or in Cin7.
- `status` is new and belongs to the Hub. Until the Hub sets it, it follows the tier: 1 → active, 2 → deprecated, 3 → obsolete, new or untiered → draft. Setting it doesn't change the tier.
- **Hosting is Jordan's call (Ken's choice).** The API is built and tested but not deployed. It needs a permanent Postgres and an HTTPS host. The key is generated on the host (`python -m msku new-api-key`) so it never passes through chat or email.
- `distro_eu` and `distro_ca` are returned in EUR and CAD, as the price list holds them. No currency conversion.

## 2026-10-27: Hub API before go-live (from Ken and Jordan)

- **Every price has a `<price>_currency` field right after it** (USD, CAD, EUR, GBP). CA and EU prices stay in CAD and EUR, as the price list holds them.
- **UK prices** (`msrp_uk`, `wholesale_uk`, `distro_uk`) are the US numbers in GBP (Ken: "price is same as USD but with lbs", read as pounds sterling). They're read-only and follow the US prices.
- **Read-only extras in GET /skus:** family, category, hts_code, country_of_origin, producer, map (US), msrp_ca, msrp_eu, wholesale_ca, wholesale_eu, cin7_id, store_url, asset_url. `cin7_id` is the SKU as Cin7 exports it. No source supplies `country_of_origin`, `store_url` or `asset_url` yet, so they're null.
- **The API connects as `msku_hub_api_login`**, which has no access to the cost schema (`MSKU_API_DATABASE_URL`, made by `python -m msku hub-login`). It never falls back to the owner's `DATABASE_URL`.
- **Hosting:** Vercel, team grenco-medical, with Neon Postgres (Ken). `requirements.txt` holds only what the API needs; the sync and tests use `requirements-dev.txt`.

## 2026-10-27: UK prices editable, and the Hub is pinged on every change (from Jordan via Ken)

- **UK prices are editable in the Hub.** `msrp_uk`, `wholesale_uk` and `distro_uk` (GBP) are stored as UK-region prices (migration 011). Until the Hub sets one, it equals the US figure and follows it; `null` makes it follow again. The sheets have no UK prices, so the sync never touches them.
- **Webhook:** after each write that changes something, one POST goes to `https://gpen-crm.vercel.app/api/master-sku/changed` with `{"skus": [...], "changed_at": ...}` and `x-api-key: HUB_WEBHOOK_KEY`. A sync sends one ping with every SKU it changed. Fire and forget: 5-second timeout, failures are only logged. The Hub re-checks every 15 minutes.
- **The key variable is `MSKU_API_KEYS`** (`<new>,<old>` while rotating), as Jordan specified. `MSKU_API_KEY` and `MSKU_API_KEY_PREVIOUS` still work.
