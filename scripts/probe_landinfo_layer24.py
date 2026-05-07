"""
Quick probe of MD_LandInformation Layer 24 (Property @ PaGis).
This layer was skipped by the previous probe — but it's likely where DOR Use Code lives.

Usage:
    python3 -m scripts.probe_landinfo_layer24
"""
import sys

TEST_FOLIO = "0141160040250"
URL = "https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer/24"


def main() -> int:
    try:
        import requests
    except ImportError:
        print("pip3 install requests")
        return 1

    print(f"Probing layer metadata: {URL}")
    r = requests.get(URL, params={"f": "json"}, timeout=15)
    data = r.json()
    if "error" in data:
        print(f"ERROR fetching layer: {data['error']}")
        return 1

    fields = data.get("fields", [])
    print(f"\nLayer name: {data.get('name', '?')}")
    print(f"Total fields: {len(fields)}")
    print("\nALL fields:")
    for f in fields:
        print(f"  {f.get('name'):30s} | {f.get('alias', ''):30s} | {f.get('type', ''):25s}")

    # Now query with our test folio
    print(f"\nQuerying for folio {TEST_FOLIO}...")
    qr = requests.get(
        f"{URL}/query",
        params={"where": f"FOLIO='{TEST_FOLIO}'", "outFields": "*", "f": "json"},
        timeout=15,
    )
    qdata = qr.json()
    if "error" in qdata:
        print(f"ERROR: {qdata['error']}")
        return 1

    feats = qdata.get("features", [])
    if not feats:
        print("No features returned for that folio.")
        return 0

    print(f"\nFEATURE 0 attributes ({len(feats[0]['attributes'])} fields):")
    for k, v in feats[0]["attributes"].items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
