"""
Miami-Dade Clerk — Foreclosure & Lis Pendens collectors.

DESCUBRIMIENTO de leads (no enriquecimiento).

Fuentes posibles para foreclosure data:

    A) Online Foreclosure Auction (RealAuction platform)
        URL: https://www.miamidade.realforeclose.com/
        Pros: estructurado, lista de auctions próximas con address + case #.
        Cons: solo cubre las que ya llegaron a subasta (etapa final del foreclosure).
        Estado: ESTE archivo implementa A.

    B) Online Case Search (OCS)
        URL: https://www2.miamidadeclerk.gov/ocs/
        Pros: cubre TODAS las foreclosures (Lis Pendens + casos en proceso).
        Cons: portal ASP.NET con querystrings encriptados. Scraping complejo.
        Estado: TODO — usar B para Lis Pendens.

    C) Foreclosure Registry (Building Department ordinance)
        URL: https://bldgappl.miamidade.gov/foreclosureregistry/
        Pros: estructurado.
        Cons: solo lenders que cumplen con la ordinance se registran. Subset.
        Estado: opcional, fallback.

NOTA SOBRE VALIDACIÓN:
    El portal RealAuction usa estructura HTML que puede cambiar. Antes de confiar
    en datos del cron, corré `python -m scripts.probe_miami_dade` para verificar
    que los selectores siguen funcionando.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Iterable

from .base import Collector, Lead

log = logging.getLogger(__name__)


# =========================================================================
# (A) Foreclosure auctions via RealAuction
# =========================================================================

REALAUCTION_BASE = "https://www.miamidade.realforeclose.com"
REALAUCTION_CALENDAR = f"{REALAUCTION_BASE}/index.cfm?zaction=AUCTION&Zmethod=PREVIEW"


def _http_get(url: str, timeout: int = 20) -> str:
    """Fetch a URL and return the response body. Raises on HTTP errors."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; 101AdvisorsBot/0.2; "
                "+https://github.com/SamuelReyes17/101-Advisors-Software)"
            ),
            "Accept": "text/html,application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_realauction_calendar(days_ahead: int = 30) -> list[dict]:
    """Pull upcoming foreclosure auctions from the Miami-Dade RealAuction site.

    Returns a list of dicts with:
        case_number, sale_date, property_address, opening_bid, parcel_id

    The structure of the calendar page is:
        - Top-level page lists dates with scheduled auctions.
        - Click a date → list of auctions for that date.
        - Each auction has property details inline or in a detail page.

    This implementation walks the calendar for the next `days_ahead` days.
    """
    try:
        from bs4 import BeautifulSoup  # imported here so a missing dep doesn't crash imports
    except ImportError:
        log.error(
            "beautifulsoup4 not installed. Add it to requirements.txt and "
            "`pip install -r requirements.txt`."
        )
        return []

    out: list[dict] = []
    today = date.today()

    for delta in range(days_ahead):
        target = today + timedelta(days=delta)
        url = (
            f"{REALAUCTION_BASE}/index.cfm?zaction=AUCTION&Zmethod=PREVIEW"
            f"&AUCTIONDATE={target.strftime('%m/%d/%Y')}"
        )
        try:
            html = _http_get(url)
        except Exception as e:
            log.warning("Could not fetch %s: %s", url, e)
            continue

        soup = BeautifulSoup(html, "lxml")

        # The auction list table on RealAuction sites typically has rows with class
        # "AUCTION_ITEM" or contains links labeled "Details". Both patterns covered.
        items = soup.select(".AUCTION_ITEM") or soup.select("tr.even, tr.odd")
        for item in items:
            try:
                parsed = _parse_realauction_row(item, target)
                if parsed:
                    out.append(parsed)
            except Exception as e:
                log.debug("Skipping unparseable row: %s", e)
                continue

    log.info("RealAuction calendar: found %d auctions in next %d days", len(out), days_ahead)
    return out


