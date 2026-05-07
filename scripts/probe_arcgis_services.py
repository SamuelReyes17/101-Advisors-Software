"""
Targeted probe of the ArcGIS services that look like Property Appraiser data.

Three candidates from the directory listing:
    1. MD_ComparableSales        — likely has property + owner data
    2. AddressSearchMap_PropertiesWithZip — address search
    3. MD_NSPApp                 — neighborhood stabilization (probably less useful)

For each, we:
    - Fetch the service metadata (?f=json)
    - List its layers
    - For each layer, list the fields (so we can see if it has folio, owner, units, beds)
    - Run a sample query for one folio to see what data comes back

Usage:
    python3 -m scripts.probe_arcgis_services
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CAPTURES = Path(__file__).parent / "captures"
TEST_FOLIO = "0141160040250"

CANDIDATES = [
    "MD_ComparableSales",
    "AddressSearchMap_PropertiesWithZip",
    "MD_NSPApp",
    "MD_LandInformation",  # also worth probing
]


def probe_service(service_name: str) -> None:
    print("\n" + "=" * 70)
    print(f"SERVICE: {service_name}")
    print("=" * 70)

    try:
        import requests
    except ImportError:
        print("requests not installed.")
        return

    base = f"https://gisweb.miamidade.gov/arcgis/rest/services/{service_name}/MapServer"

    # 1) Fetch service metadata
    try:
        r = requests.get(f"{base}?f=json", timeout=15)
        meta = r.json()
    except Exception as e:
        print(f"FAILED to fetch service: {e}")
        return

    if "error" in meta:
        print(f"ERROR: {meta['error']}")
        # Try as FeatureServer instead
        base = f"https://gisweb.miamidade.gov/arcgis/rest/services/{service_name}/FeatureServer"
        try:
            r = requests.get(f"{base}?f=json", timeout=15)
            meta = r.json()
            if "error" in meta:
                print(f"FeatureServer also failed: {meta['error']}")
                return
            print(f"  (using FeatureServer instead)")
        except Exception as e:
            print(f"FeatureServer failed: {e}")
            return

    layers = meta.get("layers", [])
    print(f"  Description: {meta.get('description', '?')[:200]}")
    print(f"  Layers: {len(layers)}")
    for layer in layers:
        print(f"    [{layer['id']}] {layer['name']} ({layer.get('type', '?')})")

    # 2) For each layer, fetch its fields
    for layer in layers:
        lid = layer["id"]
        try:
            lr = requests.get(f"{base}/{lid}?f=json", timeout=15)
            ldata = lr.json()
        except Exception as e:
            print(f"  Layer {lid}: FAILED to fetch ({e})")
            continue

        fields = ldata.get("fields", [])
        if not fields:
            continue

        # Print fields that look interesting
        interesting = []
        for f in fields:
            name = f.get("name", "")
            alias = f.get("alias", "")
            ftype = f.get("type", "")
            keywords = ["folio", "owner", "address", "site", "parcel", "unit",
                       "bed", "bath", "year", "value", "land", "use", "type",
                       "city", "zip", "name"]
            if any(k in name.lower() or k in alias.lower() for k in keywords):
                interesting.append(f"{name} ({alias}) [{ftype}]")

        if interesting:
            print(f"\n  Layer {lid} '{layer['name']}' has interesting fields:")
            for f in interesting[:25]:
                print(f"    • {f}")

        # 3) Try a sample query — search for our test folio
        try:
            # Try common field name variants for folio
            for field_name in ["FOLIO", "Folio", "folio", "PARCEL_ID", "PARCELID"]:
                qr = requests.get(
                    f"{base}/{lid}/query",
                    params={
                        "where": f"{field_name}='{TEST_FOLIO}'",
                        "outFields": "*",
                        "f": "json",
                        "resultRecordCount": "1",
                    },
                    timeout=15,
                )
                qdata = qr.json()
                if "error" not in qdata:
                    feats = qdata.get("features", [])
                    if feats:
                        print(f"\n  ✓ Layer {lid} query succeeded with {field_name}={TEST_FOLIO}:")
                        attrs = feats[0].get("attributes", {})
                        for k, v in list(attrs.items())[:20]:
                            print(f"    {k}: {v}")
                        # Save full response
                        (CAPTURES / f"sample_query_{service_name}_layer{lid}.json").write_text(
                            json.dumps(qdata, indent=2), encoding="utf-8"
                        )
                        return  # found it, stop here for this service
                    break  # field exists but folio not found → wrong folio or field
        except Exception as e:
            pass


def main() -> int:
    print("=" * 70)
    print("Targeted ArcGIS Property-Data Service Discovery")
    print("=" * 70)
    print(f"Test folio: {TEST_FOLIO}")

    for svc in CANDIDATES:
        probe_service(svc)

    print("\n" + "=" * 70)
    print("Done. Check above for ✓ marks indicating successful queries.")
    print("If any service returned data with folio/owner/units fields, ese es nuestro endpoint.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
