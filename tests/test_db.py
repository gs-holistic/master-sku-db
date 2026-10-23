"""Integration tests against a throwaway Postgres database."""
import copy
import os
import uuid

import psycopg
import pytest

from msku import db
from msku.consolidate import consolidate
from tests.fixtures import sources

ADMIN = os.environ.get("MSKU_TEST_ADMIN_URL", "postgresql://postgres@/postgres?host=/tmp&port=5433")


@pytest.fixture()
def conn():
    name = "msku_test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute(f"CREATE DATABASE {name}")
    c = psycopg.connect(ADMIN.replace("/postgres?", f"/{name}?"))
    db.migrate(c)
    yield c
    c.close()
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


def run(conn, src, dry=False):
    return db.load(conn, consolidate(src), src, "test", dry_run=dry)


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def test_dry_run_saves_nothing(conn):
    st = run(conn, sources(), dry=True)
    assert st["changes"]["core.sku insert"] > 0
    assert one(conn, "SELECT count(*) FROM core.sku")[0] == 0


def test_import_is_idempotent(conn):
    run(conn, sources())
    v1 = conn.execute("SELECT code, version, updated_at FROM core.sku ORDER BY code").fetchall()
    st = run(conn, sources())
    assert st["changes"] == {} and st["prices_opened"] == 0 and st["cost_records_added"] == 0
    assert conn.execute("SELECT code, version, updated_at FROM core.sku ORDER BY code").fetchall() == v1


def test_price_change_keeps_history(conn):
    run(conn, sources())
    src = sources()
    src["prices"]["tabs"]["GP US WS"][5][4] = "$65.00"
    st = run(conn, src)
    assert st["prices_opened"] == 1 and st["prices_closed"] == 1
    rows = conn.execute("""SELECT amount, effective_to IS NULL FROM api.price_history
                           WHERE sku_code = 'GPM-001-APZZ' AND region = 'US' AND price_tier = 'wholesale' ORDER BY amount""").fetchall()
    assert [(float(a), cur) for a, cur in rows] == [(60.0, False), (65.0, True)]


def test_tier_change_recorded(conn):
    run(conn, sources())
    src = sources()
    src["prices"]["tabs"]["STG US WS"].pop()       # SG4-KIT-STGR-02 leaves every price tab
    for t in ("STG US D", "STG CA WS", "STG CA D", "STG EU W", "STG EU D"):
        src["prices"]["tabs"][t].pop()
    st = run(conn, src)
    assert st["tier_moves"] == 1
    assert one(conn, "SELECT old_tier, new_tier FROM api.tier_history WHERE sku_code = 'SG4-KIT-STGR-02' AND old_tier IS NOT NULL") == (1, 3)
    assert one(conn, "SELECT count(*) FROM api.prices WHERE sku_code = 'SG4-KIT-STGR-02'")[0] == 0   # prices closed


def test_resolution_is_remembered_and_reopens_when_sources_change(conn):
    run(conn, sources())
    fp = "GPM-001-APZZ|upc"
    db.resolve(conn, fp, "811736020343", "ken")
    run(conn, sources())
    assert one(conn, "SELECT status FROM ops.conflict WHERE fingerprint = %s", fp)[0] == "resolved"
    assert one(conn, "SELECT upc FROM core.sku WHERE code = 'GPM-001-APZZ'")[0] == "811736020343"
    src = sources()
    src["gp_tpl"]["tabs"]["SKU Details"][4][4] = "811736020111"
    run(conn, src)
    assert one(conn, "SELECT status FROM ops.conflict WHERE fingerprint = %s", fp)[0] == "reopened"


def test_conflict_clears_when_sources_agree(conn):
    run(conn, sources())
    src = sources()
    src["gp_tpl"]["tabs"]["SKU Details"][4][4] = "811736020343"
    run(conn, src)
    assert one(conn, "SELECT status FROM ops.conflict WHERE fingerprint = 'GPM-001-APZZ|upc'")[0] == "cleared"


