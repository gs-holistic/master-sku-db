"""The G Pen Hub API, called as WSGI against a throwaway database loaded from the fixture sheets."""
import io
import json
import uuid
from urllib.parse import quote, urlencode

import psycopg
import pytest

from msku import db, hub_api
from msku.consolidate import consolidate
from tests.fixtures import sources
from tests.test_db import ADMIN

KEY = "test-key-" + "x" * 40
WHO = "jordan@example.com"


@pytest.fixture()
def api(monkeypatch):
    name = "msku_test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute(f"CREATE DATABASE {name}")
    url = ADMIN.replace("/postgres?", f"/{name}?")
    conn = psycopg.connect(url)
    db.migrate(conn)
    db.load(conn, consolidate(sources()), sources(), "ken")
    monkeypatch.setenv("MSKU_DATABASE_URL", url)
    monkeypatch.setenv("MSKU_API_KEYS", f"old-key-{'y' * 40}, {KEY}")
    monkeypatch.delenv("MSKU_ALLOW_HTTP", raising=False)
    yield conn
    conn.close()
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


def call(method, path, body=None, key=KEY, proto="https", query=None):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": quote(path, safe="/").encode().decode("latin-1"),
           "QUERY_STRING": urlencode(query or {}), "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
           "wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": proto}
    # A real server hands PATH_INFO over already %-decoded, as latin-1 text
    from urllib.parse import unquote_to_bytes
    env["PATH_INFO"] = unquote_to_bytes(env["PATH_INFO"]).decode("latin-1")
    if key is not None:
        env["HTTP_X_API_KEY"] = key
    got = {}
    out = hub_api.app(env, lambda status, headers: got.update(status=int(status.split()[0])))
    return got["status"], json.loads(b"".join(out))


def sku(code):
    return call("GET", f"/skus/{code}")[1]


# ---------- auth and transport

def test_rejects_missing_wrong_key_and_plain_http(api):
    assert call("GET", "/health", key=None)[0] == 401
    assert call("GET", "/health", key="nope")[0] == 401
    assert call("GET", "/health", key="")[0] == 401
    assert call("GET", "/health", proto="http")[0] == 403
    assert call("GET", "/health") == (200, {"ok": True})


def test_both_keys_work_while_rotating(api):
    assert call("GET", "/health", key="old-key-" + "y" * 40)[0] == 200


# ---------- reading

def test_get_one_sku_in_hub_field_names(api):
    status, r = call("GET", "/skus/GPM-001-APZZ")
    assert status == 200
    assert list(r) == list(hub_api.FIELDS)
    assert r["sku"] == "GPM-001-APZZ" and r["brand"] == "G Pen"
    assert r["msrp"] == 99.95 and r["wholesale"] == 60.0 and r["distro"] == 51.0
    assert r["status"] == "active" and r["tier"] == 1
    assert r["pack_size"] == 1 and r["case_pack"] == 200
    assert r["product_dims"] == "18 x 18 x 90 mm" and r["product_weight"] == "45 g"
    assert r["case_dims"] == "400 x 300 x 200 mm" and r["case_weight"] == "9.5 kg"
    assert r["updated_at"].endswith("Z") and r["updated_by"] == "ken"


def test_no_cost_ever(api):
    text = json.dumps(call("GET", "/skus")[1]).lower()
    assert "cost" not in text and "13.37" not in text and "12.34" not in text


def test_codes_with_spaces_and_unknown_sku(api):
    assert call("GET", "/skus/GPM-001-APZZ-Inner Pack")[1]["pack_size"] == 10
    assert call("GET", "/skus/NOPE-1")[0] == 404


def test_list_search_and_updated_since(api):
    status, r = call("GET", "/skus")
    assert status == 200 and r["count"] == len(r["skus"]) > 3
    assert {s["sku"] for s in call("GET", "/skus", query={"q": "micro"})[1]["skus"]} == {"GPM-001-APZZ", "GPM-001-APZZ-Inner Pack"}
    assert call("GET", "/skus", query={"q": "%"})[1]["count"] == 0
    latest = max(s["updated_at"] for s in r["skus"])
    assert call("GET", "/skus", query={"updated_since": latest})[1]["count"] == 0
    assert call("GET", "/skus", query={"updated_since": "yesterday"})[0] == 400


