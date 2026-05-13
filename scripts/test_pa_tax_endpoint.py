"""
Test the PA's PaServicesProxy.ashx endpoint directly with requests.

Discovered in probe_spa_xhr — this is the canonical endpoint the PA SPA
uses to load property + tax + sales data. If it works with requests
(no browser), we have a clean automation path for tax delinquency.

Usage:
    python3 -m scripts.test_pa_tax_endpoint
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

CAPTURE = Path(__file__).resolve().parent / "captures"

TEST_FOLIO = "0141160040250"

# Try various Operation names — the SPA uses these internally
OPERATIONS = [
    "GetPropertySearchByFolio",
    "GetPropertyInformation",
    "GetTaxBill",
    "GetTaxes",
    "GetPropertyTaxes",
    "GetPropertyDetails",
    "GetSalesByFolio",
    "GetAssessmentByFolio",
]

BASE = "https://apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://apps.miamidadepa.gov/propertysearch/",
    "Origin": "https://apps.miamidadepa.gov",
}


def call(op: str, folio: str = TEST_FOLIO) -> dict | None:
    params = {
        "Operation": op,
        "clientAppName": "PropertySearch",
        "folioNumber": folio,
    }
    print(f"\n→ Operation={op}")
    try:
        r = requests.get(BASE, params=params, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  ❌ {e}")
        return None

    print(f"  HTTP {r.status_code} · {len(r.content)} bytes")
    if r.status_code != 200:
        return None

    try:
        data = r.json()
    except Exception:
        print(f"  (not JSON) snippet: {r.text[:200]}")
        return None

    # Save full response
    save = CAPTURE / f"pa_op_{op}.json"
    save.write_text(json.dumps(data, indent=2)[:50000])
    print(f"  ✅ JSON saved to {save.name}")

    # Inspect top-level keys
    if isinstance(data, dict):
        print(f"  Top-level keys: {list(data.keys())[:10]}")
        # Try to find tax-related fields
        flat = json.dumps(data).lower()
        for marker in ("tax", "delinquent", "owing", "due", "unpaid", "sale", "owner", "address"):
            if marker in flat:
                print(f"  ✓ Contains '{marker}'")

        # Print first level of nested structure
        def explore(obj, indent="    "):
            if isinstance(obj, dict):
                for k, v in list(obj.items())[:15]:
                    if isinstance(v, (dict, list)):
                        size = len(v) if isinstance(v, list) else len(v.keys())
                        print(f"{indent}{k}: ({type(v).__name__}, {size} items)")
                    else:
                        val = str(v)[:60]
                        print(f"{indent}{k}: {val}")
            elif isinstance(obj, list) and obj:
                print(f"{indent}(list of {len(obj)} items, first:)")
                explore(obj[0], indent + "  ")

        explore(data)
    return data


def main() -> int:
    print("=" * 70)
    print(f"Test PA endpoints directly · folio={TEST_FOLIO}")
    print("=" * 70)

    for op in OPERATIONS:
        call(op)

    print()
    print("=" * 70)
    print("Listo. Buscá las que devolvieron HTTP 200 + JSON con campos de tax")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
