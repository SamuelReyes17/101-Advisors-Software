"""
Deep probe of Miami-Dade Clerk OCS — navigate THROUGH the SPA to find the
real search form and the API endpoints it fires.

The previous probe failed because the search input isn't on the home page.
The OCS uses Angular hash-routing — the search lives at `/#/Search` or
`/#/Cases`. This probe navigates there explicitly, takes screenshots at
each step, dumps the rendered DOM, and tries to find the search form.

After running this, we'll know:
    - The exact URL for case search
    - The DOM selectors for Last Name / First Name fields
    - The API endpoint the search fires (e.g., /api/search/cases)
    - The shape of the response JSON

Usage:
    python3 -m scripts.probe_clerk_v2
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright not installed. Run: pip3 install playwright --break-system-packages")
    print("                                  playwright install chromium")
    raise SystemExit(1)

CAPTURE = Path(__file__).resolve().parent / "captures"
CAPTURE.mkdir(exist_ok=True)

TEST_LAST_NAME = "BAEZ"

# Routes to try inside the OCS SPA. Angular hash-routes; #/Search is the most common.
ROUTES = [
    "https://www2.miamidadeclerk.gov/ocs/#/Search",
    "https://www2.miamidadeclerk.gov/ocs/#/PartySearch",
    "https://www2.miamidadeclerk.gov/ocs/#/NameSearch",
    "https://www2.miamidadeclerk.gov/ocs/#/CaseSearch",
]


def is_api(url: str) -> bool:
    if any(url.endswith(ext) for ext in
           (".js", ".css", ".png", ".jpg", ".woff", ".woff2", ".svg",
            ".gif", ".ico", ".map", ".html")):
        return False
    return any(h in url for h in ("clerk.gov", "miamidade.gov", "/api/", "/rest/"))


def probe_url(url: str, label: str) -> dict:
    print(f"\n{'═' * 70}")
    print(f"PROBE: {label}")
    print(f"URL:   {url}")
    print(f"{'═' * 70}")

    log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        def on_request(req):
            log.append({"url": req.url, "method": req.method, "type": req.resource_type})

        def on_response(resp):
            for r in log:
                if r["url"] == resp.url and "status" not in r:
                    r["status"] = resp.status
                    r["content_type"] = resp.headers.get("content-type", "")
                    if "json" in r["content_type"].lower() and is_api(resp.url):
                        try:
                            body = resp.text()[:2000]
                            r["body_preview"] = body
                        except Exception:
                            pass
                    break

        page.on("request", on_request)
        page.on("response", on_response)

        # Step 1: go to URL
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  ⚠️  Initial load: {e}")

        page.wait_for_timeout(4000)
        page.screenshot(path=str(CAPTURE / f"clerk_v2_{label}_step1.png"), full_page=True)

        # Print page title + URL
        print(f"\n  Page title: {page.title()}")
        print(f"  Final URL:  {page.url}")

        # Try to find all form inputs on the page
        print(f"\n  🔍 Looking for form inputs...")
        inputs = page.query_selector_all('input, select, textarea')
        print(f"  Found {len(inputs)} input elements")

        # Detail visible inputs
        visible_inputs = []
        for i, inp in enumerate(inputs):
            try:
                if not inp.is_visible():
                    continue
                attrs = page.evaluate("""(el) => ({
                    type: el.type,
                    name: el.name,
                    id: el.id,
                    placeholder: el.placeholder,
                    ariaLabel: el.getAttribute('aria-label'),
                    formcontrolname: el.getAttribute('formcontrolname'),
                })""", inp)
                visible_inputs.append(attrs)
            except Exception:
                pass

        print(f"  Visible inputs ({len(visible_inputs)}):")
        for i, attrs in enumerate(visible_inputs):
            info = {k: v for k, v in attrs.items() if v}
            print(f"    [{i}] {info}")

        # Look for buttons/links labeled "Search" or "Name"
        print(f"\n  🔍 Looking for buttons/links with 'Search', 'Name', 'Party'...")
        for keyword in ("Search Cases", "Name Search", "Party Search", "Search by Name",
                        "Search", "Party"):
            try:
                els = page.get_by_text(keyword, exact=False).all()
                visible = [e for e in els if e.is_visible()]
                if visible:
                    print(f"    '{keyword}': {len(visible)} visible matches")
                    for el in visible[:3]:
                        text = el.inner_text()[:60]
                        tag = el.evaluate("el => el.tagName")
                        print(f"      <{tag}> {text}")
            except Exception:
                pass

        # Save full HTML
        (CAPTURE / f"clerk_v2_{label}_step1.html").write_text(
            page.content(), encoding="utf-8"
        )

        # Step 2: try to click on something that looks like "Search Cases" / "Name Search"
        for click_target in ("Name Search", "Search Cases", "Party Name", "Search by Party"):
            try:
                btn = page.get_by_text(click_target, exact=False).first
                if btn and btn.is_visible():
                    print(f"\n  🖱️  Clicking: '{click_target}'")
                    btn.click()
                    page.wait_for_timeout(3000)
                    page.screenshot(path=str(CAPTURE / f"clerk_v2_{label}_afterclick.png"),
                                    full_page=True)
                    print(f"  After click: {page.url}")
                    break
            except Exception as e:
                pass

        # Step 3: try to type into the most likely Last Name field
        page.wait_for_timeout(2000)
        last_name_selectors = [
            'input[placeholder*="Last" i]',
            'input[aria-label*="Last" i]',
            'input[formcontrolname*="last" i]',
            'input[id*="lastName" i]',
            'input[name*="lastName" i]',
            'input[name*="LastName" i]',
            'input[id*="LName" i]',
        ]
        last_name_input = None
        for sel in last_name_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    last_name_input = el
                    print(f"\n  ✅ Found Last Name input: {sel}")
                    break
            except Exception:
                pass

        if last_name_input:
            try:
                last_name_input.fill(TEST_LAST_NAME)
                page.wait_for_timeout(1000)
                page.screenshot(path=str(CAPTURE / f"clerk_v2_{label}_typed.png"),
                                full_page=True)

                # Find a Submit / Search button
                for label_txt in ("Search", "Find", "Submit", "Go"):
                    try:
                        btn = page.get_by_role("button", name=label_txt).first
                        if btn and btn.is_visible():
                            print(f"  🖱️  Clicking submit button: '{label_txt}'")
                            btn.click()
                            break
                    except Exception:
                        pass
                else:
                    # Fallback: press Enter
                    last_name_input.press("Enter")
                    print(f"  🖱️  Pressed Enter on last name input")

                page.wait_for_timeout(5000)
                page.screenshot(path=str(CAPTURE / f"clerk_v2_{label}_results.png"),
                                full_page=True)
                (CAPTURE / f"clerk_v2_{label}_results.html").write_text(
                    page.content(), encoding="utf-8"
                )
            except Exception as e:
                print(f"  ⚠️  Search submission: {e}")
        else:
            print(f"\n  ❌ No Last Name input found on this page")

        browser.close()

    # Filter API requests
    api_calls = [r for r in log if is_api(r["url"])
                 and r.get("type") in ("xhr", "fetch")]
    print(f"\n  📡 API calls captured: {len(api_calls)}")
    for r in api_calls:
        method = r.get("method", "GET")
        status = r.get("status", "?")
        url = r["url"]
        if len(url) > 130:
            url = url[:130] + "..."
        print(f"    [{method:5s} {status:>3}] {url}")
        if r.get("body_preview"):
            print(f"           body: {r['body_preview'][:200]}")

    # Save full log
    (CAPTURE / f"clerk_v2_{label}_log.json").write_text(
        json.dumps(log, indent=2)[:300000]
    )

    return {"label": label, "api_calls": api_calls}


def main() -> int:
    print("=" * 70)
    print("Miami-Dade Clerk OCS — deep probe with navigation")
    print("=" * 70)
    print(f"Test last name: {TEST_LAST_NAME}")

    results = []
    for url in ROUTES:
        label = url.split("#/")[-1].lower()
        try:
            results.append(probe_url(url, label))
        except Exception as e:
            print(f"\n❌ {url}: {e}")

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        print(f"\n{r['label']}: {len(r['api_calls'])} API calls")
        # Find search-related calls
        search_calls = [c for c in r["api_calls"]
                        if any(kw in c["url"].lower()
                               for kw in ("/search", "/party", "/case", "/name", "/find"))]
        if search_calls:
            print("  🎯 Search-related endpoints:")
            for c in search_calls:
                print(f"     [{c.get('method','GET')}] {c['url']}")
    print()
    print("Mirá las screenshots en scripts/captures/clerk_v2_*.png")
    return 0


if __name__ == "__main__":
    main()
