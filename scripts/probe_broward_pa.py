"""
Discovery probe for the Broward County Property Appraiser (BCPA).

Goal: find the canonical REST endpoint that returns property records with
owner name, ZIP, city, property type, etc. — analogous to what we have
for Miami-Dade at MD_LandInformation/MapServer/24.

Known facts about BCPA:
  - Public site: https://web.bcpa.net/bcpaclient/#/Record-Search
  - They run ArcGIS on gis.bcpa.net
  - They use a "Folio" (e.g., 504216050010) which is the BCPA equivalent
    of Miami-Dade's folio.

This script tries 4 categories of endpoints and reports which respond
with usable JSON.

Usage:
    python3 -m scripts.probe_broward_pa

After running, share the output and we'll lock in the right endpoint.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

# Sample BCPA folio for testing (Fort Lauderdale beachfront condo, public record)
TEST_FOLIO = "504216050010"
TEST_ADDRESS = "100 N Birch Rd, Fort Lauderdale"

ENDPOINTS = [
    # ArcGIS service catalog roots
    ("gis_bcpa_root", "https://gis.bcpa.net/arcgis/rest/services?f=json"),
    ("services_bcpa_root", "https://services.bcpa.net/arcgis/rest/services?f=json"),
    ("maps_bcpa_root", "https://maps.bcpa.net/arcgis/rest/services?f=json"),

    # Specific service guesses (BCPA naming conventions)
    ("bcpa_parcels", "https://gis.bcpa.net/arcgis/rest/services/BCPA_Parcels/MapServer?f=json"),
    ("bcpa_propsearch", "https://gis.bcpa.net/arcgis/rest/services/PropertySearch/MapServer?f=json"),
    ("bcpa_publicportal", "https://gis.bcpa.net/arcgis/rest/services/PublicPortal/MapServer?f=json"),

    # Broward County (non-BCPA) ArcGIS
    ("broward_county_gis", "https://gis.broward.org/arcgis/rest/services?f=json"),

    # Direct BCPA web API
    ("bcpa_webapi_search", f"https://web.bcpa.net/BcpaServices/SearchService.asmx/SearchAddress?address={TEST_ADDRESS.replace(' ', '%20')}"),
    ("bcpa_webapi_folio", f"https://web.bcpa.net/BcpaServices/SearchService.asmx/SearchByFolio?folio={TEST_FOLIO}"),

    # JSON variants
    ("bcpa_propinfo_json", f"https://web.bcpa.net/BcpaServices/Property.asmx/GetPropertyByFolio?folio={TEST_FOLIO}"),

    # SPA endpoint (might reveal real API on inspection)
    ("bcpa_spa", "https://web.bcpa.net/bcpaclient/index.html"),
]


def probe(name: str, url: str) -> dict:
    print(f"\n→ {name}")
    print(f"  {url[:100]}")
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
                "Accept": "application/json, text/html",
            },
            timeout=15,
        )
        ct = resp.headers.get("content-type", "?")
        print(f"  HTTP {resp.status_code} · {len(resp.content)} bytes · {ct}")
        save_path = CAPTURE_DIR / f"broward_{name}.txt"
        save_path.write_bytes(resp.content[:8192])
        is_json = "json" in ct.lower()
        body = resp.text
        if is_json:
            try:
                data = json.loads(body)
                keys = list(data.keys())[:8] if isinstance(data, dict) else "(list)"
                print(f"  JSON keys: {keys}")
                if isinstance(data, dict):
                    if "services" in data:
                        names = [s.get("name") for s in data["services"][:10]]
                        print(f"  Services: {names}")
                    if "folders" in data:
                        print(f"  Folders: {data['folders'][:10]}")
                    if "error" in data:
                        print(f"  ERROR field: {data['error']}")
                return {"name": name, "status": resp.status_code, "ok": True, "json": True}
            except Exception as e:
                print(f"  JSON parse failed: {e}")
        else:
            preview = body[:200].replace("\n", " ")
            print(f"  (not JSON) preview: {preview}")
        return {"name": name, "status": resp.status_code, "ok": True, "json": False}
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return {"name": name, "status": None, "ok": False, "error": str(e)}


def main() -> int:
    print("=" * 70)
    print("Broward County Property Appraiser endpoint discovery")
    print("=" * 70)
    print(f"Test folio:   {TEST_FOLIO}")
    print(f"Test address: {TEST_ADDRESS}")

    results = []
    for name, url in ENDPOINTS:
        results.append(probe(name, url))

    ok = [r for r in results if r["ok"]]
    print()
    print("=" * 70)
    print(f"Reachable endpoints: {len(ok)}/{len(results)}")
    for r in ok:
        marker = "🟢 JSON" if r.get("json") else "⚪ HTML/text"
        print(f"  {marker}  {r['name']}")
    print("=" * 70)
    print()
    print("Mandame este output. Vamos a apuntar al endpoint que:")
    print("  1. Devuelve JSON con folders/services O")
    print("  2. Devuelve datos de la propiedad directamente con TEST_FOLIO")
    print()
    print("Si todos los ArcGIS dieron 404, vamos a la opción B:")
    print("  abrir https://web.bcpa.net/bcpaclient/#/Record-Search en Chrome,")
    print("  inspeccionar las llamadas XHR cuando buscás una propiedad,")
    print("  y copiar la URL real del JSON que vuelve.")
    return 0


if __name__ == "__main__":
    main()
