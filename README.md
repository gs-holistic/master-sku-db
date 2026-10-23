# Master SKU database

One place for G Pen and Stündenglass product master data. It consolidates Ken's Google Sheets and the Cin7 inventory report, and serves read-only views to other systems.

- **Decisions and rules:** [DECISIONS.md](DECISIONS.md) (tiers, counted locations, exclusions, costs)
- **What the sheets contain:** [INVENTORY.md](INVENTORY.md)
- **Every table explained:** [docs/SCHEMA.md](docs/SCHEMA.md)
- **For systems that read this database (Tim):** [docs/API.md](docs/API.md)
- **Running on GitHub (scheduled sync, live page):** [docs/HOSTING.md](docs/HOSTING.md)

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                    # then edit
docker compose up -d                    # or any Postgres 16
set -a; . ./.env; set +a
.venv/bin/python -m msku migrate
```

The Google service-account key goes in `secrets/` (git-ignored). Share each sheet with
`master-sku-db@grenco-master-sku.iam.gserviceaccount.com` as **Viewer**.

## Day to day

```bash
scripts/dev-db.sh                           # cloud sessions only: start the local Postgres
.venv/bin/python -m msku sync               # the normal routine: fetch, read decisions, import, rewrite outputs sheet
.venv/bin/python -m msku sync --dry-run     # same, but show what would change and save nothing
.venv/bin/python -m msku fetch              # read the sheets (read-only) into .cache/sources
.venv/bin/python -m msku import --dry-run   # show what would change, save nothing
.venv/bin/python -m msku import             # load; running it twice changes nothing
.venv/bin/python -m msku conflicts          # open disagreements between sources
.venv/bin/python -m msku resolve 'GPM-001-APZZ|upc' 811736020343 --note "Per Ken"
.venv/bin/python -m msku preview            # build master-sku-preview.html (no costs)
.venv/bin/python -m pytest -q               # tests (need a local Postgres)
```

## How an import works

1. **Fetch:** every tab of the five sheets is read with read-only scopes and cached.
2. **Stage:** every row goes into `staging.raw_row` with its sheet, tab and row number. Cost columns are blanked.
3. **Map:** `msku/consolidate.py` applies the rules in `msku/mapping_rules.py` (Ken's decisions) and `msku/rules.py` (validation and parsing).
4. **Load:** `msku/db.py` upserts. `updated_at` and `version` only move when a value really changes. Prices and costs are effective-dated, and tier moves are recorded.
5. **Conflicts:** disagreements between sources go in `ops.conflict` and are never silently resolved. Decisions live in `ops.conflict_resolution` and are reapplied on every import. If the sources change, the conflict reopens.

## The outputs spreadsheet

`sync` writes to a separate spreadsheet, **"Master SKU Database – Outputs"**, never to Ken's source sheets (the code refuses them).

| Tab | Contents |
|---|---|
| Read me | What each tab is and when it was last updated |
| Master SKU List | Every SKU: tier, prices by region/tier, UPC, HTS, stock, flags, SKU ID. No costs. |
| Conflicts | Disagreements for Ken. He types the answer in the yellow **Your decision** column (dropdown of the source values, or free text) and an optional note. The next sync reads it first, records it in `ops.conflict_resolution`, applies it and remembers it. |
| Fix list (other systems) | Values in Cin7 or the master sheet that differ from the price list. The price list wins (Ken's rule), so these are to-dos for whoever maintains those systems. |

Before each rewrite, the previous version of each tab is saved as a hidden "Backup …" tab (the last 3 are kept).
Decisions are checked: a price must read as a price and a UPC as 11–14 digits. If the sources changed after the row was written, the decision is not applied and the row asks again.

## Not done yet

- **Public sites** (gpen.com, stundenglass.com, asset portals): blocked by this environment's network policy.
- **Outputs sheet:** waiting for Ken to create "Master SKU Database – Outputs" and share it as Editor.
- **In-development SKUs:** list to come from Ken.
- **Hosting:** Jordan decides. Everything here runs locally.
