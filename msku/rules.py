"""Pure rules: SKU code validation, exclusions, pack types, parsing, tiers. No I/O here."""
import re

from . import mapping_rules as R

# ---------- SKU code conventions
# G Pen:         GPD-001-APZZ            (prefix-3 digits-4 letters), optional pack suffix
# Stündenglass:  SG4-KIT-STGR-02         (prefix-component-brand/colour-country)
# Collateral:    GMK-008-APZZ, MRH-001-AFZZ, MRC-DHB-STBK-02
GPEN_BASE = re.compile(r"^(?P<prefix>G[A-Z]{2}|ASE|VPM|MRH)-(?P<num>\d{3}|[A-Z]{3})-(?P<variant>[A-Z]{4})$")
STG_BASE = re.compile(r"^(?P<prefix>SG[A-Z0-9]|MRC)-(?P<part>[A-Z0-9]{3})-(?P<variant>[A-Z0-9]{4})-(?P<country>[A-Z0-9]{2})$")
PACK_SUFFIXES = {
    "-Inner Pack": "inner_pack",
    "-Master Case": "master_case",
    "-POP": "pop_display",
}
VARIANT_SUFFIXES = ("-WP", "-RDP", "-WA", "-WL", "-PROMO", "-T")   # seen in data, meaning not yet confirmed


def split_code(code):
    """Return (base, suffix) where suffix is a known pack/variant suffix or ''."""
    for suf in list(PACK_SUFFIXES) + ["-Master Case 20 IP"]:
        if code.endswith(suf):
            return code[: -len(suf)], suf
    m = re.match(r"^(G[A-Z]{2}-\d{3}-[A-Z]{4})-(\d{2})$", code)
    if m:
        return m.group(1), "-" + m.group(2)
    for suf in VARIANT_SUFFIXES:
        if code.endswith(suf):
            return code[: -len(suf)], suf
    return code, ""


def check_code(code):
    """None if the code follows our conventions, otherwise a short reason. Never blocks import."""
    base, suf = split_code(code)
    if GPEN_BASE.match(base) or STG_BASE.match(base):
        if suf in VARIANT_SUFFIXES:
            return f"Suffix {suf} not yet documented"
        if suf == "-Master Case 20 IP":
            return "Non-standard master case suffix"
        return None
    if code != code.strip() or "  " in code:
        return "Extra spaces in code"
    return "Does not match G Pen / Stündenglass / collateral patterns"


def brand_for(code):
    if code.startswith(("SG", "MRC")):
        return "Stündenglass"
    if code.startswith("VPM"):
        return "Vapium"
    if code.startswith(("G", "ASE", "MRH")):
        return "G Pen"
    return None


def exclusion_reason(code):
    """Why a code is left out of the database, or None to keep it."""
    if not code or set(code) <= {"-"}:
        return "Placeholder row"
    if code in R.KEEP_PACKS:
        return None
    if R.DROPPED_PACK_RE.match(code):
        return "-10 / -20 pack SKU (removed per Ken)"
    for prefix, why in R.EXCLUDED_PREFIXES:
        if code.startswith(prefix):
            return why
    if re.fullmatch(r"\d+_\d+", code):
        return "Printful merch ID"
    if re.fullmatch(r"\d{5,7}", code):
        return "Legacy numeric ID"
    if not re.match(r"^[A-Z0-9]{3}-[A-Z0-9]{3}-[A-Z0-9]{4}", code):
        return "Non-product / non-standard code"
    return None


def pack_info(code):
    """(pack_type, pack_qty) from the code. Quantity comes from data later when the code doesn't say."""
    base, suf = split_code(code)
    if suf in PACK_SUFFIXES:
        return PACK_SUFFIXES[suf], None
    if suf.startswith("-Master Case"):
        return "master_case", None
    if re.fullmatch(r"-\d{2}", suf):
        return "multi_pack", int(suf[1:])
    if re.match(r"^[A-Z0-9]{3}-KIT-", code):
        return "kit", None
    return "single_unit", 1


def base_code(code):
    base, suf = split_code(code)
    return base if suf and (suf in PACK_SUFFIXES or suf.startswith("-Master Case") or re.fullmatch(r"-\d{2}", suf)) else None


# ---------- parsing
def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def money(s):
    s = norm(s).replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    return round(float(m.group()), 2) if m else None


def number(s):
    try:
        return float(norm(s).replace(",", ""))
    except ValueError:
        return None


def upc(s):
    """Digits-only UPC/GTIN, or None if the cell holds a link or file name."""
    s = norm(s)
    return s if re.fullmatch(r"\d{11,14}", s) else None


def upc_key(s):
    """Compare UPC-A and GTIN-14 forms of the same number."""
    return s.lstrip("0") if s else None


_UNIT_MM = {"mm": 1, "cm": 10, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4}
_UNIT_G = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "kg": 1000, "lb": 453.592, "lbs": 453.592, "oz": 28.3495}


def dims_mm(s, default_unit="mm"):
    """'92 x 92 x 62 mm' -> (92, 92, 62). None if not three numbers."""
    s = norm(s).lower().replace("×", "x")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) != 3 or "/" in s:
        return None
    unit = next((u for u in sorted(_UNIT_MM, key=len, reverse=True) if u in s), default_unit)
    return tuple(round(float(n) * _UNIT_MM[unit], 1) for n in nums)


def weight_g(s, default_unit=None):
    """'749 gr' -> 749, '15.7 Kg' -> 15700. None when there's no unit and no default."""
    s = norm(s).lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]*)", s)
    if not m:
        return None
    unit = m.group(2) or default_unit
    if unit not in _UNIT_G:
        return None
    return round(float(m.group(1)) * _UNIT_G[unit], 1)


# ---------- tiers
def tier_for(on_price_list, available_counted, in_development=False):
    """Ken's rule. Returns (tier, reason)."""
    if on_price_list:
        return 1, "On the price list"
    if in_development:
        return 1, "In development"
    if available_counted > 0:
        return 2, f"Not on price list; {available_counted:,.0f} available in counted locations"
    return 3, "Not on price list; no available stock in counted locations"
