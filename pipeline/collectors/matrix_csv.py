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
# Includes alias for SEF MLS Matrix "Agent Single Line" format.
COLUMN_ALIASES = {
    "mls_id": ["ML#", "MLS #", "MLS Number", "Listing ID", "MLS_ID",
               "MLS # Link", "MLS#", "MLS_NUM", "MLS Link"],
    "status": ["Status", "MLS Status", "St"],
    "list_price": ["List Price", "LP$", "LP", "Price", "Asking Price",
                   "Current Price", "List $"],
    "address": ["Address", "Street Address", "Full Address", "Site Address"],
    "street_num": ["Street #", "Street Number", "HSE_NUM"],
    "street_dir": ["Street Dir", "Direction", "Pre Dir"],
    "street_name": ["Street Name", "ST_NAME"],
    "street_type": ["Street Type", "ST_TYPE"],
    "city": ["City", "Municipality", "City Name"],
    "zip": ["Zip", "Zip Code", "Postal Code", "ZIP"],
    "state": ["State"],
    "county": ["County"],
    "area": ["Area"],   # Matrix uses numeric "Area" code as geographic zone
    "property_type": ["Property Type", "Type", "Type of Property", "RES Property Type",
                      "Property Sub Type", "Prop Type"],
    "subtype": ["Property Subtype", "Subtype"],
    "beds": ["Beds", "Bedrooms", "# Beds", "#Beds", "Total Bedrooms", "BR", "Bd"],
    "baths_full": ["# Full Baths", "#FBaths", "Full Baths", "FB", "Full Bths"],
    "baths_half": ["# Half Baths", "#HBaths", "Half Baths", "HB", "Half Bths"],
    "sqft": ["SqFt Living Area", "SqFt LA", "Living Area", "SqFt", "Sqft Living",
             "Heated Area", "SF Heated", "Heated SqFt"],
    "year_built": ["Year Built", "YR", "Year", "Yr Built"],
    "lot_size": ["Lot SF", "Lot Size", "Lot Sqft", "Lot Size SF", "Lot SqFt"],
    "reo": ["REO", "Bank Owned", "Bank-Owned", "REO YN"],
    "short_sale": ["Short Sale", "Short_Sale", "Short Sale YN"],
    "auction_type": ["Auction Type", "Auction"],
    "dom": ["DOM", "Days on Market", "Days On Market", "CDOM"],
    "agent_name": ["Listing Agent", "Listing Agent Name", "LA Name", "Agent Name",
                   "List Agent"],
    "agent_phone": ["Listing Agent Phone", "LA Phone", "Agent Phone", "List Agent Phone"],
    "subdivision": ["Subdivision", "Subdivision/Complex", "Sub/Complex", "Complex"],
    "remarks": ["Remarks", "Public Remarks", "Description", "Listing Remarks"],
    "garage": ["#Garage", "# Garage Spaces", "Garage Spaces", "Garage"],
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
    r = (raw or "").lower().strip()
    if r == "single" or "single family" in r or "sfr" in r:
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


def parse_matrix_csv(content: str, default_category: str = "Foreclosure") -> list[Lead]:
    """Parse a Matrix CSV export string and return Lead objects.

    Args:
        content: raw CSV text (from file upload or file read).
        default_category: assumed category when the CSV doesn't have REO/Short Sale
            columns (typical for "Agent Single Line" format). All rows from a
            specific Saved Search inherit this category. Override per-export
            if needed (REO, Short Sale, Auction).

    Returns:
        List of Lead objects normalized to our canonical schema.
    """
    today = date.today()
    leads: list[Lead] = []

    # Try to detect delimiter (Matrix sometimes uses tabs)
    sample = content[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel

    # Read raw rows so we can fix empty/duplicate headers
    raw_reader = csv.reader(io.StringIO(content), dialect=dialect)
    try:
        headers = next(raw_reader)
    except StopIteration:
        log.warning("CSV is empty")
        return []

    # Rename empty/duplicate headers so DictReader doesn't drop columns
    seen: dict[str, int] = {}
    clean_headers: list[str] = []
    for i, h in enumerate(headers):
        h_clean = (h or "").strip()
        if not h_clean:
            h_clean = f"col_{i}"
        if h_clean in seen:
            seen[h_clean] += 1
            h_clean = f"{h_clean}_{seen[h_clean]}"
        else:
            seen[h_clean] = 1
        clean_headers.append(h_clean)

    log.info("Detected %d columns: %s", len(clean_headers), clean_headers[:10])

    for i, raw_row in enumerate(raw_reader, 1):
        try:
            row = dict(zip(clean_headers, raw_row))
            lead = _row_to_lead(row, today, default_category)
            if lead:
                leads.append(lead)
            else:
                log.debug("Row %d: no MLS# or address found, skipping", i)
        except Exception as e:
            log.warning("Failed to parse row %d: %s", i, e)
            continue

    log.info("Parsed %d leads from Matrix CSV", len(leads))
    return leads


def _row_to_lead(row: dict, today: date, default_category: str = "Foreclosure") -> Lead | None:
    """Convert one CSV row into a Lead object."""
    mls_id_raw = _find_column(row, *COLUMN_ALIASES["mls_id"])
    # Clean MLS# — sometimes Matrix exports it with leading/trailing chars or as a link.
    mls_id = re.sub(r"[^A-Z0-9-]", "", mls_id_raw.upper()) if mls_id_raw else ""
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

    # Normalize duplicated street-type suffix that Matrix sometimes injects
    # (e.g. "857 Wandering Willow Way Way" → "857 Wandering Willow Way").
    # This is the canonical list of FL street suffixes that appear in MLS
    # data. The regex collapses repeats only when the SAME suffix word
    # immediately follows itself, so we don't accidentally clobber legit
    # "Court Drive" or "Park Way" patterns.
    _SUFFIX_DEDUP_RE = re.compile(
        r'\b(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Court|Ct|'
        r'Place|Pl|Lane|Ln|Way|Terrace|Ter|Highway|Hwy|Circle|Cir|Parkway|Pkwy|'
        r'Trail|Trl|Square|Sq|Loop|Run|Path|Walk|Crescent|Cres|Plaza|Plz)'
        r'\s+\1\b',
        re.IGNORECASE,
    )
    full_addr = _SUFFIX_DEDUP_RE.sub(r'\1', full_addr).strip()

    city = _find_column(row, *COLUMN_ALIASES["city"])
    zip_code = _find_column(row, *COLUMN_ALIASES["zip"])

    # If no explicit ZIP column, try to extract a Florida ZIP from the address text.
    # Florida ZIPs always start with 32, 33, or 34 (e.g. 33133 Miami, 33301 Fort Lauderdale).
    # This guard avoids matching 5-digit house numbers like "13231 SW 220 ST".
    FL_ZIP_RE = re.compile(r"\b(3[234]\d{3})\b")
    if not zip_code and full_addr:
        zip_match = FL_ZIP_RE.search(full_addr)
        if zip_match:
            zip_code = zip_match.group(1)

    # If still no ZIP, try the Subdivision column (rare, but sometimes there)
    if not zip_code:
        subdivision = _find_column(row, *COLUMN_ALIASES["subdivision"])
        zip_match = FL_ZIP_RE.search(subdivision)
        if zip_match:
            zip_code = zip_match.group(1)

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

    # If the CSV has REO/Short Sale/Auction columns, use them. Otherwise fall back
    # to the default_category passed by the caller (which assumes the CSV came
    # from a specific Saved Search like "REO Daily Alert").
    has_distressed_cols = any(
        _find_column(row, *COLUMN_ALIASES[k]) for k in ("reo", "short_sale", "auction_type")
    )
    if has_distressed_cols:
        category = _detect_category(row)
    else:
        category = default_category

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
        # Always "New" for freshly-uploaded leads — pipeline state, not MLS state.
        # MLS status ('Active', 'Coming Soon') is captured in notes.
        status="New",
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
