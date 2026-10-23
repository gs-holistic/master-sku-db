"""Write-back to the "Master SKU Database – Outputs" spreadsheet, and read Ken's conflict decisions from it.

Safety rules:
- Only ever writes to the outputs spreadsheet. Refuses any spreadsheet that is one of the import sources.
- Backs up every tab it is about to rewrite (hidden "Backup …" tabs, the last few kept).
- Decisions are read BEFORE the Conflicts tab is rewritten, so nothing Ken typed is lost.
- No costs are ever written.
"""
import os
import re
from datetime import datetime, timezone

from . import mapping_rules as R
from .rules import money, upc

OUTPUT_NAME = "Master SKU Database – Outputs"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.metadata.readonly"]
BACKUPS_KEPT = 3

TAB_README = "Read me"
TAB_SKUS = "Master SKU List"
TAB_CONFLICTS = "Conflicts"
TAB_FIXES = "Fix list (other systems)"

CONFLICT_HEADER = ["SKU", "Type", "Issue", "What each source says", "Your decision", "Your note", "Status",
                   "Decided by", "Decided at", "Key (do not edit)", "Check (do not edit)"]
COL_DECISION, COL_NOTE, COL_KEY, COL_HASH = 4, 5, 9, 10
PRICE_TIER_LABEL = {"msrp": "MSRP", "map": "MAP (B2B)", "wholesale": "Wholesale", "distribution": "Distribution"}
SHORT_SOURCE = {R.SPREADSHEETS["prices"][1]: "Price list", R.SPREADSHEETS["master"][1]: "Master SKU list"}


class Sheet:
    """Thin wrapper over the Sheets API so tests can use a fake."""

    def __init__(self, service, spreadsheet_id):
        self.api, self.id = service.spreadsheets(), spreadsheet_id

    def tabs(self):
        meta = self.api.get(spreadsheetId=self.id, fields="sheets(properties(sheetId,title,hidden))").execute()
        return {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}

    def read(self, tab):
        return self.api.values().get(spreadsheetId=self.id, range=f"'{tab}'").execute().get("values", [])

    def write(self, tab, rows):
        self.api.values().clear(spreadsheetId=self.id, range=f"'{tab}'").execute()
        if rows:
            self.api.values().update(spreadsheetId=self.id, range=f"'{tab}'!A1", valueInputOption="RAW",
                                     body={"values": rows}).execute()

    def batch(self, requests):
        if requests:
            return self.api.batchUpdate(spreadsheetId=self.id, body={"requests": requests}).execute()


def open_output_sheet():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "secrets/google-service-account.json"), scopes=SCOPES)
    sid = os.environ.get("MSKU_OUTPUT_SHEET_ID")
    if not sid:
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        # "contains" so a hyphen instead of the en dash in the name still matches
        files = drive.files().list(q="name contains 'Master SKU Database' and name contains 'Outputs' and "
                                     "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
                                   fields="files(id,name,capabilities(canEdit))").execute()["files"]
        if not files:
            raise SystemExit(f'No spreadsheet named "{OUTPUT_NAME}" is shared with the service account yet.')
        if len(files) > 1:
            raise SystemExit(f'{len(files)} spreadsheets are named "{OUTPUT_NAME}". Set MSKU_OUTPUT_SHEET_ID to pick one.')
        if not files[0].get("capabilities", {}).get("canEdit"):
            raise SystemExit(f'"{OUTPUT_NAME}" is shared as Viewer. Share it with the service account as Editor.')
        sid = files[0]["id"]
    check_target(sid)
    return Sheet(build("sheets", "v4", credentials=creds, cache_discovery=False), sid)


def check_target(spreadsheet_id):
    if spreadsheet_id in {sid for sid, _ in R.SPREADSHEETS.values()}:
        raise SystemExit("Refusing to write: that spreadsheet is one of Ken's source sheets.")


# ---------- reading decisions
def read_decisions(sheet, conn, actor="Ken (Outputs sheet)"):
    """Record every new decision typed in the Conflicts tab. Returns (recorded, problems)."""
    from .db import resolve
    if TAB_CONFLICTS not in sheet.tabs():
        return 0, []
    rows = sheet.read(TAB_CONFLICTS)
    current = {fp: (h, kind) for fp, h, kind in conn.execute("SELECT fingerprint, values_hash, kind FROM ops.conflict")}
    recorded = {fp: v for fp, v in conn.execute("SELECT fingerprint, chosen_value FROM ops.conflict_resolution")}
    n, problems = 0, []
    for i, r in enumerate(rows[1:], start=2):
        get = lambda c: str(r[c]).strip() if c < len(r) else ""
        fp, decision, note, h = get(COL_KEY), get(COL_DECISION), get(COL_NOTE), get(COL_HASH)
        if not fp or not decision or fp not in current:
            continue
        if h != current[fp][0]:
            problems.append(f"Row {i} ({fp}): the sources changed after this row was written; decide again after the next sync")
            continue
        value, err = normalise_decision(current[fp][1], decision)
        if err:
            problems.append(f"Row {i} ({fp}): {err}")
            continue
        if recorded.get(fp) == value:
            continue
        resolve(conn, fp, value, actor, note or None, source="Outputs sheet")
        n += 1
    return n, problems


