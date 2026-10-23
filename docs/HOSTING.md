# Running on GitHub

Two workflows in `.github/workflows/`:

| Workflow | When | What |
|---|---|---|
| **Tests** (`ci.yml`) | Every push and pull request | Runs the test suite against a throwaway Postgres |
| **Sync and publish** (`sync.yml`) | Daily at 13:17 UTC (about 6am Pacific), or on demand | Reads the sheets and the Conflicts decisions, loads the database, rewrites the "Master SKU Database – Outputs" sheet, and builds the SKU browser page |

## One-time setup (repository Settings)

1. **Secrets and variables → Actions → Secrets → New repository secret**
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: paste the **entire contents** of the service-account key file (`master-sku-db@grenco-master-sku.iam.gserviceaccount.com`). Use a freshly created key, not one that has been shared in chat or email.
   - `MSKU_DATABASE_URL` (optional): a permanent Postgres 16, e.g. `postgresql://user:password@host:5432/master_sku?sslmode=require`. **Without it**, each run rebuilds the database from the sheets. The view stays correct and conflict decisions are recovered from the outputs sheet, but price, tier and cost **history** isn't kept, and "tier since" dates show the run date.
2. **Run it:** Actions → **Sync and publish** → **Run workflow**.
3. **See the page:** open the finished run → **Artifacts** → `master-sku-page` → download and open `index.html`. Only people with access to the repository can download it.

## Live web page (GitHub Pages)

The page shows wholesale and distribution prices and stock, so publish it **only if the site can be private**:

1. Settings → **Pages** → Source: **GitHub Actions**.
2. If the organization is on GitHub Enterprise Cloud: set **Visibility: Private** (members only). If that option isn't offered, the site would be **public**, so stop here and use the artifact download instead.
3. Settings → Secrets and variables → Actions → **Variables** → New variable `PUBLISH_PAGES` = `true`.
4. Run **Sync and publish**. The Pages URL appears on the run summary and in Settings → Pages.

The page is never published unless `PUBLISH_PAGES` is `true`.

## What never leaves the database

Costs are not written to the outputs sheet, the page, the artifact or the `api` views. The key file is written to the runner's temp folder for the run and deleted at the end.
