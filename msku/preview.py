"""Build master-sku-preview.html from the database. Read-only; costs are never queried."""
import collections as C
import json
from datetime import date

PACK_LABEL = {"single_unit": "Single unit", "inner_pack": "Inner pack / POP", "pop_display": "POP display",
              "master_case": "Master case", "multi_pack": "Multi-pack", "kit": "Kit"}
TIER_LABEL = {"msrp": "MSRP", "wholesale": "Wholesale", "distribution": "Distribution", "retail": "Retail"}


def build(conn, out="master-sku-preview.html", template="scripts/preview_template.html"):
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    fs = C.defaultdict(lambda: C.defaultdict(list))
    for sid, field, value, source, ref in q("SELECT sku_id, field, value, source, source_ref FROM core.field_source ORDER BY source, source_ref"):
        fs[sid][field].append({"v": value, "src": source, "at": ref})
    prices = C.defaultdict(list)
    for sid, region, tier, cur, amt, src, ref in q("SELECT sku_id, region::text, tier::text, currency, amount, source, source_ref FROM core.price WHERE effective_to IS NULL"):
        prices[sid].append({"region": region, "tier": TIER_LABEL[tier], "currency": cur, "amount": float(amt), "src": src, "at": ref,
                            "note": "Written with $; read as EUR (per Ken)" if ref.startswith("GP EU WS") and cur == "EUR" else ""})
    phys = C.defaultdict(list)
    for sid, level, l, w, h, g, units, src in q("SELECT sku_id, level::text, length_mm, width_mm, height_mm, weight_g, units_per_level, source FROM core.sku_packaging_level ORDER BY level"):
        lv = level.replace("_", " ").title()
        if l:
            phys[sid].append({"field": f"{lv} dimensions", "v": f"{float(l):g} × {float(w):g} × {float(h):g} mm", "src": src, "at": ""})
        if g:
            phys[sid].append({"field": f"{lv} weight", "v": f"{float(g):,.0f} g", "src": src, "at": ""})
        if units:
            phys[sid].append({"field": f"Units per {lv.lower()}", "v": str(units), "src": src, "at": ""})
    stock = C.defaultdict(dict)
    as_of = q("SELECT max(as_of) FROM core.stock_snapshot")[0][0]
    for sid, loc, av, oh, oo, counted in q("""SELECT s.sku_id, s.location, s.available, s.on_hand, s.on_order, l.counted
                                              FROM core.stock_snapshot s JOIN core.stock_location l ON l.name = s.location WHERE s.as_of = %s""", as_of):
        stock[sid][loc] = {"available": float(av), "on_hand": float(oh or 0), "on_order": float(oo or 0), "counted": counted}
    links = C.defaultdict(list)
    for sid, kind, url, src in q("SELECT sku_id, kind, url, source FROM core.sku_link ORDER BY kind"):
        links[sid].append({"label": kind.replace("_", " ").capitalize(), "url": url, "src": src})

    skus = []
    for (sid, code, name, brand, family, category, pack, upc, is_new, tier, reason, flags, master_active, hts) in q("""
            SELECT s.id, s.code, s.name, b.name, f.name, s.category, s.pack_type::text, s.upc, s.is_new, t.tier, t.reason,
                   s.review_flags, s.master_active, s.hts_code
            FROM core.sku s LEFT JOIN core.brand b ON b.id = s.brand_id LEFT JOIN core.family f ON f.id = s.family_id
            LEFT JOIN core.sku_tier t ON t.sku_id = s.id ORDER BY s.code"""):
        st = stock.get(sid, {})
        f = fs[sid]
        skus.append({
            "code": code, "name": name or "", "brand": brand or "", "family": family or "", "category": category or "",
            "pack": PACK_LABEL[pack], "tier": tier, "tier_reason": reason, "new": is_new, "upc": upc or "", "hts": hts or "",
            "available": sum(v["available"] for v in st.values() if v["counted"]),
            "cin7_status": (f.get("cin7_status") or [{"v": ""}])[0]["v"], "master_active": master_active or "",
            "names": f.get("name", []), "upcs": f.get("upc", []), "prices": prices.get(sid, []), "physical": phys.get(sid, []),
            "stock": st, "flags": flags, "links": links.get(sid, []),
            "master_rows": sorted({x["at"] for x in f.get("name", []) if x["src"] == "Master SKU list"}),
            "price_tabs": sorted({x["at"].split(" row")[0] for x in f.get("name", []) if x["src"] == "Price list"}),
        })
    conflicts = [{"code": code, "kind": kind, "detail": detail, "status": status, "fingerprint": fp,
                  "values": [{"v": c["value"], "src": f"{c['source']} {c.get('ref', '')}".strip()} for c in cands],
                  "decision": dec}
                 for fp, code, kind, detail, status, cands, dec in q("""
                     SELECT c.fingerprint, c.sku_code, c.kind, c.detail, c.status, c.candidates, r.chosen_value
                     FROM ops.conflict c LEFT JOIN ops.conflict_resolution r USING (fingerprint)
                     WHERE c.status <> 'cleared' ORDER BY c.status DESC, c.sku_code""")]
    exclusions = [{"code": c, "reason": r, "seen_in": s, "name": ""} for c, r, s in q("SELECT code, reason, seen_in FROM ops.exclusion ORDER BY reason, code")]
    run = q("SELECT finished_at::date, sources FROM ops.import_run WHERE NOT dry_run ORDER BY id DESC LIMIT 1")[0]
    data = {"built": date.today().isoformat(), "imported": run[0].isoformat(), "stock_as_of": as_of.isoformat(),
            "sources": [s["name"] for s in run[1]], "counted_locations": sorted(l for l, c in q("SELECT name, counted FROM core.stock_location") if c),
            "skus": skus, "conflicts": conflicts, "exclusions": exclusions}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    open(out, "w").write(open(template).read().replace("/*DATA*/", blob))
    print(f"{out}: {len(skus)} SKUs, {len(conflicts)} conflicts, {len(exclusions)} exclusions")
