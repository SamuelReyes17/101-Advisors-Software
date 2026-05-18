"""
OneHome (Miami Realtors) auto-email parser.

These emails come from SEF MLS saved searches but in the OneHome consumer-portal
format (not the classic Matrix Agent format that has CSV export). Each email
contains a list of listings shown as cards with: photo, price, property type,
address, beds/baths/sqft, MLS#, and a status tag (New Listing, Back on Market,
Price Reduced, etc.).

The parser handles both:
    - .eml files  (raw RFC822 with HTML part embedded) — preferred
    - .html files (saved via Cmd+S "Save Page As") — fallback

Usage:
    from pipeline.collectors.onehome_email import parse_onehome_file

    leads = parse_onehome_file("scripts/captures/onehome_sample.eml",
                                category="Foreclosure")
    # leads is a list of Lead dataclass instances

Category determination order:
    1. Explicit `category` arg
    2. Inferred from email subject keywords (Foreclosure / Auction / Short Sale / REO)
    3. Default to "Foreclosure" with a warning
"""
from __future__ import annotations

import email
import logging
import re
from dataclasses import replace
from datetime import date
from email.header import decode_header
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

from .base import Lead

log = logging.getLogger(__name__)

# Florida counties — used to bucket addresses
COUNTY_BY_CITY = {
    # Miami-Dade (sample — extend as needed)
    "MIAMI": "Miami-Dade", "MIAMI BEACH": "Miami-Dade",
    "MIAMI GARDENS": "Miami-Dade", "MIAMI LAKES": "Miami-Dade",
    "MIAMI SHORES": "Miami-Dade", "MIAMI SPRINGS": "Miami-Dade",
    "NORTH MIAMI": "Miami-Dade", "NORTH MIAMI BEACH": "Miami-Dade",
    "HIALEAH": "Miami-Dade", "HIALEAH GARDENS": "Miami-Dade",
    "HOMESTEAD": "Miami-Dade", "CUTLER BAY": "Miami-Dade",
    "PALMETTO BAY": "Miami-Dade", "PINECREST": "Miami-Dade",
    "AVENTURA": "Miami-Dade", "SUNNY ISLES BEACH": "Miami-Dade",
    "DORAL": "Miami-Dade", "KEY BISCAYNE": "Miami-Dade",
    "OPA LOCKA": "Miami-Dade", "OPA-LOCKA": "Miami-Dade",
    "CORAL GABLES": "Miami-Dade", "SOUTH MIAMI": "Miami-Dade",
    "SWEETWATER": "Miami-Dade", "WEST MIAMI": "Miami-Dade",
    "FLORIDA CITY": "Miami-Dade", "BAY HARBOR ISLANDS": "Miami-Dade",
    "BAL HARBOUR": "Miami-Dade", "SURFSIDE": "Miami-Dade",
    "VIRGINIA GARDENS": "Miami-Dade", "MEDLEY": "Miami-Dade",
    "INDIAN CREEK": "Miami-Dade", "UNINCORPORATED COUNTY": "Miami-Dade",
    # Broward
    "FORT LAUDERDALE": "Broward", "HOLLYWOOD": "Broward",
    "PEMBROKE PINES": "Broward", "PEMBROKE PARK": "Broward",
    "MIRAMAR": "Broward", "DAVIE": "Broward", "PLANTATION": "Broward",
    "SUNRISE": "Broward", "WESTON": "Broward", "TAMARAC": "Broward",
    "MARGATE": "Broward", "COCONUT CREEK": "Broward",
    "POMPANO BEACH": "Broward", "DEERFIELD BEACH": "Broward",
    "OAKLAND PARK": "Broward", "WILTON MANORS": "Broward",
    "LAUDERHILL": "Broward", "LAUDERDALE LAKES": "Broward",
    "NORTH LAUDERDALE": "Broward", "COOPER CITY": "Broward",
    "CORAL SPRINGS": "Broward", "PARKLAND": "Broward",
    "DANIA BEACH": "Broward", "HALLANDALE BEACH": "Broward",
    "HILLSBORO BEACH": "Broward", "LIGHTHOUSE POINT": "Broward",
    "SOUTHWEST RANCHES": "Broward",
    # Palm Beach
    "WEST PALM BEACH": "Palm Beach", "PALM BEACH": "Palm Beach",
    "PALM BEACH GARDENS": "Palm Beach", "BOCA RATON": "Palm Beach",
    "BOYNTON BEACH": "Palm Beach", "DELRAY BEACH": "Palm Beach",
    "JUPITER": "Palm Beach", "LAKE WORTH": "Palm Beach",
    "LAKE WORTH BEACH": "Palm Beach", "RIVIERA BEACH": "Palm Beach",
    "WELLINGTON": "Palm Beach", "ROYAL PALM BEACH": "Palm Beach",
    "GREENACRES": "Palm Beach", "LANTANA": "Palm Beach",
    "TEQUESTA": "Palm Beach", "JUNO BEACH": "Palm Beach",
    "MANALAPAN": "Palm Beach", "GULF STREAM": "Palm Beach",
    "OCEAN RIDGE": "Palm Beach", "HIGHLAND BEACH": "Palm Beach",
    "PALM SPRINGS": "Palm Beach", "ATLANTIS": "Palm Beach",
    "HAVERHILL": "Palm Beach", "BELLE GLADE": "Palm Beach",
    "PAHOKEE": "Palm Beach", "SOUTH BAY": "Palm Beach",
    "JUPITER FARMS": "Palm Beach", "JUPITER ISLAND": "Palm Beach",
    "LOXAHATCHEE": "Palm Beach", "LOXAHATCHEE GROVES": "Palm Beach",
    "NORTH PALM BEACH": "Palm Beach",
}

