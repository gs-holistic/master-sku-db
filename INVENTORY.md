# Source inventory (read 2026-10-22)

These are the five spreadsheets shared with `master-sku-db@grenco-master-sku.iam.gserviceaccount.com`. They were read only; nothing was written.

## 1. Master SKU-List GS Holistic (owner Ken)

| Tab | Rows | Cols | What it is |
|---|---|---|---|
| Stundenglass | 452 | 42 (A–AP) | Stündenglass master. Col A header is "SG" and holds the SKU. |
| G Pen | 224 | 28 (A–AB) | G Pen master. Col A has no header and holds the SKU. |
| Stundenglass Validation | 53 | 12 | Code lookup lists: status, product class, company, product code, brand/colour, country, producer |
| G Pen Validation | 12 | 12 | Same for G Pen |

**Stundenglass columns:** SKU, Full Name, Product Cost (Per Unit)🔒, Landed Cost🔒, MSRP, GNLN SKU, Units Per Case, MPN, Company CODE (always ST), Product Code (SG2 248, SGM 46, SG3 37, SGP, MRC, SG1, SGA), Accessory Name, Brand & Color Code (67 values), Country Code (02, CS, XX, QR, 0V, CC, 01, 04), Active (Active 138 / Inactive 59 / blank 255), Product Class (HOOKAH, FOOD/BEVERAGE, SWAG, MARKETING), Company, Producer (Dongguan Medica Tech, Deep Roots Glass, Kanary, Empire, U-Printing), Die Line Designs (2), Packaging Design Files (19 links), Barcode, UPC, package weight kg/lb, package dims mm (combined string + L/W/H) and in, case weight kg/lb, case dims mm/in, pallet weight/dims/count (5 rows, Air vs Sea values in one cell).

**G Pen columns:** SKU, Full Name, Product Cost🔒, Landed Cost🔒, MSRP, GNLN SKU, Units Per Case, Company CODE (always GS), Product Code, Accessory Name (ACC/KIT/CS), Brand & Color Code, Country Code (02/03/04), Active (Active 104 / Archived 3 / blank 117), Product Class (all VAPORIZER), Company, Producer (WEEKE, BUDDY, VAPOROUS, SMISS, Dongguan Medica Tech), Die Line/Packaging (empty), Barcode (holds the barcode **file name**), UPC, product weight kg/lb, product dims mm/in, case weight kg/lb, case dims mm/in.

**Data quality:**
- 559 unique codes, but about 100 rows are placeholders (`---`, `----`).
- Real duplicates: `SG2-UPL-GLPR-02` (rows 20, 67), `SG4-KIT-STBK-02` (rows 69 "(2025)" and 408 "V3"), `SGM-DFK-GDAO-02` (rows 285, 400), `GPD-001-AMGD` (rows 76, 83), `GPD-002-AMGD` (rows 77 "RED", 84 "BLU").
- In the SG tab, Barcode and UPC are separate columns, and Barcode sometimes holds a Drive link.

## 2. G-Pen-SKU-Details-Template (owner Tim)
1 tab, "SKU Details", 38 data rows. Columns: Product (family), Retail POP Display SKU, Full Name, UPC (GTIN-14 for packs), Product Dimensions, Unit Weight, Ships in POP Display?, Units per POP Display, Units per Master Case, Case Weight, Case Dimensions, HTS Code. Units are written inside the values ("749 gr", "15.7 Kg").

## 3. Stundenglass-SKU-Details-Template (owner Tim)
1 tab, "SKU Details", 20 data rows. Columns: Product, Full Product Name, SKU, UPC, dims, unit weight, units/case, case weight, case dims, units per pallet, pallet weight, HTS Code.

## 4. G Pen / Stündenglass Price Lists + Order Form + Ex-Factory Unit Costs (owner Ken), the Tier 1 source

| Tab | SKUs | Columns |
|---|---|---|
| GP US WS / GP US D | 40 | MSRP, Wholesale (+ Distro on D) |
| GP CA WS / GP CA D | 43 (1 duplicate: `GPD-002-AJGT`) | CAD |
| GP EU WS / GP EU D | 33 | EUR |
| STG US WS / STG US D | 101 | USD |
| STG CA WS / STG CA D | 127 | CAD |
| STG EU W / STG EU D | 100 | EUR |
| GP/STG ORDER FORM | 123 | MSRP, Wholesale, Qty, Subtotal (US) |
| GP/STG EX-FACTORY UNIT COSTS🔒 | 31 | MSRP, Wholesale, ex-factory unit cost |

- **185 unique SKUs across the 12 price tabs.** That's the Tier 1 set today.
- Layout: header on row 4, category heading rows (MICRO II, DASH II, STÜNDENGLASS, MODÜL…), SKU in col B with leading spaces, an optional "NEW" flag in col A (only `SG4-KIT-STBK-02` has it).
- Pack-code suffixes seen: `-Inner Pack`, `-10`, `-20`.
- `GHO-001-AOZZ-10` is on the order form and cost tab but on **no** price tab.
- **GP EU WS has 12 prices shown with `$`** under a "Euros" header. GP EU D is all `€`.

## 5. Cin7 INVENTORY AS OF 10/22/26 (owner Ken), the stock source

1 tab, "AvailabilityReport_2026-10-22": 4,717 rows, one per SKU × location (no duplicates), 1,185 distinct SKUs. Columns: Category, SKU, ProductName, Location, Bin, BatchSerialNumber, ExpiryDate, Discount, StockValue, OnHand, VolumeOnHand, **Available (col L, confirmed)**, OnOrder, InTransit, Allocated, Status (ACTIVE / DEPRECATED), Unit, Family, StockLocator, Brand, PriceTier1–3, NextDeliveryDate, AdditionalAttribute1–6+.

- All 13 counted locations appear with exactly the spelling you gave.
- 14 other locations also appear and will **not** be counted: BYRD EU GPEN B2B, BYRD EU GPEN B2C, BYRD EU STG B2C, **Vandeventer STG B2B**, **In Transit 2- STG**, Grenco Goods, Quarantine, Tradeshow, Empire, HongKong Buddy, SMISS, Stache, WWC, Yuebang.
- About 280 Cin7 SKUs aren't product SKUs: Grenco Goods flower/labels (`GG00-…`), Route insurance (`ROUTEINS…`), Printful merch (`2864807_4625`), numeric legacy IDs, `CS-ONLY-…` parts, fees and tests.
- A few SKUs show negative Available totals (e.g. −1, −3).

## Cross-match (by exact SKU code)
- Price list ∩ Master: 160 of 185. 25 price-list SKUs are missing from the master, mostly `-Inner Pack`/`-20` pack SKUs plus `GPC-004-AJCK/GT/LM`, `GPD-002-AJCK/GT`, `GMK-…`, `MRH-001-AFZZ`.
- Price list ∩ Cin7: 181 of 185. Missing from Cin7: `GPD-001-APGR-Inner Pack`, `GPD-001-APPU-Inner Pack`, `MRH-001-AFZZ`, `SG5-KIT-STPK-02`.
- In 10 cases the master's "Active" column says **Inactive** for a SKU that's on the price list.

## Rough tier preview (not final)
Across all codes in Master ∪ Price list ∪ Cin7 (1,315): **T1 185, T2 537, T3 593**. 116 of the T3 SKUs hold stock, but only in locations that aren't counted. These numbers include the non-product Cin7 codes listed above.