def test_cost_rules(conn):
    run(conn, sources())
    # ex-factory beats master; landed = unit x 1.24
    src_, unit, landed = one(conn, "SELECT unit_cost_source, unit_cost, approx_landed_cost FROM cost.landed_cost WHERE code = 'GPM-001-APZZ'")
    assert (src_, float(unit), float(landed)) == ("ex_factory", 13.37, 16.58)
    assert one(conn, "SELECT cost_missing FROM cost.landed_cost WHERE code = 'SG4-KIT-STGR-02'")[0] is True
    # a new per-order cost entered later wins and keeps history
    sid = one(conn, "SELECT id FROM core.sku WHERE code = 'GPM-001-APZZ'")[0]
    conn.execute("""INSERT INTO cost.unit_cost (sku_id, amount, effective_from, source, source_priority, order_ref)
                    VALUES (%s, 11.5, current_date + 1, 'manual', 1, 'PO-123')""", (sid,))
    assert float(one(conn, "SELECT unit_cost FROM cost.landed_cost WHERE code = 'GPM-001-APZZ'")[0]) == 11.5
    assert one(conn, "SELECT count(*) FROM cost.unit_cost WHERE sku_id = %s", sid)[0] == 3
    # the uplift is a setting
    conn.execute("UPDATE cost.setting SET value = 0.30 WHERE key = 'landed_uplift'")
    assert float(one(conn, "SELECT approx_landed_cost FROM cost.landed_cost WHERE code = 'GPM-001-APZZ'")[0]) == 14.95   # the PO cost (11.50) x 1.30


def test_audit_records_who_and_before(conn):
    run(conn, sources())
    conn.execute("SELECT set_config('msku.actor', 'ken', false)")
    conn.execute("UPDATE core.sku SET name = 'Renamed' WHERE code = 'GPX-999-ZZZZ'")
    actor, before, after = one(conn, """SELECT actor, before->>'name', after->>'name' FROM ops.audit_log
                                        WHERE table_name = 'core.sku' AND action = 'UPDATE' ORDER BY id DESC LIMIT 1""")
    assert (actor, before, after) == ("ken", "Old thing", "Renamed")
    assert one(conn, "SELECT version FROM core.sku WHERE code = 'GPX-999-ZZZZ'")[0] == 2


def test_api_reader_cannot_see_costs(conn):
    run(conn, sources())
    conn.commit()
    conn.execute("SET ROLE msku_api_reader")
    assert one(conn, "SELECT count(*) FROM api.skus")[0] > 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM cost.unit_cost")
    conn.rollback()
    conn.execute("SET ROLE msku_api_reader")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM core.sku")
    conn.rollback()
    conn.execute("SET ROLE msku_cost_reader")
    assert one(conn, "SELECT count(*) FROM cost.landed_cost")[0] > 0
    conn.rollback()


def test_api_has_no_cost_columns(conn):
    cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'api'")}
    assert not any("cost" in c for c in cols)
    assert {"sku_id", "sku_code", "updated_at", "version"} <= cols


def test_sku_that_leaves_every_source_drops_to_tier_3(conn):
    run(conn, sources())
    src = sources()
    rows = src["cin7"]["tabs"]["AvailabilityReport_2026-10-22"]
    src["cin7"]["tabs"]["AvailabilityReport_2026-10-22"] = [r for r in rows if r[1] != "GPX-999-ZZZZ"]
    src["master"]["tabs"]["G Pen"] = [r for r in src["master"]["tabs"]["G Pen"] if not (r and r[0] == "GPX-999-ZZZZ")]
    st = run(conn, src)
    assert st["skus_no_longer_in_sources"] == ["GPX-999-ZZZZ"]
    assert one(conn, "SELECT tier FROM api.skus WHERE sku_code = 'GPX-999-ZZZZ'")[0] == 3      # was Tier 2, still kept
    assert one(conn, "SELECT old_tier, new_tier FROM api.tier_history WHERE sku_code = 'GPX-999-ZZZZ' AND old_tier IS NOT NULL") == (2, 3)
    assert run(conn, src)["tier_moves"] == 0                                                   # idempotent
