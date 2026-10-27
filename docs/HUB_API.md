# G Pen Hub API

Server-to-server JSON API that lets the G Pen Hub (gpen-crm.vercel.app) read and write the master SKU database.
Code: `msku/hub_api.py`. Tests: `tests/test_hub_api.py`.

**Base URL:** `https://<project>.vercel.app` once the Vercel project is deployed (see [Deploying](#deploying)).
Every path below goes after it.

## Authentication

- Every request needs an `x-api-key` header. A missing or wrong key gets `401`.
- HTTPS only. A plain-HTTP request gets `403` (judged from `X-Forwarded-Proto`, which every HTTPS host sets).
- No CORS and no browser login: the Hub calls this from its server, with the key kept in the Hub's server-side env.

**The key** lives only in Vercel's environment variables (`MSKU_API_KEY`) and the Hub's server-side env. It's never
in code, chat, Slack or email.

- Make one: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`, which prints a random 64-character key.
  (`python -m msku new-api-key` does the same inside the repo.)
- **Rotate** without downtime:
  1. Move the current key to `MSKU_API_KEY_PREVIOUS`, put the new one in `MSKU_API_KEY`, and redeploy.
  2. Update the Hub.
  3. Delete `MSKU_API_KEY_PREVIOUS` and redeploy.

## Conventions

- JSON in and out, UTF-8. Errors are `{"error": "...", "fields": {"<field>": "<what's wrong>"}}`.
- Timestamps are ISO 8601 in UTC with milliseconds: `2026-10-26T18:04:05.123Z`.
- Money is a plain number (`49.95`). **Every price has a `<price>_currency` field right after it**: `USD`, `CAD`,
  `EUR` or `GBP`. CA and EU prices are as the price list holds them; nothing is converted.
- **UK prices** (`msrp_uk`, `wholesale_uk`, `distro_uk`) are the US numbers in GBP (Ken, 2026-10-27). They follow
  the US prices and are read-only.
- Quantities are whole numbers. Dimensions and weights are text with units (`"4.5 x 2 x 1 in"`, `"3.2 oz"`). Values
  that come from the sheets are shown in mm, g and kg.
- Nothing is deleted. To retire a SKU, set `"status": "obsolete"`.

## Endpoints

### `GET /health`

Checks the key and the database connection.

```
curl -H "x-api-key: $KEY" https://<base>/health
```
```json
{"ok": true}
```

### `GET /skus`

Every SKU (about 1,030 today, roughly 570 KB), oldest change first. Optional:

- `?updated_since=<ISO timestamp>`: only SKUs changed after it. Pass the largest `updated_at` from your last pull.
- `?q=<text>`: SKU # or name contains the text, ignoring case.

```
curl -H "x-api-key: $KEY" "https://<base>/skus?q=micro%20ii&updated_since=2026-10-20T00:00:00Z"
```
```json
{"skus": [ <SKU record>, ... ], "count": 3}
```

### `GET /skus/:sku`

One SKU. URL-encode the SKU # (`GPM-001-APZZ-Inner%20Pack`). `404` if it doesn't exist.

```
curl -H "x-api-key: $KEY" "https://<base>/skus/GPM-001-APZZ-Inner%20Pack"
```
```json
{
  "sku": "GPM-001-APZZ-Inner Pack",
  "name": "G Pen Micro II Vaporizer, 10-Pack POP",
  "brand": "G Pen",
  "status": "active",
  "upc": "10811736020340",
  "msrp": 499.5, "msrp_currency": "USD", "wholesale": 300.0, "wholesale_currency": "USD",
  "distro": 255.0, "distro_currency": "USD", "distro_eu": 255.0, "distro_eu_currency": "EUR",
  "distro_ca": 357.0, "distro_ca_currency": "CAD",
  "pack_size": 10,
  "product_dims": "145 x 107.5 x 73 mm", "product_weight": "1.007 kg",
  "packaging_dims": null, "packaged_weight": null,
  "case_pack": 160, "case_dims": "325 x 305 x 235 mm", "case_weight": "16.8 kg",
  "pallet_qty": null, "pallet_dims": null, "pallet_weight": null,
  "notes": null,
  "tier": 1, "family": "Micro II", "category": "Micro Ii", "hts_code": "8543.70.9940", "country_of_origin": null,
  "producer": null,
  "map": null, "map_currency": "USD",
  "msrp_ca": 699.5, "msrp_ca_currency": "CAD", "msrp_eu": 499.5, "msrp_eu_currency": "EUR",
  "wholesale_ca": 420.0, "wholesale_ca_currency": "CAD", "wholesale_eu": 300.0, "wholesale_eu_currency": "EUR",
  "msrp_uk": 499.5, "msrp_uk_currency": "GBP", "wholesale_uk": 300.0, "wholesale_uk_currency": "GBP",
  "distro_uk": 255.0, "distro_uk_currency": "GBP",
  "cin7_id": "GPM-001-APZZ-Inner Pack", "store_url": null, "asset_url": null,
  "updated_at": "2026-10-22T23:05:05.315Z",
  "updated_by": "ken"
}
```

### `POST /skus`

Creates a SKU. `sku` and `changed_by` are required; every other field is optional.

- `409` (with the existing record in `current`) if the SKU # exists, ignoring case.
- `400` lists every bad field.

```
curl -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" https://<base>/skus -d '{
  "sku": "GPN-123-APZZ", "name": "New Thing", "brand": "G Pen", "upc": "00811736020000",
  "msrp": 49.95, "case_pack": 50, "product_dims": "4.5 x 2 x 1 in",
  "changed_by": "jordan@grencoscience.com"}'
```
`201`, with the new record:
```json
{"sku": "GPN-123-APZZ", "name": "New Thing", "brand": "G Pen", "status": "draft", "upc": "00811736020000",
 "msrp": 49.95, ..., "case_pack": 50, "product_dims": "4.5 x 2 x 1 in", "tier": null,
 "updated_at": "2026-10-26T18:04:05.123Z", "updated_by": "jordan@grencoscience.com"}
```

### `PATCH /skus/:sku`

Changes only the fields sent; `null` clears a field.

- Send `updated_at` exactly as you last received it. If the SKU changed since then, nothing is saved: `409` returns
  the current record in `current`, so the Hub can show it and let the person redo the edit.
- The SKU # can't be renamed.

```
curl -X PATCH -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  "https://<base>/skus/GPM-001-APZZ" -d '{
  "updated_at": "2026-10-22T23:05:05.315Z", "msrp": 109.95, "notes": "New box from Q1",
  "changed_by": "jordan@grencoscience.com"}'
