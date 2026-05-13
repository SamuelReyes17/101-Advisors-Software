"""
Miami-Dade Property Appraiser — full property + tax record via the
PaServicesProxy.ashx endpoint discovered via Playwright XHR capture.

The endpoint returns a comprehensive JSON with:
    - Assessment values (LandValue, BuildingValue, TotalValue, AssessedValue) per year
    - Taxable values (CountyTaxableValue, etc.) per year
    - Exemptions (Homestead, Save Our Homes)
    - Building details (year built, sqft, bedrooms, bathrooms)
    - Owner info, mailing address, sale history

This complements pipeline/collectors/property_appraiser.py (which only used
the ArcGIS REST). This new endpoint is RICHER — gives us tax-related fields.

Note: actual TAX DELINQUENCY (paid vs unpaid) is on a separate Tax Collector
system. The 'estimated tax bill' computed here is Taxable × millage_rate.

Endpoint:
    https://apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx
    ?Operation=GetPropertySearchByFolio
    &clientAppName=PropertySearch
    &folioNumber=<FOLIO>
"""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

ENDPOINT = "https://apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx"

# Miami-Dade average millage rate (county + school + city + regional).
# Real rates vary by location: 18-23 mills. Using 22 as a conservative estimate.
# 22 mills = 0.022 = $22 per $1,000 of taxable value.
DEFAULT_MILLAGE = 0.022

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://apps.miamidadepa.gov/propertysearch/",
}


def fetch_property_by_folio(folio: str, timeout: int = 15) -> dict[str, Any] | None:
    """Fetch the full PA record for a given folio.

    Returns the raw JSON dict or None on failure.
    """
    if not folio:
        return None
    folio = folio.replace("-", "").strip()

    params = {
        "Operation": "GetPropertySearchByFolio",
        "clientAppName": "PropertySearch",
        "folioNumber": folio,
    }
    try:
        r = requests.get(ENDPOINT, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.debug("PA fetch failed for folio %s: %s", folio, e)
        return None

    if not data.get("Completed"):
        log.debug("PA returned non-completed response for folio %s", folio)
        return None
    return data


def extract_tax_info(pa_json: dict) -> dict[str, Any]:
    """Pull the tax-related fields from the PaServicesProxy response.

    Returns a flat dict with:
        assessed_value_2025, assessed_value_2024, assessed_value_2023
        total_value_2025, total_value_2024
        land_value_2025
        taxable_value_2025, taxable_value_2024
        est_tax_2025, est_tax_2024 (Taxable × millage)
        homestead_exemption (boolean)
        has_save_our_homes_cap (boolean)
    """
    out: dict[str, Any] = {}

    # Assessment values per year
    for assess in (pa_json.get("Assessment") or {}).get("AssessmentInfos", []):
        yr = assess.get("Year")
        if yr in (2023, 2024, 2025):
            out[f"assessed_value_{yr}"] = assess.get("AssessedValue") or 0
            out[f"total_value_{yr}"] = assess.get("TotalValue") or 0
            out[f"land_value_{yr}"] = assess.get("LandValue") or 0

    # Taxable values per year + estimated tax bill
    for tax in (pa_json.get("Taxable") or {}).get("TaxableInfos", []):
        yr = tax.get("Year")
        if yr in (2023, 2024, 2025):
            taxable = tax.get("CountyTaxableValue") or 0
            out[f"taxable_value_{yr}"] = taxable
            out[f"est_tax_{yr}"] = round(taxable * DEFAULT_MILLAGE)

    # Exemptions
    homestead = False
    saveourhomes = False
    for b in (pa_json.get("Benefit") or {}).get("BenefitInfos", []):
        desc = (b.get("Description") or "").lower()
        if "homestead" in desc and b.get("TaxYear") == 2025:
            homestead = True
        if "save our homes" in desc and b.get("TaxYear") == 2025:
            saveourhomes = True
    out["has_homestead"] = "yes" if homestead else "no"
    out["has_save_our_homes_cap"] = "yes" if saveourhomes else "no"

    # Year built (most recent from buildings)
    buildings = (pa_json.get("Building") or {}).get("BuildingInfos") or []
    if buildings:
        years_built = [b.get("Actual") for b in buildings if b.get("Actual")]
        if years_built:
            out["year_built"] = min(years_built)  # oldest = original

    # Property info — additional details
    prop = pa_json.get("PropertyInfo") or {}
    if prop.get("BedroomCount"):
        out["bedrooms"] = prop["BedroomCount"]
    if prop.get("BathroomCount"):
        out["bathrooms"] = prop["BathroomCount"]
    if prop.get("UnitCount"):
        out["units"] = prop["UnitCount"]
    if prop.get("DORCodeAndDescription"):
        out["dor_description"] = prop["DORCodeAndDescription"]
    if prop.get("HxLotSize"):
        out["lot_size_sqft"] = prop["HxLotSize"]
    if prop.get("HxStdBuildingArea") or prop.get("HxHeatedArea"):
        out["heated_area_sqft"] = prop.get("HxHeatedArea") or prop.get("HxStdBuildingArea")

    return out


# Smoke test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    TEST_FOLIO = "0141160040250"
    print(f"Testing folio: {TEST_FOLIO}")
    data = fetch_property_by_folio(TEST_FOLIO)
    if not data:
        print("❌ No data returned")
        raise SystemExit(1)
    info = extract_tax_info(data)
    print(f"\n✅ Tax info extracted ({len(info)} fields):")
    for k, v in info.items():
        print(f"   {k}: {v}")
