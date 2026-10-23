"""Turn raw sheet rows into canonical records, conflicts and exclusions.

Input: the dict from sheets.load_all(). Output: a Model (plain dicts, no DB).
Every value keeps its source and row so it can be traced.
"""
import collections as C
import hashlib
import json
import re

from . import mapping_rules as R
from .rules import (base_code, brand_for, check_code, dims_mm, exclusion_reason, money, norm, number,
                    pack_info, tier_for, upc, upc_key, weight_g)

cell = lambda r, i: norm(r[i]) if i < len(r) else ""


class Model:
    def __init__(self):
        self.skus = {}            # code -> record
        self.prices = []          # loaded into core.price (Tier 1 price list only)
        self.price_obs = C.defaultdict(list)   # (code, region, tier) -> every observed value, for conflicts
        self.costs = []           # confidential, never mixed into conflicts or the preview
        self.sheet_landed = {}    # code -> (amount, ref), reference only
        self.stock = []
        self.exclusions = {}
        self.conflicts = {}
        self.source_fixes = []    # Cin7 / master values that differ from the price list (price list wins)
        self.warnings = []
        self.staging = []         # (spreadsheet_id, spreadsheet, tab, row_num, row)

    def sku(self, code):
        if code not in self.skus:
            ptype, pqty = pack_info(code)
            self.skus[code] = {
                "code": code, "pack_type": ptype, "pack_qty": pqty, "base_code": base_code(code),
                "brand": None, "family": None, "category": None, "product_class": None, "variant_code": None,
                "upc": None, "hts_code": None, "country_of_origin": None, "producer": None, "is_new": False,
                "name": None, "code_check": check_code(code), "master_active": None,
                "price_tabs": set(), "master_rows": [], "field_sources": [], "links": set(),
                "external_ids": set(), "packaging": {}, "flags": [], "_cand": C.defaultdict(list),
            }
        return self.skus[code]

    def exclude(self, code, reason, where, name=""):
        e = self.exclusions.setdefault(code, {"code": code, "reason": reason, "seen_in": set(), "name": name})
        e["seen_in"].add(where)

    def conflict(self, code, field, kind, detail, candidates):
        fp = f"{code}|{field}"
        vh = hashlib.sha1(json.dumps(sorted((c["value"], c["source"]) for c in candidates)).encode()).hexdigest()[:16]
        self.conflicts[fp] = {"fingerprint": fp, "sku_code": code, "kind": kind, "detail": detail,
                              "candidates": candidates, "values_hash": vh}


def _cand(s, field, value, source, ref):
    """Record a candidate value for a field. Precedence is applied later."""
    if value not in (None, ""):
        s["_cand"][field].append((source, value, ref))


def consolidate(src):
    m = Model()
    _read_prices(m, src["prices"])
    _read_master(m, src["master"])
    _read_templates(m, src["gp_tpl"], src["sg_tpl"])
    _read_cin7(m, src["cin7"])
    _resolve_fields(m, src)
    _derive(m)
    return m


