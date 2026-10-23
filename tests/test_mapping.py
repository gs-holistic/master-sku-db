"""Mapping rules and conflict detection on synthetic sheets."""
import pytest

from msku.consolidate import consolidate
from tests.fixtures import sources


@pytest.fixture(scope="module")
def m():
    return consolidate(sources())


def test_tiers(m):
    t = {c: s["tier"] for c, s in m.skus.items()}
    assert t["GPM-001-APZZ"] == 1 and t["GPM-001-APZZ-Inner Pack"] == 1 and t["SG4-KIT-STGR-02"] == 1
    assert t["GPX-999-ZZZZ"] == 2
    assert t["GPX-888-ZZZZ"] == 3     # stock only in Tradeshow, which doesn't count
    assert t["GPX-777-ZZZZ"] == 3
    assert t["GHO-007-AOZZ-10"] == 2  # the one kept -10 pack, tiered by its own row
    assert "available only in locations that don't count" in " ".join(m.skus["GPX-888-ZZZZ"]["flags"])


def test_exclusions(m):
    assert {"GHK-001-AOZZ-20", "GG00-ASH-FL-10", "ROUTEINS10"} <= set(m.exclusions)
    assert "GHK-001-AOZZ-20" not in m.skus
    assert "----" not in m.skus


def test_dropped_duplicate_row_and_overrides(m):
    s = m.skus["GPD-002-AMGD"]
    assert s["master_rows"] == ["G Pen row 3"]
    assert any("row 84" in k for k in m.exclusions)
    assert s["variant_code"] == "RED"          # Ken: RED is correct, sheet says BLU
    assert ("variant_code", "RED", "Ken (decision)", "DECISIONS.md") in s["field_sources"]


def test_missing_dropped_row_warns(m):
    assert any("not found where expected" in w for w in m.warnings)   # other dropped rows don't exist in the fixture


def test_upc_from_swapped_columns(m):
    assert m.skus["GPD-002-AMGD"]["upc"] == "811736027670"


def test_name_precedence(m):
    assert m.skus["GPM-001-APZZ"]["name"] == "G Pen Micro II Vaporizer"     # price list wins
    assert m.skus["GPX-999-ZZZZ"]["name"] == "Old thing"                     # master when not on price list


def test_eur_dollar_typo(m):
    eu = [p for p in m.prices if p["code"] == "GPM-001-APZZ" and p["region"] == "EU" and p["tier"] == "msrp"]
    assert eu and eu[0]["currency"] == "EUR"


def test_price_primary_tab(m):
    ws = [p for p in m.prices if p["code"] == "GPM-001-APZZ" and p["region"] == "US" and p["tier"] == "wholesale"][0]
    d = [p for p in m.prices if p["code"] == "GPM-001-APZZ" and p["region"] == "US" and p["tier"] == "distribution"][0]
    assert "WS" in ws["ref"] and " D " in d["ref"] + " "


def test_conflicts(m):
    c = m.conflicts
    assert "GPM-001-APZZ|upc" in c                     # master vs template UPC
    assert "GPM-001-APZZ|status_master" in c           # master Inactive but on price list
    assert "GPM-001-APZZ|price_CA_msrp" in c           # WS tab 99.95 vs D tab 129.95: Ken decides
    # Ken: the price list beats Cin7 and the master MSRP, so these are fix-list items, not conflicts
    assert "GPM-001-APZZ|price_US_distribution" not in c
    assert "SG4-KIT-STGR-02|price_US_msrp" not in c
    fixes = {(f["code"], f["field"], f["source"]) for f in m.source_fixes}
    assert ("GPM-001-APZZ", "US distribution", "Cin7") in fixes
    assert ("GPX-999-ZZZZ", "US msrp", "Master SKU-List GS Holistic") not in fixes   # not on the price list
    assert "GPM-001-APZZ|price_US_msrp" not in c       # all sources agree
    assert "GPM-001-APZZ|units_master_case" in c       # 100 (master) vs 200 (template)


def test_map_and_b2c_msrp(m):
    # Ken: for the SG4 Gravity Infusers the price list "MSRP" is the B2B MAP; B2C MSRP is 499.95
    p = {(x["tier"]): x for x in m.prices if x["code"] == "SG4-KIT-STGR-02" and x["region"] == "US"}
    assert p["map"]["amount"] == 449.95 and p["msrp"]["amount"] == 499.95
    assert p["msrp"]["source"] == "Ken (decision)"
    fixes = {(f["code"], f["field"], f["source"]) for f in m.source_fixes}
    assert ("SG4-KIT-STGR-02", "US msrp", "Master SKU-List GS Holistic") not in fixes   # master 499.95 agrees
    # CA / EU: same split; MAP from the price list, B2C MSRP left empty until Ken gives it
    ca = {x["tier"]: x for x in m.prices if x["code"] == "SG4-KIT-STGR-02" and x["region"] == "CA"}
    assert set(ca) == {"map", "wholesale", "distribution"} and ca["map"]["amount"] == 449.95
    assert "CA B2C MSRP not set yet (price list value is the MAP)" in m.skus["SG4-KIT-STGR-02"]["flags"]
    # every other product keeps the price list "MSRP" as MSRP
    assert {x["tier"] for x in m.prices if x["code"] == "GPM-001-APZZ" and x["region"] == "CA"} == {"msrp", "wholesale", "distribution"}


def test_conflict_hash_is_stable():
    a, b = consolidate(sources()), consolidate(sources())
    assert {k: v["values_hash"] for k, v in a.conflicts.items()} == {k: v["values_hash"] for k, v in b.conflicts.items()}


def test_costs_never_in_conflicts_and_bad_costs_rejected(m):
    assert not any("cost" in fp for fp in m.conflicts)
    assert not any(c["code"] == "SG4-KIT-STGR-02" for c in m.costs)       # 12-digit "cost" rejected
    assert any("implausible" in w for w in m.warnings)
    assert {c["source"] for c in m.costs if c["code"] == "GPM-001-APZZ"} == {"ex_factory", "master"}


def test_missing_cost_flagged(m):
    assert "SG4-KIT-STGR-02" in m.missing_cost and "GPM-001-APZZ" not in m.missing_cost


def test_packaging_parsed(m):
    p = m.skus["GPM-001-APZZ"]["packaging"]
    assert p["unit"]["weight_g"][0][0] == 45            # template "45 gr" before master "0.05" kg
    assert p["master_case"]["dims_mm"][0][0] == (400, 300, 200)


def test_staging_keeps_row_numbers_but_not_costs(m):
    assert any(t == "GP US WS" and row == 6 for _, _, t, row, _ in m.staging)
    master_rows = [r for _, _, t, _, r in m.staging if t == "G Pen"]
    assert all(len(r) < 3 or r[2] == "" for r in master_rows)
