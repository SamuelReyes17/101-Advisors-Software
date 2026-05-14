"""
Final endpoint discovery — dump ALL fields and find the right service.

Phase A — Palm Beach:
    Dump all fields of Parcels/Parcels/MapServer/0 (no keyword filtering).
    Try a query that returns ANY feature so we can see real attribute values.

Phase B — Broward:
    Enumerate every service at gisweb-adapters.bcpa.net/arcgis/rest/services.
    For each MapServer, list its layers. For the most-recent BCPA_EXTERNAL_*
    service, drill into layer 0 fields and try a sample query.

Usage:
    python3 -m scripts.probe_final
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
    "Accept": "application/json",
}


def http_get(url: str, params: dict | None = None, timeout: int = 20):
    try:
        return requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return None


# =============================================================================
# Phase A — Palm Beach: dump all fields, run a query
# =============================================================================

def phase_a() -> None:
    print("=" * 70)
    print("PHASE A — Palm Beach: dump ALL fields of Parcels layer 0")
    print("=" * 70)

    base = "https://maps.co.palm-beach.fl.us/arcgis/rest/services/Parcels/Parcels/MapServer/0"
    r = http_get(base, {"f": "json"})
    if not r or r.status_code != 200:
        print("❌ failed")
        return
    data = r.json()
    fields = data.get("fields", [])
    print(f"\nALL fields ({len(fields)}):")
    for fld in fields:
        print(f"  • {fld.get('name','?'):<30} | {fld.get('alias','?'):<30} | {fld.get('type','?')}")

    # Run a query that returns any feature (limit 1) so we see what real data looks like
    print(f"\n→ Sample query: returnGeometry=false, resultRecordCount=1")
    qr = http_get(f"{base}/query", {
        "where": "1=1",
        "outFields": "*",
        "resultRecordCount": "1",
        "returnGeometry": "false",
        "f": "json",
    })
    if qr and qr.status_code == 200:
        try:
            qd = qr.json()
            feats = qd.get("features", [])
            print(f"  Got {len(feats)} feature(s)")
            if feats:
                attrs = feats[0].get("attributes", {})
                print("  Sample attributes:")
                for k, v in attrs.items():
                    print(f"    {k}: {v}")
                save = CAPTURE_DIR / "palmbeach_parcels_sample.json"
                save.write_text(json.dumps(qd, indent=2)[:8000])
        except Exception as e:
            print(f"  parse error: {e}")


# =============================================================================
# Phase B — Broward: enumerate every BCPA_EXTERNAL_* service
# =============================================================================

def phase_b() -> None:
    print()
    print("=" * 70)
    print("PHASE B — Broward: enumerate services at gisweb-adapters.bcpa.net")
    print("=" * 70)

    root = "https://gisweb-adapters.bcpa.net/arcgis/rest/services"
    r = http_get(root, {"f": "json"})
    if not r or r.status_code != 200:
        print("❌ failed")
        return
    data = r.json()
    services = data.get("services", [])
    print(f"\nAll services ({len(services)}):")
    for s in services:
        print(f"  📄 {s.get('name','?'):<40} ({s.get('type','?')})")

    # Sort to find the most recent EXTERNAL service (preferred for public data)
    externals = [s for s in services if "external" in (s.get("name") or "").lower()]
    print(f"\nEXTERNAL services (public data): {[s['name'] for s in externals]}")

    # Probe each external service
    for s in externals[:3]:
        name = s["name"]
        stype = s.get("type", "MapServer")
        svc_url = f"{root}/{name}/{stype}"
        print(f"\n{'─' * 60}")
        print(f"SERVICE: {name}")
        print(f"  URL: {svc_url}")
        r = http_get(svc_url, {"f": "json"})
        if not r or r.status_code != 200:
            continue
        try:
            sdata = r.json()
            layers = sdata.get("layers", [])
            print(f"  Layers ({len(layers)}):")
            for L in layers[:30]:
                print(f"    [{L.get('id')}] {L.get('name')} ({L.get('type')})")

            # Find the layer most likely to contain property records
            property_layer = None
            for L in layers:
                lname = (L.get("name") or "").lower()
                if any(k in lname for k in ("parcel", "property", "folio", "tax", "owner", "real")):
                    property_layer = L
                    break

            if property_layer:
                lid = property_layer["id"]
                print(f"\n  → Drilling into layer {lid}: {property_layer['name']}")
                meta_url = f"{svc_url}/{lid}"
                mr = http_get(meta_url, {"f": "json"})
                if mr and mr.status_code == 200:
                    md = mr.json()
                    flds = md.get("fields", [])
                    print(f"  Fields ({len(flds)}):")
                    for fld in flds[:30]:
                        print(f"    • {fld.get('name','?'):<30} | {fld.get('alias','?'):<30}")

                    # Try a sample query
                    print(f"\n  → Sample query (resultRecordCount=1):")
                    qr = http_get(f"{meta_url}/query", {
                        "where": "1=1", "outFields": "*",
                        "resultRecordCount": "1", "returnGeometry": "false", "f": "json",
                    })
                    if qr and qr.status_code == 200:
                        qd = qr.json()
                        feats = qd.get("features", [])
                        if feats:
                            attrs = feats[0].get("attributes", {})
                            print(f"  Sample attributes:")
                            for k, v in list(attrs.items())[:30]:
                                print(f"    {k}: {v}")
                            save = CAPTURE_DIR / f"broward_{name}_layer{lid}_sample.json"
                            save.write_text(json.dumps(qd, indent=2)[:8000])
        except Exception as e:
            print(f"  parse error: {e}")


def main() -> int:
    phase_a()
    phase_b()
    print()
    print("=" * 70)
    print("Done.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
