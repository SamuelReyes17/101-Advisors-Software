"""
Targeted probes for Broward + Palm Beach Property Appraisers.

Phase A — Palm Beach:
    Now that we know Parcels/Parcels/MapServer exists, enumerate its
    layers and try a real query.

Phase B — Broward:
    Probe gisweb-adapters.bcpa.net (the hostname referenced in the SPA HTML)
    + BCPA-hosted JS bundles (index.min.js, common.min.js, etc).

Usage:
    python3 -m scripts.probe_targeted
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://web.bcpa.net/bcpaclient/",
}

# =============================================================================
# Phase A — Palm Beach: Parcels/Parcels/MapServer
# =============================================================================

PB_PARCELS_BASE = "https://maps.co.palm-beach.fl.us/arcgis/rest/services/Parcels/Parcels/MapServer"
PB_TEST_PCN = "74434312060010350"
PB_TEST_ADDRESS = "316 S Olive Ave"


def http_get(url: str, params: dict | None = None, timeout: int = 20):
    try:
        return requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return None


def phase_a_palmbeach() -> None:
    print("=" * 70)
    print("PHASE A — Palm Beach: enumerate Parcels/Parcels layers")
    print("=" * 70)

    print(f"\n→ {PB_PARCELS_BASE}?f=json")
    r = http_get(PB_PARCELS_BASE, {"f": "json"})
    if not r or r.status_code != 200:
        print("❌ failed")
        return
    try:
        data = r.json()
    except Exception as e:
        print(f"❌ not JSON: {e}")
        return

    layers = data.get("layers", [])
    print(f"\nLayers ({len(layers)}):")
    for L in layers:
        print(f"  [{L.get('id')}] {L.get('name')} ({L.get('type')})")

    # Probe each layer's fields and test queries
    for L in layers[:8]:
        lid = L["id"]
        name = L["name"]
        print(f"\n--- Layer {lid}: {name} ---")
        meta_url = f"{PB_PARCELS_BASE}/{lid}"
        r = http_get(meta_url, {"f": "json"})
        if not r or r.status_code != 200:
            continue
        try:
            mdata = r.json()
        except Exception:
            continue

        fields = mdata.get("fields", [])
        owner_field = address_field = pcn_field = zip_field = None
        for fld in fields:
            n = (fld.get("name") or "").lower()
            alias = (fld.get("alias") or "").lower()
            text = n + " " + alias
            if "owner" in text or "name" in text:
                owner_field = fld["name"]
            if "addr" in text or "site" in text:
                address_field = fld["name"]
            if "pcn" in text or "parcel" in text and "control" in text:
                pcn_field = fld["name"]
            if "zip" in text or "postal" in text:
                zip_field = fld["name"]

        interesting = [fld for fld in fields if any(
            k in (fld.get("name", "").lower() + (fld.get("alias", "").lower()))
            for k in ("folio", "pcn", "parcel", "owner", "addr", "city", "zip", "site", "use", "type", "dor", "bedroom", "unit", "value", "year")
        )]
        print(f"  Interesting fields ({len(interesting)}):")
        for fld in interesting[:25]:
            print(f"    • {fld['name']} ({fld.get('alias','')}) [{fld.get('type','?')}]")

        # Try a query with the test PCN if there's a PCN-like field
        if pcn_field:
            where = f"{pcn_field}='{PB_TEST_PCN}'"
            qr = http_get(f"{PB_PARCELS_BASE}/{lid}/query",
                          {"where": where, "outFields": "*", "f": "json"})
            if qr and qr.status_code == 200:
                try:
                    qdata = qr.json()
                    feats = qdata.get("features", [])
                    print(f"\n  ✅ Query by {pcn_field}='{PB_TEST_PCN}' → {len(feats)} feature(s)")
                    if feats:
                        attrs = feats[0].get("attributes", {})
                        for k, v in list(attrs.items())[:25]:
                            print(f"    {k}: {v}")
                        save = CAPTURE_DIR / f"palmbeach_layer{lid}_query.json"
                        save.write_text(json.dumps(qdata, indent=2)[:8000])
                        return  # we found the right layer, stop early
                except Exception as e:
                    print(f"  query failed: {e}")


# =============================================================================
# Phase B — Broward: gisweb-adapters.bcpa.net + JS bundles
# =============================================================================

def phase_b_broward() -> None:
    print()
    print("=" * 70)
    print("PHASE B — Broward: probe gisweb-adapters.bcpa.net + JS bundles")
    print("=" * 70)

    TEST_FOLIO = "504216050010"

    # The URL referenced in the SPA HTML
    base_urls = [
        f"https://gisweb-adapters.bcpa.net/bcpawebmap_ex_new_web/bcpawebmap.aspx",
        f"https://gisweb-adapters.bcpa.net/bcpawebmap_ex_new_web/bcpawebmap.aspx?folio={TEST_FOLIO}",
        f"https://gisweb-adapters.bcpa.net/bcpawebmap_ex_new_web/bcpawebmap.aspx?FolioNumber={TEST_FOLIO}",
        f"https://gisweb-adapters.bcpa.net/bcpawebmap_ex_new_web/bcpawebmap.aspx?id={TEST_FOLIO}",
        # ArcGIS roots on the new hostname
        f"https://gisweb-adapters.bcpa.net/arcgis/rest/services?f=json",
        f"https://gisweb-adapters.bcpa.net/?f=json",
        f"https://gisweb-adapters.bcpa.net/",
    ]
    for url in base_urls:
        print(f"\n→ {url[:120]}")
        r = http_get(url)
        if not r:
            continue
        ct = r.headers.get("content-type", "?")
        print(f"  HTTP {r.status_code} · {len(r.content)} bytes · {ct}")
        save = CAPTURE_DIR / f"broward_adapter_{abs(hash(url))%100000}.txt"
        save.write_bytes(r.content[:8192])
        body = r.text[:500].replace("\n", " ")
        print(f"  preview: {body[:300]}")

    # Now download the BCPA-hosted JS bundles we couldn't fetch before
    js_urls = [
        "https://web.bcpa.net/bcpaclient/js/angular/index.min.js",
        "https://web.bcpa.net/bcpaclient/js/common.min.js",
        "https://web.bcpa.net/bcpaclient/js/externalwhitelist.js",
        "https://web.bcpa.net/bcpaclient/js/plugins/angular-ui-router.min.js",
        "https://web.bcpa.net/bcpaclient/js/router-menu.js",
    ]
    api_pattern = re.compile(r'https?://[^\s"\'`<>]{15,200}', re.IGNORECASE)
    interesting = ("asmx", "api/", "/json", "/property", "/parcel", "/folio",
                   "/search", "bcpa", "adapter", "gisweb", "/owner", "/sales",
                   "appraiser", "Property.", "Search.", "/record")
    all_eps: set[str] = set()
    for url in js_urls:
        print(f"\n→ {url}")
        r = http_get(url)
        if not r:
            continue
        print(f"  HTTP {r.status_code} · {len(r.content)} bytes")
        if r.status_code != 200:
            print(f"  body preview: {r.text[:200]}")
            continue
        body = r.text
        save = CAPTURE_DIR / f"broward_js_{url.split('/')[-1]}.txt"
        save.write_text(body[:200_000], encoding="utf-8")
        hits = 0
        for m in api_pattern.finditer(body):
            u = m.group(0).rstrip(",.;)\"'")
            if any(k.lower() in u.lower() for k in interesting):
                all_eps.add(u)
                hits += 1
        print(f"  found {hits} interesting URLs")

    print(f"\nBroward API endpoint candidates ({len(all_eps)}):")
    for ep in sorted(all_eps):
        print(f"  → {ep}")


def main() -> int:
    phase_a_palmbeach()
    phase_b_broward()
    print()
    print("=" * 70)
    print("Done. Pegame el output.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
