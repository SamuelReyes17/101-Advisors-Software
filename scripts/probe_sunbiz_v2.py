"""
Verbose probe for Sunbiz — try multiple URL patterns and show ALL responses.

Usage:
    python3 -m scripts.probe_sunbiz_v2
"""
from __future__ import annotations

from pathlib import Path

import requests

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

# Try multiple realistic browser User-Agents — Sunbiz blocks "Bot" strings.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://search.sunbiz.org/",
}

TEST_NAME = "A20 LLC"


def probe(label: str, url: str, params: dict | None = None) -> None:
    print(f"\n→ {label}")
    print(f"   URL: {url}")
    if params:
        print(f"   params: {params}")
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30,
                         allow_redirects=True)
    except Exception as e:
        print(f"   ❌ {type(e).__name__}: {e}")
        return

    print(f"   HTTP {r.status_code} · {len(r.content)} bytes")
    print(f"   Final URL: {r.url}")
    print(f"   Content-Type: {r.headers.get('content-type', '?')}")
    if r.history:
        print(f"   Redirects: {[h.status_code for h in r.history]}")

    safe = label.replace(" ", "_").replace("/", "_")
    save = CAPTURE_DIR / f"sunbiz_v2_{safe}.html"
    save.write_bytes(r.content[:30000])
    print(f"   → saved to {save.name}")

    if "html" in r.headers.get("content-type", "").lower():
        body = r.text
        # Show <title>
        import re
        m = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if m:
            print(f"   <title>: {m.group(1).strip()[:100]}")
        # Show first <h1> or <h2>
        for tag in ("h1", "h2"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", body, re.IGNORECASE | re.DOTALL)
            if m:
                print(f"   <{tag}>: {m.group(1).strip()[:100]}")
                break
        # Show snippet around the search term
        if TEST_NAME.upper() in body.upper():
            idx = body.upper().find(TEST_NAME.upper())
            snippet = body[max(0, idx-100):idx+200].replace("\n", " ")
            print(f"   📌 Found search term, context:")
            print(f"      ...{snippet}...")


def main() -> int:
    print("=" * 70)
    print(f"Verbose Sunbiz probe — search term: {TEST_NAME}")
    print("=" * 70)

    # First: hit the home page to establish a session cookie
    print("\n[1] Hit Sunbiz home page to seed session...")
    s = requests.Session()
    s.headers.update(HEADERS)
    home = s.get("https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
                 timeout=30)
    print(f"   Home HTTP {home.status_code} · cookies: {list(s.cookies.keys())}")

    # Then try multiple search URL patterns
    base_attempts = [
        ("ByName_get_searchTerm",
         "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
         {"searchTerm": TEST_NAME, "inquiryType": "EntityName"}),

        ("ByName_get_SearchTerm",
         "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
         {"SearchTerm": TEST_NAME, "inquiryType": "EntityName"}),

        ("ByName_searchNameOrder",
         "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
         {"searchNameOrder": TEST_NAME.replace(" ", "").upper(),
          "SearchTerm": TEST_NAME,
          "inquiryType": "EntityName"}),

        ("SearchResults",
         "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults",
         {"inquiryType": "EntityName",
          "searchNameOrder": TEST_NAME.replace(" ", "").upper(),
          "searchTerm": TEST_NAME}),

        ("entityname_path",
         f"https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults",
         {"inquirytype": "EntityName",
          "directionType": "Initial",
          "searchNameOrder": TEST_NAME.replace(" ", "").upper() + "L",
          "aggregateId": "",
          "searchTerm": TEST_NAME}),
    ]

    for label, url, params in base_attempts:
        # Use the session so cookies persist
        print(f"\n→ {label}")
        print(f"   URL: {url}")
        print(f"   params: {params}")
        try:
            r = s.get(url, params=params, timeout=30)
            print(f"   HTTP {r.status_code} · {len(r.content)} bytes · {r.headers.get('content-type','?')}")
            print(f"   Final URL: {r.url}")
            if r.history:
                print(f"   Redirects through: {[h.status_code for h in r.history]}")
            save = CAPTURE_DIR / f"sunbiz_v2_{label}.html"
            save.write_bytes(r.content[:50000])
            # Quick parse
            body = r.text
            import re as _re
            m = _re.search(r"<title>(.*?)</title>", body, _re.IGNORECASE | _re.DOTALL)
            if m:
                print(f"   <title>: {m.group(1).strip()[:100]}")
            if "A20" in body.upper():
                idx = body.upper().find("A20")
                snippet = body[max(0, idx-50):idx+200].replace("\n", " ")
                print(f"   📌 Found 'A20' in body. Context: ...{snippet}...")
            else:
                print(f"   (search term not found in body)")
        except Exception as e:
            print(f"   ❌ {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    main()
