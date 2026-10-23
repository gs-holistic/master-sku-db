"""Reviewable mapping rules: Ken's decisions and where each field comes from.

Every rule here traces to DECISIONS.md. Change rules here, not in the import code.
"""
import re

# ---------- sources (Google Sheets shared with the service account)
SPREADSHEETS = {
    "prices":   ("1py6ZHFpUhNcK7hLxJNAecqUOiWlZ8cQ05Qmcp9w6kpc", "G Pen / Stündenglass Price Lists + Order Form + Ex-Factory Unit Costs"),
    "master":   ("1vMuhrqFVbgF_sgQGQIpfr_BtQPoeTsxJzEHYZSPEqik", "Master SKU-List GS Holistic"),
    "cin7":     ("1ju5tBsHgA9Wg9TSqfbP5gdV6-UPx5aCJMTdyQ1mUj5o", "Cin7 INVENTORY"),
    "gp_tpl":   ("1HL308_98Vfn-mFGkCury3rQPcfwqG_ISusoUbwZFCCY", "G-Pen-SKU-Details-Template"),
    "sg_tpl":   ("1q80TbUUDTqif3KXRoeRsb0tYz_Jf_sZVwXHWnsi2skE", "Stundenglass-SKU-Details-Template"),
}

# ---------- Tier 1: the 12 price tabs. tab -> (brand, region, currency, columns)
# Columns: B = SKU, C = name, D = MSRP, E = wholesale, F = distribution (D tabs only). Header on row 4.
PRICE_TABS = {
    "GP US WS": ("G Pen", "US", "USD"), "GP US D": ("G Pen", "US", "USD"),
    "GP CA WS": ("G Pen", "CA", "CAD"), "GP CA D": ("G Pen", "CA", "CAD"),
    "GP EU WS": ("G Pen", "EU", "EUR"), "GP EU D": ("G Pen", "EU", "EUR"),
    "STG US WS": ("Stündenglass", "US", "USD"), "STG US D": ("Stündenglass", "US", "USD"),
    "STG CA WS": ("Stündenglass", "CA", "CAD"), "STG CA D": ("Stündenglass", "CA", "CAD"),
    "STG EU W": ("Stündenglass", "EU", "EUR"), "STG EU D": ("Stündenglass", "EU", "EUR"),
}
PRICE_COLUMNS = {3: "msrp", 4: "wholesale", 5: "distribution"}
PRICE_HEADER_ROWS = 4
ORDER_FORM_TAB = "GP/STG ORDER FORM"            # compared against, not a Tier 1 source
EX_FACTORY_TAB = "GP/STG EX-FACTORY UNIT COSTS"  # col F = ex-factory unit cost (confidential)
EX_FACTORY_COST_COL = 5
# Ken: "$" on GP EU WS is a typo for €.
EUR_TABS_WITH_DOLLAR_TYPO = {"GP EU WS"}

# ---------- Cin7 stock: only column L "Available", only these locations
CIN7_COLUMNS = {"category": 0, "sku": 1, "name": 2, "location": 3, "on_hand": 9, "available": 11,
                "on_order": 12, "status": 15, "brand": 19, "msrp": 20, "wholesale": 21, "distribution": 22}
CIN7_AVAILABLE_HEADER = "Available"   # import refuses to run if column L is renamed
COUNTED_LOCATIONS = frozenset({
    "Anlerr", "DMT GPEN", "DMT STG", "In Transit - STG", "In Transit- GPEN",
    "Retail North LTD (Franklins 3PL)", "South Reed", "Vandeventer GPEN B2B",
    "Vandeventer GPEN B2C", "Vandeventer STG B2C", "WeFill GPEN B2B", "WeFill GPEN B2C",
    "WeFill STG B2C",
})
# Cin7 PriceTier1/2/3 = US MSRP / wholesale / distribution (confirmed by Ken).

# ---------- exclusions
KEEP_PACKS = {"GHO-007-AOZZ-10"}
DROPPED_PACK_RE = re.compile(r"^G[A-Z0-9]{2}-[A-Z0-9]{3}-[A-Z0-9]{4}-(10|20)$")
EXCLUDED_PREFIXES = [
    ("GG00-", "Grenco Goods (not G Pen / Stündenglass)"),
    ("ROUTEINS", "Route shipping protection"),
    ("CS-ONLY", "Customer-service-only part code"),
]

