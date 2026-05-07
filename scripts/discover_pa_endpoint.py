"""
Two-part discovery:
    A) Parse the gisweb services directory and look for Property-Appraiser-ish services.
    B) Fetch the apps.miamidadepa.gov SPA, extract its JS bundle URLs, fetch them,
       and search for API endpoint patterns the SPA calls.

Usage:
    python3 -m scripts.discover_pa_endpoint
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CAPTURES = Path(__file__).parent / "captures"
CAPTURES.mkdir(parents=True, exist_ok=True)


def part_a_services_directory() -> None:
    print("\n" + "=" * 70)
    print("PART A — gisweb.miamidade.gov ArcGIS services directory")
    print("=" * 70)

    try:
        import requests
    except ImportError:
        print("requests not installed.")
        return

    url = "https://gisweb.miamidade.gov/arcgis/rest/services?f=json"
    try:
        r = requests.get(url, timeout=20)
        data = r.json()
    except Exception as e:
        print(f"FAILED: {e}")
        return

    folders = data.get("folders", [])
    services = data.get("services", [])
    print(f"\nFolders ({len(folders)}):")
    for f in folders:
        marker = "  ← LIKELY PA" if any(k in f.lower() for k in ["pa", "appraiser", "property", "tax"]) else ""
        print(f"  {f}{marker}")

    print(f"\nServices at root ({len(services)}):")
    for s in services:
        name = s.get("name", "?")
        kind = s.get("type", "?")
        marker = "  ← LIKELY PA" if any(k in name.lower() for k in ["pa", "appraiser", "property", "tax"]) else ""
        print(f"  {name} ({kind}){marker}")

    # Probe each likely-PA folder to enumerate services inside
    likely = [f for f in folders if any(k in f.lower() for k in ["pa", "appraiser", "property", "tax"])]
    if likely:
        print(f"\nProbing {len(likely)} likely PA folder(s)...")
        for folder in likely:
            sub_url = f"https://gisweb.miamidade.gov/arcgis/rest/services/{folder}?f=json"
            try:
                sr = requests.get(sub_url, timeout=15)
                sdata = sr.json()
                print(f"\n  📁 {folder}/")
                for s in sdata.get("services", []):
                    print(f"      {s.get('name')} ({s.get('type')})")
            except Exception as e:
                print(f"  {folder}: FAILED ({e})")


def part_b_spa_api_extraction() -> None:
    print("\n" + "=" * 70)
    print("PART B — Extract API endpoints from the propertysearch SPA")
    print("=" * 70)

    try:
        import requests
    except ImportError:
        print("requests not installed.")
        return

    spa_url = "https://apps.miamidadepa.gov/propertysearch/"
    try:
        r = requests.get(spa_url, timeout=20)
        html = r.text
    except Exception as e:
        print(f"FAILED to fetch SPA: {e}")
        return

    print(f"\nSPA HTML: {len(html)} bytes")

    # Save full HTML this time (no truncation)
    (CAPTURES / "pa_spa_full.html").write_text(html, encoding="utf-8")
    print(f"Saved full HTML to: {CAPTURES / 'pa_spa_full.html'}")

    # Find JS bundle URLs
    js_urls = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html)
    css_urls = re.findall(r'<link[^>]+href="([^"]+\.css[^"]*)"', html)
    print(f"\nFound {len(js_urls)} JS files, {len(css_urls)} CSS files referenced.")

    # Resolve relative URLs
    base = "https://apps.miamidadepa.gov/propertysearch/"
    full_js_urls = []
    for u in js_urls:
        if u.startswith("http"):
            full_js_urls.append(u)
        elif u.startswith("//"):
            full_js_urls.append("https:" + u)
        elif u.startswith("/"):
            full_js_urls.append("https://apps.miamidadepa.gov" + u)
        else:
            full_js_urls.append(base + u)

    print("\nJS files to inspect:")
    for u in full_js_urls[:10]:
        print(f"  {u}")

    # Fetch each JS file and search for API patterns
    print("\nFetching JS bundles and searching for API endpoints...")
    api_patterns_found: dict[str, list[str]] = {}

    for js_url in full_js_urls[:6]:  # limit to avoid spam
        try:
            jr = requests.get(js_url, timeout=20)
            content = jr.text
            print(f"\n  📄 {js_url.split('/')[-1]}: {len(content):,} bytes")
        except Exception as e:
            print(f"  FAILED {js_url}: {e}")
            continue

        # Save for manual inspection
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", js_url.split("/")[-1])
        (CAPTURES / f"pa_js_{fname}.txt").write_text(content[:200000], encoding="utf-8")

        # Search for URLs/API patterns in the JS
        # Common patterns: fetch("/api/..."), axios.get("..."), "https://...", fetch(`...`)
        patterns = [
            (r'"(https?://[^"\s]+)"', "absolute URL"),
            (r'`(https?://[^`\s]+)`', "template URL"),
            (r'"(/api/[^"]+)"', "/api/ path"),
            (r'fetch\(["`](\S+?)["`]', "fetch() call"),
            (r'axios\.\w+\(["`](\S+?)["`]', "axios call"),
        ]

        found_here = set()
        for pat, label in patterns:
            for m in re.findall(pat, content):
                # Filter for things that look like data endpoints
                m_lower = m.lower()
                if any(k in m_lower for k in [
                    "api", "rest/services", "folio", "search", "property",
                    "miamidade", "appraiser", "json", "rpc", "graphql",
                ]):
                    if not any(skip in m_lower for skip in [
                        "fonts.gstatic", "googleapis.com/css",
                        "schema.org", "w3.org",
                    ]):
                        found_here.add(m[:200])

        if found_here:
            api_patterns_found[js_url.split("/")[-1]] = sorted(found_here)
            for u in sorted(found_here)[:15]:
                print(f"      → {u}")

    print("\n" + "=" * 70)
    print(f"Total candidate endpoints found: {sum(len(v) for v in api_patterns_found.values())}")
    print("=" * 70)
    if api_patterns_found:
        print("\nMandame este output (todo lo que aparece arriba con →) y armo el cliente para")
        print("el endpoint correcto. Las URLs que terminan en folios/numbers o tienen 'rest/services'")
        print("son las más probables.")


def main() -> int:
    part_a_services_directory()
    part_b_spa_api_extraction()
    return 0


if __name__ == "__main__":
    sys.exit(main())
