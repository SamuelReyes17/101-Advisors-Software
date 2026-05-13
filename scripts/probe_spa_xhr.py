"""
Capture XHR / fetch calls made by Miami-Dade Tax Collector + Clerk SPAs.

When a React/Angular SPA loads, it fires AJAX calls to the underlying REST
API. By capturing those calls in a real browser, we discover the endpoints
to use directly with `requests` later (no browser required for production).

Strategy:
    1. Open Playwright Chromium (headless)
    2. Navigate to PA/Clerk page with our test folio/owner
    3. Listen to network: capture every URL contacted during load
    4. Wait ~5s for SPA to settle
    5. Save HTML + XHR list per page

Setup:
    pip install playwright --break-system-packages
    playwright install chromium

Usage:
    python3 -m scripts.probe_spa_xhr
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright no está instalado. Corré primero:")
    print("   pip3 install playwright --break-system-packages")
    print("   playwright install chromium")
    raise SystemExit(1)

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

TEST_FOLIO = "0141160040250"
TEST_OWNER = "EDUARDO BAEZ"

# URLs que queremos investigar
TARGETS = [
    {
        "label": "pa_spa_property",
        "url": f"https://www.miamidade.gov/Apps/PA/PropertySearch/#/?folio={TEST_FOLIO}",
        "wait_ms": 8000,
    },
    {
        "label": "pa_apps_spa",
        "url": f"https://apps.miamidadepa.gov/propertysearch/#/property?folio={TEST_FOLIO}",
        "wait_ms": 8000,
    },
    {
        "label": "clerk_ocs",
        "url": "https://www2.miamidadeclerk.gov/ocs/",
        "wait_ms": 6000,
    },
    {
        "label": "clerk_officialrecords",
        "url": "https://onlineservices.miamidadeclerk.gov/officialrecords/",
        "wait_ms": 6000,
    },
]


def is_interesting_url(url: str) -> bool:
    """Filter out static asset URLs; keep API-looking calls."""
    if any(url.endswith(ext) for ext in (".js", ".css", ".png", ".jpg", ".woff",
                                          ".woff2", ".svg", ".gif", ".ico",
                                          ".map", ".eot", ".ttf")):
        return False
    if any(host in url for host in ("googletagmanager", "google-analytics",
                                     "googleapis", "cloudflare", "doubleclick",
                                     "facebook.com", "ruxit", "dynatrace")):
        return False
    return True


def probe_page(label: str, url: str, wait_ms: int) -> dict:
    print(f"\n{'─' * 70}")
    print(f"PROBING: {label}")
    print(f"URL: {url}")
    print(f"{'─' * 70}")

    requests_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0 Safari/537.36"),
        )
        page = ctx.new_page()

        def on_request(req):
            try:
                requests_log.append({
                    "url": req.url,
                    "method": req.method,
                    "resource_type": req.resource_type,
                })
            except Exception:
                pass

        def on_response(resp):
            try:
                # Update log entry with status
                for r in requests_log:
                    if r["url"] == resp.url and "status" not in r:
                        r["status"] = resp.status
                        r["content_type"] = resp.headers.get("content-type", "")
                        break
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  ⚠️  Page load: {e}")

        # Extra wait for SPA to finish AJAX
        page.wait_for_timeout(wait_ms)

        html = page.content()
        save_html = CAPTURE_DIR / f"spa_{label}.html"
        save_html.write_text(html, encoding="utf-8")

        # Screenshot for visual reference
        save_png = CAPTURE_DIR / f"spa_{label}.png"
        page.screenshot(path=str(save_png), full_page=True)

        browser.close()

    # Filter for interesting URLs
    api_calls = [r for r in requests_log
                 if is_interesting_url(r["url"]) and r.get("resource_type") in ("xhr", "fetch")]
    other_interesting = [r for r in requests_log
                          if is_interesting_url(r["url"])
                          and r.get("resource_type") not in ("xhr", "fetch", "document")]

    print(f"\n  Total requests: {len(requests_log)}")
    print(f"  XHR/fetch (interesting): {len(api_calls)}")
    print(f"  📸 Saved: {save_html.name}, {save_png.name}")

    print(f"\n  🎯 XHR / API calls captured:")
    for r in api_calls[:30]:
        method = r.get("method", "GET")
        status = r.get("status", "?")
        ct = (r.get("content_type") or "")[:30]
        url = r["url"]
        if len(url) > 110:
            url = url[:110] + "..."
        print(f"    [{method:4s} {status:>3}] {url}")
        if ct:
            print(f"           {ct}")

    if other_interesting:
        print(f"\n  Other non-document URLs:")
        for r in other_interesting[:10]:
            print(f"    [{r['resource_type']}] {r['url'][:100]}")

    # Save full log as JSON
    save_json = CAPTURE_DIR / f"spa_{label}_requests.json"
    save_json.write_text(json.dumps(requests_log, indent=2)[:200000])

    return {
        "label": label,
        "total_requests": len(requests_log),
        "api_calls": api_calls,
    }


def main() -> int:
    print("=" * 70)
    print("XHR capture — Miami-Dade Tax + Clerk SPAs")
    print("=" * 70)
    print(f"Test folio: {TEST_FOLIO}")
    print(f"Test owner: {TEST_OWNER}")

    results = []
    for target in TARGETS:
        try:
            results.append(probe_page(target["label"], target["url"], target["wait_ms"]))
        except Exception as e:
            print(f"\n❌ {target['label']}: {e}")

    print()
    print("=" * 70)
    print("Resumen — endpoints API descubiertos por SPA:")
    print("=" * 70)
    for r in results:
        unique_hosts = sorted(set(
            re.match(r"https?://([^/]+)", c["url"]).group(1)
            for c in r["api_calls"]
        ))
        print(f"\n📄 {r['label']}: {len(r['api_calls'])} API calls")
        for host in unique_hosts:
            print(f"   → {host}")

    print()
    print("Si ves URLs tipo /api/... o /rest/services/... en los API calls,")
    print("esas son las que podemos usar con `requests` directo (sin browser).")
    return 0


if __name__ == "__main__":
    main()
