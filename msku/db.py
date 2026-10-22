"""Migrations and the idempotent loader. Running an import twice changes nothing."""
import glob
import json
import os
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from . import mapping_rules as R
from .rules import money

PACK_LEVELS = ("unit", "inner_pack", "master_case", "pallet")


def connect():
    return psycopg.connect(os.environ.get("MSKU_DATABASE_URL", "postgresql://postgres@/master_sku?host=/tmp&port=5433"))


def migrate(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migrations")}
    applied = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "migrations", "*.sql"))):
        name = os.path.basename(path)
        if name in done:
            continue
        with conn.transaction():
            conn.execute(open(path).read())
            conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (name,))
        applied.append(name)
    conn.commit()
    return applied


class Rollback(Exception):
    pass


def load(conn, model, sources, actor, dry_run=False):
    """Write the consolidated model. Returns a summary of what changed (or would change)."""
    stats = {}
    try:
        with conn.transaction():
            conn.execute("SELECT set_config('msku.actor', %s, true)", (actor,))
            audit_start = conn.execute("SELECT coalesce(max(id), 0) FROM ops.audit_log").fetchone()[0]
            run_id = conn.execute(
                "INSERT INTO ops.import_run (dry_run, actor, sources) VALUES (%s, %s, %s) RETURNING id",
                (dry_run, actor, Jsonb([{"key": k, "name": d["name"], "read_at": d["read_at"]} for k, d in sources.items()]))).fetchone()[0]
            read_at = min(d["read_at"] for d in sources.values())
            stats.update(_load(conn, model, run_id, read_at))
            rows = conn.execute("""SELECT table_name, action, count(*) FROM ops.audit_log WHERE id > %s
                                   GROUP BY 1, 2 ORDER BY 1, 2""", (audit_start,)).fetchall()
            stats["changes"] = {f"{t} {a.lower()}": n for t, a, n in rows if not t.startswith("ops.")}
            stats["conflict_changes"] = {a.lower(): n for t, a, n in rows if t == "ops.conflict"}
            conn.execute("UPDATE ops.import_run SET finished_at = now(), stats = %s WHERE id = %s", (Jsonb(stats), run_id))
            if dry_run:
                raise Rollback
    except Rollback:
        pass
    conn.commit()
    return stats


def _id_map(conn, sql):
    return {k: v for k, v in conn.execute(sql)}