def test_status_follows_tier_until_the_hub_sets_it(api):
    assert sku("GPX-999-ZZZZ")["status"] == "deprecated"   # Tier 2
    assert sku("GPX-777-ZZZZ")["status"] == "obsolete"     # Tier 3


# ---------- creating

def test_create_then_duplicate(api):
    body = {"sku": "GPN-123-APZZ", "name": "New Thing", "brand": "g pen", "upc": "00811736020000",
            "msrp": 49.95, "case_pack": 50, "product_dims": "4.5 x 2 x 1 in", "changed_by": WHO}
    status, r = call("POST", "/skus", body)
    assert status == 201
    assert r["brand"] == "G Pen" and r["upc"] == "00811736020000" and r["msrp"] == 49.95
    assert r["status"] == "draft" and r["tier"] is None and r["updated_by"] == WHO
    assert r["product_dims"] == "4.5 x 2 x 1 in" and r["case_pack"] == 50
    status, r = call("POST", "/skus", {**body, "sku": "gpn-123-apzz"})
    assert status == 409 and r["current"]["sku"] == "GPN-123-APZZ"


def test_create_validates_every_field(api):
    status, r = call("POST", "/skus", {"upc": 811736020000, "msrp": "$49.95", "case_pack": 2.5, "brand": "Acme",
                                       "status": "live", "tier": 1, "colour": "red"})
    assert status == 400
    assert set(r["fields"]) == {"sku", "changed_by", "upc", "msrp", "case_pack", "brand", "status", "tier", "colour"}
    assert "leading zeros" in r["fields"]["upc"] and "$" in r["fields"]["msrp"]
    assert call("POST", "/skus", {"sku": "X-1", "upc": "81173602A", "changed_by": WHO})[1]["fields"] == {"upc": "digits only, 8 to 14 of them"}
    assert call("POST", "/skus", {"sku": "X-1", "msrp": 1.005, "changed_by": WHO})[0] == 400
    assert call("POST", "/skus", {"sku": "X-1", "changed_by": "jordan"})[1]["fields"]["changed_by"].startswith("required")


def test_no_delete(api):
    assert call("DELETE", "/skus/GPM-001-APZZ")[0] == 405


# ---------- updating

def test_patch_changes_only_what_is_sent(api):
    before = sku("GPM-001-APZZ")
    status, r = call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": before["updated_at"], "msrp": 109.95,
                                                    "notes": "New box in Q1", "changed_by": WHO})
    assert status == 200
    assert r["msrp"] == 109.95 and r["notes"] == "New box in Q1" and r["updated_by"] == WHO
    assert {k: v for k, v in r.items() if k not in ("msrp", "notes", "updated_at", "updated_by")} == \
           {k: v for k, v in before.items() if k not in ("msrp", "notes", "updated_at", "updated_by")}
    hist = api.execute("""SELECT amount, effective_to IS NULL, source, source_ref FROM core.price p JOIN core.sku s ON s.id = p.sku_id
                          WHERE s.code = 'GPM-001-APZZ' AND region = 'US' AND tier = 'msrp' ORDER BY p.id""").fetchall()
    assert [(float(a), cur) for a, cur, *_ in hist] == [(99.95, False), (109.95, True)]
    assert hist[-1][2:] == ("G Pen Hub", WHO)


def test_patch_refuses_a_stale_record(api):
    first = sku("GPM-001-APZZ")
    assert call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": first["updated_at"], "name": "Micro II", "changed_by": WHO})[0] == 200
    status, r = call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": first["updated_at"], "name": "Other", "changed_by": WHO})
    assert status == 409 and r["current"]["name"] == "Micro II"
    assert call("PATCH", "/skus/GPM-001-APZZ", {"name": "Other", "changed_by": WHO})[1]["fields"] == {"updated_at": "required"}


def test_patch_accepts_the_same_sku_but_not_a_rename(api):
    s = sku("GPM-001-APZZ")
    assert call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "sku": "GPM-001-APZZ", "changed_by": WHO})[0] == 200
    assert call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "sku": "GPM-002", "changed_by": WHO})[0] == 400


