"""
Discovery probe for the Miami-Dade Clerk of Court Online Case Search (OCS).

The OCS at https://www2.miamidadeclerk.gov/ocs/ is a React SPA. We need to:
  1. Download its bundled JS to find the underlying REST API.
  2. Find endpoints that let us search cases by:
       - Case type (LP = Lis Pendens)
       - Property address or folio
       - Defendant name
  3. Verify we can retrieve plaintiff (the bank), attorney info,
     case status, filed date, next hearing.

Once we have these, we wire a collector that:
  - Takes a lead → searches Clerk for cases against that owner/address
  - Fills lender_name, lender_phone, attorney name, case_number,
    lis_pendens_filed_date, next_hearing.

Usage:
    python3 -m scripts.probe_clerk
"""
from __future__ import annotations

import re
from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux) AppleWebKit/537.36 Chrome/120.0",
    "Accept": "*/*",
    "Referer": "https://www2.miamidadeclerk.gov/ocs/",
}


def http_get(url: str, **kw):
    try:
        return requests.get(url, headers=HEADERS, timeout=20, **kw)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return None


def main() -> int:
    print("=" * 70)
    print("Miami-Dade Clerk of Court — OCS API discovery")
    print("=" * 70)

    # ── Step 1: fetch the SPA HTML, find script bundles ──────────────────
    spa = "https://www2.miamidadeclerk.gov/ocs/"
    r = http_get(spa)
    if not r or r.status_code != 200:
        print("❌ SPA not reachable")
        return 1
    html = r.text
    (CAPTURE_DIR / "clerk_spa.html").write_text(html, encoding="utf-8")
    print(f"\n📄 SPA HTML: {len(html)} bytes")

    # Extract bundle URLs
    js_urls = set()
    for m in re.finditer(r'src="([^"]+\.js[^"]*)"', html):
        u = m.group(1)
        if u.startswith("http"):
            js_urls.add(u)
        elif u.startswith("/"):
            js_urls.add(f"https://www2.miamidadeclerk.gov{u}")
        else:
            js_urls.add(f"https://www2.miamidadeclerk.gov/ocs/{u}")

    print(f"\n📦 JS bundles referenced: {len(js_urls)}")
    for u in sorted(js_urls):
        print(f"   → {u}")

    # ── Step 2: download each bundle, search for API URLs ────────────────
    keywords = (
        "api/", "/case", "/search", "/lispendens", "/foreclosure",
        "/party", "/docket", "/court", "asmx", "/Property", "/Owner",
        "ocs", "clerk", "/v1/", "/v2/", "graphql",
    )
    pattern = re.compile(r'https?://[^\s"\'`<>]{15,200}', re.IGNORECASE)
    all_eps: set[str] = set()
    for url in sorted(js_urls):
        r = http_get(url)
        if not r or r.status_code != 200:
            continue
        body = r.text
        print(f"\n📄 {url.split('/')[-1]}: {len(body):,} bytes")
        save = CAPTURE_DIR / f"clerk_js_{url.split('/')[-1][:60]}.txt"
        save.write_text(body[:300_000], encoding="utf-8")

        hits = 0
        for m in pattern.finditer(body):
            u = m.group(0).rstrip(",.;)\"'")
            if any(k.lower() in u.lower() for k in keywords):
                all_eps.add(u)
                hits += 1
        print(f"   found {hits} interesting URLs")

    # Also grep the SPA HTML itself for any inline API references
    for m in pattern.finditer(html):
        u = m.group(0).rstrip(",.;)\"'")
        if any(k.lower() in u.lower() for k in keywords):
            all_eps.add(u)

    print(f"\n{'=' * 70}")
    print(f"Candidate Clerk API endpoints ({len(all_eps)}):")
    print(f"{'=' * 70}")
    for ep in sorted(all_eps):
        print(f"  → {ep}")
    print()

    # ── Step 3: poke at common OCS paths ────────────────────────────────
    print(f"\n{'=' * 70}")
    print("Probing common OCS paths directly...")
    print(f"{'=' * 70}")

    common = [
        "https://www2.miamidadeclerk.gov/ocs/api/casetypes",
        "https://www2.miamidadeclerk.gov/ocs/api/cases/search",
        "https://www2.miamidadeclerk.gov/ocs/api/search",
        "https://www2.miamidadeclerk.gov/ocs/api/v1/search",
        "https://www2.miamidadeclerk.gov/ocs/api/parties/search",
        # Other Clerk subdomains
        "https://onlineservices.miamidadeclerk.gov/officialrecords/",
        "https://onlineservices.miamidadeclerk.gov/officialrecords/api/search",
        "https://onlineservices.miamidadeclerk.com/officialrecords/",
    ]
    for url in common:
        print(f"\n→ {url}")
        r = http_get(url)
        if not r:
            continue
        ct = r.headers.get("content-type", "?")
        print(f"  HTTP {r.status_code} · {len(r.content)} bytes · {ct}")
        if "json" in ct.lower():
            print(f"  preview: {r.text[:300]}")

    return 0


if __name__ == "__main__":
    main()
