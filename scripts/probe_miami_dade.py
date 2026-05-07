"""
Diagnostic probe — investiga los portales de Miami-Dade y reporta qué encuentra.

Correr en TU computadora:

    python3 -m scripts.probe_miami_dade

Si ves errores SSL (CERTIFICATE_VERIFY_FAILED), primero probá:

    /Applications/Python\\ 3.12/Install\\ Certificates.command
    pip3 install --upgrade certifi

Como ÚLTIMO RECURSO (solo para testing, no para producción), corré:

    python3 -m scripts.probe_miami_dade --insecure

Output:
    - Logs detallados a stdout.
    - Guarda HTML capturado en scripts/captures/ para inspección manual.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

CAPTURES_DIR = Path(__file__).parent / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


def fetch(url: str, label: str, verify_ssl: bool = True) -> str | None:
    """Fetch using requests (preferred, more robust than urllib for SSL)."""
    print(f"\n→ Probing: {label}")
    print(f"  URL: {url}")

    try:
        import requests
    except ImportError:
        print("  ERROR: 'requests' not installed. Run: pip3 install requests")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20, verify=verify_ssl)
        html = resp.text
        print(f"  Status: HTTP {resp.status_code} · {len(html)} bytes")
        if resp.status_code >= 400:
            print(f"  WARN: non-2xx response (might still have useful HTML)")
    except Exception as e:
        print(f"  Status: FAILED — {e}")
        return None

    capture_path = CAPTURES_DIR / f"{label}.html"
    capture_path.write_text(html, encoding="utf-8")
    print(f"  Saved: {capture_path}")
    return html


def analyze_html(html: str, label: str) -> None:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  (bs4 not installed — skipping analysis)")
        return

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else "(no title)"
    forms = len(soup.find_all("form"))
    tables = len(soup.find_all("table"))
    links = len(soup.find_all("a"))
    inputs = len(soup.find_all("input"))

    has_viewstate = bool(soup.find("input", {"name": "__VIEWSTATE"}))
    has_event_validation = bool(soup.find("input", {"name": "__EVENTVALIDATION"}))

    auction_classes = soup.select(".AUCTION_ITEM")
    even_rows = soup.select("tr.even")
    odd_rows = soup.select("tr.odd")
    grid_rows = soup.select("[class*='Grid'], [class*='auction'], [class*='listing']")

    print(f"  Title: {title}")
    print(f"  Forms: {forms} · Tables: {tables} · Links: {links} · Inputs: {inputs}")
    print(f"  ASP.NET viewstate: {has_viewstate} · event_validation: {has_event_validation}")
    print(f"  Selector .AUCTION_ITEM: {len(auction_classes)} matches")
    print(f"  Selector tr.even / tr.odd: {len(even_rows)} / {len(odd_rows)}")
    print(f"  Selector [class*='Grid|auction|listing']: {len(grid_rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostic probe for Miami-Dade portals")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip SSL certificate verification (testing only, NOT for production).",
    )
    args = parser.parse_args()

    if args.insecure:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("⚠️  Running with --insecure (SSL verification disabled).")

    print("=" * 70)
    print("Miami-Dade Foreclosure Portals — Diagnostic Probe")
    print("=" * 70)

    today = date.today()
    seven_days = today + timedelta(days=7)
    fourteen_days = today + timedelta(days=14)

    targets = [
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={today.strftime('%m/%d/%Y')}",
            "realauction_today",
        ),
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={seven_days.strftime('%m/%d/%Y')}",
            "realauction_7d",
        ),
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={fourteen_days.strftime('%m/%d/%Y')}",
            "realauction_14d",
        ),
        (
            "https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=PREVIEW",
            "realauction_landing",
        ),
        (
            "https://www2.miamidadeclerk.gov/ocs/",
            "ocs_home",
        ),
        (
            "https://bldgappl.miamidade.gov/foreclosureregistry/MainPage.aspx",
            "foreclosure_registry",
        ),
        (
            "https://gisweb.miamidade.gov/arcgis/rest/services/MD_PropertyAppraiser/PropertySearch/FeatureServer/0?f=json",
            "property_appraiser_metadata",
        ),
    ]

    successes = 0
    for url, label in targets:
        html = fetch(url, label, verify_ssl=not args.insecure)
        if html:
            successes += 1
            if "<html" in html.lower():
                analyze_html(html, label)

    print()
    print("=" * 70)
    print(f"Summary: {successes}/{len(targets)} endpoints reachable")
    print(f"Captures saved to: {CAPTURES_DIR}")
    print("=" * 70)

    if successes == 0:
        print()
        print("Todos los endpoints fallaron. Causas comunes:")
        print("  • Certificados SSL no instalados (clásico en Python Mac):")
        print("      /Applications/Python\\ 3.12/Install\\ Certificates.command")
        print("      pip3 install --upgrade certifi")
        print("  • Firewall corporativo o VPN intercepta SSL — probá con hotspot del celular.")
        print("  • Como último recurso para testing:")
        print("      python3 -m scripts.probe_miami_dade --insecure")

    return 0 if successes > 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
