"""
Discovery probe: Miami-Dade Tax Collector + Clerk public APIs.

GOAL — find endpoints that give us, by FOLIO or owner name:
    1. TAX:    current tax due + delinquency for prior years
    2. CLERK:  Lis Pendens / Foreclosure case + plaintiff (bank) + attorney

Both are PUBLIC RECORD by Florida law. The hard part is finding the
underlying REST endpoint behind their SPAs.

Strategies tried:
    A) ArcGIS catalogs at multiple hostnames
    B) Direct REST patterns the SPA might be using
    C) Miami-Dade Open Data Hub (gis-mdc.opendata.arcgis.com)
    D) JS bundle extraction (find fetch() / axios.get() calls)

Usage:
    python3 -m scripts.probe_tax_and_clerk
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Accept": "application/json, text/html",
    "Referer": "https://www.miamidade.gov/",
}

# Real folio from our enriched data — for testing
TEST_FOLIO = "0141160040250"
TEST_OWNER = "EDUARDO BAEZ"


def http(label: str, url: str, **kw):
    print(f"\n→ {label}")
    print(f"  {url[:120]}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, **kw)
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {str(e)[:120]}")
        return None
    ct = r.headers.get("content-type", "?")
    print(f"  HTTP {r.status_code} · {len(r.content)} bytes · {ct}")
    if r.history:
        print(f"  Redirects: {[h.status_code for h in r.history]}")

    # Save
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
    save = CAPTURE_DIR / f"probe_{safe}.txt"
    save.write_bytes(r.content[:30000])

    # Quick inspection
    if "json" in ct.lower():
        try:
            data = r.json()
            if isinstance(data, dict):
                print(f"  JSON keys: {list(data.keys())[:8]}")
                if "error" in data:
                    print(f"  ERROR: {data['error']}")
                elif "features" in data:
                    feats = data["features"]
                    print(f"  Features: {len(feats)}")
                    if feats:
                        print(f"  Sample: {list(feats[0].get('attributes', {}).items())[:5]}")
                elif "services" in data:
                    names = [s.get("name") for s in data["services"][:15]]
                    print(f"  Services: {names}")
                elif "folders" in data:
                    print(f"  Folders: {data['folders'][:15]}")
        except Exception as e:
            print(f"  parse error: {e}")
    elif "html" in ct.lower():
        body = r.text
        m = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if m:
            print(f"  <title>: {m.group(1).strip()[:80]}")
    return r


def section(title: str):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def phase_tax():
    section("PHASE 1 — Miami-Dade Tax Collector")

    # Strategy A: ArcGIS at tax-collector hostnames
    http("tax_gisweb_root", "https://gisweb.miamidade.gov/arcgis/rest/services?f=json")
    http("tax_taxcollector_root", "https://www.miamidade.gov/taxcollector/api?f=json")
    http("tax_global_finance", "https://www.miamidade.gov/global/finance/tax-collector/")

    # Strategy B: PA SPA — they may use the same backend for tax
    http("pa_spa_root", "https://apps.miamidadepa.gov/propertysearch/")
    # Try a tax-by-folio endpoint
    http("pa_tax_by_folio", f"https://apps.miamidadepa.gov/propertysearch/api/tax/{TEST_FOLIO}")
    http("pa_taxinfo_by_folio", f"https://apps.miamidadepa.gov/propertysearch/api/taxinfo?folio={TEST_FOLIO}")
    http("pa_propertytax", f"https://apps.miamidadepa.gov/propertysearch/api/propertytax?folio={TEST_FOLIO}")

    # Strategy C: Miami-Dade Tax Collector's own search
    http("tax_search_main", "https://www.miamidade.gov/PApps/Property/Tax")
    http("tax_search_folio", f"https://www.miamidade.gov/PApps/Property/Tax?folio={TEST_FOLIO}")

    # Strategy D: Open Data Hub
    http("opendata_tax", "https://gis-mdc.opendata.arcgis.com/datasets?q=tax")

    # Strategy E: Possible secondary REST services we missed
    for svc_name in ["TaxCollector", "MD_TaxCollector", "TaxBill", "PropertyTax",
                     "MD_PropertyTax", "MD_TaxAccount"]:
        http(f"gisweb_{svc_name}",
             f"https://gisweb.miamidade.gov/arcgis/rest/services/{svc_name}/MapServer?f=json")


def phase_clerk():
    section("PHASE 2 — Miami-Dade Clerk (Lis Pendens / Cases)")

    # The Clerk's SPA
    http("clerk_spa", "https://www2.miamidadeclerk.gov/ocs/")
    http("clerk_old_search", "https://www2.miamidadeclerk.gov/cgtb/CCISWebSearch.aspx")
    http("clerk_records", "https://www2.miamidadeclerk.gov/PublicRecords/")
    http("clerk_officialrecords",
         "https://onlineservices.miamidadeclerk.gov/officialrecords/")

    # Try official records search by name
    name_q = "EDUARDO+BAEZ"
    http("clerk_oficial_byname",
         f"https://onlineservices.miamidadeclerk.gov/officialrecords/StandardSearch?searchType=name&name={name_q}")

    # Try the legacy CCIS (Civil Case Information System)
    http("ccis_inquiry", "https://www2.miamidadeclerk.gov/cgtb/CCIS_Search.aspx")
    http("ccis_inquiry2", "https://www2.miamidadeclerk.gov/cvweb/")

    # Lis Pendens is recorded as an official record — search those
    http("lis_pendens_recordtype",
         "https://onlineservices.miamidadeclerk.gov/officialrecords/StandardSearch?DocType=LP")

    # Strategy: maybe they have a v3 / GraphQL endpoint
    http("clerk_graphql", "https://www2.miamidadeclerk.gov/ocs/graphql")
    http("clerk_api_v1", "https://www2.miamidadeclerk.gov/ocs/api/v1/cases")
    http("clerk_api_v2", "https://www2.miamidadeclerk.gov/ocs/api/v2/cases")

    # Open Data Hub for foreclosure / clerk data
    http("opendata_clerk", "https://gis-mdc.opendata.arcgis.com/datasets?q=foreclosure")


def phase_opendata():
    section("PHASE 3 — Miami-Dade Open Data Hub")

    # Try the GIS open data hub search API
    queries = ["tax", "delinquent", "foreclosure", "lis pendens", "auction", "clerk"]
    for q in queries:
        url = f"https://gis-mdc.opendata.arcgis.com/api/search/v1/datasets?q={q}"
        http(f"opendata_{q}", url)


def main() -> int:
    print("=" * 70)
    print(f"Tax + Clerk discovery · test folio={TEST_FOLIO}, owner={TEST_OWNER}")
    print("=" * 70)
    phase_tax()
    phase_clerk()
    phase_opendata()
    print()
    print("=" * 70)
    print("Done. Mandame el output completo — vamos a buscar los HTTP 200 con JSON")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