# Map saved-search keywords in the subject to our Leon category
CATEGORY_BY_SUBJECT_KW = (
    ("LIS PENDENS",   "Lis Pendens"),
    ("FORECLOSUR",    "Foreclosure"),   # Foreclosure / Foreclosures
    ("REO",           "Foreclosure"),
    ("AUCTION",       "Auction"),
    ("SHORT SALE",    "Short Sale"),
    ("PROBATE",       "Probate"),
)

# Status tag → standard label  (we keep raw too)
STATUS_TAGS_OF_INTEREST = {
    "NEW LISTING",
    "BACK ON MARKET",
    "PRICE REDUCED", "PRICE DROP", "PRICE CHANGE",
    "UNDER CONTRACT", "ACTIVE", "FORECLOSURE", "SHORT SALE",
    "AUCTION", "REO", "BANK OWNED",
}

# ── Regexes for the in-card text patterns observed in OneHome cards ─────
PRICE_RE       = re.compile(r"\$\s?([0-9][\d,]*)")
MLS_RE         = re.compile(r"MLS\s*#\s*([A-Z][0-9]+)", re.IGNORECASE)
BED_BATH_RE    = re.compile(
    r"(\d+)\s*bd\s*[·\.\-•]\s*(\d+)\s*(?:\(\d+(?:\s*\d+)?\))?\s*ba\s*[·\.\-•]\s*([\d,]+)\s*sqft",
    re.IGNORECASE,
)
# Florida address ZIP — 5 digits
CITY_STATE_ZIP_RE = re.compile(
    r"([A-Za-z .\-]+),\s*(FL)\s*(\d{5})", re.IGNORECASE
)
# Property type keywords (the OneHome cards spell these out in their own row)
TYPE_KEYWORDS = (
    "Single Family", "Townhouse", "Townhome", "Condo", "Condominium",
    "Multi Family", "Multi-Family", "Duplex", "Triplex", "Fourplex",
    "Apartment", "Villa", "Land", "Lot", "Mobile Home",
)
STATUS_KEYWORDS = (
    "Back on Market", "New Listing", "Price Reduced", "Price Drop",
    "Price Change", "Active", "Foreclosure", "Short Sale", "Auction",
    "REO", "Bank Owned", "Pending", "Under Contract",
)