def _parse_realauction_row(item, sale_date: date) -> dict | None:
    """Best-effort parse of a single auction row.

    Different RealAuction-powered counties use slightly different layouts.
    This handles the most common patterns; if parsing fails, we log and skip.
    """
    text = item.get_text(" ", strip=True)

    # Case number (Florida format e.g. "2024-CA-012345")
    case_match = re.search(r"\b\d{4}[-\s]?(?:CA|CC)[-\s]?\d{5,8}\b", text)
    case_number = case_match.group(0).replace(" ", "-") if case_match else ""

    # Address — heuristic: first sequence of "<digits> <words>" before the city.
    # Case-insensitive to handle "92nd Ave" etc.
    addr_match = re.search(
        r"(\d{1,6}\s+[A-Za-z0-9 .,#-]+?(?:ST|AVE|RD|BLVD|DR|CT|PL|LN|WAY|TER|HWY|CIR)\b[^,]*)",
        text,
        re.IGNORECASE,
    )
    address = addr_match.group(1).strip() if addr_match else ""

    # Opening bid
    bid_match = re.search(r"\$([0-9,]+(?:\.\d{2})?)", text)
    opening_bid = float(bid_match.group(1).replace(",", "")) if bid_match else 0.0

    # Parcel/folio if present
    folio_match = re.search(r"\b(\d{2}[-\s]?\d{4}[-\s]?\d{3}[-\s]?\d{4})\b", text)
    parcel_id = folio_match.group(1).replace(" ", "-") if folio_match else ""

    if not (case_number or address):
        return None

    return {
        "case_number": case_number,
        "sale_date": sale_date.isoformat(),
        "property_address": address,
        "opening_bid": opening_bid,
        "parcel_id": parcel_id,
    }


def _split_address(full: str) -> tuple[str, str, str]:
    """Split a "123 Main St, Miami FL 33136" string into (street, city, zip)."""
    if "," in full:
        street, rest = full.split(",", 1)
        rest = rest.strip()
        zip_match = re.search(r"\b(\d{5})\b", rest)
        zip_code = zip_match.group(1) if zip_match else ""
        city = re.sub(r"\b(FL|FLORIDA)\b.*$", "", rest, flags=re.I).strip()
        return street.strip(), city, zip_code
    return full.strip(), "", ""


# =========================================================================
# Collector wrappers
# =========================================================================

class MiamiDadeForeclosureCollector(Collector):
    """Discover Miami-Dade foreclosure auctions scheduled in the next 30 days."""

    name = "miami_dade_foreclosure"
    county = "Miami-Dade"
    category = "Foreclosure"

    def fetch(self) -> Iterable[Lead]:
        log.info("MiamiDadeForeclosureCollector starting...")
        rows = fetch_realauction_calendar(days_ahead=30)
        if not rows:
            log.warning(
                "No auctions returned. This could mean: (a) no auctions in the "
                "next 30 days, (b) the RealAuction HTML structure changed and "
                "the parser needs an update. Run scripts/probe_miami_dade.py "
                "to investigate."
            )
            return

        today = date.today()
        for row in rows:
            street, city, zip_code = _split_address(row["property_address"])
            if not street:
                continue

            lead_id = f"MDF-{row['case_number']}" if row["case_number"] else f"MDF-{row['sale_date']}-{abs(hash(street)) % 100000}"

            yield Lead(
                lead_id=lead_id,
                first_seen=today,
                last_updated=today,
                county=self.county,
                category=self.category,
                property_address=street,
                city=city or "Miami",
                zip=zip_code,
                folio=row.get("parcel_id", ""),
                outstanding_debt=row.get("opening_bid", 0.0),
                notes=f"Auction date: {row['sale_date']} · Case: {row['case_number']}",
                source=self.name,
            )


class MiamiDadeLisPendensCollector(Collector):
    """Discover newly-filed Lis Pendens via Miami-Dade OCS portal.

    TODO: implement OCS portal scraping. The portal uses ASP.NET WebForms
    with __VIEWSTATE — needs a session cookie + form POST. Park until OCS
    investigation is complete (run scripts/probe_miami_dade.py).
    """

    name = "miami_dade_lispendens"
    county = "Miami-Dade"
    category = "Lis Pendens"

    def fetch(self) -> Iterable[Lead]:
        log.warning("MiamiDadeLisPendensCollector still STUB — see TODO.")
        return
        yield  # noqa


class MiamiDadeProbateCollector(Collector):
    """Discover newly-filed probate cases. STUB pending OCS implementation."""

    name = "miami_dade_probate"
    county = "Miami-Dade"
    category = "Probate"

    def fetch(self) -> Iterable[Lead]:
        log.warning("MiamiDadeProbateCollector still STUB — see TODO.")
        return
        yield  # noqa
