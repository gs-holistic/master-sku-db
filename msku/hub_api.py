"""HTTP API for the G Pen Hub (gpen-crm.vercel.app): read and write SKUs server to server.

A WSGI app with no framework, so it runs on any host (gunicorn, Vercel's Python runtime, Cloud Run...).
Docs: docs/HUB_API.md. Configuration, all from the environment, never from code:

  MSKU_API_DATABASE_URL  Postgres login in the msku_hub_api role, which can't see costs (python -m msku hub-login).
                         Never the owner's DATABASE_URL: the API refuses to start without this one.
  MSKU_API_KEYS          the x-api-key the Hub sends (python -m msku new-api-key). "new,old" while rotating.
                         (MSKU_API_KEY and MSKU_API_KEY_PREVIOUS are read too.)
  HUB_WEBHOOK_KEY        the key sent to the Hub when SKUs change (see msku/webhook.py)
  MSKU_ALLOW_HTTP=1      local development only: accept plain HTTP
"""
import hmac
import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs

import psycopg
from psycopg.rows import dict_row

from .db import HUB_PRICE_FIELDS, SKU_TABLES
from .webhook import notify
from .rules import check_code

STATUSES = ("draft", "active", "deprecated", "obsolete")
SPEC_INT = ("pack_size", "case_pack", "pallet_qty")
SPEC_TEXT = ("notes", "product_dims", "product_weight", "packaging_dims", "packaged_weight",
             "case_dims", "case_weight", "pallet_dims", "pallet_weight")
# Read-only prices: field -> (region, tier). Shown next to the Hub's five writable ones.
READ_PRICE_FIELDS = {"map": ("US", "map"), "msrp_ca": ("CA", "msrp"), "msrp_eu": ("EU", "msrp"),
                     "wholesale_ca": ("CA", "wholesale"), "wholesale_eu": ("EU", "wholesale")}
ALL_PRICE_FIELDS = {**HUB_PRICE_FIELDS, **READ_PRICE_FIELDS}
# A UK price the Hub hasn't set shows the US figure, in pounds (Ken, 2026-10-27).
UK_FROM_US = {"msrp_uk": "msrp", "wholesale_uk": "wholesale", "distro_uk": "distro"}
CURRENCY = {"US": "USD", "CA": "CAD", "EU": "EUR", "UK": "GBP"}
EXTRA = ("family", "category", "hts_code", "country_of_origin", "producer")
LINKS = ("cin7_id", "store_url", "asset_url")
LOCKED = ("name", "brand", "upc", *HUB_PRICE_FIELDS)   # sheet-fed fields: a Hub write wins (see db.hub_value)
WRITABLE = ("name", "brand", "status", "upc", *HUB_PRICE_FIELDS, *SPEC_INT, *SPEC_TEXT)
def _with_currency(fields):
    return tuple(x for f in fields for x in (f, f + "_currency"))


FIELDS = ("sku", "name", "brand", "status", "upc", *_with_currency(HUB_PRICE_FIELDS),
          "pack_size", "product_dims", "product_weight", "packaging_dims", "packaged_weight",
          "case_pack", "case_dims", "case_weight", "pallet_qty", "pallet_dims", "pallet_weight",
          "notes",
          # read-only
          "tier", *EXTRA, *_with_currency(READ_PRICE_FIELDS), *LINKS,
          "updated_at", "updated_by")
READ_ONLY = set(FIELDS) - {"sku", *WRITABLE, "updated_at"}
TIER_STATUS = {1: "active", 2: "deprecated", 3: "obsolete"}
AUDITED = SKU_TABLES
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MAX_BODY = 64 * 1024