def _load(conn, m, run_id, read_at):
    today = date.today()
    st = {}
    # staging: raw rows, every one with sheet / tab / row
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO staging.raw_row VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(run_id, sid, sname, tab, row, Jsonb(r)) for sid, sname, tab, row, r in m.staging])
    st["staging_rows"] = len(m.staging)

    # lookups
    for name in sorted({s["brand"] for s in m.skus.values() if s["brand"]}):
        conn.execute("INSERT INTO core.brand (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
    brands = _id_map(conn, "SELECT name, id FROM core.brand")
    for b, f in sorted({(s["brand"], s["family"]) for s in m.skus.values() if s["family"]}):
        conn.execute("INSERT INTO core.family (brand_id, name) VALUES (%s, %s) ON CONFLICT (brand_id, name) DO NOTHING", (brands[b], f))
    families = {(b, n): i for i, b, n in conn.execute("SELECT f.id, b.name, f.name FROM core.family f JOIN core.brand b ON b.id = f.brand_id")}
    for p in sorted({s["producer"] for s in m.skus.values() if s["producer"]}):
        conn.execute("INSERT INTO core.producer (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (p,))
    producers = _id_map(conn, "SELECT name, id FROM core.producer")

    resolutions = {fp: (v, h) for fp, v, h in conn.execute("SELECT fingerprint, chosen_value, values_hash FROM ops.conflict_resolution")}

    def resolved(fp, current_hash):
        r = resolutions.get(fp)
        return r[0] if r and r[1] == current_hash else None

    # SKUs
    with conn.cursor() as cur:
        for code, s in sorted(m.skus.items()):
            upc = s["upc"]
            c = m.conflicts.get(f"{code}|upc")
            if c and resolved(c["fingerprint"], c["values_hash"]):
                upc = resolved(c["fingerprint"], c["values_hash"])
            cur.execute("""
                INSERT INTO core.sku (code, name, brand_id, family_id, category, product_class, variant_code, pack_type,
                                      pack_qty, upc, hts_code, producer_id, is_new, code_check, master_active, review_flags)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, brand_id = EXCLUDED.brand_id,
                  family_id = EXCLUDED.family_id, category = EXCLUDED.category, product_class = EXCLUDED.product_class,
                  variant_code = EXCLUDED.variant_code, pack_type = EXCLUDED.pack_type, pack_qty = EXCLUDED.pack_qty,
                  upc = EXCLUDED.upc, hts_code = EXCLUDED.hts_code, producer_id = EXCLUDED.producer_id,
                  is_new = EXCLUDED.is_new, code_check = EXCLUDED.code_check, master_active = EXCLUDED.master_active,
                  review_flags = EXCLUDED.review_flags""",
                (code, s["name"], brands.get(s["brand"]), families.get((s["brand"], s["family"])), s["category"],
                 s["product_class"], s["variant_code"], s["pack_type"], s["pack_qty"], upc, s["hts_code"],
                 producers.get(s["producer"]), s["is_new"], s["code_check"], s["master_active"], sorted(set(s["flags"]))))
    ids = _id_map(conn, "SELECT code, id FROM core.sku")
    with conn.cursor() as cur:
        for code, s in m.skus.items():
            base = ids.get(s["base_code"]) if s["base_code"] else None
            cur.execute("UPDATE core.sku SET base_sku_id = %s WHERE id = %s AND base_sku_id IS DISTINCT FROM %s", (base, ids[code], base))

    # tiers + history (history row only when the tier changes)
    current = {r[0]: r[1] for r in conn.execute("SELECT sku_id, tier FROM core.sku_tier")}
    as_of = date.fromisoformat(getattr(m, "stock_as_of", read_at))
    moved = 0
    with conn.cursor() as cur:
        for code, s in m.skus.items():
            sid, old = ids[code], current.get(ids[code])
            if old != s["tier"]:
                moved += old is not None
                cur.execute("INSERT INTO core.sku_tier_history (sku_id, old_tier, new_tier, effective_date, reason, import_run_id) VALUES (%s,%s,%s,%s,%s,%s)",
                            (sid, old, s["tier"], as_of, s["tier_reason"], run_id))
                cur.execute("""INSERT INTO core.sku_tier (sku_id, tier, since, reason) VALUES (%s,%s,%s,%s)
                               ON CONFLICT (sku_id) DO UPDATE SET tier = EXCLUDED.tier, since = EXCLUDED.since, reason = EXCLUDED.reason""",
                            (sid, s["tier"], as_of, s["tier_reason"]))
            else:
                cur.execute("UPDATE core.sku_tier SET reason = %s WHERE sku_id = %s", (s["tier_reason"], sid))
    st["tier_moves"] = moved

    # packaging levels: first value per field (template before master)
    with conn.cursor() as cur:
        for code, s in m.skus.items():
            for level, fields in s["packaging"].items():
                first = lambda f: fields[f][0][0] if fields.get(f) else None
                dims = first("dims_mm") if isinstance(first("dims_mm"), tuple) else None
                raw = {f: v[0][1] for f, v in fields.items() if v and v[0][1]}
                src = "; ".join(sorted({v[0][2] for v in fields.values() if v}))
                cur.execute("""INSERT INTO core.sku_packaging_level (sku_id, level, length_mm, width_mm, height_mm, weight_g, units_per_level, raw, source)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (sku_id, level) DO UPDATE SET length_mm = EXCLUDED.length_mm, width_mm = EXCLUDED.width_mm,
                                 height_mm = EXCLUDED.height_mm, weight_g = EXCLUDED.weight_g, units_per_level = EXCLUDED.units_per_level,
                                 raw = EXCLUDED.raw, source = EXCLUDED.source""",
                            (ids[code], level, *(dims or (None, None, None)), first("weight_g"),
                             first("units") if isinstance(first("units"), int) else None, Jsonb(raw), src))

    # prices: effective-dated. A changed amount closes the old row and opens a new one.
    cur_prices = {(r[0], r[1], r[2]): (r[3], r[4], r[5]) for r in conn.execute(
        "SELECT sku_id, region::text, tier::text, id, amount, currency FROM core.price WHERE effective_to IS NULL")}
    seen, opened, closed = set(), 0, 0
    with conn.cursor() as cur:
        for p in m.prices:
            key = (ids[p["code"]], p["region"], p["tier"])
            amount = p["amount"]
            c = m.conflicts.get(f"{p['code']}|price_{p['region']}_{p['tier']}")
            if c and resolved(c["fingerprint"], c["values_hash"]):
                amount = money(resolved(c["fingerprint"], c["values_hash"]))
            seen.add(key)
            old = cur_prices.get(key)
            if old and float(old[1]) == amount and old[2] == p["currency"]:
                continue
            if old:
                cur.execute("UPDATE core.price SET effective_to = %s WHERE id = %s", (today, old[0]))
                closed += 1
            cur.execute("""INSERT INTO core.price (sku_id, region, tier, currency, amount, effective_from, source, source_ref)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (*key, p["currency"], amount, today if old else read_at, p["source"], p["ref"]))
            opened += 1
        for key, old in cur_prices.items():   # no longer on the price list
            if key not in seen:
                cur.execute("UPDATE core.price SET effective_to = %s WHERE id = %s", (today, old[0]))
                closed += 1
    st["prices_opened"], st["prices_closed"] = opened, closed

    # links + external IDs (add-only)
    with conn.cursor() as cur:
        for code, s in m.skus.items():
            for kind, url, src in s["links"]:
                cur.execute("INSERT INTO core.sku_link (sku_id, kind, url, source) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (ids[code], kind, url, src))
            for system, key in s["external_ids"]:
                cur.execute("INSERT INTO core.external_id (sku_id, system, external_key) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (ids[code], system, key))

    # provenance
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO core.field_source (sku_id, field, value, source, source_ref, read_at) VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (sku_id, field, source, source_ref) DO UPDATE SET value = EXCLUDED.value, read_at = EXCLUDED.read_at
                           WHERE core.field_source.value IS DISTINCT FROM EXCLUDED.value""",
                        [(ids[code], f, v, src, ref, read_at) for code, s in m.skus.items() for f, v, src, ref in s["field_sources"]])

    # stock
    for loc, counted in sorted(m.locations.items()):
        conn.execute("""INSERT INTO core.stock_location (name, counted) VALUES (%s,%s)
                        ON CONFLICT (name) DO UPDATE SET counted = EXCLUDED.counted""", (loc, counted))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO core.stock_snapshot (sku_id, location, as_of, available, on_hand, on_order) VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (sku_id, location, as_of) DO UPDATE SET available = EXCLUDED.available,
                             on_hand = EXCLUDED.on_hand, on_order = EXCLUDED.on_order""",
                        [(ids[x["code"]], x["location"], as_of, x["available"], x["on_hand"], x["on_order"]) for x in m.stock])

    # costs: a new dated record only when a source's value changes
    latest = {(r[0], r[1]): float(r[2]) for r in conn.execute(
        "SELECT DISTINCT ON (sku_id, source) sku_id, source, amount FROM cost.unit_cost ORDER BY sku_id, source, effective_from DESC, id DESC")}
    added = 0
    with conn.cursor() as cur:
        for c in m.costs:
            key = (ids[c["code"]], c["source"])
            if latest.get(key) == c["amount"]:
                continue
            cur.execute("""INSERT INTO cost.unit_cost (sku_id, amount, currency, effective_from, source, source_priority, source_ref)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (key[0], c["amount"], c["currency"], c["read_at"] if key not in latest else today, c["source"],
                         R.COST_PRIORITY[c["source"]], c["ref"]))
            latest[key] = c["amount"]
            added += 1
        for code, (amt, ref) in m.sheet_landed.items():
            if code in ids:
                cur.execute("""INSERT INTO cost.sheet_landed_cost (sku_id, amount, source_ref) VALUES (%s,%s,%s)
                               ON CONFLICT (sku_id) DO UPDATE SET amount = EXCLUDED.amount, source_ref = EXCLUDED.source_ref""", (ids[code], amt, ref))
    st["cost_records_added"] = added

    # exclusions
    with conn.cursor() as cur:
        for e in m.exclusions.values():
            cur.execute("""INSERT INTO ops.exclusion (code, reason, seen_in) VALUES (%s,%s,%s)
                           ON CONFLICT (code) DO UPDATE SET reason = EXCLUDED.reason, seen_in = EXCLUDED.seen_in, last_seen = current_date""",
                        (e["code"], e["reason"], sorted(e["seen_in"])))

    # conflicts: remember decisions; reopen when the sources change; clear when they agree again
    existing = {r[0]: r[1] for r in conn.execute("SELECT fingerprint, status FROM ops.conflict")}
    with conn.cursor() as cur:
        for fp, c in m.conflicts.items():
            r = resolutions.get(fp)
            status = "open" if not r else ("resolved" if r[1] == c["values_hash"] else "reopened")
            cur.execute("""INSERT INTO ops.conflict (fingerprint, sku_code, kind, detail, candidates, values_hash, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (fingerprint) DO UPDATE SET kind = EXCLUDED.kind, detail = EXCLUDED.detail,
                             candidates = EXCLUDED.candidates, values_hash = EXCLUDED.values_hash, status = EXCLUDED.status,
                             last_seen = current_date""",
                        (fp, c["sku_code"], c["kind"], c["detail"], Jsonb(c["candidates"]), c["values_hash"], status))
        for fp, status in existing.items():
            if fp not in m.conflicts and status != "cleared":
                cur.execute("UPDATE ops.conflict SET status = 'cleared' WHERE fingerprint = %s", (fp,))
    # fix list: values elsewhere that differ from the trusted source; 'fixed' once they agree
    seen_fix = set()
    with conn.cursor() as cur:
        for f in m.source_fixes:
            seen_fix.add((f["code"], f["field"], f["source"]))
            cur.execute("""INSERT INTO ops.source_fix (sku_code, field, source, source_value, correct_value, source_ref, correct_ref)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (sku_code, field, source) DO UPDATE SET source_value = EXCLUDED.source_value,
                             correct_value = EXCLUDED.correct_value, source_ref = EXCLUDED.source_ref,
                             correct_ref = EXCLUDED.correct_ref, status = 'open', last_seen = current_date""",
                        (f["code"], f["field"], f["source"], f["source_value"], f["correct_value"], f["source_ref"], f["correct_ref"]))
        for key in conn.execute("SELECT sku_code, field, source FROM ops.source_fix WHERE status = 'open'").fetchall():
            if tuple(key) not in seen_fix:
                cur.execute("UPDATE ops.source_fix SET status = 'fixed' WHERE (sku_code, field, source) = (%s,%s,%s)", key)
    st["source_fixes_open"] = len(seen_fix)

    st["conflicts_open"] =sum(1 for fp in m.conflicts if fp not in resolutions or resolutions[fp][1] != m.conflicts[fp]["values_hash"])
    st["skus"] = len(m.skus)
    st["missing_cost_tier1"] = len(m.missing_cost)
    st["warnings"] = m.warnings
    return st


def resolve(conn, fingerprint, value, actor, note=None, source=None):
    row = conn.execute("SELECT values_hash FROM ops.conflict WHERE fingerprint = %s", (fingerprint,)).fetchone()
    if not row:
        raise SystemExit(f"No conflict {fingerprint!r}")
    with conn.transaction():
        conn.execute("SELECT set_config('msku.actor', %s, true)", (actor,))
        conn.execute("""INSERT INTO ops.conflict_resolution (fingerprint, chosen_value, chosen_source, note, values_hash, decided_by)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (fingerprint) DO UPDATE SET chosen_value = EXCLUDED.chosen_value, chosen_source = EXCLUDED.chosen_source,
                          note = EXCLUDED.note, values_hash = EXCLUDED.values_hash, decided_by = EXCLUDED.decided_by, decided_at = now()""",
                     (fingerprint, value, source, note, row[0], actor))
        conn.execute("UPDATE ops.conflict SET status = 'resolved' WHERE fingerprint = %s", (fingerprint,))
    conn.commit()