# =========================================================================
# Email loading
# =========================================================================
def _decode_header_safe(raw: str | None) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(chunk.decode("latin-1", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


def _load_email_html(path: Path) -> tuple[str, dict]:
    """Return (html_body, meta) where meta has subject, from, date.

    Accepts .eml or .html. For .html, meta is empty (no headers).
    """
    raw = path.read_bytes()
    suffix = path.suffix.lower()

    if suffix == ".eml" or raw.lstrip().startswith(b"From ") or b"\nFrom:" in raw[:2000]:
        # Treat as RFC822 message
        msg = email.message_from_bytes(raw)
        subject = _decode_header_safe(msg.get("Subject"))
        from_   = _decode_header_safe(msg.get("From"))
        date_   = _decode_header_safe(msg.get("Date"))

        html = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html = payload.decode(charset, errors="replace")
                    except Exception:
                        html = payload.decode("latin-1", errors="replace")
                    break
            if not html:
                # Fallback to text/plain
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True) or b""
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            html = payload.decode(charset, errors="replace")

        return html, {"subject": subject, "from": from_, "date": date_}

    # Plain HTML
    try:
        html = raw.decode("utf-8", errors="replace")
    except Exception:
        html = raw.decode("latin-1", errors="replace")
    return html, {"subject": "", "from": "", "date": ""}


# =========================================================================
# Category inference
# =========================================================================
def infer_category(subject: str, override: str = "") -> str:
    if override:
        return override
    s = (subject or "").upper()
    for kw, cat in CATEGORY_BY_SUBJECT_KW:
        if kw in s:
            return cat
    return ""  # caller decides default


# =========================================================================
# Address parsing
# =========================================================================
def _county_for_city(city: str) -> str:
    return COUNTY_BY_CITY.get((city or "").strip().upper(), "")


def _clean_address(s: str) -> str:
    """Strip stray duplicated words ('PLACE PLACE', 'TERRACE TERRACE') that
    appear in some OneHome cards because the street-type suffix is doubled."""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    # Collapse repeated street suffix: 'KENDALE PLACE PLACE' → 'KENDALE PLACE'
    for suf in ("PLACE", "TERRACE", "AVENUE", "STREET", "DRIVE",
                "BOULEVARD", "COURT", "LANE", "ROAD"):
        s = re.sub(rf"\b({suf})\s+\1\b", r"\1", s, flags=re.IGNORECASE)
    return s


# =========================================================================
# Listing extraction
# =========================================================================
def _text_of(node) -> str:
    """Join all visible text of a BeautifulSoup node, normalized whitespace."""
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _find_listing_blocks(soup: BeautifulSoup) -> list:
    """Heuristic: a listing block is any container that holds an MLS# string.

    OneHome cards use <td> elements (it's an HTML email — tables for layout).
    We find every text node with MLS# and walk up to the smallest <table> or
    <td> that also contains the price.
    """
    blocks = []
    seen = set()
    for node in soup.find_all(string=MLS_RE):
        # Walk up to find a node that has both MLS# and price text
        parent = node.parent
        for _ in range(8):
            if parent is None:
                break
            text = _text_of(parent)
            if MLS_RE.search(text) and PRICE_RE.search(text):
                if id(parent) not in seen:
                    blocks.append(parent)
                    seen.add(id(parent))
                break
            parent = parent.parent
    return blocks


def _parse_listing_block(block, today: date, category: str, source: str) -> Lead | None:
    text = _text_of(block)
    if not text:
        return None

    mls_m  = MLS_RE.search(text)
    price_m = PRICE_RE.search(text)
    if not mls_m:
        return None

    mls = mls_m.group(1).upper()
    price = 0.0
    if price_m:
        try:
            price = float(price_m.group(1).replace(",", ""))
        except ValueError:
            pass

    # City / State / Zip
    city = ""
    zip_code = ""
    csz_m = CITY_STATE_ZIP_RE.search(text)
    if csz_m:
        city = csz_m.group(1).strip()
        zip_code = csz_m.group(3)

    # Property address (street) — usually the line right before city/state/zip.
    # Pull all lines, find the one just before 'CITY, FL ZIP'.
    lines = [l.strip() for l in block.get_text("\n", strip=True).splitlines() if l.strip()]
    street = ""
    if csz_m:
        csz_str = csz_m.group(0)
        for i, line in enumerate(lines):
            if csz_str.upper() in line.upper():
                if i > 0:
                    street = lines[i-1]
                break
    if not street:
        # Fallback: look for a line containing digits (street # + name)
        for line in lines:
            if re.match(r"^\d+\s+\w", line) and not BED_BATH_RE.search(line):
                street = line
                break
    street = _clean_address(street)

    # Property type
    ptype = ""
    for kw in TYPE_KEYWORDS:
        if kw.lower() in text.lower():
            ptype = kw
            break

    # Beds / baths / sqft
    bedrooms = 0
    bb_m = BED_BATH_RE.search(text)
    if bb_m:
        try:
            bedrooms = int(bb_m.group(1))
        except ValueError:
            pass

    # Status tag (we add to notes for downstream context)
    status_tag = ""
    for kw in STATUS_KEYWORDS:
        if kw.lower() in text.lower():
            status_tag = kw
            break

    if not street or not zip_code:
        log.debug("Skipping listing — missing street/zip. text[:200]=%r", text[:200])
        return None

    county = _county_for_city(city)

    lead = Lead(
        lead_id=f"onehome-{mls}",
        first_seen=today,
        last_updated=today,
        county=county,
        category=category or "Foreclosure",
        property_address=street,
        city=city,
        zip=zip_code,
        property_type=ptype,
        outstanding_debt=price,   # MLS list price → "Purchase Price" col in Leon's sheet
        status="New",
        notes=f"MLS#{mls}" + (f" · {status_tag}" if status_tag else ""),
        source=f"onehome-email/{source}" if source else "onehome-email",
    )
    return lead


# =========================================================================
# Public API
# =========================================================================
def parse_onehome_file(path: str | Path,
                       category: str = "",
                       today: date | None = None) -> list[Lead]:
    """Parse one OneHome auto-email (.eml or .html) into Lead objects.

    Args:
        path: filesystem path to the .eml or .html file
        category: explicit category (Foreclosure / Auction / Short Sale / Lis Pendens).
            If empty, inferred from the email subject line.
        today: optional override for first_seen / last_updated (default: today)

    Returns:
        list of Lead objects (one per listing found)
    """
    path = Path(path)
    if not path.exists():
        log.warning("OneHome file not found: %s", path)
        return []

    today = today or date.today()
    html, meta = _load_email_html(path)
    subject = meta.get("subject", "")

    inferred = infer_category(subject, override=category)
    if not inferred:
        log.warning(
            "Could not infer category from subject %r — defaulting to 'Foreclosure'. "
            "Pass --category explicitly to override.", subject,
        )
        inferred = "Foreclosure"

    soup = BeautifulSoup(html, "lxml") if html else BeautifulSoup("", "lxml")
    blocks = _find_listing_blocks(soup)
    log.info("OneHome parser: found %d listing blocks in %s (category=%s)",
             len(blocks), path.name, inferred)

    leads: list[Lead] = []
    for blk in blocks:
        lead = _parse_listing_block(blk, today=today, category=inferred,
                                     source=path.stem)
        if lead:
            leads.append(lead)

    # Dedupe by MLS#
    seen_mls = set()
    out: list[Lead] = []
    for l in leads:
        mls_key = l.notes.split("·")[0].strip() if l.notes else l.lead_id
        if mls_key in seen_mls:
            continue
        seen_mls.add(mls_key)
        out.append(l)
    return out


def parse_onehome_directory(dir_path: str | Path,
                             default_category: str = "") -> list[Lead]:
    """Parse all .eml and .html files in a directory.

    Auto-detects category per file based on the email subject; falls back to
    default_category if subject is uninformative.
    """
    dir_path = Path(dir_path)
    out: list[Lead] = []
    for p in sorted(list(dir_path.glob("*.eml")) + list(dir_path.glob("*.html"))):
        leads = parse_onehome_file(p, category=default_category)
        log.info("  %s → %d leads", p.name, len(leads))
        out.extend(leads)
    return out