# ---------- master sheet
MASTER_TABS = {"Stundenglass": "Stündenglass", "G Pen": "G Pen"}
MASTER_COST_HEADERS = {"Product Cost (Per Unit)": "unit_cost", "Landed Cost": "landed_cost"}
# (tab, sheet row, code) -> why. The code is part of the key so a shifted row is never dropped by mistake.
DROPPED_MASTER_ROWS = {
    ("G Pen", 84, "GPD-002-AMGD"): "Duplicate: Ken removed the BLU row (kept row 77)",
    ("G Pen", 76, "GPD-001-AMGD"): "Duplicate: SKU is blue, kept row 83",
    ("Stundenglass", 67, "SG2-UPL-GLPR-02"): "Duplicate: Ken kept row 20",
    ("Stundenglass", 400, "SGM-DFK-GDAO-02"): "Duplicate: Ken kept row 285",
}
KEEP_BOTH_DUPLICATES = {"SG4-KIT-STBK-02"}

# ---------- field overrides (Ken's corrections). Applied last, and recorded as source "Ken (decision)".
OVERRIDES = {
    ("GPD-002-AMGD", "variant_code"): "RED",
    ("GPD-001-AMGD", "variant_code"): "BLU",
    ("SGM-DFK-GDAO-02", "name"): "Grateful Dead x Modül + Dok Deluxe Travel Set - Legacy Patchwork",
}

# ---------- name precedence (first source with a value wins; others kept in field_source)
NAME_SOURCES = ("override", "prices", "master", "gp_tpl", "sg_tpl", "cin7")

# ---------- cost source priority (lower wins on the same date). Master sheet is fallback only.
COST_PRIORITY = {"manual": 1, "ex_factory": 2, "master": 3}

# ---------- family from the price-list category heading (headings not listed -> no family)
FAMILY_FROM_HEADING = {
    "MICRO II": "Micro II", "MICRO+": "Micro+", "DASH": "Dash", "DASH II": "Dash II", "DASH+": "Dash+",
    "CONNECT": "Connect", "ROAM": "Roam", "HYDOUT": "Hydout", "MELT": "Melt", "GRINDER": "Grinder",
    "510": "510", "510 OG": "510",
    "STÜNDENGLASS": "Gravity Infuser", "STÜNDENGLASS - CLASSIC": "Gravity Infuser Classic",
    "GLASS GLOBES": "Gravity Infuser", "HOSE TIPS": "Gravity Infuser",
    "ACCESSORIES / FULL-SIZE / BLACK": "Gravity Infuser", "ACCESSORIES / FULL-SIZE / COOKIES": "Gravity Infuser",
    "ACCESSORIES / FULL-SIZE / TYSON 2.0": "Gravity Infuser",
    "KOMPACT": "Kompact", "ACCESSORIES / KOMPACT / BLACK": "Kompact",
    "MODÜL": "Modül", "MODÜL ACCESSORIES": "Modül", "EMPIRE GLASS": "Empire Glass",
}

# ---------- prices: which tab is primary when the WS and D tab disagree (conflict stays open until Ken decides)
PRICE_PRIMARY = {"msrp": "WS", "wholesale": "WS", "distribution": "D"}

# Costs above this are rejected as data errors (e.g. a UPC pasted into a cost cell) and reported.
MAX_PLAUSIBLE_COST = 100_000

# Ken (2026-10-22): the price list always beats Cin7 and the master sheet's MSRP.
# Only these observation kinds can create a price conflict; anything else that differs goes on the fix list.
PRICE_LIST_KINDS = ("WS", "D", "order_form")

# Ken (2026-10-23): for the Gravity Infuser V3 SKUs the price list's "MSRP" column is really the B2B MAP,
# in every region. The B2C MSRP is separate. (code, region) -> B2C MSRP, or None while Ken hasn't given it
# (then MAP is loaded and MSRP is left empty and flagged). Every other product keeps "MSRP" as labelled.
_GRAVITY_V3 = ("SG4-KIT-STBK-02", "SG4-KIT-STBU-02", "SG4-KIT-STDR-02", "SG4-KIT-STGR-02", "SG4-KIT-STPU-02")
_B2C_MSRP = {"US": 499.95, "CA": None, "EU": None}   # US matches stundenglass.com and Cin7 PriceTier1
MAP_ON_PRICE_LIST = {(code, region): msrp for code in _GRAVITY_V3 for region, msrp in _B2C_MSRP.items()}

# ---------- manual tier overrides (Ken's decisions). code -> (tier, why). Applied after the normal rule,
# recorded in tier history with the reason, and kept on every future import.
TIER_OVERRIDES = {
    "GPM-001-APZZ": (1, "Set by Ken (2026-10-23): Micro II Vaporizer is active; sold on the price list as its 10-pack POP"),
}
