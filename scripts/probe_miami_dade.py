"""
Diagnostic probe — investiga los portales de Miami-Dade y reporta qué encuentra.

Correr en TU computadora (no funciona en GitHub Actions sandbox tampoco):

    python -m scripts.probe_miami_dade

Output:
    - Logs detallados a stdout.
    - Guarda HTML capturado en scripts/captures/ para inspección manual.

Cuando termines de correrlo, mandame:
    1. El output completo de stdout.
    2. El contenido de scripts/captures/ (especialmente realauction_calendar.html).
    Con eso ajusto los selectores del parser para que funcione 100%.
"""
from __future__ import annotations

import logging
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

CAPTURES_DIR = Path(__file__).parent / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


def fetch(url: str, label: str) -> str | None:
    """Fetch and save HTML, log status."""
    print(f"\n→ Probing: {label}")
    print(f"  URL: {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2)",
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        print(f"  Status: OK · {len(html)} bytes")
    except Exception as e:
        print(f"  Status: FAILED — {e}")
        return None

    capture_path = CAPTURES_DIR / f"{label}.html"
    capture_path.write_text(html, encoding="utf-8")
    print(f"  Saved: {capture_path}")
    return html


def analyze_html(html: str, label: str) -> None:
    """Quick analysis: title, common selectors, table count, link count."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  (bs4 not installed — skipping analysis)")
        return

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string if soup.title else "(no title)"
    forms = len(soup.find_all("form"))
    tables = len(soup.find_all("table"))
    links = len(soup.find_all("a"))
    inputs = len(soup.find_all("input"))

    has_viewstate = bool(soup.find("input", {"name": "__VIEWSTATE"}))
    has_event_validation = bool(soup.find("input", {"name": "__EVENTVALIDATION"}))

    auction_classes = soup.select(".AUCTION_ITEM")
    even_rows = soup.select("tr.even")
    odd_rows = soup.select("tr.odd")

    print(f"  Title: {title}")
    print(f"  Forms: {forms} · Tables: {tables} · Links: {links} · Inputs: {inputs}")
    print(f"  ASP.NET viewstate: {has_viewstate} · event_validation: {has_event_validation}")
    print(f"  Selector .AUCTION_ITEM: {len(auction_classes)} matches")
    print(f"  Selector tr.even: {len(even_rows)} · tr.odd: {len(odd_rows)} matches")


def main() -> int:
    print("=" * 70)
    print("Miami-Dade Foreclosure Portals — Diagnostic Probe")
    print("=" * 70)

    today = date.today()
    seven_days = today + timedelta(days=7)
    fourteen_days = today + timedelta(days=14)

    targets = [
        # RealAuction calendar (today)
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={today.strftime('%m/%d/%Y')}",
            "realauction_today",
        ),
        # RealAuction calendar (in 7 days — usually has more)
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={seven_days.strftime('%m/%d/%Y')}",
            "realauction_7d",
        ),
        # RealAuction calendar (in 14 days)
        (
            f"https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION"
            f"&Zmethod=PREVIEW&AUCTIONDATE={fourteen_days.strftime('%m/%d/%Y')}",
            "realauction_14d",
        ),
        # Main RealAuction landing — see what root structure looks like
        (
            "https://www.miamidade.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=PREVIEW",
            "realauction_landing",
        ),
        # OCS portal home
        (
            "https://www2.miamidadeclerk.gov/ocs/",
            "ocs_home",
        ),
        # Foreclosure Registry
        (
            "https://bldgappl.miamidade.gov/foreclosureregistry/MainPage.aspx",
            "foreclosure_registry",
        ),
        # Property Appraiser ArcGIS — sanity check it's reachable from your machine
        (
            "https://gisweb.miamidade.gov/arcgis/rest/services/MD_PropertyAppraiser/PropertySearch/FeatureServer/0?f=json",
            "property_appraiser_metadata",
        ),
    ]

    successes = 0
    for url, label in targets:
        html = fetch(url, label)
        if html:
            successes += 1
            if "<html" in html.lower() or "<HTML" in html:
                analyze_html(html, label)

    print()
    print("=" * 70)
    print(f"Summary: {successes}/{len(targets)} endpoints reachable")
    print(f"Captures saved to: {CAPTURES_DIR}")
    print("=" * 70)
    print()
    print("NEXT STEPS:")
    print("  1. Mandá el output de este script + el contenido de scripts/captures/")
    print("     a Samuel/Claude para ajustar los selectores del parser.")
    print("  2. Si todos los endpoints fallaron, probable problema de red local.")
    print("  3. Si solo algunos fallaron, registramos esos como TODO y avanzamos")
    print("     con los que sí responden.")
    return 0 if successes > 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