# ---------- price list (Tier 1 + prices + ex-factory cost)
def _read_prices(m, doc):
    sid, sname, tabs = doc["id"], doc["name"], doc["tabs"]
    for tab, (brand, region, cur) in R.PRICE_TABS.items():
        rows = tabs.get(tab)
        if rows is None:
            m.warnings.append(f"Price tab missing: {tab}")
            continue
        kind = "D" if tab.endswith(" D") else "WS"
        heading = ""
        seen = C.Counter()
        for i, r in enumerate(rows[R.PRICE_HEADER_ROWS:], start=R.PRICE_HEADER_ROWS + 1):
            m.staging.append((sid, sname, tab, i, r))
            a, code, name = cell(r, 0), cell(r, 1), cell(r, 2)
            if a and not code:
                heading = a.upper()
                continue
            if not code or code.upper() == "SKU":
                continue
            why = exclusion_reason(code)
            if why:
                m.exclude(code, why, f"{sname} / {tab}")
                continue
            seen[code] += 1
            if seen[code] > 1:
                m.sku(code)["flags"].append(f"Listed more than once on {tab}")
            s = m.sku(code)
            ref = f"{tab} row {i}"
            s["price_tabs"].add(tab)
            s["is_new"] |= a.upper() == "NEW"
            _cand(s, "name", name, "prices", ref)
            _cand(s, "brand", brand, "prices", ref)
            _cand(s, "category", heading.title(), "prices", ref)
            _cand(s, "family", R.FAMILY_FROM_HEADING.get(heading), "prices", ref)
            for col, tier in R.PRICE_COLUMNS.items():
                raw = cell(r, col)
                amt = money(raw)
                if amt is None:
                    continue
                note = "Written with $; read as EUR (per Ken)" if tab in R.EUR_TABS_WITH_DOLLAR_TYPO and "$" in raw else ""
                obs = {"value": amt, "currency": cur, "source": sname, "ref": ref, "kind": kind, "note": note}
                m.price_obs[(code, region, tier)].append(obs)

    # order form: compare only
    for i, r in enumerate(doc["tabs"].get(R.ORDER_FORM_TAB, [])[R.PRICE_HEADER_ROWS:], start=R.PRICE_HEADER_ROWS + 1):
        code = cell(r, 1)
        if code and code.upper() != "SKU" and not exclusion_reason(code):
            for col, tier in ((3, "msrp"), (4, "wholesale")):
                amt = money(cell(r, col))
                if amt is not None:
                    m.price_obs[(code, "US", tier)].append({"value": amt, "currency": "USD", "source": "Order form",
                                                            "ref": f"row {i}", "kind": "order_form"})

    # ex-factory unit cost (confidential)
    for i, r in enumerate(doc["tabs"].get(R.EX_FACTORY_TAB, [])[R.PRICE_HEADER_ROWS:], start=R.PRICE_HEADER_ROWS + 1):
        code = cell(r, 1)
        amt = money(cell(r, R.EX_FACTORY_COST_COL))
        if code and code.upper() != "SKU" and amt is not None and not exclusion_reason(code):
            m.costs.append({"code": code, "amount": amt, "currency": "USD", "source": "ex_factory",
                            "ref": f"{R.EX_FACTORY_TAB} row {i}", "read_at": doc["read_at"]})