def normalise_decision(kind, text):
    """Check a typed decision fits the conflict type. Returns (value, error)."""
    if kind.startswith("Price"):
        v = money(text)
        return (f"{v:.2f}", None) if v is not None and v >= 0 else (None, f"couldn't read {text!r} as a price")
    if kind == "UPC":
        digits = re.sub(r"\D", "", text)
        return (digits, None) if upc(digits) else (None, f"{text!r} isn't an 11–14 digit UPC")
    return text, None


# ---------- writing
def write_all(sheet, conn):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tabs = sheet.tabs()
    _ensure_tabs(sheet, tabs, [TAB_README, TAB_SKUS, TAB_CONFLICTS, TAB_FIXES])
    tabs = sheet.tabs()
    for t in (TAB_SKUS, TAB_CONFLICTS, TAB_FIXES):
        _backup(sheet, tabs, t, stamp)
    tabs = sheet.tabs()
    skus = sku_rows(conn)
    conflicts, options = conflict_rows(conn)
    fixes = fix_rows(conn)
    sheet.write(TAB_README, readme_rows(stamp, len(skus) - 1, len(conflicts) - 1, len(fixes) - 1))
    sheet.write(TAB_SKUS, skus)
    sheet.write(TAB_CONFLICTS, conflicts)
    sheet.write(TAB_FIXES, fixes)
    sheet.batch(_format_requests(tabs, skus, conflicts, fixes, options))
    return {"skus": len(skus) - 1, "conflicts": len(conflicts) - 1, "fixes": len(fixes) - 1}


def _ensure_tabs(sheet, tabs, wanted):
    sheet.batch([{"addSheet": {"properties": {"title": t}}} for t in wanted if t not in tabs])


