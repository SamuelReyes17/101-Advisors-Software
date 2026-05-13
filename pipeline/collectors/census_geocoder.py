"""
US Census Bureau Geocoder — free, public, no-auth address normalizer.

Used as a fallback when the county Property Appraiser doesn't have the lead
(i.e., Broward and Palm Beach, where the PA's public ArcGIS only exposes
parcel geometry, not the owner/address/ZIP attribute tables).

API docs:
    https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html

Endpoint we use ("geographies/onelineaddress"):
    Returns matchedAddress + addressComponents (zip, city, state) +
    geographies (county BASENAME, FIPS, etc.).

Rate limits:
    Officially: 10,000 records/day per IP (batch endpoint).
    Single-address endpoint: untracked but be polite — add a small delay.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


def geocode_address(address: str, state: str = "FL", timeout: int = 10) -> dict[str, Any] | None:
    """Normalize an address via Census Geocoder. Returns:

        {
            "matched_address": "100 N BIRCH RD, FORT LAUDERDALE, FL, 33304",
            "zip": "33304",
            "city": "FORT LAUDERDALE",
            "state": "FL",
            "county": "Broward",     # canonical, NO "County" suffix
            "lat": 26.131,
            "lon": -80.105,
        }

    Returns None if no match (which happens for non-existent or very-old
    addresses, and for property addresses without a real street number).
    """
    if not address:
        return None

    # Census likes "address, city, state" form. We don't always have city,
    # but at minimum we should send the state to constrain the search.
    one_line = address.strip()
    if state and state.upper() not in one_line.upper():
        one_line = f"{one_line}, {state}"

    params = {
        "address": one_line,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }

    try:
        resp = requests.get(GEOCODE_URL, params=params, timeout=timeout,
                            headers={"User-Agent": "101AdvisorsBot/0.2"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.debug("Census geocode failed for %s: %s", address[:40], e)
        return None

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return None

    m = matches[0]
    comp = m.get("addressComponents", {})
    coords = m.get("coordinates", {})
    geog = m.get("geographies", {})

    county_raw = ""
    for c in geog.get("Counties", []):
        county_raw = c.get("BASENAME") or c.get("NAME", "")
        if county_raw:
            break

    return {
        "matched_address": m.get("matchedAddress", "").strip(),
        "zip": (comp.get("zip") or "").strip(),
        "city": (comp.get("city") or "").strip().title(),
        "state": (comp.get("state") or "").strip(),
        "county": county_raw.strip(),  # e.g. "Broward", "Miami-Dade", "Palm Beach"
        "lat": coords.get("y"),
        "lon": coords.get("x"),
    }


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tests = [
        "100 N Birch Rd, Fort Lauderdale, FL",   # Broward
        "316 S Olive Ave, West Palm Beach",      # Palm Beach
        "125 SW 29th Rd, Miami",                 # Miami-Dade
        "2735 SW 36 AVE",                        # Miami-Dade no city
    ]
    for addr in tests:
        print(f"\n=== {addr} ===")
        result = geocode_address(addr)
        if result:
            for k, v in result.items():
                print(f"  {k}: {v}")
        else:
            print("  (no match)")
