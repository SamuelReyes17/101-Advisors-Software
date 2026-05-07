"""
Probe specifically the Miami-Dade Property Appraiser endpoints.

The first probe found that gisweb.miamidade.gov has no PropertySearch service.
The Property Appraiser uses its own domain: apps.miamidadepa.gov.

This script tries multiple candidate URLs and reports which respond with
useful data. Run after probe_miami_dade.py to pin down the correct endpoint.

Usage:
    python3 -m scripts.probe_property_appraiser
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CAPTURES = Path(__file__).parent / "captures"
CAPTURES.mkdir(parents=True, exist_ok=True)

# A real Miami-Dade folio used as test (Bayfront Park area)
TEST_FOLIO = "0141160040250"


def try_url(url: str, label: str) -> bool:
    print(f"\n→ {label}")
    print(f"  {url}")
    try:
        import requests
    except ImportError:
        print("  requests not installed")
        return False

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36",
                "Accept": "application/json,text/html",
            },
            timeout=15,
        )
        print(f"  HTTP {r.status_code} · {len(r.text)} bytes · content-type: {r.headers.get('content-type', '?')}")
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

    capture_path = CAPTURES / f"pa_{label}.txt"
    capture_path.write_text(r.text[:5000], encoding="utf-8")
    print(f"  saved (first 5KB) to: {capture_path.name}")

    # Try parsing as JSON
    try:
        data = r.json()
        print(f"  JSON keys: {list(data.keys())[:10]}")
        # Look for typical ArcGIS-like fields
        if "features" in data:
            print(f"  features: {len(data['features'])}")
        if "error" in data:
            print(f"  ERROR field: {data['error']}")
        if "fields" in data:
            print(f"  service fields: {len(data['fields'])}")
        return r.status_code == 200 and "error" not in data
    except (ValueError, json.JSONDecodeError):
        print(f"  (not JSON) snippet: {r.text[:120]}")
        return r.status_code == 200


def main() -> int:
    print("=" * 70)
    print("Miami-Dade Property Appraiser endpoint discovery")
    print("=" * 70)

    candidates = [
        # gis.miamidadepa.gov possibilities
        ("gis_root_pa", "https://gis.miamidadepa.gov/arcgis/rest/services?f=json"),
        # gisws.miamidadepa.gov possibilities
        ("gisws_root", "https://gisws.miamidadepa.gov/arcgis/rest/services?f=json"),
        # The original wrong URL — for confirmation
        ("gisweb_root", "https://gisweb.miamidade.gov/arcgis/rest/services?f=json"),
        # apps.miamidadepa.gov SPA — its API likely lives here
        ("apps_propertysearch_html", "https://apps.miamidadepa.gov/propertysearch/"),
        ("apps_pa_root", "https://apps.miamidadepa.gov/"),
        # Property Appraiser opendata hub
        ("opendata_hub", "https://gis-mdc.opendata.arcgis.com/"),
        # Try common patterns at gis.miamidadepa.gov
        (
            "gis_pa_propertysearch_layer0",
            "https://gis.miamidadepa.gov/arcgis/rest/services/PropertySearch/MapServer/0?f=json",
        ),
        (
            "gis_pa_pa_layer0",
            "https://gis.miamidadepa.gov/arcgis/rest/services/PA/MapServer/0?f=json",
        ),
        # Try gisweb with different service names
        (
            "gisweb_md_pa_propertysearch",
            "https://gisweb.miamidade.gov/arcgis/rest/services/MD_PA_PropertySearch/MapServer?f=json",
        ),
        # The actual Property Search SPA's API (educated guess)
        (
            "apps_api_property",
            f"https://apps.miamidadepa.gov/propertysearch/api/property/{TEST_FOLIO}",
        ),
        (
            "apps_api_folio",
            f"https://apps.miamidadepa.gov/propertysearch/api/folio/{TEST_FOLIO}",
        ),
        (
            "apps_api_search",
            f"https://apps.miamidadepa.gov/propertysearch/api/search?folio={TEST_FOLIO}",
        ),
    ]

    successes = []
    for label, url in candidates:
        if try_url(url, label):
            successes.append((label, url))

    print()
    print("=" * 70)
    print(f"Successful endpoints: {len(successes)}/{len(candidates)}")
    for lbl, url in successes:
        print(f"  ✓ {lbl}: {url}")
    print("=" * 70)
    print()
    print("If gisweb_root or gis_root_pa returned 200 with JSON listing service")
    print("folders, mandame el output completo y ahi identifico el servicio correcto.")
    print("Si apps_propertysearch_html dio HTML, abrí ese archivo guardado y buscá")
    print("scripts que llamen a un /api/ — ese es nuestro endpoint real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
