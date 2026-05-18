"""
Probe Miami-Dade Clerk OCS for case-type / date-range search.

We currently search ONLY by party name (last name → cases). For pure Lis
Pendens lead generation, we need to search by:
    - Case Type:  "Mortgage/Real Property Foreclosure"
    - Date Filed: last 30-60 days
    - Status:     OPEN

This probe:
    1. Opens OCS Search
    2. Inspects the sidebar / dropdowns to find non-party search modes
    3. Captures every XHR that fires when we change search mode
    4. Saves the requests + a screenshot for analysis

Usage:
    python3 -m scripts.probe_clerk_case_type_search
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise SystemExit("pip3 install playwright --break-system-packages")

CAPTURE = Path(__file__).resolve().parent / "captures"
CAPTURE.mkdir(exist_ok=True)


def main() -> int:
    print("=" * 70)
    print("PROBE: Clerk OCS case-type / date-range search modes")
    print("=" * 70)

    requests_log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            if ("miamidadeclerk.gov" in url
                and ("/api/" in url or "/rest/" in url)
                and resp.request.resource_type in ("xhr", "fetch")):
                entry = {
                    "url": url, "method": resp.request.method,
                    "status": resp.status,
                    "ct": resp.headers.get("content-type", ""),
                }
                if "json" in entry["ct"].lower():
                    try:
                        entry["body_preview"] = resp.text()[:3000]
                    except Exception:
                        pass
                requests_log.append(entry)

        page.on("response", on_response)

        print("\n[1] Opening Clerk OCS Search …")
        page.goto("https://www2.miamidadeclerk.gov/ocs/#/Search",
                  wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(CAPTURE / "clerk_ct_step1_search_home.png"),
                        full_page=True)

        # Discover the search modes available in the left sidebar
        print("\n[2] Discovering search modes …")
        modes_discovered: list[str] = []
        try:
            sidebar_text = page.locator("body").inner_text()
            for candidate in (
                "Case Number", "Party Name", "Citation",
                "Case Type", "Hearing Date", "Filing Date", "Date Filed",
                "Judge", "Court Location", "Real Property",
            ):
                if candidate in sidebar_text:
                    modes_discovered.append(candidate)
        except Exception as e:
            print(f"  couldn't read body text: {e}")
        print(f"  Visible mode labels: {modes_discovered}")

        # Try each mode that's NOT "Party Name" / "Case Number" / "Citation"
        for mode in modes_discovered:
            if mode in ("Party Name", "Case Number", "Citation"):
                continue
            print(f"\n[3] Trying mode: '{mode}' …")
            try:
                page.get_by_text(mode, exact=False).first.click(timeout=5000)
                page.wait_for_timeout(2500)
                safe = mode.lower().replace(" ", "_")
                page.screenshot(
                    path=str(CAPTURE / f"clerk_ct_mode_{safe}.png"),
                    full_page=True,
                )
                # Save the HTML of the form area
                (CAPTURE / f"clerk_ct_mode_{safe}.html").write_text(
                    page.content(), encoding="utf-8",
                )
                # Look for date inputs, case type dropdowns
                inputs = page.evaluate(
                    """
                    () => {
                        const out = [];
                        document.querySelectorAll('input, select').forEach(el => {
                            out.push({
                                tag: el.tagName,
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                placeholder: el.placeholder || '',
                                value: el.value || '',
                            });
                        });
                        return out;
                    }
                    """
                )
                print(f"  → found {len(inputs)} inputs:")
                for inp in inputs[:15]:
                    label_info = (
                        f"id={inp['id'][:30]} "
                        f"name={inp['name'][:20]} "
                        f"type={inp['type']:<10} "
                        f"ph={inp['placeholder'][:30]}"
                    ).strip()
                    print(f"     • {label_info}")
            except Exception as e:
                print(f"  couldn't activate mode {mode!r}: {e}")

        # Save full request log for analysis
        (CAPTURE / "clerk_ct_requests.json").write_text(
            json.dumps(requests_log, indent=2)[:600000]
        )

        print("\n[4] Saved artifacts to scripts/captures/")
        print("    clerk_ct_step1_search_home.png")
        for mode in modes_discovered:
            if mode not in ("Party Name", "Case Number", "Citation"):
                safe = mode.lower().replace(" ", "_")
                print(f"    clerk_ct_mode_{safe}.png + .html")
        print("    clerk_ct_requests.json")

        browser.close()

    print("\n" + "=" * 70)
    print("API CALLS captured (XHR/fetch only):")
    print("=" * 70)
    interesting = [
        r for r in requests_log
        if any(k in r["url"].lower() for k in (
            "casetype", "case_type", "date", "search", "filing", "lookup",
            "dropdown", "options", "metadata",
        ))
    ]
    for r in interesting:
        url = r["url"]
        if len(url) > 130:
            url = url[:130] + "…"
        print(f"  [{r['method']:5s} {r.get('status','?')}] {url}")
        if r.get("body_preview"):
            preview = r["body_preview"][:200].replace("\n", " ")
            print(f"           body: {preview}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