def test_status_obsolete_and_clearing_a_price(api):
    s = sku("GPD-002-AMGD")
    status, r = call("PATCH", "/skus/GPD-002-AMGD", {"updated_at": s["updated_at"], "status": "obsolete",
                                                    "distro": None, "changed_by": WHO})
    assert status == 200 and r["status"] == "obsolete" and r["distro"] is None and r["tier"] == 1


# ---------- history

def test_changes_lists_who_changed_what(api):
    since = sku("GPM-001-APZZ")["updated_at"]
    s = sku("GPM-001-APZZ")
    call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "msrp": 109.95, "upc": "811736020998",
                                         "case_pack": 240, "changed_by": WHO})
    status, r = call("GET", "/changes", query={"since": since})
    assert status == 200
    got = {(c["sku"], c["field"], c["old_value"], c["new_value"], c["changed_by"]) for c in r["changes"]}
    assert ("GPM-001-APZZ", "msrp", 99.95, 109.95, WHO) in got
    assert ("GPM-001-APZZ", "case_pack", None, 240, WHO) in got
    assert any(f == "upc" and new == "811736020998" for _, f, _, new, _ in got)
    assert r["next_cursor"] is None
    assert call("GET", "/changes")[0] == 400


def test_changes_page_with_a_cursor(api):
    status, r = call("GET", "/changes", query={"since": "2000-01-01T00:00:00Z", "limit": 5})
    assert status == 200 and r["next_cursor"]
    nxt = call("GET", "/changes", query={"cursor": r["next_cursor"], "limit": 5})[1]
    assert nxt["changes"] and nxt["changes"] != r["changes"]


# ---------- the daily sync after a Hub write

def resync(conn):
    return db.load(conn, consolidate(sources()), sources(), "ken")


def test_sync_keeps_the_hub_value_and_flags_the_difference(api):
    s = sku("GPM-001-APZZ")
    call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "msrp": 109.95, "name": "Micro II", "changed_by": WHO})
    st = resync(api)
    after = sku("GPM-001-APZZ")
    assert after["msrp"] == 109.95 and after["name"] == "Micro II"
    flagged = {r[0] for r in api.execute("SELECT fingerprint FROM ops.conflict WHERE status = 'open'")}
    assert {"GPM-001-APZZ|hub_msrp", "GPM-001-APZZ|hub_name"} <= flagged
    assert st["prices_opened"] == 0


def test_deciding_for_the_sheet_hands_the_field_back(api):
    s = sku("GPM-001-APZZ")
    call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "msrp": 109.95, "changed_by": WHO})
    resync(api)
    db.resolve(api, "GPM-001-APZZ|hub_msrp", "99.95", "Ken")
    resync(api)
    assert sku("GPM-001-APZZ")["msrp"] == 99.95
    assert api.execute("SELECT count(*) FROM core.hub_lock WHERE field = 'msrp'").fetchone()[0] == 0
    resync(api)
    assert api.execute("SELECT status FROM ops.conflict WHERE fingerprint = 'GPM-001-APZZ|hub_msrp'").fetchone()[0] == "cleared"


def test_a_value_the_sheet_agrees_with_raises_nothing(api):
    s = sku("GPM-001-APZZ")
    call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "msrp": 99.95, "changed_by": WHO})
    resync(api)
    assert api.execute("SELECT count(*) FROM ops.conflict WHERE fingerprint LIKE '%%|hub_%%'").fetchone()[0] == 0


def test_sync_leaves_hub_created_skus_alone(api):
    call("POST", "/skus", {"sku": "GPN-123-APZZ", "name": "New Thing", "msrp": 49.95, "changed_by": WHO})
    st = resync(api)
    r = sku("GPN-123-APZZ")
    assert r["msrp"] == 49.95 and r["tier"] is None and r["status"] == "draft"
    assert "GPN-123-APZZ" not in st["skus_no_longer_in_sources"]


def test_sync_is_still_idempotent_with_hub_data(api):
    s = sku("GPM-001-APZZ")
    call("PATCH", "/skus/GPM-001-APZZ", {"updated_at": s["updated_at"], "msrp": 109.95, "changed_by": WHO})
    resync(api)
    st = resync(api)
    assert st["changes"] == {} and st["prices_opened"] == 0
