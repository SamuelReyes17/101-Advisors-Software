"""
Miami-Dade Property Appraiser — enrichment collector.

This is NOT a discovery collector — it doesn't find new leads on its own.
It takes addresses or folios from OTHER collectors and enriches them with:
- DOR Use Code (property type)
- # of units, bedrooms
- Owner of record (name as registered)
- Market value, assessed value

Endpoint:
    https://gisweb.miamidade.gov/arcgis/rest/services/MD_PropertyAppraiser/PropertySearch/FeatureServer/0/query

This is a public ArcGIS REST endpoint, no authentication required.
Rate limit is generous (~ 1000 req/min).

Reference:
    https://www.miamidade.gov/Apps/PA/PAOnlineTools

USAGE:
    from pipeline.collectors.property_appraiser import enrich_by_folio

    info = enrich_by_folio("0141160040250")
    # {'folio': '...', 'dor_code': '0001', 'property_type': 'Single Family', ...}
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

ENDPOINT = (
    "https://gisweb.miamidade.gov/arcgis/rest/services/"
    "MD_PropertyAppraiser/PropertySearch/FeatureServer/0/query"
)

# Mapping from DOR Use Code → human-readable property type.
# Source: Florida Department of Revenue Use Code list.
DOR_CODE_TO_TYPE = {
    "0001": "Single Family",
    "0002": "Mobile Home",
    "0003": "Multi Family",
    "0004": "Condominium",
    "0005": "Cooperative",
    "0006": "Retirement Home",
    "0007": "Boarding House",
    "0008": "Multi Family",
    "0009": "Townhouse",
}


def _http_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    """Wrapper around urllib for testability."""
    req = urllib.request.Request(url, headers={"User-Agent": "101AdvisorsBot/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def enrich_by_folio(folio: str) -> dict[str, Any] | None:
    """Look up a property by its folio number.

    Returns a dict with normalized fields, or None if not found.
    """
    folio = folio.replace("-", "").strip()
    where = f"FOLIO='{folio}'"
    params = {
        "where": where,
        "outFields": "*",
        "f": "json",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    try:
        data = _http_get_json(url)
    except Exception as e:
        log.warning("Property Appraiser query failed for folio=%s: %s", folio, e)
        return None

    features = data.get("features", [])
    if not features:
        return None

    attrs = features[0].get("attributes", {})
    return _normalize(attrs)


def enrich_by_address(address: str, city: str = "") -> dict[str, Any] | None:
    """Look up by site address (less reliable than folio — addresses vary)."""
    # Property Appraiser stores addresses in TRUE_SITE_ADDR_LINE1 etc.
    # Use ILIKE-style matching with %.
    addr_clean = address.upper().strip().replace("'", "''")
    where = f"TRUE_SITE_ADDR_LINE1 LIKE '%{addr_clean}%'"
    params = {
        "where": where,
        "outFields": "*",
        "f": "json",
        "resultRecordCount": "5",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    try:
        data = _http_get_json(url)
    except Exception as e:
        log.warning("Property Appraiser address query failed for %s: %s", address, e)
        return None

    features = data.get("features", [])
    if not features:
        return None

    # If multiple matches, prefer one whose city matches.
    if city and len(features) > 1:
        for f in features:
            if f.get("attributes", {}).get("TRUE_SITE_CITY", "").upper() == city.upper():
                return _normalize(f["attributes"])

    return _normalize(features[0]["attributes"])


def _normalize(attrs: dict[str, Any]) -> dict[str, Any]:
    """Map raw ArcGIS attribute names to our canonical schema."""
    dor_code = str(attrs.get("DOR_CODE", "")).zfill(4)

    return {
        "folio": str(attrs.get("FOLIO", "")),
        "dor_code": dor_code,
        "property_type": DOR_CODE_TO_TYPE.get(dor_code, "Other"),
        "property_address": attrs.get("TRUE_SITE_ADDR_LINE1", "").strip(),
        "city": attrs.get("TRUE_SITE_CITY", "").strip(),
        "zip": str(attrs.get("TRUE_SITE_ZIP_CODE", "")).strip(),
        "units": int(attrs.get("BUILDING_ACTUAL_UNIT_COUNT") or 0),
        "bedrooms": int(attrs.get("BEDROOM_COUNT") or 0),
        "owner_name": attrs.get("OWNER1", "").strip(),
        "market_value": float(attrs.get("ASSESSED_VAL_CURRENT") or 0),
    }


def is_target_property_type(info: dict[str, Any], include: list[str], exclude: list[str]) -> bool:
    """Apply the include/exclude property type rules from config.yaml."""
    pt = info.get("property_type", "")
    if pt in exclude:
        return False
    if pt in include:
        return True
    # Edge cases by units count:
    units = info.get("units", 0)
    if pt == "Multi Family" and 2 <= units <= 4:
        return True
    return False


# =========================================================================
# Smoke test — run directly to validate endpoint
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sample_folio = "0141160040250"  # known good Miami folio for testing
    print(f"Testing folio {sample_folio}...")
    info = enrich_by_folio(sample_folio)
    if info:
        print("OK — got property data:")
        for k, v in info.items():
            print(f"  {k}: {v}")
    else:
        print("FAILED — no data returned. Check the endpoint URL or network.")