def _backup(sheet, tabs, tab, stamp):
    if tab not in tabs or not sheet.read(tab):
        return
    name, k = f"Backup {tab} {stamp}"[:95], 2
    while name in tabs:                     # two syncs in the same minute
        name, k = f"Backup {tab} {stamp} ({k})"[:99], k + 1
    reply = sheet.batch([{"duplicateSheet": {"sourceSheetId": tabs[tab]["sheetId"], "newSheetName": name,
                                             "insertSheetIndex": 99}}])
    new_id = reply["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
    sheet.batch([{"updateSheetProperties": {"properties": {"sheetId": new_id, "hidden": True}, "fields": "hidden"}}])
    old = sorted((t for t in sheet.tabs() if t.startswith(f"Backup {tab} ")), reverse=True)[BACKUPS_KEPT:]
    all_tabs = sheet.tabs()
    sheet.batch([{"deleteSheet": {"sheetId": all_tabs[t]["sheetId"]}} for t in old])


def readme_rows(stamp, n_skus, n_conflicts, n_fixes):
    return [
        ["Master SKU Database – Outputs"],
        [f"Last updated {stamp} by the Master SKU database. Do not edit the other tabs except the two yellow columns on Conflicts."],
        [],
        ["Tab", "What it is"],
        [TAB_SKUS, f"{n_skus} SKUs with tier, prices, UPC and stock. Rewritten on every sync. Costs are never included."],
        [TAB_CONFLICTS, f"{n_conflicts} places where sources disagree. Type the correct value in 'Your decision' (pick from the list or type your own), "
                        "add a note if useful. The next sync records it, applies it, and remembers it."],
        [TAB_FIXES, f"{n_fixes} values in Cin7 or the master sheet that differ from the price list. The price list wins; "
                    "these are a to-do list for whoever maintains those systems."],
        [],
        ["Tiers", "1 Active = on the price list · 2 Falling = off the price list, stock in counted locations · 3 Discontinued / out of stock"],
        ["Backups", f"Before each rewrite, the previous version of each tab is kept as a hidden 'Backup …' tab (last {BACKUPS_KEPT})."],
    ]


def sku_rows(conn):
    price_cols = [(r, t) for r in ("US", "CA", "EU") for t in ("msrp", "map", "wholesale", "distribution")]
    prices = {}
    for sid, region, tier, cur, amt in conn.execute("SELECT sku_id, region, price_tier, currency, amount FROM api.prices"):
        prices[(sid, region, tier)] = f"{amt:,.2f} {cur}"
    stock = {sid: av for sid, av in conn.execute("SELECT sku_id, available_counted FROM api.stock")}
    hdr = ["SKU", "Name", "Brand", "Family", "Category", "Pack type", "Tier", "Tier since", "Tier reason", "UPC", "HTS code",
           *[f"{r} {PRICE_TIER_LABEL[t]}" for r, t in price_cols], "Available (counted)", "NEW", "Review flags", "SKU ID", "Updated"]
    rows = [hdr]
    for (sid, code, name, brand, family, cat, pack, tier, since, reason, upc_, hts, new, flags, upd) in conn.execute("""
            SELECT a.sku_id, a.sku_code, a.name, a.brand, a.family, a.category, a.pack_type, a.tier, a.tier_since, a.tier_reason,
                   a.upc, a.hts_code, a.is_new, s.review_flags, a.updated_at
            FROM api.skus a JOIN core.sku s ON s.id = a.sku_id ORDER BY a.tier, a.brand, a.sku_code"""):
        rows.append([code, name or "", brand or "", family or "", cat or "", pack.replace("_", " "), tier,
                     since.isoformat() if since else "", reason or "", upc_ or "", hts or "",
                     *[prices.get((sid, r, t), "") for r, t in price_cols],
                     float(stock[sid]) if stock.get(sid) is not None else "", "NEW" if new else "",
                     "; ".join(flags or []), str(sid), upd.strftime("%Y-%m-%d %H:%M")])
    return rows


def conflict_rows(conn):
    rows, options = [CONFLICT_HEADER], []
    for fp, code, kind, detail, status, cands, h, dec, by, at in conn.execute("""
            SELECT c.fingerprint, c.sku_code, c.kind, c.detail, c.status, c.candidates, c.values_hash,
                   r.chosen_value, r.decided_by, r.decided_at
            FROM ops.conflict c LEFT JOIN ops.conflict_resolution r USING (fingerprint)
            WHERE c.status <> 'cleared'
            ORDER BY (c.status = 'resolved'), c.kind, c.sku_code"""):
        says = "\n".join(f"{c['value']}  ←  {SHORT_SOURCE.get(c['source'], c['source'])} {c.get('ref', '')}".strip() for c in cands)
        shown_status = {"open": "Needs decision", "reopened": "Sources changed: decide again", "resolved": "Decided"}[status]
        rows.append([code, kind, detail, says, dec if status == "resolved" else "", "", shown_status,
                     by or "", at.strftime("%Y-%m-%d") if at else "", fp, h])
        opts = []
        for c in cands:
            v = str(c["value"])
            v = f"{money(v):.2f}" if kind.startswith("Price") and money(v) is not None else v
            if v not in opts:
                opts.append(v)
        options.append(opts)
    return rows, options


def fix_rows(conn):
    rows = [["SKU", "Field", "System to fix", "Value there now", "Correct value", "Correct value comes from", "Where (in that system)", "First seen"]]
    for code, field, source, sv, cv, sref, cref, first in conn.execute("""
            SELECT sku_code, field, source, source_value, correct_value, source_ref, correct_ref, first_seen
            FROM ops.source_fix WHERE status = 'open' ORDER BY source, sku_code, field"""):
        rows.append([code, field, source, sv, cv, cref or "", sref or "", first.isoformat()])
    return rows


def _format_requests(tabs, skus, conflicts, fixes, options):
    req = []
    for name, rows in ((TAB_SKUS, skus), (TAB_CONFLICTS, conflicts), (TAB_FIXES, fixes), (TAB_README, None)):
        sid = tabs[name]["sheetId"]
        req.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1 if rows else 0}},
                                              "fields": "gridProperties.frozenRowCount"}})
        req.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0 if rows else 3, "endRowIndex": 1 if rows else 4},
                                   "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}})
        if rows:
            req.append({"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(rows[0])}}})
    c = tabs[TAB_CONFLICTS]["sheetId"]
    n = len(conflicts)
    yellow = {"red": 1, "green": 0.95, "blue": 0.7}
    grey = {"red": 0.6, "green": 0.6, "blue": 0.6}
    req += [
        {"repeatCell": {"range": {"sheetId": c, "startRowIndex": 0, "endRowIndex": n, "startColumnIndex": COL_DECISION, "endColumnIndex": COL_NOTE + 1},
                        "cell": {"userEnteredFormat": {"backgroundColor": yellow}}, "fields": "userEnteredFormat.backgroundColor"}},
        {"repeatCell": {"range": {"sheetId": c, "startRowIndex": 0, "endRowIndex": n, "startColumnIndex": COL_KEY, "endColumnIndex": COL_HASH + 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": grey}}}, "fields": "userEnteredFormat.textFormat.foregroundColor"}},
        {"repeatCell": {"range": {"sheetId": c, "startRowIndex": 1, "endRowIndex": n, "startColumnIndex": 3, "endColumnIndex": 4},
                        "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat.wrapStrategy"}},
        {"updateDimensionProperties": {"range": {"sheetId": c, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
                                       "properties": {"pixelSize": 420}, "fields": "pixelSize"}},
    ]
    # dropdown of the values the sources gave; Ken can still type something else (strict = False)
    for i, opts in enumerate(options, start=1):
        if opts:
            req.append({"setDataValidation": {
                "range": {"sheetId": c, "startRowIndex": i, "endRowIndex": i + 1, "startColumnIndex": COL_DECISION, "endColumnIndex": COL_DECISION + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in opts]},
                         "strict": False, "showCustomUi": True}}})
    return req