# ---------- master sheet
def _read_master(m, doc):
    sid, sname = doc["id"], doc["name"]
    found = set()
    for tab, brand in R.MASTER_TABS.items():
        rows = doc["tabs"].get(tab, [])
        if not rows:
            m.warnings.append(f"Master tab missing: {tab}")
            continue
        hdr = [norm(h) for h in rows[0]]
        for i, r in enumerate(rows[1:], start=2):
            if not any(norm(c) for c in r):
                continue
            code = cell(r, 0)
            # Staging keeps the row but never the cost columns.
            m.staging.append((sid, sname, tab, i, [("" if hdr[j] in R.MASTER_COST_HEADERS else c) if j < len(hdr) else c for j, c in enumerate(r)]))
            why = exclusion_reason(code)
            if why:
                if why != "Placeholder row":
                    m.exclude(code, why, f"{sname} / {tab}")
                continue
            if (tab, i, code) in R.DROPPED_MASTER_ROWS:
                found.add((tab, i, code))
                m.exclude(f"{code} (master {tab} row {i})", R.DROPPED_MASTER_ROWS[(tab, i, code)], f"{sname} / {tab}")
                continue
            f = {h: cell(r, j) for j, h in enumerate(hdr) if j and h and cell(r, j)}
            s = m.sku(code)
            ref = f"{tab} row {i}"
            s["master_rows"].append(ref)
            _cand(s, "name", f.get("Full Name"), "master", ref)
            _cand(s, "brand", brand, "master", ref)
            _cand(s, "product_class", (f.get("Product Class") or "").title(), "master", ref)
            _cand(s, "variant_code", f.get("Brand & Color Code"), "master", ref)
            _cand(s, "producer", f.get("Producer"), "master", ref)
            _cand(s, "master_active", f.get("Active"), "master", ref)
            # G Pen tab has Barcode/UPC swapped (number in Barcode, file name in UPC): take whichever is digits.
            for col in ("UPC", "Barcode"):
                if upc(f.get(col)):
                    _cand(s, "upc", upc(f[col]), "master", f"{ref}, {col}")
                    break
            msrp = money(f.get("MSRP"))
            if msrp is not None:
                m.price_obs[(code, "US", "msrp")].append({"value": msrp, "currency": "USD", "source": sname,
                                                          "ref": ref, "kind": "compare", "note": "Currency assumed USD"})
            for k, kind in (("GNLN SKU", "gnln"), ("MPN", "mpn")):
                if f.get(k):
                    s["external_ids"].add((kind, f[k]))
            for k, kind in (("Packaging Design Files", "packaging_files"), ("Die Line Designs", "die_line"),
                            ("Barcode", "barcode_file"), ("UPC", "barcode_file")):
                if (f.get(k) or "").startswith("http"):
                    s["links"].add((kind, f[k], sname))
            _master_packaging(s, f, brand, ref)
            for h, kind in R.MASTER_COST_HEADERS.items():
                amt = money(f.get(h))
                if amt is None:
                    continue
                if amt > R.MAX_PLAUSIBLE_COST:
                    m.warnings.append(f"Rejected implausible {h} for {code} ({ref}): looks like a UPC or typo")
                    s["flags"].append(f"{h} cell holds an implausible value (rejected)")
                    continue
                if kind == "unit_cost":
                    m.costs.append({"code": code, "amount": amt, "currency": "USD", "source": "master",
                                    "ref": ref, "read_at": doc["read_at"]})
                else:
                    m.sheet_landed.setdefault(code, (amt, ref))
    for key in set(R.DROPPED_MASTER_ROWS) - found:
        m.warnings.append(f"Duplicate row to drop not found where expected (sheet edited?): {key}")
    for code in R.KEEP_BOTH_DUPLICATES:
        if code in m.skus and len(m.skus[code]["master_rows"]) > 1:
            m.skus[code]["flags"].append("Two master rows kept on purpose: " + ", ".join(m.skus[code]["master_rows"]))


def _pk(s, level, field, value, raw, source):
    if value is None:
        return
    lv = s["packaging"].setdefault(level, {})
    lv.setdefault(field, []).append((value, raw, source))


def _master_packaging(s, f, brand, ref):
    src = f"master {ref}"
    if brand == "Stündenglass":
        kg = number(f.get("Package Weight (kg)"))
        _pk(s, "unit", "weight_g", kg * 1000 if kg else None, f.get("Package Weight (kg)"), src)
        dims = tuple(number(f.get(k)) for k in ("PackageLength mm", "Product Width mm", "Package Height mm"))
        if all(dims):
            _pk(s, "unit", "dims_mm", dims, "/".join(f.get(k, "") for k in ("PackageLength mm", "Product Width mm", "Package Height mm")), src)
        kg = number(f.get("Case Weight (kg)"))
        _pk(s, "master_case", "weight_g", kg * 1000 if kg else None, f.get("Case Weight (kg)"), src)
        dims = tuple(number(f.get(k)) for k in ("Case Length mm", "Case Width mm", "Case Height mm"))
        if all(dims):
            _pk(s, "master_case", "dims_mm", dims, "/".join(f.get(k, "") for k in ("Case Length mm", "Case Width mm", "Case Height mm")), src)
        if f.get("Palet Count"):
            _pk(s, "pallet", "raw", f.get("Palet Count"), f.get("Palet Count"), src)
    else:
        _pk(s, "unit", "weight_g", weight_g(f.get("Product Weight (kg)"), "kg"), f.get("Product Weight (kg)"), src)
        _pk(s, "unit", "dims_mm", dims_mm(f.get("Product Dimensions (mm)")), f.get("Product Dimensions (mm)"), src)
        _pk(s, "master_case", "weight_g", weight_g(f.get("Case Weight (kg)"), "kg"), f.get("Case Weight (kg)"), src)
        _pk(s, "master_case", "dims_mm", dims_mm(f.get("Case Dimensions (mm)")), f.get("Case Dimensions (mm)"), src)
    upc_ = number(f.get("Units Per Case"))
    _pk(s, "master_case", "units", int(upc_) if upc_ else None, f.get("Units Per Case"), src)


