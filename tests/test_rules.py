import pytest

from msku import rules


@pytest.mark.parametrize("code", ["GPD-001-APZZ", "GPD-001-APZZ-Inner Pack", "SG4-KIT-STGR-02", "GMK-008-APZZ",
                                  "MRC-DHB-STBK-02", "GSB-001-AOZZ-Master Case", "GCB-001-ANZZ-POP", "GHO-007-AOZZ-10"])
def test_valid_codes(code):
    assert rules.check_code(code) is None


@pytest.mark.parametrize("code,why", [
    ("SG2-KIT-STBK-02-RDP", "Suffix -RDP"),
    ("GPD-001-APZZ-Master Case 20 IP", "Non-standard master case"),
    ("GPD-1-APZZ", "Does not match"),
    ("gpd-001-apzz", "Does not match"),
])
def test_odd_codes_are_flagged(code, why):
    assert why in rules.check_code(code)


@pytest.mark.parametrize("code,reason", [
    ("GHK-001-AOZZ-20", "-10 / -20"), ("GHO-001-AOZZ-10", "-10 / -20"), ("GG00-ASH-FL-10", "Grenco Goods"),
    ("ROUTEINS10", "Route"), ("2864807_4625", "Printful"), ("106650", "Legacy"), ("CS-ONLY-Magnetic-Elbow-Green", "Customer-service"),
    ("---", "Placeholder"), ("", "Placeholder"), ("shopifyDefaultSKU", "Non-product"),
])
def test_exclusions(code, reason):
    assert reason in rules.exclusion_reason(code)


@pytest.mark.parametrize("code", ["GHO-007-AOZZ-10", "GPD-001-APZZ", "SG4-KIT-STGR-02", "SG2-GLB-STBK-02"])
def test_not_excluded(code):
    assert rules.exclusion_reason(code) is None


def test_stundenglass_country_code_is_not_a_pack_suffix():
    # "-02" on Stündenglass codes is the country code, never a 2-pack
    assert rules.pack_info("SG2-GLB-STBK-02") == ("single_unit", 1)
    assert rules.base_code("SG2-GLB-STBK-02") is None


@pytest.mark.parametrize("code,expected", [
    ("GPD-001-APZZ", ("single_unit", 1)), ("GPD-001-APZZ-Inner Pack", ("inner_pack", None)),
    ("GSB-001-AOZZ-Master Case", ("master_case", None)), ("GHO-007-AOZZ-10", ("multi_pack", 10)),
    ("SG4-KIT-STGR-02", ("kit", None)), ("GCB-001-ANZZ-POP", ("pop_display", None)),
])
def test_pack_info(code, expected):
    assert rules.pack_info(code) == expected


def test_base_code():
    assert rules.base_code("GPM-001-APZZ-Inner Pack") == "GPM-001-APZZ"
    assert rules.base_code("GPM-001-APZZ") is None


@pytest.mark.parametrize("raw,val", [("$499.50", 499.5), ("€1,299.00", 1299.0), ("  $9.95 ", 9.95), ("", None), ("N/A", None)])
def test_money(raw, val):
    assert rules.money(raw) == val


@pytest.mark.parametrize("raw,val", [("811736020343", "811736020343"), ("10811736020357", "10811736020357"),
                                     ("G Pen Melt_00811736029711 UPC-A SST1.eps", None), ("https://drive.google.com/x", None)])
def test_upc(raw, val):
    assert rules.upc(raw) == val


def test_upc_key_matches_gtin_forms():
    assert rules.upc_key("00811736020343") == rules.upc_key("811736020343")


@pytest.mark.parametrize("raw,val", [("92 x 92 x 62 mm", (92, 92, 62)), ("320 × 220 × 260 mm", (320, 220, 260)),
                                     ("10 x 5 x 2 cm", (100, 50, 20)), ("122x102x143 / Air", None), ("big", None)])
def test_dims(raw, val):
    assert rules.dims_mm(raw) == val


@pytest.mark.parametrize("raw,default,val", [("749 gr", None, 749), ("15.7 Kg", None, 15700), ("2.52 kg", None, 2520),
                                             ("0.05", "kg", 50), ("0.05", None, None), ("heavy", None, None)])
def test_weight(raw, default, val):
    assert rules.weight_g(raw, default) == val


def test_tiers():
    assert rules.tier_for(True, 0)[0] == 1          # active at zero stock stays Tier 1
    assert rules.tier_for(False, 0, in_development=True)[0] == 1
    assert rules.tier_for(False, 5)[0] == 2
    assert rules.tier_for(False, 0)[0] == 3
    assert rules.tier_for(False, -2)[0] == 3
