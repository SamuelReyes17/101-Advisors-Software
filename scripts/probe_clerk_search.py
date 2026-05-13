"""
Capture the Clerk OCS search API by performing an actual search via Playwright.

The home page only fires session endpoints. The real case search API only
triggers when the user types a name and clicks search. We automate that.

Usage:
    python3 -m scripts.probe_clerk_search
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Run: pip3 install playwright && playwright install chromium")
    raise SystemExit(1)

CAPTURE = Path(__file__).resolve().parent / "captures"
CAPTURE.mkdir(exist_ok=True)

TEST_NAME = "BAEZ"


def is_api_url(url: str) -> bool:
    if any(url.endswith(ext) for ext in
           (".js", ".css", ".png", ".jpg", ".woff", ".woff2", ".svg",
            ".gif", ".ico", ".map")):
        return False
    return any(h in url for h in
               ("miamidadeclerk.gov", "miamidade.gov", "/api/", "/rest/"))


def probe_search(label: str, start_url: str, do_search) -> list:
    print(f"\n{'─' * 70}")
    print(f"PROBE WITH SEARCH: {label}")
    print(f"URL: {start_url}")
    print(f"{'─' * 70}")

    requests_log = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
        )
        page = ctx.new_page()

        def on_request(req):
            try:
                requests_log.append({
                    "url": req.url, "method": req.method,
                    "resource_type": req.resource_type,
                })
            except Exception:
                pass

        def on_response(resp):
            try:
                for r in requests_log:
                    if r["url"] == resp.url and "status" not in r:
                        r["status"] = resp.status
                        r["ct"] = resp.headers.get("content-type", "")
                        # Try to capture small JSON bodies
                        if "json" in r["ct"].lower() and is_api_url(resp.url):
                            try:
                                r["body_preview"] = resp.text()[:1500]
                            except Exception:
                                pass
                        break
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(start_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        print(f"  Initial requests: {len(requests_log)}")
        # Save a screenshot of the home page so user can verify
        page.screenshot(path=str(CAPTURE / f"clerk_home_{label}.png"))

        try:
            do_search(page)
        except Exception as e:
            print(f"  ⚠️  Search action failed: {e}")
            page.screenshot(path=str(CAPTURE / f"clerk_error_{label}.png"))
            page.wait_for_timeout(3000)

        page.wait_for_timeout(5000)
        print(f"  Total after search: {len(requests_log)}")

        page.screenshot(path=str(CAPTURE / f"clerk_after_{label}.png"))
        html = page.content()
        (CAPTURE / f"clerk_after_{label}.html").write_text(html, encoding="utf-8")

        browser.close()

    api_calls = [r for r in requests_log if is_api_url(r["url"])
                 and r.get("resource_type") in ("xhr", "fetch")]
    print(f"\n  🎯 API calls (XHR/fetch):")
    for r in api_calls:
        method = r.get("method", "GET")
        status = r.get("status", "?")
        url = r["url"]
        if len(url) > 130:
            url = url[:130] + "..."
        print(f"    [{method:5s} {status:>3}] {url}")
        if r.get("body_preview"):
            preview = r["body_preview"][:200].replace("\n", " ")
            print(f"           body: {preview}...")

    save = CAPTURE / f"clerk_search_{label}_log.json"
    save.write_text(json.dumps(requests_log, indent=2)[:300000])
    return api_calls


def search_ocs(page):
    """OCS: type name in search box and submit."""
    # Try to find a search field
    page.wait_for_timeout(2000)
    # Try various selectors
    selectors = [
        'input[placeholder*="Search" i]',
        'input[placeholder*="name" i]',
        'input[name*="search" i]',
        'input[type="search"]',
        'input[type="text"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                print(f"  Found search input: {sel}")
                el.fill(TEST_NAME)
                el.press("Enter")
                return
        except Exception:
            continue
    print(f"  ⚠️  No search input found")


def search_officialrecords(page):
    """Official Records: same approach."""
    page.wait_for_timeout(2000)
    # Click a "Standard Search" button if visible
    for label in ("Standard Search", "Search", "Name Search"):
        try:
            btn = page.get_by_text(label, exact=False).first
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(2000)
                break
        except Exception:
            continue

    # Now look for input
    selectors = [
        'input[placeholder*="last" i]',
        'input[name*="last" i]',
        'input[id*="LastName" i]',
        'input[type="text"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(TEST_NAME)
                el.press("Enter")
                return
        except Exception:
            continue


def main() -> int:
    probe_search("ocs",
                 "https://www2.miamidadeclerk.gov/ocs/",
                 search_ocs)
    probe_search("officialrecords",
                 "https://onlineservices.miamidadeclerk.gov/officialrecords/",
                 search_officialrecords)
    print()
    print("Listo. Screenshots en scripts/captures/clerk_*.png")
    return 0


if __name__ == "__main__":
    main()
