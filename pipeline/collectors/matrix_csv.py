"""
SEF MLS Matrix — CSV upload parser.

Matrix lets users export Saved Search results to CSV (Results page → Export CSV).
Samuel downloads the CSV daily (5 min) and uploads to the dashboard.
This module parses any Matrix CSV and converts rows into Lead objects.

CSV columns vary slightly between MLSs, but the standard ones for SEF Matrix include:
    - ML#  (MLS number)
    - Status  (Active, Coming Soon, Pending, etc.)
    - List Price
    - Address (or "Street #", "Street Name" separate)
    - City
    - Zip
    - State
    - County
    - Property Type / Type
    - Beds / Bedrooms / # Beds
    - Baths / # Full Baths
    - SqFt Living Area
    - Year Built
    - REO  (Yes/No)
    - Short Sale  (Yes/No)
    - Auction Type
    - Days on Market (DOM)
    - Listing Agent Name
    - Listing Agent Phone
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date
from typing import Iterable

from .base import Lead

log = logging.getLogger(__name__)


# Map possible column names to our canonical fields. Order matters — first hit wins.
COLUMN_ALIASES = {
    "mls_id": ["ML#", "MLS #", "MLS Number", "Listing ID", "MLS_ID"],
    "status": ["Status", "MLS Status"],
    "list_price": ["List Price", "LP$", "LP", "Price", "Asking Price"],
    "address": ["Address", "Street Address", "Full Address"],
    "street_num": ["Street #", "Street Number", "HSE_NUM"],
    "street_dir": ["Street Dir", "Direction", "Pre Dir"],
    "street_name": ["Street Name", "ST_NAME"],
    "street_type": ["Street Type", "ST_TYPE"],
    "city": ["City", "Municipality"],
    "zip": ["Zip", "Zip Code", "Postal Code"],
    "state": ["State", "ST"],
    "county": ["County"],
    "property_type": ["Property Type", "Type", "Type of Property", "RES Property Type"],
    "subtype": ["Property Subtype", "Subtype"],
    "beds": ["Beds", "Bedrooms", "# Beds", "Total Bedrooms", "BR"],
    "baths_full": ["# Full Baths", "Full Baths", "FB"],
    "baths_half": ["# Half Baths", "Half Baths", "HB"],
    "sqft": ["SqFt Living Area", "Living Area", "SqFt", "Sqft Living", "Heated Area"],
    "year_built": ["Year Built", "YR", "Year"],
    "lot_size": ["Lot SF", "Lot Size", "Lot Sqft"],
    "reo": ["REO", "Bank Owned", "Bank-Owned"],
    "short_sale": ["Short Sale", "Short_Sale"],
    "auction_type": ["Auction Type", "Auction"],
    "dom": ["DOM", "Days on Market", "Days On Market"],
    "agent_name": ["Listing Agent", "Listing Agent Name", "LA Name", "Agent Name"],
    "agent_phone": ["Listing Agent Phone", "LA Phone", "Agent Phone"],
    "subdivision": ["Subdivision", "Subdivision/Complex"],
    "remarks": ["Remarks", "Public Remarks", "Description"],
}


def _find_column(row: dict, *names: str) -> str:
    """Return the value of the first matching column name (case-insensitive)."""
    keys = {k.lower().strip(): k for k in row.keys()}
    for name in names:
        if not name:
            continue
        k = name.lower().strip()
        if k in keys:
            value = row[keys[k]]
            if value is not None and str(value).strip() not in {"", "-", "—", "N/A"}:
                return str(value).strip()
    return ""


def _detect_category(row: dict) -> str:
    """Detect category from the row contents.

    Priority:
        REO/Bank Owned → Foreclosure
        Auction Type non-empty → Foreclosure (auction)
        Short Sale → Short Sale
        Fallback → Foreclosure
    """
    reo = _find_column(row, *COLUMN_ALIASES["reo"]).lower()
    short = _find_column(row, *COLUMN_ALIASES["short_sale"]).lower()
    auction = _find_column(row, *COLUMN_ALIASES["auction_type"]).lower()
    remarks = _find_column(row, *COLUMN_ALIASES["remarks"]).lower()

    if reo in {"yes", "y", "true", "1"} or "reo" in remarks or "bank owned" in remarks:
        return "Foreclosure"
    if auction and auction not in {"no", "n"}:
        return "Foreclosure"
    if short in {"yes", "y", "true", "1"} or "short sale" in remarks:
        return "Short Sale"
    return "Foreclosure"


def _normalize_property_type(raw: str, beds: int) -> str:
    """Map Matrix property type strings to our standard set."""
    r = (raw or "").lower()
    if "single family" in r or "sfr" in r:
        return "Single Family"
    if "condo" in r:
        return "Condominium"
    if "townhouse" in r or "townhome" in r:
        return "Townhouse"
    if "duplex" in r or "2 units" in r:
        return "Duplex"
    if "triplex" in r or "3 units" in r:
        return "Triplex"
    if "fourplex" in r or "quadplex" in r or "4 units" in r:
        return "Fourplex"
    if "multi" in r:
        return "Multi Family"
    if "villa" in r:
        return "Villa"
    if not r and beds > 0:
        return "Single Family"
    return raw or "Unknown"


def _detect_county_from_city(city: str, zip_code: str) -> str:
    """Best-effort county detection from city or zip."""
    city_lower = city.lower().strip()
    miami_dade = {"miami", "miami beach", "doral", "hialeah", "kendall", "homestead",
                  "coral gables", "miami gardens", "north miami", "aventura", "miami lakes",
                  "pinecrest", "palmetto bay", "key biscayne", "cutler bay", "florida city"}
    broward = {"fort lauderdale", "ft lauderdale", "hollywood", "pembroke pines",
               "plantation", "sunrise", "davie", "coral springs", "weston",
               "tamarac", "deerfield beach", "pompano beach", "miramar", "oakland park",
               "wilton manors", "dania beach", "hallandale beach", "cooper city"}
    palm_beach = {"west palm beach", "palm beach", "boca raton", "boynton beach",
                  "delray beach", "wellington", "jupiter", "lake worth", "royal palm beach",
                  "palm beach gardens", "greenacres", "riviera beach", "lantana"}

    if city_lower in miami_dade:
        return "Miami-Dade"
    if city_lower in broward:
        return "Broward"
    if city_lower in palm_beach:
        return "Palm Beach"

    # Fallback by zip
    if zip_code and len(zip_code) >= 3:
        prefix = zip_code[:3]
        if prefix in {"331", "332"}:
            return "Miami-Dade"
        if prefix in {"330", "333"}:
            return "Broward"
        if prefix == "334":
            return "Palm Beach"
    return ""


def _safe_int(s: str) -> int:
    if not s:
        return 0
    try:
        # Remove commas, dollar signs, etc.
        clean = re.sub(r"[^\d-]", "", str(s))
        return int(clean) if clean else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(s: str) -> float:
    if not s:
        return 0.0
    try:
        clean = re.sub(r"[^\d.-]", "", str(s))
        return float(clean) if clean else 0.0
    except (ValueError, TypeError):
        return 0.0


def parse_matrix_csv(content: str) -> list[Lead]:
    """Parse a Matrix CSV export string and return Lead objects.

    Args:
        content: raw CSV text (from file upload or file read).

    Returns:
        List of Lead objects normalized to our canonical schema.
    """
    today = date.today()
    leads: list[Lead] = []

    # Try to detect delimiter (Matrix sometimes uses tabs)
    sample = content[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")

    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    for i, row in enumerate(reader, 1):
        try:
            lead = _row_to_lead(row, today)
            if lead:
                leads.append(lead)
        except Exception as e:
            log.warning("Failed to parse row %d: %s", i, e)
            continue

    log.info("Parsed %d leads from Matrix CSV", len(leads))
    return leads


def _row_to_lead(row: dict, today: date) -> Lead | None:
    """Convert one CSV row into a Lead object."""
    mls_id = _find_column(row, *COLUMN_ALIASES["mls_id"])
    if not mls_id:
        return None

    # Address — try full address first, then assemble from parts.
    full_addr = _find_column(row, *COLUMN_ALIASES["address"])
    if not full_addr:
        num = _find_column(row, *COLUMN_ALIASES["street_num"])
        direction = _find_column(row, *COLUMN_ALIASES["street_dir"])
        name = _find_column(row, *COLUMN_ALIASES["street_name"])
        stype = _find_column(row, *COLUMN_ALIASES["street_type"])
        full_addr = " ".join(p for p in [num, direction, name, stype] if p).strip()

    if not full_addr:
        return None

    city = _find_column(row, *COLUMN_ALIASES["city"])
    zip_code = _find_column(row, *COLUMN_ALIASES["zip"])
    county = _find_column(row, *COLUMN_ALIASES["county"])
    if not county:
        county = _detect_county_from_city(city, zip_code)

    list_price = _safe_float(_find_column(row, *COLUMN_ALIASES["list_price"]))
    beds = _safe_int(_find_column(row, *COLUMN_ALIASES["beds"]))
    baths_full = _safe_int(_find_column(row, *COLUMN_ALIASES["baths_full"]))
    year_built = _safe_int(_find_column(row, *COLUMN_ALIASES["year_built"]))
    sqft = _safe_float(_find_column(row, *COLUMN_ALIASES["sqft"]))
    dom = _safe_int(_find_column(row, *COLUMN_ALIASES["dom"]))
    agent_name = _find_column(row, *COLUMN_ALIASES["agent_name"])
    agent_phone = _find_column(row, *COLUMN_ALIASES["agent_phone"])
    subdivision = _find_column(row, *COLUMN_ALIASES["subdivision"])

    property_type_raw = _find_column(row, *COLUMN_ALIASES["property_type"])
    property_type = _normalize_property_type(property_type_raw, beds)

    category = _detect_category(row)

    # Build notes — captures useful info that doesn't fit canonical schema
    notes_parts = [f"MLS# {mls_id}"]
    if dom:
        notes_parts.append(f"DOM: {dom}")
    if subdivision:
        notes_parts.append(f"Sub: {subdivision}")
    if agent_name:
        notes_parts.append(f"Listing Agent: {agent_name}")
        if agent_phone:
            notes_parts.append(agent_phone)
    notes = " · ".join(notes_parts)

    # Use list price as proxy for equity / debt — refined later by Property Appraiser
    return Lead(
        lead_id=f"MLS-{mls_id}",
        first_seen=today,
        last_updated=today,
        county=county or "",
        category=category,
        property_address=full_addr,
        city=city,
        zip=zip_code,
        property_type=property_type,
        bedrooms=beds,
        outstanding_debt=list_price,
        equity=list_price,  # placeholder until Property Appraiser enriches
        status=_find_column(row, *COLUMN_ALIASES["status"]) or "New",
        notes=notes,
        source="mls_matrix_csv",
    )


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Simulated Matrix CSV
    sample = """ML#,Status,LP$,Address,City,Zip,Property Type,Beds,# Full Baths,SqFt Living Area,Year Built,REO,Short Sale,DOM,Listing Agent,Listing Agent Phone,Subdivision
A11986389,Active,1999999,2319 NE 35th Dr,Fort Lauderdale,33308,Single Family,6,5,4961,2014,Yes,No,12,John Smith,(305) 555-1234,Coral Ridge Country Club
A11864941,Active,1960000,4220 NE 27th Ave,Fort Lauderdale,33308,Single Family,3,3,2603,1971,No,Yes,8,Mary Johnson,(954) 555-5678,Venetian Isles
F10542798,Active,849000,2854 Primrose Place,Fort Lauderdale,33305,Single Family,4,3,2130,2024,Yes,No,5,Carlos Lopez,(786) 555-9012,Oak Tree
"""
    leads = parse_matrix_csv(sample)
    print(f"Parsed {len(leads)} leads:")
    for l in leads:
        print(f"  • {l.lead_id} · {l.property_address}, {l.city} {l.zip} · {l.category} · {l.property_type} · {l.bedrooms}BR · ${l.outstanding_debt:,.0f}")