```
`200`, with the updated record. When the record is out of date, `409`:
```json
{"error": "This SKU changed since you loaded it. Nothing was saved; here is the current record.",
 "current": { <SKU record> }}
```

### `GET /changes?since=<ISO timestamp>`

Who changed what, oldest first, one row per field. This covers changes made through the Hub and changes made by the
daily sheet sync (`changed_by` is then the sync's user).

- `limit`: default 500, maximum 2000.
- When `next_cursor` isn't null, call again with `?cursor=<next_cursor>` for the next page.

```
curl -H "x-api-key: $KEY" "https://<base>/changes?since=2026-10-26T00:00:00Z"
```
```json
{"changes": [
  {"sku": "GPM-001-APZZ", "field": "msrp", "old_value": 99.95, "new_value": 109.95,
   "changed_by": "jordan@grencoscience.com", "changed_at": "2026-10-26T18:04:05.123Z"}],
 "next_cursor": null}
```

## Status codes

| Code | When |
|---|---|
| 200 / 201 | OK / created |
| 400 | Bad JSON or bad fields (see `fields`) |
| 401 | Missing or wrong `x-api-key` |
| 403 | Plain HTTP |
| 404 | No such SKU or path |
| 405 | Wrong method (there's no DELETE) |
| 409 | SKU # already exists (POST), or the record changed since `updated_at` (PATCH) |
| 413 | Body over 64 KB |
| 503 | Database unreachable |

## Validation

| Field | Rule |
|---|---|
| `sku` | Required on create, unique ignoring case, at most 80 characters, no `/` |
| `changed_by` | Required on every write: the person's email. Recorded as the author of the change |
| `name` | Non-empty text |
| `brand` | An existing brand: G Pen, Stündenglass, ... (`400` lists them) |
| `status` | `draft`, `active`, `deprecated` or `obsolete` |
| `upc` | Text, digits only, 8–14 digits (text, so leading zeros survive) |
| `msrp`, `wholesale`, `distro`, `distro_eu`, `distro_ca` | Number from 0 to 1,000,000, at most 2 decimals, or `null` |
| `pack_size`, `case_pack`, `pallet_qty` | Whole number, or `null` |
| dims, weights | Text up to 100 characters; `notes` up to 5,000 |
| `tier`, `updated_by`, every `_currency`, and the read-only fields below | Read-only (`400` if sent) |

## Where each field comes from

| Field | Read from | A Hub write goes to |
|---|---|---|
| `sku`, `name`, `brand`, `upc` | `core.sku` | `core.sku` + a Hub lock |
| `msrp` / `wholesale` / `distro` | current US MSRP / wholesale / distribution price | a new effective-dated price row + a Hub lock |
| `distro_eu` / `distro_ca` | current EU (EUR) / CA (CAD) distribution price | same |
| `status` | the Hub's value; otherwise Tier 1 → `active`, Tier 2 → `deprecated`, Tier 3 → `obsolete`, new or untiered → `draft` | `core.sku_spec` |
| `pack_size` | the Hub's value; else the code (single unit or kit = 1, `-10` = 10); else, for a POP or master case, the unit count recorded on its single-unit SKU | `core.sku_spec` |
| `product_dims` / `product_weight`, `packaging_dims` / `packaged_weight` | the Hub's value; else the sheets' "unit" measurements (see the note below) | `core.sku_spec` |
| `case_*`, `pallet_*` | the Hub's value; else the master case and pallet rows from the sheets | `core.sku_spec` |
| `notes` | the Hub's value | `core.sku_spec` |
| `tier` | price list and Cin7 stock | read-only |
| `family`, `category`, `hts_code`, `country_of_origin`, `producer` | the sheets | read-only |
| `map` | current US MAP (only the 5 Gravity Infuser V3 SKUs have one) | read-only |
| `msrp_ca`, `wholesale_ca` / `msrp_eu`, `wholesale_eu` | current CA (CAD) / EU (EUR) prices | read-only |
| `msrp_uk`, `wholesale_uk`, `distro_uk` | the US numbers, in GBP | read-only |
| `cin7_id` | the SKU as Cin7 knows it (Cin7 exports identify products by SKU); `null` if not in Cin7 | read-only |
| `store_url`, `asset_url` | store page and asset portal links. **No source supplies them yet, so they're `null`** | read-only |
| `<price>_currency` | the price's region: USD, CAD, EUR, GBP | read-only |
| `updated_at` | the latest change to any of the above | — |
| `updated_by` | who made that change | — |

**When the Hub and the sheets disagree, the Hub wins.** Once the Hub sets `name`, `brand`, `upc` or a price, the
daily sync stops overwriting it. If a sheet later says something different, the difference goes to the **Conflicts**
tab of the outputs sheet for Ken:

- Deciding for the sheet's value hands the field back to the sheets.
- Deciding for the Hub's value keeps it.

Every write is logged in `ops.audit_log` with the full before and after, `changed_by` and the time. `/changes` reads
that log.

## Deploying

Hosted on Vercel (team grenco-medical) with Neon Postgres. `vercel.json` sends every path to `api/index.py`, which
serves the WSGI `app`. Vercel installs `requirements.txt` (just the database driver). The sheet sync and the tests
use `requirements-dev.txt`.

**Two database logins:**

| Env var | Login | Used by |
|---|---|---|
| `DATABASE_URL` | Neon's owner login, set by Vercel's Neon integration | `migrate`, `sync`, `hub-login` only. The API never uses it |
| `MSKU_API_DATABASE_URL` | `msku_hub_api_login`, a member of `msku_hub_api`: SKU data and the audit log, no cost schema | the API. It returns `503` if this isn't set, rather than falling back to the owner |

**Environment variables on the Vercel project:**

- `DATABASE_URL`: set by the Neon integration.
- `MSKU_API_DATABASE_URL`: printed by `python -m msku hub-login`.
- `MSKU_API_KEY`: the Hub's key.
- `MSKU_API_KEY_PREVIOUS`: optional, used only while rotating.

**One-time setup** (from a computer with the repo, Python 3.11+ and the Vercel CLI):

```
git clone https://github.com/gs-holistic/master-sku-db && cd master-sku-db
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
vercel link                      # pick team grenco-medical, project master-sku-db
vercel env pull .env.local       # writes DATABASE_URL locally; .env* is git-ignored
set -a && . ./.env.local && set +a
.venv/bin/python -m msku migrate
.venv/bin/python -m msku hub-login   # prints MSKU_API_DATABASE_URL: paste it into Vercel, never into chat
```

Then load the data with `python -m msku sync`. It needs the Google service account key; see docs/HOSTING.md.

**Local development:** `MSKU_API_KEY=dev python -m msku serve` runs the API on `http://localhost:8080` over plain
HTTP, against the local database. It's for development only; never expose it.
