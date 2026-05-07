"""
Miami-Dade Property Appraiser — enrichment via public ArcGIS REST services.

DISCOVERED ENDPOINTS (validated 2026-05):

    PRIMARY — owner + address + folio:
        https://gisweb.miamidade.gov/arcgis/rest/services/MD_NSPApp/MapServer/0/query
        Layer: PaGis
        Fields: FOLIO, TRUE_SITE_ADDR, TRUE_OWNER1, MAILING_BLOCK_LINE3, MAILING_BLOCK_LINE4

    SECONDARY — units count + premise type:
        https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer/9/query
        Layer: WASD CISCustomer
        Fields: FOLIO, ADDRESS, CITY, ZIPCODE, DUNIT (dwelling units), PREMTYPE (RES|COM)

    TODO — DOR Use Code (canonical property type):
        Probably in MD_LandInformation/MapServer/24 (Property @ PaGis).
        Run scripts/probe_landinfo_layer24.py to inspect.

USAGE:
    from pipeline.collectors.property_appraiser import enrich_by_folio

    info = enrich_by_folio("0141160040250")
    # {'folio': '0141160040250', 'property_address': '2735 SW 36 AVE',
    #  'city': 'MIAMI', 'zip': '33133', 'owner_name': 'HERNANDO AMIL LE',
    #  'units': 1, 'premise_type': 'RES', 'property_type': 'Single Family' }
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

PAGIS_QUERY_URL = (
    "https://gisweb.miamidade.gov/arcgis/rest/services/"
    "MD_NSPApp/MapServer/0/query"
)
WASD_QUERY_URL = (
    "https://gisweb.miamidade.gov/arcgis/rest/services/"
    "MD_LandInformation/MapServer/9/query"
)


def _http_get_json(url: str, params: dict, timeout: int = 15) -> dict[str, Any]:
    """Wrapper around requests for SSL robustness on macOS."""
    try:
        import requests
    except ImportError:
        # Fallback for sandboxes or minimal envs
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
    """Run an ArcGIS query and return the first feature's attributes (or None)."""
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


def _classify_property_type(units: int, premise: str) -> str:
    """Heuristic classification — refine when DOR Use Code is wired up.

    NOTE: this CANNOT distinguish single-family from condominium when units==1.
    Both show up as RES + 1 unit. Once we plug in DOR Use Code, this becomes precise.
    """
    if not premise:
        return ""
    if premise.upper() != "RES":
        return "Other"  # Commercial, vacant, etc.
    if units == 1:
        return "Single Family or Condo (verify DOR code)"
    if units == 2:
        return "Duplex"
    if units == 3:
        return "Triplex"
    if units == 4:
        return "Fourplex"
    if units >= 5:
        return "Multi Family"
    return ""


def enrich_by_folio(folio: str) -> dict[str, Any] | None:
    """Look up a property by its folio number across all available services.

    Returns a normalized dict, or None if the folio is unknown to MD-NSPApp.
    """
    folio = folio.replace("-", "").strip()
    where = f"FOLIO='{folio}'"

    # Primary: PaGis layer for owner + address.
    pagis = _query_first_feature(PAGIS_QUERY_URL, where)
    if not pagis:
        return None

    site_addr = (pagis.get("TRUE_SITE_ADDR") or "").strip()
    owner_full = (pagis.get("TRUE_OWNER1") or "").strip()

    # MAILING_BLOCK_LINE4 typically holds "MIAMI, FL 33133" — extract city + zip.
    mailing_line4 = (pagis.get("MAILING_BLOCK_LINE4") or "").strip()
    city, zip_code = _split_city_zip(mailing_line4)

    # Secondary: WASD CISCustomer for unit count + premise type.
    wasd = _query_first_feature(WASD_QUERY_URL, where)
    units = 0
    premise_type = ""
    if wasd:
        try:
            units = int((wasd.get("DUNIT") or "0").strip())
        except (ValueError, AttributeError):
            units = 0
        premise_type = (wasd.get("PREMTYPE") or "").strip()
        # Use WASD address if PaGis didn't have one
        if not site_addr:
            site_addr = (wasd.get("ADDRESS") or "").strip()
        if not city:
            city = (wasd.get("CITY") or "").strip()
        if not zip_code:
            zip_code = str(wasd.get("ZIPCODE") or "")

    # Owner name parsing — TRUE_OWNER1 is usually "LASTNAME FIRSTNAME [LE/TR/etc]".
    # Real estate docs use suffixes like "LE" (life estate), "TR" (trust), etc.
    owner_first, owner_last = _split_owner_name(owner_full)

    return {
        "folio": folio,
        "property_address": site_addr,
        "city": city,
        "zip": zip_code,
        "owner_name": owner_full,
        "owner_first": owner_first,
        "owner_last": owner_last,
        "units": units,
        "premise_type": premise_type,
        "property_type": _classify_property_type(units, premise_type),
    }


def _split_city_zip(line: str) -> tuple[str, str]:
    """Parse 'MIAMI, FL 33133' → ('MIAMI', '33133')."""
    if not line:
        return "", ""
    if "," in line:
        city, rest = line.split(",", 1)
        # rest is typically " FL 33133" or " FL 33133-1234"
        parts = rest.strip().split()
        zip_code = ""
        for p in parts:
            if p[:5].isdigit():
                zip_code = p[:5]
                break
        return city.strip(), zip_code
    return line.strip(), ""


def _split_owner_name(full: str) -> tuple[str, str]:
    """Best-effort split. PA records often use 'LASTNAME FIRSTNAME [SUFFIX]'."""
    if not full:
        return "", ""
    # Strip trailing legal suffixes
    for suffix in [" LE", " TR", " ETAL", " JR", " SR", " III", " II"]:
        if full.upper().endswith(suffix):
            full = full[: -len(suffix)].strip()
    parts = full.split()
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    # Heuristic: first word = last name (PA convention)
    return parts[1] if len(parts) > 1 else "", parts[0]


def is_target_property_type(info: dict[str, Any], include: list[str], exclude: list[str]) -> bool:
    """Apply include/exclude property type rules from config.yaml.

    Until DOR code is wired, when units==1 we can't tell SFR from condo, so we
    LEAVE IT IN (the human review on the dashboard catches false positives).
    """
    pt = info.get("property_type", "")
    if pt in exclude:
        return False
    if any(pt.startswith(t) for t in include):
        return True
    if "Single Family or Condo" in pt:
        return True  # err on the side of including; flag for human review
    return False


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    test_folios = [
        "0141160040250",  # known good — Hernando Amil residence
    ]
    for folio in test_folios:
        print(f"\n=== Folio {folio} ===")
        info = enrich_by_folio(folio)
        if info:
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print("  (no data returned)")