# ---------- Tim's SKU detail templates
def _read_templates(m, gp, sg):
    for doc, sku_col, name_col in ((gp, 2, 3), (sg, 3, 2)):
        sid, sname = doc["id"], doc["name"]
        rows = next(iter(doc["tabs"].values()))
        hdr = [norm(h) for h in rows[3]]
        col = {h: j for j, h in enumerate(hdr)}
        for i, r in enumerate(rows[4:], start=5):
            m.staging.append((sid, sname, "SKU Details", i, r))
            code = cell(r, sku_col)
            if not code:
                continue
            why = exclusion_reason(code)
            if why:
                m.exclude(code, why, sname)
                continue
            s = m.sku(code)
            ref = f"{sname} row {i}"
            g = lambda h: cell(r, col[h]) if h in col else ""
            _cand(s, "name", cell(r, name_col), "gp_tpl" if doc is gp else "sg_tpl", ref)
            _cand(s, "upc", upc(g("UPC")), "template", ref)
            _cand(s, "hts_code", g("HTS (Harmonized Tariff Schedule) Code"), "template", ref)
            _pk(s, "unit", "dims_mm", dims_mm(g("Product Dimensions (L × W × H, incl. unit)")), g("Product Dimensions (L × W × H, incl. unit)"), ref)
            _pk(s, "unit", "weight_g", weight_g(g("Unit Weight (incl. unit, e.g. 45 g)") or g("Unit Weight (incl. unit, e.g. 2.5 kg)")),
                g("Unit Weight (incl. unit, e.g. 45 g)") or g("Unit Weight (incl. unit, e.g. 2.5 kg)"), ref)
            case_w = g("Case Weight (incl. unit, e.g. 16.07 kg)") or g("Case Weight (incl. unit, e.g. 16 kg)")
            _pk(s, "master_case", "weight_g", weight_g(case_w), case_w, ref)
            _pk(s, "master_case", "dims_mm", dims_mm(g("Case Dimensions (L × W × H, incl. unit)")), g("Case Dimensions (L × W × H, incl. unit)"), ref)
            units = number(g("Units per Master Case") or g("Units per Case"))
            _pk(s, "master_case", "units", int(units) if units else None, g("Units per Master Case") or g("Units per Case"), ref)
            pop = number(g("Units per POP Display"))
            _pk(s, "inner_pack", "units", int(pop) if pop else None, g("Units per POP Display"), ref)
            pal = number(g("Units per Pallet"))
            _pk(s, "pallet", "units", int(pal) if pal else None, g("Units per Pallet"), ref)
            _pk(s, "pallet", "weight_g", weight_g(g("Pallet Weight (incl. unit, e.g. 320 kg)")), g("Pallet Weight (incl. unit, e.g. 320 kg)"), ref)


# ---------- Cin7 stock
def _read_cin7(m, doc):
    sid, sname = doc["id"], doc["name"]
    rows = next(iter(doc["tabs"].values()))
    c = R.CIN7_COLUMNS
    if norm(rows[0][c["available"]]) != R.CIN7_AVAILABLE_HEADER:
        raise SystemExit(f"Cin7 column L is {rows[0][c['available']]!r}, expected 'Available'. Stopping.")
    m.stock_as_of = _as_of(doc)
    seen_locations = C.Counter()
    for i, r in enumerate(rows[1:], start=2):
        m.staging.append((sid, sname, next(iter(doc["tabs"])), i, r))
        code, loc = cell(r, c["sku"]), cell(r, c["location"])
        why = exclusion_reason(code)
        if why:
            m.exclude(code, why, "Cin7", cell(r, c["name"]))
            continue
        s = m.sku(code)
        seen_locations[loc] += 1
        m.stock.append({"code": code, "location": loc, "available": number(cell(r, c["available"])) or 0,
                        "on_hand": number(cell(r, c["on_hand"])), "on_order": number(cell(r, c["on_order"]))})
        ref = f"Cin7 row {i}"
        _cand(s, "name", cell(r, c["name"]), "cin7", ref)
        _cand(s, "category", cell(r, c["category"]), "cin7", ref)
        _cand(s, "cin7_status", cell(r, c["status"]), "cin7", ref)
        s["external_ids"].add(("cin7", code))
        # Cin7 PriceTier1/2/3 = US MSRP / wholesale / distribution (confirmed). One observation per SKU.
        for t in ("msrp", "wholesale", "distribution"):
            amt = money(cell(r, c[t]))
            obs = m.price_obs[(code, "US", t)]
            if amt and not any(o["source"] == "Cin7" for o in obs):
                obs.append({"value": amt, "currency": "USD", "source": "Cin7", "ref": f"PriceTier ({ref})", "kind": "compare"})
    m.locations = {loc: loc in R.COUNTED_LOCATIONS for loc in seen_locations}
    missing = R.COUNTED_LOCATIONS - set(seen_locations)
    if missing:
        m.warnings.append(f"Counted locations not present in this Cin7 report: {sorted(missing)}")


