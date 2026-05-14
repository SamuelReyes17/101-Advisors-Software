"""
Miami-Dade Property Appraiser — enrichment via public ArcGIS REST.

PRIMARY ENDPOINT (validated 2026-05-07):

    https://gisweb.miamidade.gov/arcgis/rest/services/
    MD_LandInformation/MapServer/24/query

    Layer: "Property @ PaGis" — the canonical Property Appraiser GIS table.
    44 fields including: FOLIO, TRUE_SITE_ADDR, TRUE_OWNER1/2/3,
    DOR_CODE_CUR + DOR_DESC, CONDO_FLAG, BEDROOM_COUNT, UNIT_COUNT,
    BUILDING_COUNT, YEAR_BUILT, LOT_SIZE, TRUE_MAILING_* fields, etc.

ADDRESS SEARCH ENDPOINT — to map address → folio:
    https://gisweb.miamidade.gov/arcgis/rest/services/
    AddressSearchMap_PropertiesWithZip/MapServer/0/query

USAGE:
    from pipeline.collectors.property_appraiser import enrich_by_folio

    info = enrich_by_folio("0141160040250")
    # {
    #   "folio": "0141160040250",
    #   "property_address": "2735 SW 36 AVE",
    #   "city": "Miami",
    #   "zip": "33133",
    #   "owner_name": "HERNANDO AMIL LE",
    #   "owners": ["HERNANDO AMIL LE", "JULIA AMIL LE", "REM HERNANDO AMIL JR"],
    #   "property_type": "Single Family",
    #   "dor_code": "0101",
    #   "dor_description": "RESIDENTIAL - SINGLE FAMILY : 1 UNIT",
    #   "is_condo": False,
    #   "units": 1,
    #   "bedrooms": 3,
    #   "bathrooms": 1.0,
    #   "year_built": 1946,
    #   "lot_size_sqft": 8145.92,
    #   "heated_area_sqft": 1454,
    #   "is_absentee_owner": False,
    #   "mailing_address": "2735 SW 36 AVE, MIAMI, FL 33133",
    # }
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

PAGIS_QUERY_URL = (
    "https://gisweb.miamidade.gov/arcgis/rest/services/"
    "MD_LandInformation/MapServer/24/query"
)
ADDRESS_QUERY_URL = (
    "https://gisweb.miamidade.gov/arcgis/rest/services/"
    "AddressSearchMap_PropertiesWithZip/MapServer/0/query"
)


def _http_get_json(url: str, params: dict, timeout: int = 15) -> dict[str, Any]:
    """Wrapper around requests for SSL robustness on macOS."""
    try:
        import requests
    except ImportError:
        full = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(full, headers={"User-Agent": "101AdvisorsBot/0.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
        "Accept": "application/json",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _query_first_feature(url: str, where: str, out_fields: str = "*") -> dict[str, Any] | None:
    try:
        data = _http_get_json(url, {"where": where, "outFields": out_fields, "f": "json"})
    except Exception as e:
        log.warning("ArcGIS query failed: %s · where=%s", e, where)
        return None
    if "error" in data:
        log.warning("ArcGIS error: %s", data["error"])
        return None
    feats = data.get("features", [])
    if not feats:
        return None
    return feats[0].get("attributes", {})


def _classify_from_dor(dor_desc: str, condo_flag: str, units: int) -> str:
    """Classify property type from DOR_DESC + CONDO_FLAG.

    DOR_DESC examples seen in Miami-Dade:
        "RESIDENTIAL - SINGLE FAMILY : 1 UNIT"
        "RESIDENTIAL - CONDOMINIUM : 1 UNIT"
        "MULTIFAMILY - 2-9 UNITS"
        "MULTIFAMILY - 10+ UNITS"
        "TOWNHOUSE"
        "VACANT LAND"
        "COMMERCIAL - ..."
        ...

    Returns one of: Single Family, Multi Family, Duplex, Triplex, Fourplex,
                    Condominium, Townhouse, Vacant Land, Commercial, Other.
    """
    desc = (dor_desc or "").upper()

    if (condo_flag or "").upper() == "Y" or "CONDO" in desc:
        return "Condominium"
    if "TOWNHOUSE" in desc or "TOWNHOME" in desc:
        return "Townhouse"
    if "VACANT" in desc:
        return "Vacant Land"
    if "COMMERCIAL" in desc or "COMM" in desc and "MULTI" not in desc:
        return "Commercial"
    if "SINGLE FAMILY" in desc or "SINGLE-FAMILY" in desc:
        return "Single Family"

    if "MULTIFAMILY" in desc or "MULTI-FAMILY" in desc or "MULTI FAMILY" in desc:
        # Try to refine by units count.
        if units == 2:
            return "Duplex"
        if units == 3:
            return "Triplex"
        if units == 4:
            return "Fourplex"
        return "Multi Family"

    if "MOBILE HOME" in desc:
        return "Mobile Home"

    # Fallback by units count
    if units == 1:
        return "Single Family"
    if units == 2:
        return "Duplex"
    if units == 3:
        return "Triplex"
    if units == 4:
        return "Fourplex"
    if units >= 5:
        return "Multi Family"

    return "Other"


def _normalize_address(line: str) -> str:
    """Normalize whitespace in an address string."""
    return re.sub(r"\s+", " ", (line or "").strip())


def enrich_by_folio(folio: str) -> dict[str, Any] | None:
    """Look up a property by its folio. Returns normalized dict or None."""
    folio = folio.replace("-", "").strip()
    where = f"FOLIO='{folio}'"

    attrs = _query_first_feature(PAGIS_QUERY_URL, where)
    if not attrs:
        return None

    # Owners (up to 3)
    owners = [
        (attrs.get(f"TRUE_OWNER{i}") or "").strip()
        for i in (1, 2, 3)
    ]
    owners = [o for o in owners if o]

    primary_owner = owners[0] if owners else ""
    owner_first, owner_last = _split_owner_name(primary_owner)

    # Site address
    site_addr = _normalize_address(attrs.get("TRUE_SITE_ADDR") or "")
    site_city = (attrs.get("TRUE_SITE_CITY") or "").strip()
    site_zip = (attrs.get("TRUE_SITE_ZIP_CODE") or "").strip().split("-")[0]  # strip ZIP+4

    # Mailing address (where the owner actually lives — if different = absentee)
    m_addr1 = _normalize_address(attrs.get("TRUE_MAILING_ADDR1") or "")
    m_addr2 = _normalize_address(attrs.get("TRUE_MAILING_ADDR2") or "")
    m_city = (attrs.get("TRUE_MAILING_CITY") or "").strip()
    m_state = (attrs.get("TRUE_MAILING_STATE") or "").strip()
    m_zip = (attrs.get("TRUE_MAILING_ZIP_CODE") or "").strip().split("-")[0]

    mailing_full = ", ".join(p for p in [
        f"{m_addr1} {m_addr2}".strip(),
        m_city,
        f"{m_state} {m_zip}".strip(),
    ] if p)

    is_absentee = (
        m_addr1 and site_addr
        and m_addr1.upper() != site_addr.upper()
    )

    # Property classification
    dor_code = (attrs.get("DOR_CODE_CUR") or "").strip()
    dor_desc = (attrs.get("DOR_DESC") or "").strip()
    condo_flag = (attrs.get("CONDO_FLAG") or "").strip()
    units = int(attrs.get("UNIT_COUNT") or 0)
    property_type = _classify_from_dor(dor_desc, condo_flag, units)

    return {
        "folio": folio,
        "property_address": site_addr,
        "city": site_city,
        "zip": site_zip,
        "owner_name": primary_owner,
        "owner_first": owner_first,
        "owner_last": owner_last,
        "owners": owners,
        "property_type": property_type,
        "dor_code": dor_code,
        "dor_description": dor_desc,
        "is_condo": condo_flag.upper() == "Y",
        "units": units,
        "bedrooms": int(attrs.get("BEDROOM_COUNT") or 0),
        "bathrooms": float(attrs.get("BATHROOM_COUNT") or 0),
        "half_bathrooms": int(attrs.get("HALF_BATHROOM_COUNT") or 0),
        "floors": int(attrs.get("FLOOR_COUNT") or 0),
        "buildings": int(attrs.get("BUILDING_COUNT") or 0),
        "year_built": int(attrs.get("YEAR_BUILT") or 0) or None,
        "lot_size_sqft": float(attrs.get("LOT_SIZE") or 0) or None,
        "heated_area_sqft": float(attrs.get("BUILDING_HEATED_AREA") or 0) or None,
        "land_value": float(attrs.get("LAND_VAL_CUR") or 0) or None,
        "building_value": float(attrs.get("BUILDING_VAL_CUR") or 0) or None,
        "total_value": float(attrs.get("TOTAL_VAL_CUR") or 0) or None,
        "mailing_address": mailing_full,
        "is_absentee_owner": is_absentee,
    }


def enrich_by_address(address: str, city: str = "") -> dict[str, Any] | None:
    """Look up a property by site address (slower than by folio).

    1. AddressSearchMap → find FOLIO matching the address.
    2. enrich_by_folio() → full enrichment.
    """
    if not address:
        return None

    addr_upper = address.upper().strip()
    pattern = re.compile(
        r"^(?P<num>\d{1,6})\s+"
        r"(?:(?P<pre>NE|NW|SE|SW|N|S|E|W)\s+)?"
        r"(?P<name>.+?)\s+"
        r"(?P<type>ST|AVE|AVENUE|RD|ROAD|BLVD|BOULEVARD|DR|DRIVE|CT|COURT|"
        r"PL|PLACE|LN|LANE|WAY|TER|TERRACE|HWY|HIGHWAY|CIR|CIRCLE|PKWY|PARKWAY)"
        r"\s*(?:(?P<suf>NE|NW|SE|SW|N|S|E|W))?\s*$",
        re.IGNORECASE,
    )
    m = pattern.match(addr_upper)
    if not m:
        log.debug("Could not parse address: %s", address)
        return None

    house_num = m.group("num")
    pre_dir = (m.group("pre") or "").upper()
    street_name = m.group("name").strip()
    street_name = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", street_name, flags=re.IGNORECASE)

    where_parts = [f"HSE_NUM={house_num}"]
    where_parts.append(f"ST_NAME LIKE '%{street_name.replace(chr(39), chr(39)*2)}%'")
    if pre_dir:
        where_parts.append(f"PRE_DIR='{pre_dir}'")

    feat = _query_first_feature(ADDRESS_QUERY_URL, " AND ".join(where_parts))
    if not feat and pre_dir:
        feat = _query_first_feature(
            ADDRESS_QUERY_URL,
            " AND ".join(p for p in where_parts if not p.startswith("PRE_DIR")),
        )
    if not feat:
        return None

    folio = (feat.get("FOLIO") or "").strip()
    if not folio:
        return None
    return enrich_by_folio(folio)


_ORG_PATTERN = re.compile(
    r"\b(LLC|INC|CORP|CORPORATION|TRUST|TRS|LTD|LP|LLP|HOLDINGS|GROUP|"
    r"ASSOC|ASSN|BANK|MORTGAGE|NA|NATIONAL|FEDERAL|FANNIE|FREDDIE|"
    r"DEVELOPMENT|INVESTMENTS|PROPERTIES|REAL ESTATE|CAPITAL|FINANCE|"
    r"FINANCIAL|FUND|EQUITY|REALTY)\b",
    re.IGNORECASE,
)


def _split_owner_name(full: str) -> tuple[str, str]:
    """Split Miami-Dade PA owner name into (first_name, last_name).

    The PA stores person names in NORMAL ORDER ('FIRST [MIDDLE] LAST').
    For organizations (LLC, INC, CORP, etc.), the whole name goes into
    last_name and first_name stays empty — these aren't real human names
    so splitting them would be wrong.

    Examples:
        'EDUARDO BAEZ'                  → ('EDUARDO', 'BAEZ')
        'MARIA C VILLEGAS'              → ('MARIA', 'C VILLEGAS')
        'ROY ANTHONY HERNANDEZ TRS'     → ('ROY', 'ANTHONY HERNANDEZ')  [TRS stripped]
        'EVERGLADES PAINTERS LLC'       → ('', 'EVERGLADES PAINTERS LLC')
        'US BANK NATIONAL ASSOCIATION'  → ('', 'US BANK NATIONAL ASSOCIATION')
    """
    if not full:
        return "", ""
    full = full.strip()

    # Detect organizations — don't split these into first/last.
    if _ORG_PATTERN.search(full):
        return "", full

    # Strip legal suffix from people names ('JOHN SMITH JR' → 'JOHN SMITH')
    upper = full.upper()
    for suffix in (" LE", " TR", " ETAL", " JR", " SR", " III", " II", " SR.", " JR."):
        if upper.endswith(suffix):
            full = full[: -len(suffix)].strip()
            upper = full.upper()

    parts = full.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""

    # Normal order: first word = first name, rest = last name (+ middle)
    return parts[0], " ".join(parts[1:])


def is_target_property_type(info: dict[str, Any], include: list[str], exclude: list[str]) -> bool:
    """Apply include/exclude rules from config.yaml.

    Now PRECISE thanks to DOR_CODE_CUR + CONDO_FLAG.
    """
    pt = info.get("property_type", "")
    if pt in exclude:
        return False
    return pt in include


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    test_folios = [
        "0141160040250",  # known good — Hernando Amil
    ]
    for folio in test_folios:
        print(f"\n=== Folio {folio} ===")
        info = enrich_by_folio(folio)
        if info:
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print("  (no data)")
