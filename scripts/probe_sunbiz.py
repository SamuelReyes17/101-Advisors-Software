"""
Probe Sunbiz.org — Florida Department of State corporation search.

Goal: understand the URL structure + HTML so we can write a parser that
extracts officer names, mailing address, and registered agent for any LLC
owner found in our leads CSV.

Public search URL pattern:
    https://search.sunbiz.org/Inquiry/CorporationSearch/ByName?searchTerm=<name>

Usage:
    python3 -m scripts.probe_sunbiz
"""
from __future__ import annotations

import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
    "Accept": "text/html,application/xhtml+xml",
}

# Real LLC names from our enriched leads
TEST_NAMES = [
    "A20 LLC",
    "CAPCAZ LLC",
    "NICVALCOR LLC",
    "ONE SKY CAPITAL LLC",
    "ECKEN INVESTMENT GROUP LLC",
]


def http_get(url: str, params: dict | None = None):
    try:
        return requests.get(url, params=params, headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")
        return None


def probe_search(name: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"SEARCH: {name}")
    print(f"{'─' * 60}")

    # Sunbiz search URL — they redirect through a wrapper, the real search is ByName
    url = "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName"
    params = {
        "inquiryType": "EntityName",
        "searchTerm": name,
        "searchNameOrder": name.replace(" ", "").upper(),
    }
    r = http_get(url, params=params)
    if not r or r.status_code != 200:
        return

    html = r.text
    safe_name = name.replace(" ", "_")
    save = CAPTURE_DIR / f"sunbiz_search_{safe_name}.html"
    save.write_text(html, encoding="utf-8")
    print(f"  HTTP {r.status_code} · {len(html)} bytes")
    print(f"  → saved to {save.name}")

    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: parse the results table (when there are multiple matches)
    tables = soup.find_all("table")
    print(f"  Tables found: {len(tables)}")
    for i, tbl in enumerate(tables[:3]):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
        print(f"  Table {i}: {len(rows)} rows, headers={headers[:5]}")
        # First data row sample
        if len(rows) > 1:
            data = [td.get_text(strip=True) for td in rows[1].find_all("td")]
            print(f"    sample row: {data[:6]}")

    # Strategy 2: detail page links
    links = soup.find_all("a", href=re.compile(r"SearchResultDetail"))
    print(f"  Detail links found: {len(links)}")
    for L in links[:3]:
        href = L.get("href", "")
        text = L.get_text(strip=True)
        print(f"    → {text[:50]:<50} {href[:80]}")

    # Strategy 3: look for officer/agent labels
    for label in ("Officer", "Director", "Registered Agent", "Authorized Person"):
        if label in html:
            print(f"  ✓ Found label '{label}' in HTML")


def main() -> int:
    print("=" * 70)
    print("Sunbiz.org probe — Florida corporation registry")
    print("=" * 70)

    for name in TEST_NAMES:
        probe_search(name)

    print()
    print("=" * 70)
    print("Hecho. Pegame el output y armo el parser real.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    main()