def _as_of(doc):
    mt = re.search(r"(\d{4}-\d{2}-\d{2})", " ".join(doc["tabs"]))
    return mt.group(1) if mt else doc["read_at"]


# ---------- precedence + conflicts
SOURCE_LABEL = {"prices": "Price list", "master": "Master SKU list", "gp_tpl": "G Pen SKU details",
                "sg_tpl": "Stündenglass SKU details", "template": "SKU details template", "cin7": "Cin7",
                "override": "Ken (decision)"}


def _resolve_fields(m, src):
    for code, s in m.skus.items():
        cand = s["_cand"]
        for (oc, field), v in R.OVERRIDES.items():
            if oc == code:
                cand[field].insert(0, ("override", v, "DECISIONS.md"))
        for field, vals in cand.items():
            for source, value, ref in vals:
                s["field_sources"].append((field, str(value), SOURCE_LABEL.get(source, source), ref))
        order = {k: i for i, k in enumerate(R.NAME_SOURCES)}
        pick = lambda f: (sorted(cand[f], key=lambda x: order.get(x[0], 99))[0][1] if cand.get(f) else None)
        s["name"] = pick("name")
        for f in ("family", "category", "product_class", "variant_code", "producer", "hts_code", "master_active"):
            s[f] = pick(f)
        s["brand"] = pick("brand") or brand_for(code)
        s["cin7_status"] = pick("cin7_status")
        # UPC: master first, then template; conflict if they disagree
        upcs = C.OrderedDict()
        for source, value, ref in sorted(cand.get("upc", []), key=lambda x: 0 if x[0] == "master" else 1):
            upcs.setdefault(upc_key(value), []).append((source, value, ref))
        if upcs:
            s["upc"] = next(iter(upcs.values()))[0][1]
        if len(upcs) > 1:
            m.conflict(code, "upc", "UPC", "Sources give different UPCs",
                       [{"value": v, "source": SOURCE_LABEL[src_], "ref": ref} for g in upcs.values() for src_, v, ref in g])
        # packaging: template before master; flag numeric disagreements on units
        for level, fields in s["packaging"].items():
            for field, vals in fields.items():
                vals.sort(key=lambda x: 0 if not x[2].startswith("master") else 1)
                if field == "units" and len({v for v, _, _ in vals}) > 1:
                    m.conflict(code, f"units_{level}", f"Units per {level.replace('_', ' ')}", "Sources disagree",
                               [{"value": str(v), "source": src_, "ref": ""} for v, _, src_ in vals])
        del s["_cand"]


