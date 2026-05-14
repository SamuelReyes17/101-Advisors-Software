"""
Deep discovery for Broward + Palm Beach Property Appraisers.

Phase A — Palm Beach:
    Enumerate ALL folders in maps.co.palm-beach.fl.us/arcgis/rest/services
    and probe each candidate (PA, Parcels, Property, Appraiser, Cadastral,
    PropertyAppraiser, PAPA, etc.) for property-data services.

Phase B — Broward:
    Fetch the BCPA SPA HTML, extract every <script src=...>, download each
    JS bundle, and grep for URLs that look like API endpoints (similar to
    the technique used for Miami-Dade's propertysearch SPA).

Usage:
    python3 -m scripts.probe_broward_palmbeach_deep
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
    "Accept": "application/json, text/html",
}


def http_get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return None


# =============================================================================
# Phase A — Palm Beach: enumerate ArcGIS folders & find the PA service
# =============================================================================

PA_KEYWORDS = ("pa", "papa", "parcel", "property", "appraiser", "cadastral",
               "tax", "assessor", "land", "real", "estate", "ownership")


def phase_a_palm_beach() -> None:
    print("=" * 70)
    print("PHASE A — Palm Beach: enumerate ArcGIS folders")
    print("=" * 70)

    root_url = "https://maps.co.palm-beach.fl.us/arcgis/rest/services?f=json"
    resp = http_get(root_url)
    if not resp or resp.status_code != 200:
        print(f"❌ Root catalog not reachable")
        return

    try:
        data = resp.json()
    except Exception:
        print(f"❌ Root catalog not JSON")
        return

    folders = data.get("folders", [])
    root_services = data.get("services", [])
    print(f"\nFolders found: {len(folders)}")
    for f in folders:
        kw_hit = any(k in f.lower() for k in PA_KEYWORDS)
        marker = "  ← LIKELY PA" if kw_hit else ""
        print(f"  📁 {f}{marker}")

    print(f"\nServices at root: {len(root_services)}")
    for s in root_services[:30]:
        name = s.get("name", "?")
        kw_hit = any(k in name.lower() for k in PA_KEYWORDS)
        marker = "  ← LIKELY PA" if kw_hit else ""
        print(f"  {name} ({s.get('type','?')}){marker}")

    # Probe folders that look related to property data
    candidates = [f for f in folders if any(k in f.lower() for k in PA_KEYWORDS)]
    print(f"\nProbing {len(candidates)} candidate folder(s)...")
    for folder in candidates:
        folder_url = f"https://maps.co.palm-beach.fl.us/arcgis/rest/services/{folder}?f=json"
        print(f"\n  📁 {folder}/ → {folder_url}")
        r = http_get(folder_url)
        if not r or r.status_code != 200:
            continue
        try:
            fdata = r.json()
            for s in fdata.get("services", [])[:20]:
                name = s.get("name", "?")
                stype = s.get("type", "?")
                print(f"    📄 {name} ({stype})")
        except Exception as e:
            print(f"    JSON parse failed: {e}")

    # Also try a fixed set of common service names directly under root
    print(f"\nProbing common service paths directly...")
    common_services = [
        "PA/MapServer", "PAPA/MapServer", "Parcels/MapServer",
        "Property/MapServer", "Cadastral/MapServer", "PropertyAppraiser/MapServer",
        "PA/FeatureServer", "PAPA/FeatureServer",
    ]
    for path in common_services:
        url = f"https://maps.co.palm-beach.fl.us/arcgis/rest/services/{path}?f=json"
        r = http_get(url)
        if not r:
            continue
        try:
            d = r.json()
            if "error" in d:
                continue  # not found
            print(f"\n  ✅ {path}")
            print(f"    keys: {list(d.keys())[:6]}")
            for layer in d.get("layers", [])[:5]:
                print(f"    layer {layer.get('id')}: {layer.get('name')}")
        except Exception:
            pass


# =============================================================================
# Phase B — Broward: inspect the BCPA SPA + its JS bundles for API URLs
# =============================================================================

def phase_b_broward() -> None:
    print()
    print("=" * 70)
    print("PHASE B — Broward: extract API URLs from BCPA SPA bundles")
    print("=" * 70)

    spa_url = "https://web.bcpa.net/bcpaclient/index.html"
    resp = http_get(spa_url)
    if not resp or resp.status_code != 200:
        print(f"❌ SPA not reachable")
        return

    html = resp.text
    spa_path = CAPTURE_DIR / "broward_spa_full.html"
    spa_path.write_text(html, encoding="utf-8")
    print(f"SPA HTML: {len(html)} bytes → {spa_path.name}")

    # Find <script src="..."> and <link href="...js">
    js_urls = set()
    for m in re.finditer(r'src="([^"]+\.js[^"]*)"', html):
        u = m.group(1)
        if not u.startswith("http"):
            u = "https://web.bcpa.net/bcpaclient/" + u.lstrip("/")
        js_urls.add(u)
    # Also angular bundles often referenced relatively
    for m in re.finditer(r'"([\./\w\-]+\.js)"', html):
        u = m.group(1)
        if u.startswith("http"):
            js_urls.add(u)
        elif u.startswith("/"):
            js_urls.add("https://web.bcpa.net" + u)
        else:
            js_urls.add("https://web.bcpa.net/bcpaclient/" + u)

    print(f"\nJS bundles referenced: {len(js_urls)}")
    for u in sorted(js_urls):
        print(f"  → {u}")

    # Download each bundle and search for URLs that look like APIs.
    api_pattern = re.compile(r'https?://[^\s"\'`<>]{20,150}', re.IGNORECASE)
    interesting_keywords = (
        "asmx", "api/", "/json", "/property", "/parcel", "/folio",
        "/search", "/record", "bcpa", "Property.", "Search.", "Owner",
    )

    all_endpoints: set[str] = set()
    for url in sorted(js_urls):
        r = http_get(url)
        if not r or r.status_code != 200:
            continue
        body = r.text
        print(f"\n  📄 {url.split('/')[-1]}: {len(body):,} bytes")
        save_to = CAPTURE_DIR / f"broward_js_{url.split('/')[-1].replace('?', '_')}.txt"
        save_to.write_text(body[:200_000], encoding="utf-8")
        for m in api_pattern.finditer(body):
            u = m.group(0)
            if any(k.lower() in u.lower() for k in interesting_keywords):
                all_endpoints.add(u)

    print(f"\nCandidate API endpoints found: {len(all_endpoints)}")
    for ep in sorted(all_endpoints):
        print(f"  → {ep}")

    # Also search the SPA HTML itself for any inline API URLs
    print(f"\nAlso searching SPA HTML for API URLs...")
    for m in api_pattern.finditer(html):
        u = m.group(0)
        if any(k.lower() in u.lower() for k in interesting_keywords):
            print(f"  → {u}")


def main() -> int:
    phase_a_palm_beach()
    phase_b_broward()
    print()
    print("=" * 70)
    print("Hecho. Mandame el output completo y armamos los collectors.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
