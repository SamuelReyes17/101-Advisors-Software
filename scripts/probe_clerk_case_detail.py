"""
Probe del endpoint case detail del Clerk de Miami-Dade.

Tenemos los caseIDs de los 41 leads pero solo info básica (number, plaintiff,
status). Para extraer ATTORNEY NAME + PHONE + EMAIL + DOCKET necesitamos
hacer click en el caso y capturar la XHR que dispara.

Estrategia:
    1. Abre OCS en Chrome headless (Playwright)
    2. Search por "BAEZ" → resultados
    3. Click en el primer caso de foreclosure
    4. Captura TODAS las XHR que dispara la página de detalle
    5. Imprime URL + body de cada response JSON

Usage:
    python3 -m scripts.probe_clerk_case_detail
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed. Run: pip3 install playwright --break-system-packages")
    raise SystemExit(1)

CAPTURE = Path(__file__).resolve().parent / "captures"
CAPTURE.mkdir(exist_ok=True)


def is_api_url(url: str) -> bool:
    if any(url.endswith(ext) for ext in
           (".js", ".css", ".png", ".jpg", ".woff", ".woff2", ".svg",
            ".gif", ".ico", ".map", ".html")):
        return False
    return "miamidadeclerk.gov" in url and ("/api/" in url or "/rest/" in url)


def main() -> int:
    print("=" * 70)
    print("PROBE: case detail page on Miami-Dade Clerk OCS")
    print("=" * 70)

    requests_log = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=100)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        def on_request(req):
            requests_log.append({
                "url": req.url, "method": req.method,
                "type": req.resource_type, "phase": "request",
            })

        def on_response(resp):
            for r in requests_log:
                if r["url"] == resp.url and "status" not in r:
                    r["status"] = resp.status
                    r["ct"] = resp.headers.get("content-type", "")
                    if "json" in r["ct"].lower() and is_api_url(resp.url):
                        try:
                            r["body_preview"] = resp.text()[:3000]
                        except Exception:
                            pass
                    break

        page.on("request", on_request)
        page.on("response", on_response)

        # Step 1: Open OCS
        print("\n[1] Opening OCS Search page...")
        page.goto("https://www2.miamidadeclerk.gov/ocs/#/Search",
                  wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Step 2: Click "Party Name"
        try:
            page.get_by_text("Party Name", exact=False).first.click()
            page.wait_for_timeout(2000)
            print("    Party Name option clicked")
        except Exception as e:
            print(f"    couldn't click Party Name: {e}")

        # Step 3: Search "BAEZ"
        print("\n[2] Searching for 'BAEZ'...")
        try:
            last_input = page.locator('input[id*="lastName" i]').first
            last_input.fill("BAEZ")
            page.wait_for_timeout(500)

            with page.expect_response(
                lambda r: "GetMultipleCaseResult" in r.url,
                timeout=15000,
            ) as resp_info:
                page.get_by_role("button", name="Search").first.click()
            resp = resp_info.value
            cases = resp.json().get("caseListResult", [])
            print(f"    Found {len(cases)} cases")
        except Exception as e:
            print(f"    Search failed: {e}")
            browser.close()
            return 1

        page.wait_for_timeout(2000)
        page.screenshot(path=str(CAPTURE / "clerk_detail_step1_results.png"))

        # Step 4: Find a foreclosure case and click it
        print("\n[3] Looking for a foreclosure case to click...")
        clicked_case_id = None
        # We want to click on a case number that's a real estate foreclosure
        # Looking at past data, case numbers tipo 2025-115455-CC-25 (BAEZ family)
        target_case = "2025-115455-CC-25"
        try:
            # The OCS results page renders case numbers as clickable links
            link = page.get_by_text(target_case, exact=True).first
            if link.count() > 0 and link.is_visible():
                print(f"    Clicking case: {target_case}")
                # Snapshot count BEFORE click
                pre_count = len(requests_log)
                link.click()
                page.wait_for_timeout(5000)
                clicked_case_id = target_case
                post_count = len(requests_log)
                print(f"    Requests fired by click: {post_count - pre_count}")
            else:
                print(f"    Target case '{target_case}' not visible — trying any link")
                # Fallback: click first case number-looking link
                any_case = page.locator('a:has-text("-CA-"), a:has-text("-CC-")').first
                if any_case.count() > 0:
                    any_case.click()
                    page.wait_for_timeout(5000)
                    clicked_case_id = "fallback"
        except Exception as e:
            print(f"    couldn't click case: {e}")

        page.screenshot(path=str(CAPTURE / "clerk_detail_step2_detail.png"),
                        full_page=True)
        (CAPTURE / "clerk_detail_page.html").write_text(
            page.content(), encoding="utf-8"
        )

        # Save full log
        (CAPTURE / "clerk_detail_requests.json").write_text(
            json.dumps(requests_log, indent=2)[:500000]
        )

        browser.close()

    # Analyze the requests that fired AFTER the click
    print("\n" + "=" * 70)
    print("ALL API CALLS captured:")
    print("=" * 70)
    api_calls = [r for r in requests_log if is_api_url(r["url"])
                 and r.get("type") in ("xhr", "fetch")]
    for r in api_calls:
        method = r.get("method", "GET")
        status = r.get("status", "?")
        url = r["url"]
        if len(url) > 130:
            url = url[:130] + "..."
        print(f"  [{method:5s} {status:>3}] {url}")
        if r.get("body_preview"):
            preview = r["body_preview"][:250].replace("\n", " ")
            print(f"           body: {preview}")

    # Highlight the most likely detail endpoints
    print("\n" + "=" * 70)
    print("CASE DETAIL endpoint candidates (URLs after the click):")
    print("=" * 70)
    detail_calls = [r for r in api_calls
                    if any(k in r["url"].lower()
                           for k in ("getsinglecase", "casedetail", "casedocket",
                                     "caseparties", "caseinfo/get", "case/"))]
    for r in detail_calls:
        print(f"  [{r.get('method','GET')}] {r['url']}")
        if r.get("body_preview"):
            print(f"     {r['body_preview'][:400]}")
            print()

    return 0


if __name__ == "__main__":
    main()
