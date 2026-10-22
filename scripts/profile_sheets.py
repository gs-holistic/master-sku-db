"""Profile cached sheet values: column fill rates, value sets, SKU overlap. Read-only, uses .cache."""
import json, glob, re, collections as C
D = ".cache/sheets/"
MS = D + "1vMuhrqFVbgF_sgQGQIpfr_BtQPoeTsxJzEHYZSPEqik/"
PL = D + "1py6ZHFpUhNcK7hLxJNAecqUOiWlZ8cQ05Qmcp9w6kpc/"
CIN = glob.glob(D + "1ju5tBsHgA9Wg9TSqfbP5gdV6-UPx5aCJMTdyQ1mUj5o/*.json")[0]
load = lambda p: json.load(open(p))
norm = lambda s: (s or "").strip()

def profile(rows, name, show_vals=()):
    hdr = rows[0]; body = [r for r in rows[1:] if any(norm(c) for c in r)]
    w = max(len(r) for r in rows)
    print(f"\n#### {name}: {len(body)} data rows")
    for i in range(w):
        h = hdr[i] if i < len(hdr) else ""
        vals = [norm(r[i]) for r in body if i < len(r) and norm(r[i])]
        extra = ""
        if h in show_vals or len(set(vals)) <= 8:
            extra = dict(C.Counter(vals).most_common(10))
        print(f"  {chr(65+i) if i<26 else 'A'+chr(65+i-26)} {h!r}: {len(vals)} filled, {len(set(vals))} distinct {extra}")
    return hdr, body

sg_h, sg = profile(load(MS + "Stundenglass.json"), "Master SKU / Stundenglass", ("Active", "Product Class", "Producer"))
gp_h, gp = profile(load(MS + "G_Pen.json"), "Master SKU / G Pen", ("Active",))
master = {norm(r[0]) for r in sg + gp if r and norm(r[0])}
dupes = [k for k, v in C.Counter(norm(r[0]) for r in sg + gp if r and norm(r[0])).items() if v > 1]
print(f"\nMaster SKU list: {len(master)} unique SKU codes, {len(dupes)} duplicated: {dupes[:15]}")

# price list
SKU_RE = re.compile(r"^[A-Z0-9]{2,4}-[A-Z0-9]{3}-[A-Z0-9]{4}")
pl = {}
for p in sorted(glob.glob(PL + "*.json")):
    tab = p.split("/")[-1][:-5]
    rows = load(p)
    skus = [norm(r[1]) for r in rows[4:] if len(r) > 1 and norm(r[1]) and norm(r[1]) != "SKU"]
    cats = sorted({norm(r[0]) for r in rows[4:] if r and norm(r[0]) and (len(r) < 2 or not norm(r[1]))})
    flags = C.Counter(norm(r[0]) for r in rows[4:] if len(r) > 1 and norm(r[0]) and norm(r[1]))
    pl[tab] = skus
    print(f"\n[{tab}] {len(skus)} SKU rows, {len(set(skus))} unique; flags in col A on SKU rows: {dict(flags)}")
    print(f"   categories: {cats}")
    odd = [s for s in skus if not SKU_RE.match(s)]
    if odd: print(f"   non-standard codes: {odd}")
price_tabs = [t for t in pl if t not in ("GP_STG_ORDER_FORM", "GP_STG_EX-FACTORY_UNIT_COSTS")]
active = set().union(*(set(pl[t]) for t in price_tabs))
print(f"\nPRICE LIST union (12 price tabs): {len(active)} SKUs")
print(f"  order form: {len(set(pl['GP_STG_ORDER_FORM']))}, ex-factory: {len(set(pl['GP_STG_EX-FACTORY_UNIT_COSTS']))}")
print(f"  on order form but not price tabs: {sorted(set(pl['GP_STG_ORDER_FORM']) - active)}")
print(f"  on ex-factory but not price tabs: {sorted(set(pl['GP_STG_EX-FACTORY_UNIT_COSTS']) - active)}")

# cin7
rows = load(CIN); h = rows[0]; body = rows[1:]
ix = {k: h.index(k) for k in ("SKU", "Location", "Available", "Status", "OnHand", "Category", "Brand")}
locs = C.Counter(norm(r[ix["Location"]]) for r in body if len(r) > ix["Location"])
print(f"\nCIN7: {len(body)} rows, {len({norm(r[1]) for r in body})} distinct SKUs")
print(f"  column L header = {h[11]!r}")
print(f"  locations: {dict(locs)}")
print(f"  status: {dict(C.Counter(norm(r[ix['Status']]) for r in body if len(r) > ix['Status']))}")
print(f"  brand: {dict(C.Counter(norm(r[ix['Brand']]) for r in body if len(r) > ix['Brand']))}")
print(f"  rows per (SKU,Location) >1: {sum(1 for v in C.Counter((norm(r[1]), norm(r[3])) for r in body).values() if v > 1)}")
nonnum = [r[11] for r in body if len(r) > 11 and not re.fullmatch(r"-?[\d,]+(\.\d+)?", norm(r[11]))]
print(f"  non-numeric Available values: {C.Counter(nonnum).most_common(5)}")
cin = {norm(r[1]) for r in body}
print(f"\nOVERLAP: price∩master {len(active & master)}, price∩cin7 {len(active & cin)}, master∩cin7 {len(master & cin)}")
print(f"  price-list SKUs missing from master: {sorted(active - master)}")
print(f"  price-list SKUs missing from cin7: {sorted(active - cin)}")