class Reply(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body


def _error(status, message, fields=None):
    body = {"error": message}
    if fields:
        body["fields"] = fields
    return Reply(status, body)


# ---------- reading

_RECORDS = """
WITH pr AS (
  SELECT sku_id,""" + "".join(f"""
    max(amount) FILTER (WHERE region = '{r}' AND tier = '{t}' AND effective_to IS NULL) AS {f},"""
                               for f, (r, t) in ALL_PRICE_FIELDS.items()) + """
    max(updated_at) AS updated_at
  FROM core.price
  WHERE (region::text, tier::text) IN (""" + ", ".join(f"('{r}','{t}')" for r, t in ALL_PRICE_FIELDS.values()) + """)
  GROUP BY sku_id),
ext AS (
  SELECT sku_id, min(external_key) FILTER (WHERE system = 'cin7') AS cin7_id, max(updated_at) AS updated_at
  FROM core.external_id GROUP BY sku_id),
lnk AS (
  SELECT sku_id, min(url) FILTER (WHERE kind = 'store_page') AS store_url,
    min(url) FILTER (WHERE kind = 'asset_portal') AS asset_url, max(updated_at) AS updated_at
  FROM core.sku_link GROUP BY sku_id),
pk AS (
  SELECT sku_id, max(updated_at) AS updated_at,
    jsonb_object_agg(level, jsonb_build_object('l', length_mm, 'w', width_mm, 'h', height_mm, 'g', weight_g,
                                               'units', units_per_level, 'source', source)) AS levels
  FROM core.sku_packaging_level GROUP BY sku_id)
SELECT * FROM (
  SELECT s.id, s.code, s.name, b.name AS brand, s.upc, s.pack_type::text AS pack_type, s.pack_qty, s.is_new, t.tier,
    sp.status, sp.notes, sp.pack_size, sp.product_dims, sp.product_weight, sp.packaging_dims, sp.packaged_weight,
    sp.case_pack, sp.case_dims, sp.case_weight, sp.pallet_qty, sp.pallet_dims, sp.pallet_weight,
    """ + ", ".join(f"pr.{f}" for f in ALL_PRICE_FIELDS) + """, pk.levels, bpk.levels AS base_levels,
    f.name AS family, s.category, s.hts_code, s.country_of_origin, p.name AS producer,
    ext.cin7_id, lnk.store_url, coalesce(lnk.asset_url, f.asset_portal_url) AS asset_url,
    greatest(s.updated_at, t.updated_at, sp.updated_at, pr.updated_at, pk.updated_at, ext.updated_at,
             lnk.updated_at) AS updated_at,
    (SELECT a.actor FROM ops.audit_log a WHERE a.sku_key = s.id::text AND a.table_name = ANY(%(audited)s)
     ORDER BY a.id DESC LIMIT 1) AS updated_by
  FROM core.sku s
  LEFT JOIN core.brand b ON b.id = s.brand_id
  LEFT JOIN core.family f ON f.id = s.family_id
  LEFT JOIN core.producer p ON p.id = s.producer_id
  LEFT JOIN ext ON ext.sku_id = s.id
  LEFT JOIN lnk ON lnk.sku_id = s.id
  LEFT JOIN core.sku_tier t ON t.sku_id = s.id
  LEFT JOIN core.sku_spec sp ON sp.sku_id = s.id
  LEFT JOIN pr ON pr.sku_id = s.id
  LEFT JOIN pk ON pk.sku_id = s.id
  LEFT JOIN pk bpk ON bpk.sku_id = s.base_sku_id) x
"""


def _trim(x, places):
    return f"{x:.{places}f}".rstrip("0").rstrip(".")


def _dims(level):
    if level and all(level.get(k) is not None for k in "lwh"):
        return " x ".join(_trim(float(level[k]), 1) for k in "lwh") + " mm"
    return None


def _weight(level):
    g = level.get("g") if level else None
    if g is None:
        return None
    g = float(g)
    return f"{_trim(g / 1000, 3)} kg" if g >= 1000 else f"{_trim(g, 1)} g"


def _unit_is_packaging(level):
    """The 'unit' level holds package dimensions from the G Pen master sheet ("Package Length"...) and product
    dimensions from the Stündenglass master sheet and both SKU templates ("Product Dimensions")."""
    src = (level or {}).get("source") or ""
    return "master G Pen" in src and "Template" not in src


def _money(x):
    return None if x is None else float(x)


def iso(ts):
    """Milliseconds, UTC: what a JavaScript Date keeps, so the Hub can echo updated_at back exactly."""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z") if ts else None


def derived_from_packaging(levels):
    levels = levels or {}
    unit, case, pallet = levels.get("unit"), levels.get("master_case"), levels.get("pallet")
    packaging = _unit_is_packaging(unit)
    return {
        "product_dims": None if packaging else _dims(unit), "product_weight": None if packaging else _weight(unit),
        "packaging_dims": _dims(unit) if packaging else None, "packaged_weight": _weight(unit) if packaging else None,
        "case_pack": (case or {}).get("units"), "case_dims": _dims(case), "case_weight": _weight(case),
        "pallet_qty": (pallet or {}).get("units"), "pallet_dims": _dims(pallet), "pallet_weight": _weight(pallet),
    }


def _pack_size(r):
    if r["pack_size"] is not None:
        return r["pack_size"]
    if r["pack_qty"] is not None:
        return r["pack_qty"]
    if r["pack_type"] in ("single_unit", "kit"):   # a kit is one boxed product
        return 1
    # A POP or master case SKU: the sheets record its unit count on the single unit it holds.
    level = {"inner_pack": "inner_pack", "pop_display": "inner_pack", "master_case": "master_case"}.get(r["pack_type"])
    return ((r["base_levels"] or {}).get(level) or {}).get("units") if level else None


def record(r):
    """One SKU in the Hub's field names. A value the Hub wrote wins; otherwise what the sheets give."""
    d = derived_from_packaging(r["levels"])
    out = {
        "sku": r["code"], "name": r["name"], "brand": r["brand"],
        "status": r["status"] or ("draft" if r["is_new"] or r["tier"] is None else TIER_STATUS[r["tier"]]),
        "upc": r["upc"],
        **{f: _money(r[f]) for f in ALL_PRICE_FIELDS},
        **{f"{f}_currency": CURRENCY[region] for f, (region, _) in ALL_PRICE_FIELDS.items()},
        **{uk: _money(r[uk] if r[uk] is not None else r[us]) for uk, us in UK_FROM_US.items()},
        **{f: r[f] for f in (*EXTRA, *LINKS)},
        "pack_size": _pack_size(r),
        **{f: r[f] if r[f] is not None else d[f] for f in d},
        "notes": r["notes"], "tier": r["tier"], "updated_at": iso(r["updated_at"]), "updated_by": r["updated_by"],
    }
    return {f: out[f] for f in FIELDS}


def fetch(conn, where="TRUE", params=None, order="code"):
    rows = conn.cursor(row_factory=dict_row).execute(
        _RECORDS + f" WHERE {where} ORDER BY {order}", {"audited": list(AUDITED), **(params or {})}).fetchall()
    return [record(r) for r in rows]


def fetch_one(conn, code):
    found = fetch(conn, "code = %(code)s", {"code": code})
    return found[0] if found else None


# ---------- validation

def _parse_time(text, name):
    try:
        t = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        raise _error(400, f"{name} must be an ISO 8601 timestamp, e.g. 2026-10-26T18:00:00.000Z",
                     {name: "not an ISO 8601 timestamp"})
    if t.tzinfo is None:
        raise _error(400, f"{name} needs a time zone, e.g. a trailing Z for UTC", {name: "no time zone"})
    return t


def _ms(t):
    return t.astimezone(timezone.utc).replace(microsecond=t.microsecond // 1000 * 1000)


def validate(conn, body, creating, code=None):
    """Check every field sent. Returns (values, changed_by); raises 400 listing each bad field."""
    if not isinstance(body, dict):
        raise _error(400, "The request body must be a JSON object")
    errors, values = {}, {}
    brands = {n.casefold(): n for (n,) in conn.execute("SELECT name FROM core.brand")}

    changed_by = body.get("changed_by")
    if not isinstance(changed_by, str) or not EMAIL.fullmatch(changed_by.strip()):
        errors["changed_by"] = "required: the email of the person making the change"

    for k, v in body.items():
        if k in ("changed_by",):
            continue
        if k == "sku":
            if not creating:
                if v != code:
                    errors[k] = "a SKU # can't be changed"
            elif not isinstance(v, str) or not v.strip():
                errors[k] = "required, as text"
            elif len(v.strip()) > 80 or "/" in v or any(ord(c) < 32 for c in v):
                errors[k] = "must be at most 80 characters, without '/' or control characters"
            else:
                values[k] = v.strip()
        elif k == "updated_at":
            if creating:
                errors[k] = "set by the database; don't send it when creating a SKU"
        elif k in READ_ONLY:
            errors[k] = "read-only" + {"updated_by": "; send changed_by instead",
                                       "tier": ": the tier comes from the price list and Cin7 stock"}.get(
                k, ": set by the price's region" if k.endswith("_currency") else ": comes from the sheets and Cin7")
        elif k not in WRITABLE:
            errors[k] = "unknown field"
        elif k == "name":
            if not isinstance(v, str) or not v.strip():
                errors[k] = "must be non-empty text"
            elif len(v) > 300:
                errors[k] = "must be at most 300 characters"
            else:
                values[k] = v.strip()
        elif k == "brand":
            if not isinstance(v, str) or v.strip().casefold() not in brands:
                errors[k] = "must be one of: " + ", ".join(sorted(brands.values()))
            else:
                values[k] = brands[v.strip().casefold()]
        elif k == "status":
            if v not in STATUSES:
                errors[k] = "must be one of: " + ", ".join(STATUSES)
            else:
                values[k] = v
        elif k == "upc":
            if v is None or v == "":
                values[k] = None
            elif not isinstance(v, str):
                errors[k] = "send the UPC as text (a JSON number would drop leading zeros)"
            elif not re.fullmatch(r"\d{8,14}", v.strip()):
                errors[k] = "digits only, 8 to 14 of them"
            else:
                values[k] = v.strip()
        elif k in HUB_PRICE_FIELDS:
            if v is None:
                values[k] = None
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                errors[k] = "must be a number (no $ sign or text), or null to clear it"
            else:
                try:
                    d = Decimal(str(v))
                except InvalidOperation:
                    d = None
                if d is None or not d.is_finite() or d < 0 or d > 1_000_000:
                    errors[k] = "must be between 0 and 1,000,000"
                elif d != d.quantize(Decimal("0.01")):
                    errors[k] = "at most 2 decimal places"
                else:
                    values[k] = d
        elif k in SPEC_INT:
            if v is None:
                values[k] = None
            elif isinstance(v, bool) or not isinstance(v, int):
                errors[k] = "must be a whole number, or null"
            elif not 0 <= v <= 10_000_000:
                errors[k] = "must be between 0 and 10,000,000"
            else:
                values[k] = v
        elif k in SPEC_TEXT:
            if v is None or (isinstance(v, str) and not v.strip()):
                values[k] = None
            elif not isinstance(v, str):
                errors[k] = 'must be text with units, e.g. "4.5 x 2 x 1 in" or "3.2 oz"'
            elif len(v) > (5000 if k == "notes" else 100):
                errors[k] = f"must be at most {5000 if k == 'notes' else 100} characters"
            else:
                values[k] = v.strip() if k != "notes" else v
    if creating and "sku" not in body:
        errors["sku"] = "required"
    if errors:
        raise _error(400, "Some fields are invalid", errors)
    return values, changed_by.strip()


# ---------- writing

def _lock(cur, sku_id, field, value, by):
    cur.execute("""INSERT INTO core.hub_lock (sku_id, field, value, set_by) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (sku_id, field) DO UPDATE SET value = EXCLUDED.value, set_by = EXCLUDED.set_by""",
                (sku_id, field, None if value is None else str(value), by))


def _set_price(cur, sku_id, field, amount, by):
    """Effective-dated, like the importer: a change closes the current row and opens a new one."""
    region, tier = HUB_PRICE_FIELDS[field]
    old = cur.execute("""SELECT id, amount FROM core.price WHERE sku_id = %s AND region = %s AND tier = %s
                         AND effective_to IS NULL FOR UPDATE""", (sku_id, region, tier)).fetchone()
    if (old is None and amount is None) or (old and amount is not None and Decimal(old[1]) == amount):
        return False
    today = date.today()
    if old:
        cur.execute("UPDATE core.price SET effective_to = %s WHERE id = %s", (today, old[0]))
    if amount is not None:
        cur.execute("""INSERT INTO core.price (sku_id, region, tier, currency, amount, effective_from, source, source_ref)
                       VALUES (%s, %s, %s, %s, %s, %s, 'G Pen Hub', %s)""",
                    (sku_id, region, tier, CURRENCY[region], amount, today, by))
    return True


def apply(conn, sku_id, values, by, creating=False):
    cur = conn.cursor()
    now = cur.execute("SELECT name, upc, (SELECT name FROM core.brand WHERE id = brand_id) FROM core.sku WHERE id = %s",
                      (sku_id,)).fetchone()
    current = {"name": now[0], "upc": now[1], "brand": now[2]}
    for f in ("name", "upc"):
        if f in values and (creating or values[f] != current[f]):
            cur.execute(f"UPDATE core.sku SET {f} = %s WHERE id = %s", (values[f], sku_id))
            _lock(cur, sku_id, f, values[f], by)
    if "brand" in values and (creating or values["brand"] != current["brand"]):
        cur.execute("UPDATE core.sku SET brand_id = (SELECT id FROM core.brand WHERE name = %s) WHERE id = %s",
                    (values["brand"], sku_id))
        _lock(cur, sku_id, "brand", values["brand"], by)
    for f in HUB_PRICE_FIELDS:
        if f in values and (_set_price(cur, sku_id, f, values[f], by) or creating):
            _lock(cur, sku_id, f, values[f], by)
    spec = {f: values[f] for f in ("status", *SPEC_INT, *SPEC_TEXT) if f in values}
    if spec:
        cols = ", ".join(spec)
        cur.execute(f"""INSERT INTO core.sku_spec (sku_id, {cols}) VALUES (%s, {", ".join(["%s"] * len(spec))})
                        ON CONFLICT (sku_id) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in spec)}""",
                    (sku_id, *spec.values()))


def create(conn, body):
    with conn.transaction():
        values, by = validate(conn, body, creating=True)
        conn.execute("SELECT set_config('msku.actor', %s, true)", (by,))
        clash = conn.execute("SELECT code FROM core.sku WHERE lower(code) = lower(%s)", (values["sku"],)).fetchone()
        if clash:
            raise Reply(409, {"error": f"SKU {clash[0]} already exists", "current": fetch_one(conn, clash[0])})
        sku_id = conn.execute("""INSERT INTO core.sku (code, origin, code_check) VALUES (%s, 'hub', %s)
                                 ON CONFLICT (code) DO NOTHING RETURNING id""",
                              (values["sku"], check_code(values["sku"]))).fetchone()
        if sku_id is None:   # created by someone else a moment ago
            raise Reply(409, {"error": f"SKU {values['sku']} already exists", "current": fetch_one(conn, values["sku"])})
        apply(conn, sku_id[0], values, by, creating=True)
        created = fetch_one(conn, values["sku"])
    notify([created["sku"]], created["updated_at"])   # after the commit
    return created


def update(conn, code, body):
    with conn.transaction():
        row = conn.execute("SELECT id FROM core.sku WHERE code = %s FOR UPDATE", (code,)).fetchone()
        if not row:
            raise _error(404, f"No SKU {code}")
        if not isinstance(body, dict) or "updated_at" not in body:
            raise _error(400, "Send updated_at as you last saw it, so a newer change isn't overwritten",
                         {"updated_at": "required"})
        seen = _parse_time(body["updated_at"], "updated_at")
        values, by = validate(conn, body, creating=False, code=code)
        current = fetch_one(conn, code)
        if _ms(seen) != _ms(datetime.fromisoformat(current["updated_at"])):
            raise Reply(409, {"error": "This SKU changed since you loaded it. Nothing was saved; here is the current record.",
                              "current": current})
        conn.execute("SELECT set_config('msku.actor', %s, true)", (by,))
        apply(conn, row[0], values, by)
        after = fetch_one(conn, code)
    if after["updated_at"] != current["updated_at"]:   # a PATCH that changed nothing doesn't ping
        notify([code], after["updated_at"])
    return after


# ---------- history

_SKU_COLS = {"code": "sku", "name": "name", "upc": "upc", "brand_id": "brand", "family_id": "family",
             "category": "category", "hts_code": "hts_code", "country_of_origin": "country_of_origin",
             "producer_id": "producer"}
_SPEC_COLS = ("status", *SPEC_INT, *SPEC_TEXT)
_PRICE_FIELD = {v: k for k, v in ALL_PRICE_FIELDS.items()}
_UK_OF = {us: uk for uk, us in UK_FROM_US.items()}
_LINK_FIELD = {"store_page": "store_url", "asset_portal": "asset_url"}


def _level_fields(row):
    if not row:
        return {}
    level = {"l": row.get("length_mm"), "w": row.get("width_mm"), "h": row.get("height_mm"),
             "g": row.get("weight_g"), "units": row.get("units_per_level"), "source": row.get("source")}
    d = derived_from_packaging({row["level"]: level})
    return {k: v for k, v in d.items() if (row["level"] == "master_case" and k.startswith("case"))
            or (row["level"] == "pallet" and k.startswith("pallet"))
            or (row["level"] == "unit" and k.startswith(("product", "packag")))}


def changes(conn, since=None, cursor=None, limit=500):
    """Field-level changes, oldest first: one audit row can hold several fields."""
    where, params = ["a.table_name = ANY(%s)", "a.sku_key IS NOT NULL"], [list(AUDITED)]
    if cursor is not None:
        where.append("a.id > %s")
        params.append(cursor)
    if since is not None:
        where.append("date_trunc('milliseconds', a.at) > %s")
        params.append(since)
    rows = conn.cursor(row_factory=dict_row).execute(
        f"""SELECT a.id, a.table_name, a.action, a.actor, a.at, a.before, a.after, s.code
            FROM ops.audit_log a JOIN core.sku s ON s.id::text = a.sku_key
            WHERE {" AND ".join(where)} ORDER BY a.id LIMIT %s""", (*params, limit)).fetchall()
    names = {"brand_id": dict(conn.execute("SELECT id, name FROM core.brand").fetchall()),
             "family_id": dict(conn.execute("SELECT id, name FROM core.family").fetchall()),
             "producer_id": dict(conn.execute("SELECT id, name FROM core.producer").fetchall())}
    spec_set = {(str(k), c) for k, *vals in conn.execute(f"SELECT sku_id, {', '.join(_SPEC_COLS)} FROM core.sku_spec")
                for c, v in zip(_SPEC_COLS, vals) if v is not None}
    out = []
    for r in rows:
        before, after = r["before"] or {}, r["after"] or {}
        pairs = []
        if r["table_name"] == "core.sku":
            for col, field in _SKU_COLS.items():
                old, new = before.get(col), after.get(col)
                if col in names:
                    old, new = names[col].get(old), names[col].get(new)
                pairs.append((field, old, new))
        elif r["table_name"] == "core.sku_spec":
            pairs = [(c, before.get(c), after.get(c)) for c in _SPEC_COLS]
        elif r["table_name"] == "core.sku_tier":
            pairs = [("tier", before.get("tier"), after.get("tier"))]
        elif r["table_name"] == "core.price":
            p = after or before
            field = _PRICE_FIELD.get((p["region"], p["tier"]))
            if not field:
                continue
            if r["action"] == "INSERT":
                prev = conn.execute("""SELECT amount FROM core.price WHERE sku_id = %s AND region = %s AND tier = %s
                                       AND id < %s ORDER BY id DESC LIMIT 1""",
                                    (p["sku_id"], p["region"], p["tier"], p["id"])).fetchone()
                pairs = [(field, _money(prev[0]) if prev else None, _money(p["amount"]))]
            elif before.get("effective_to") is None and after.get("effective_to") is not None:
                successor = conn.execute("""SELECT 1 FROM core.price WHERE sku_id = %s AND region = %s AND tier = %s
                                            AND id > %s""", (p["sku_id"], p["region"], p["tier"], p["id"])).fetchone()
                if not successor:      # closed with nothing after it: the price was removed
                    pairs = [(field, _money(before["amount"]), None)]
        elif r["table_name"] == "core.external_id":
            p = after or before
            if p["system"] == "cin7":
                pairs = [("cin7_id", before.get("external_key"), after.get("external_key"))]
        elif r["table_name"] == "core.sku_link":
            p = after or before
            if p["kind"] in _LINK_FIELD:
                pairs = [(_LINK_FIELD[p["kind"]], before.get("url"), after.get("url"))]
        elif r["table_name"] == "core.sku_packaging_level":
            old, new = _level_fields(before), _level_fields(after)
            sku_id = (after or before)["sku_id"]   # a value the Hub set hides what the sheets say
            pairs = [(f, old.get(f), new.get(f)) for f in sorted(set(old) | set(new)) if (sku_id, f) not in spec_set]
        if r["table_name"] == "core.price" and pairs and pairs[0][0] in _UK_OF:
            # A UK price the Hub hasn't set follows the US one, so it changed too
            own = conn.execute("""SELECT 1 FROM core.price WHERE sku_id = %s AND region = 'UK' AND tier = %s
                                  AND effective_from <= %s::date AND (effective_to IS NULL OR effective_to > %s::date)""",
                               (p["sku_id"], p["tier"], r["at"], r["at"])).fetchone()
            if not own:
                pairs += [(_UK_OF[f], old, new) for f, old, new in pairs]
        for field, old, new in pairs:
            if old != new and not (r["table_name"] == "core.sku" and r["action"] == "INSERT" and new is None):
                out.append({"sku": r["code"], "field": field, "old_value": old, "new_value": new,
                            "changed_by": r["actor"], "changed_at": iso(r["at"])})
    next_cursor = str(rows[-1]["id"]) if len(rows) == limit else None
    return out, next_cursor


# ---------- HTTP

def _keys():
    keys = os.environ.get("MSKU_API_KEYS", "").split(",")   # "new,old" while rotating
    keys += [os.environ.get("MSKU_API_KEY", ""), os.environ.get("MSKU_API_KEY_PREVIOUS", "")]
    return [k.strip() for k in keys if k.strip()]


def _authorised(environ):
    given = environ.get("HTTP_X_API_KEY", "")
    ok = False
    for k in _keys():   # compare against every key, in constant time, so timing reveals nothing
        ok |= hmac.compare_digest(given.encode(), k.encode())
    return ok and bool(given)


def _https(environ):
    if os.environ.get("MSKU_ALLOW_HTTP") == "1":
        return True
    proto = environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0].strip().lower()
    return proto == "https" or (not proto and environ.get("wsgi.url_scheme") == "https")


def _body(environ):
    try:
        n = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        n = 0
    if n > MAX_BODY:
        raise _error(413, f"The body is over {MAX_BODY // 1024} KB")
    raw = environ["wsgi.input"].read(n) if n else b""
    try:
        return json.loads(raw or b"null")
    except ValueError:
        raise _error(400, "The body isn't valid JSON")


def _connect():
    url = os.environ.get("MSKU_API_DATABASE_URL")
    if not url:
        # Deliberately no fallback to DATABASE_URL: that's the owner login, which can read costs.
        raise _error(503, "MSKU_API_DATABASE_URL isn't set. See docs/HUB_API.md, Deploying.")
    # prepare_threshold=None: Neon's pooled endpoint (PgBouncer) can't keep prepared statements.
    return psycopg.connect(url, prepare_threshold=None, connect_timeout=10)


def route(environ):
    method = environ["REQUEST_METHOD"]
    path = environ.get("PATH_INFO", "").encode("latin-1").decode("utf-8", "replace")
    query = {k: v[-1] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
    # On Vercel every request arrives as /api/index; vercel.json passes the path the caller asked for as __path
    path = query.pop("__path", None) or path
    path = re.sub(r"^/api/index(?=/|$)", "", path).rstrip("/") or "/"
    parts = path.split("/")[1:]

    if parts == ["health"]:
        if method != "GET":
            raise _error(405, "Use GET")
        with _connect() as conn:
            conn.execute("SELECT 1")
        return 200, {"ok": True}

    if parts == ["skus"]:
        with _connect() as conn:
            if method == "GET":
                where, params = ["TRUE"], {}
                if "updated_since" in query:
                    # updated_at goes out at millisecond precision, so compare at that precision too
                    where.append("date_trunc('milliseconds', updated_at) > %(since)s")
                    params["since"] = _parse_time(query["updated_since"], "updated_since")
                if query.get("q", "").strip():
                    where.append("(code ILIKE %(q)s OR name ILIKE %(q)s)")
                    params["q"] = "%" + re.sub(r"([\\%_])", r"\\\1", query["q"].strip()) + "%"
                skus = fetch(conn, " AND ".join(where), params, order="updated_at, code")
                return 200, {"skus": skus, "count": len(skus)}
            if method == "POST":
                return 201, create(conn, _body(environ))
        raise _error(405, "Use GET or POST")

    if len(parts) == 2 and parts[0] == "skus" and parts[1]:
        code = parts[1]
        with _connect() as conn:
            if method == "GET":
                found = fetch_one(conn, code)
                if not found:
                    raise _error(404, f"No SKU {code}")
                return 200, found
            if method == "PATCH":
                return 200, update(conn, code, _body(environ))
        raise _error(405, "Use GET or PATCH. SKUs aren't deleted: set status to obsolete.")

    if parts == ["changes"]:
        if method != "GET":
            raise _error(405, "Use GET")
        since = _parse_time(query["since"], "since") if "since" in query else None
        cursor = None
        if "cursor" in query:
            if not query["cursor"].isdigit():
                raise _error(400, "cursor must be the next_cursor value from a previous response")
            cursor = int(query["cursor"])
        if since is None and cursor is None:
            raise _error(400, "Send since=<ISO timestamp> (or cursor=<next_cursor>)", {"since": "required"})
        try:
            limit = min(max(int(query.get("limit", 500)), 1), 2000)
        except ValueError:
            raise _error(400, "limit must be a whole number")
        with _connect() as conn:
            found, next_cursor = changes(conn, since, cursor, limit)
        return 200, {"changes": found, "next_cursor": next_cursor}

    raise _error(404, "No such endpoint. See /health, /skus, /skus/<sku>, /changes")


def app(environ, start_response):
    try:
        if not _https(environ):
            raise _error(403, "HTTPS only")
        if not _authorised(environ):
            raise _error(401, "Missing or wrong x-api-key")
        status, body = route(environ)
    except Reply as r:
        status, body = r.status, r.body
    except psycopg.OperationalError:
        status, body = 503, {"error": "The database is unavailable; try again shortly"}
    payload = json.dumps(body, ensure_ascii=False, default=str).encode()
    reason = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
              405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 503: "Service Unavailable"}
    start_response(f"{status} {reason.get(status, '')}".strip(), [
        ("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store")])
    return [payload]
