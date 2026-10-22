# Master SKU database

One place for G Pen and Stündenglass product master data. It consolidates Ken's Google Sheets and the Cin7 inventory report, and serves read-only views to other systems.

- **Decisions and rules:** [DECISIONS.md](DECISIONS.md) (tiers, counted locations, exclusions, costs)
- **What the sheets contain:** [INVENTORY.md](INVENTORY.md)
- **Every table explained:** [docs/SCHEMA.md](docs/SCHEMA.md)
- **For systems that read this database (Tim):** [docs/API.md](docs/API.md)

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

## Not done yet

- **Public sites** (gpen.com, stundenglass.com, asset portals): blocked by this environment's network policy.
- **Write-back to Sheets:** needs Editor access on a new tab or copy. Ken's original sheets are never overwritten.
- **In-development SKUs:** list to come from Ken.
- **Hosting:** Jordan decides. Everything here runs locally.
