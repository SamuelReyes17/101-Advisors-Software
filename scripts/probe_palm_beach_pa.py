"""
Discovery probe for the Palm Beach County Property Appraiser (PBCPAO).

Goal: find the canonical REST endpoint that returns property records with
owner, ZIP, city, property type, etc. — analogous to MD_LandInformation/24
in Miami-Dade.

Known facts about Palm Beach:
  - Public site: https://www.pbcpao.gov/
  - They use a "PCN" (Parcel Control Number, 17 chars) NOT a folio.
    Format: 50-43-46-04-08-001-0010
  - They also run on ArcGIS, hosted on maps.co.palm-beach.fl.us.
  - "PAPA" is the brand name of their public app.

This script tries known PBCPAO and Palm Beach County endpoints.

Usage:
    python3 -m scripts.probe_palm_beach_pa
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

# Sample PBCPAO PCN for testing (West Palm Beach property)
TEST_PCN = "74434312060010350"
TEST_ADDRESS = "316 S Olive Ave, West Palm Beach"

ENDPOINTS = [
    # ArcGIS roots
    ("pbc_maps_root", "https://maps.co.palm-beach.fl.us/arcgis/rest/services?f=json"),
    ("pbcgov_gis_root", "https://gis.pbcgov.com/arcgis/rest/services?f=json"),
    ("pbcgov_services_root", "https://services.pbcgov.com/arcgis/rest/services?f=json"),

    # Possible PBCPAO services
    ("pbcpao_parcels", "https://maps.co.palm-beach.fl.us/arcgis/rest/services/PBCPAO/MapServer?f=json"),
    ("pbcpao_papa", "https://maps.co.palm-beach.fl.us/arcgis/rest/services/PAPA/MapServer?f=json"),
    ("pbcpao_propinfo", "https://maps.co.palm-beach.fl.us/arcgis/rest/services/PropertyInformation/MapServer?f=json"),
    ("pbcpao_publicportal", "https://maps.co.palm-beach.fl.us/arcgis/rest/services/PublicPortal/MapServer?f=json"),

    # Direct PBCPAO website API guesses
    ("pbcpao_api_pcn", f"https://www.pbcpao.gov/api/Property/GetByPcn?pcn={TEST_PCN}"),
    ("pbcpao_api_address", f"https://www.pbcpao.gov/api/Property/SearchByAddress?address={TEST_ADDRESS.replace(' ', '%20')}"),
    ("pbcpao_papa_api", f"https://papa.pbcgov.org/api/property/{TEST_PCN}"),

    # SPA — to inspect for real XHR URLs
    ("pbcpao_spa", "https://www.pbcpao.gov/"),
    ("papa_spa", "https://papa.pbcgov.org/"),
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
        save_path = CAPTURE_DIR / f"palmbeach_{name}.txt"
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
    print("Palm Beach County Property Appraiser endpoint discovery")
    print("=" * 70)
    print(f"Test PCN:     {TEST_PCN}")
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
    print("Mandame el output completo y elegimos el endpoint productivo.")
    print()
    print("Plan B: si todos fallan, abrimos papa.pbcgov.org en Chrome,")
    print("buscamos una propiedad, e inspeccionamos los XHR para encontrar")
    print("el endpoint real del API que usa el sitio.")
    return 0


if __name__ == "__main__":
    main()