def _derive(m):
    avail = C.defaultdict(float)
    other = C.defaultdict(float)
    for st in m.stock:
        (avail if st["location"] in R.COUNTED_LOCATIONS else other)[st["code"]] += st["available"]
    for code, s in m.skus.items():
        s["available_counted"] = avail.get(code, 0.0)
        s["available_other"] = other.get(code, 0.0)
        s["tier"], s["tier_reason"] = tier_for(bool(s["price_tabs"]), s["available_counted"])
        if code in R.TIER_OVERRIDES:
            s["tier"], s["tier_reason"] = R.TIER_OVERRIDES[code]
        if s["tier"] == 3 and s["available_other"] > 0:
            s["flags"].append(f"{s['available_other']:,.0f} available only in locations that don't count")
        if not s["master_rows"]:
            s["flags"].append("Not in Master SKU list")
        if s["price_tabs"] and code not in avail and code not in other:
            s["flags"].append("On price list but not in Cin7")
        if s["available_counted"] < 0:
            s["flags"].append(f"Negative available total ({s['available_counted']:,.0f})")
        if s["code_check"]:
            s["flags"].append(f"Code check: {s['code_check']}")
        if s["tier"] == 1 and (s["master_active"] or "") in ("Inactive", "Archived"):
            m.conflict(code, "status_master", "Status", "Master sheet says inactive, but SKU is on the price list (Tier 1)",
                       [{"value": s["master_active"], "source": "Master SKU list", "ref": ", ".join(s["master_rows"])},
                        {"value": "Tier 1", "source": "Price list", "ref": ", ".join(sorted(s["price_tabs"]))}])
        if s["tier"] == 1 and s.get("cin7_status") == "DEPRECATED":
            m.conflict(code, "status_cin7", "Status", "Cin7 says DEPRECATED, but SKU is on the price list",
                       [{"value": "DEPRECATED", "source": "Cin7", "ref": ""}, {"value": "Tier 1", "source": "Price list", "ref": ""}])

    # prices: Tier 1 rows load from the price list. Ken: the price list always beats Cin7 and the master
    # sheet's MSRP, so those mismatches go on a fix list. Only disagreements inside the price-list
    # workbook (WS tab vs D tab vs order form) are conflicts for Ken to decide.
    for (code, region, tier), obs in sorted(m.price_obs.items()):
        if code not in m.skus or not m.skus[code]["price_tabs"]:
            continue
        pl = [o for o in obs if o["kind"] in ("WS", "D")]
        if not pl:
            continue
        primary = [o for o in pl if o["kind"] == R.PRICE_PRIMARY[tier]] or pl
        chosen = primary[0]
        if tier == "msrp" and (code, region) in R.MAP_ON_PRICE_LIST:
            # The price list's MSRP column is the B2B MAP here; the B2C MSRP is Ken's decision.
            m.prices.append({"code": code, "region": region, "tier": "map", "currency": chosen["currency"],
                             "amount": chosen["value"], "source": chosen["source"], "ref": chosen["ref"]})
            b2c = R.MAP_ON_PRICE_LIST[(code, region)]
            if b2c is None:
                m.skus[code]["flags"].append(f"{region} B2C MSRP not set yet (price list value is the MAP)")
                continue
            chosen = {**chosen, "value": b2c, "source": "Ken (decision)", "ref": "B2C MSRP (DECISIONS.md)"}
        m.prices.append({"code": code, "region": region, "tier": tier, "currency": chosen["currency"],
                         "amount": chosen["value"], "source": chosen["source"], "ref": chosen["ref"]})
        workbook = [o for o in obs if o["kind"] in R.PRICE_LIST_KINDS]
        if len({o["value"] for o in workbook}) > 1:
            m.conflict(code, f"price_{region}_{tier}", f"Price · {region} {tier}",
                       f"Price list tabs disagree (loaded {chosen['value']:,.2f} from {chosen['ref']} until decided)",
                       [{"value": f"{o['value']:,.2f} {o['currency']}", "source": o["source"], "ref": o["ref"]} for o in workbook])
        for o in obs:
            if o["kind"] not in R.PRICE_LIST_KINDS and o["value"] != chosen["value"]:
                m.source_fixes.append({"code": code, "field": f"{region} {tier}", "source": o["source"], "source_ref": o["ref"],
                                       "source_value": f"{o['value']:,.2f}", "correct_value": f"{chosen['value']:,.2f} {chosen['currency']}",
                                       "correct_ref": chosen["ref"]})

    # costs: drop ones for excluded or unknown codes
    m.costs = [c for c in m.costs if c["code"] in m.skus]
    with_cost = {c["code"] for c in m.costs}
    m.missing_cost = sorted(code for code, s in m.skus.items() if s["tier"] == 1 and code not in with_cost)
