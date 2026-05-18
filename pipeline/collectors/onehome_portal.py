"""
OneHome (Miami Realtors) portal scraper.

The OneHome consumer portal is what Leon's saved-search emails link to via
"View All Properties". Each saved search has a unique URL with a JWT token:

    https://portal.onehome.com/en-US/properties/map?token=eyJ...

This URL shows ALL results of the saved search (200+), not just the 8
highlights from the email. We use Playwright to load the portal, switch to
list view, scroll through all results, and extract each listing's details.

Saved search name is read from the page header (e.g. "101 Advisors REO -
Daily Alert") and mapped to our Leon category:
    REO / Foreclosure  → Foreclosure
    Auction            → Auction
    Short Sale         → Short Sale
    Lis Pendens        → Lis Pendens

Usage:
    from pipeline.collectors.onehome_portal import scrape_onehome_portal

    leads = scrape_onehome_portal(
        "https://portal.onehome.com/en-US/properties/map?token=...",
        headless=True,
    )
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None  # type: ignore
    Page = Any  # type: ignore

from .base import Lead

log = logging.getLogger(__name__)


# ── County mapping by city (Florida only) ────────────────────────────────
COUNTY_BY_CITY = {
    # Miami-Dade
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
    "INDIAN CREEK": "Miami-Dade",
    "EL PORTAL": "Miami-Dade", "NORTH BAY VILLAGE": "Miami-Dade",
    "BISCAYNE PARK": "Miami-Dade", "PINELANDS": "Miami-Dade",
    "GLENVAR HEIGHTS": "Miami-Dade", "WESTCHESTER": "Miami-Dade",
    "FOUNTAINEBLEAU": "Miami-Dade", "KENDALL": "Miami-Dade",
    "TAMIAMI": "Miami-Dade", "GOULDS": "Miami-Dade",
    "PERRINE": "Miami-Dade", "PRINCETON": "Miami-Dade",
    "LEISURE CITY": "Miami-Dade", "RICHMOND HEIGHTS": "Miami-Dade",
    "WEST PERRINE": "Miami-Dade", "OJUS": "Miami-Dade",
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
    "WEST PARK": "Broward", "INWOOD": "Broward",
    # Palm Beach
    "WEST PALM BEACH": "Palm Beach", "PALM BEACH": "Palm Beach",
    "PALM BEACH GARDENS": "Palm Beach", "BOCA RATON": "Palm Beach",
    "BOYNTON BEACH": "Palm Beach", "DELRAY BEACH": "Palm Beach",
    "JUPITER": "Palm Beach", "LAKE WORTH": "Palm Beach",
    "LAKE WORTH BEACH": "Palm Beach", "RIVIERA BEACH": "Palm Beach",
    "WELLINGTON": "Palm Beach", "ROYAL PALM BEACH": "Palm Beach",
    "GREENACRES": "Palm Beach", "LANTANA": "Palm Beach",
    "TEQUESTA": "Palm Beach", "JUNO BEACH": "Palm Beach",
    "LOXAHATCHEE": "Palm Beach", "LOXAHATCHEE GROVES": "Palm Beach",
    "NORTH PALM BEACH": "Palm Beach",
    "SOUTH BAY": "Palm Beach", "PALM SPRINGS": "Palm Beach",
    "BRINY BREEZES": "Palm Beach", "GLEN RIDGE": "Palm Beach",
    "MANGONIA PARK": "Palm Beach", "GOLF": "Palm Beach",
    "CLOUD LAKE": "Palm Beach", "HYPOLUXO": "Palm Beach",
    "WESTLAKE": "Palm Beach", "VILLAGE OF GOLF": "Palm Beach",
}


def _county_for(city: str) -> str:
    return COUNTY_BY_CITY.get((city or "").strip().upper(), "")


# Map keywords found in the saved-search name → Leon category
SAVED_SEARCH_CATEGORY = (
    ("LIS PENDENS",   "Lis Pendens"),
    ("FORECLOS",      "Foreclosure"),
    ("REO",           "Foreclosure"),
    ("AUCTION",       "Auction"),
    ("SHORT SALE",    "Short Sale"),
    ("PROBATE",       "Probate"),
)


def infer_category_from_search_name(name: str) -> str:
    s = (name or "").upper()
    for kw, cat in SAVED_SEARCH_CATEGORY:
        if kw in s:
            return cat
    return ""


# ── Regexes ──────────────────────────────────────────────────────────────
PRICE_RE   = re.compile(r"\$\s?([0-9][\d,]*)")
MLS_RE     = re.compile(r"MLS\s*#\s*([A-Z][0-9]+)", re.IGNORECASE)
BBS_RE     = re.compile(
    r"(\d+)\s*bd\s*[·\.\-•]\s*(\d+)\s*(?:\([\d\s]+\))?\s*ba\s*[·\.\-•]\s*([\d,]+)\s*sqft",
    re.IGNORECASE,
)
# Require group(1) to START with a letter (not a space), so start(1) points
# to the first char of the city name. If group(1) starts with a space, the
# position is off by one and we lose the boundary between street and city.
CITY_RE    = re.compile(r"([A-Za-z][A-Za-z .\-]*),\s*(FL)\s*(\d{5})(?:-\d{4})?", re.IGNORECASE)
TYPE_KWS   = (
    "Single Family Residence", "Single Family", "Townhouse", "Townhome",
    "Condominium", "Condo", "Villa", "Multi Family", "Multi-Family",
    "Duplex", "Triplex", "Fourplex", "Apartment", "Mobile Home",
    "Land", "Lot",
)
STATUS_KWS = (
    "New Listing", "Back on Market", "Price Reduced", "Price Drop",
    "Price Change", "Active", "Pending", "Under Contract",
    "Foreclosure", "Short Sale", "Auction", "REO", "Bank Owned",
    "For Sale", "Sold",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# Street suffix words (full + USPS abbreviations) that appear at the end
# of a street name. We deliberately EXCLUDE words that conflate with FL
# city names: BAY/COVE/HARBOR/WALK/PASS/KEY/SPRINGS/HEIGHTS/RIDGE/GROVE/
# GLEN/POINT/ISLE/ISLAND/VIEW/VALLEY/MEADOW/ESTATES — these all appear in
# legitimate FL place names (Cutler Bay, Coral Springs, Glenvar Heights,
# Coral Ridge, Coconut Grove, Lighthouse Point, Sunny Isles, etc.).
STREET_SUFFIXES = {
    "AVE","AV","AVENUE","AVENIDA",
    "ST","STREET",
    "RD","ROAD",
    "BLVD","BOULEVARD",
    "DR","DRIVE","DRV",
    "PL","PLACE","PLZ","PLAZA",
    "CT","COURT","CRT",
    "LN","LANE",
    "WAY","WY",
    "TER","TERR","TERRACE",
    "CIR","CIRCLE","CRC",
    "PKWY","PARKWAY",
    "HWY","HIGHWAY",
    "SQ","SQUARE",
    "PATH","TRAIL","TRL",
    "LOOP","RUN",
    "CRES","CRESCENT",
    "MNR","MANOR",
    "JCT","JUNCTION",
    "KNL","KNOLL",
    "MTN","PIKE",
}
# Ordinal suffixes that can leak from "78th" / "23rd" / "197th" into the city
ORDINAL_SUFFIXES = {"TH", "ST", "ND", "RD"}
# Direction prefixes that sometimes leak from the street into the city
# (e.g. "S Palmway Lake Worth" → "Lake Worth" with "S Palmway" trailing)
DIRECTION_PREFIXES = {"N","S","E","W","NE","NW","SE","SW"}


def _split_raw_city(raw_city: str) -> tuple[str, str]:
    """The CITY_RE regex captures all contiguous letter-words before 'FL',
    which often includes trailing parts of the street ('Ave Miami', 'th St
    Cutler Bay', 'S Palmway Lake Worth'). Split into (street_trailing,
    real_city)."""
    # Normalize possessive "Of" - it's a valid street name connector,
    # not a separator (e.g. "Boulevard Of Champions" → all street)
    words = raw_city.split()

    # 1) Find the LAST street suffix word (Ave, St, Blvd, etc.)
    last_suffix_idx = -1
    for i, w in enumerate(words):
        if w.upper().rstrip(".,") in STREET_SUFFIXES:
            last_suffix_idx = i
    if last_suffix_idx >= 0 and last_suffix_idx < len(words) - 1:
        # Include any "Of <Word>" that follows the suffix (e.g. "Boulevard Of
        # Champions" — keep "Of Champions" with the street)
        end = last_suffix_idx + 1
        # Only "OF" is a safe connector — words like "EL", "LA", "DE", "THE"
        # appear in FL city names (El Portal, La Habana, De Soto) so we
        # cannot treat them as street connectors.
        while (end + 1 < len(words)
               and words[end].upper() == "OF"):
            end += 2  # consume the connector + next word
        # Strip any leading direction word from the city portion (it really
        # belongs to the street, e.g. 'PL N Hialeah' → street='PL N', city='Hialeah')
        while end < len(words) - 1 and words[end].upper() in DIRECTION_PREFIXES:
            end += 1
        return (" ".join(words[:end]),
                " ".join(words[end:]))

    # 2) Strip leading ordinal suffix ("th Miami" → "Miami")
    if words and words[0].upper() in ORDINAL_SUFFIXES:
        return words[0], " ".join(words[1:])

    # 3) Strip leading direction prefix ("N Hialeah" → "Hialeah",
    #    "S Palmway Lake Worth" → "Lake Worth", consuming the street name too)
    #    Direction prefixes only show up when CITY_RE grabbed them from the
    #    street (because the street has no suffix word).
    if words and words[0].upper() in DIRECTION_PREFIXES:
        # If next word is also a known FL city prefix (Palm, Lake, North,
        # South, etc.), keep direction + 1 word with street, rest is city.
        # Otherwise keep just the direction.
        if len(words) >= 3 and words[1][0].isupper():
            # Heuristic: take direction + street name as trailing, leave the
            # rest as city
            return " ".join(words[:2]), " ".join(words[2:])
        return words[0], " ".join(words[1:])

    return "", raw_city


# Patterns that signal the listing has no real address (hidden by MLS) —
# skip these entirely so they don't pollute the leads CSV.
ADDRESS_HIDDEN_PATTERNS = (
    "ADDRESS NOT AVAILABLE",
    "ADDRESS WITHHELD",
    "UNDISCLOSED",
)


def _extract_full_street(full_text: str, raw_city_start: int,
                          street_trailing: str, max_len: int = 50) -> str:
    """Reconstruct the full street address.

    full_text:        raw card text
    raw_city_start:   character offset where CITY_RE's group(1) starts
    street_trailing:  the part of street that got swallowed into raw_city
                      (e.g. 'th St' for '9001 SW 197th St Cutler Bay')

    Strategy:
        1. Concatenate text_before + street_trailing (no inserted space —
           the regex split at exactly the right char boundary, so simple
           concat preserves '23rd' / '78th' as one word).
        2. Find every digit-only word that is NOT part of a comma-separated
           number (filters out '$7,900,000' style prices).
        3. Pick the earliest qualifying digit-word whose distance to the
           end ≤ max_len. This filters out page-header noise like
           '101 Advisors REO - Daily Alert' that's far from the address.
    """
    text_before = full_text[:raw_city_start]
    # NO inserted space — text_before ends exactly where street_trailing
    # picks up; the original card text dictates whether there's a space.
    full = _norm(text_before + street_trailing)

    matches = list(re.finditer(r"\b\d[\d\-]*\b", full))
    # Filter out digit-words that are part of a comma-separated number
    # (e.g. '7' from '$7,900,000' — has '$'/',' adjacent)
    filtered = []
    for m in matches:
        pos, end = m.start(), m.end()
        left  = full[pos-1] if pos > 0 else ""
        right = full[end]   if end < len(full) else ""
        if left in ",$" or right == ",":
            continue
        filtered.append(m)
    matches = filtered or matches  # if all got filtered, fall back to all

    if not matches:
        return full.strip()
    for m in matches:
        if len(full) - m.start() <= max_len:
            return full[m.start():].strip()
    return full[matches[-1].start():].strip()


def _parse_listing_card_text(text: str) -> dict | None:
    """Given the raw text of one listing card on the OneHome portal, extract
    fields we care about. Returns None if MLS# or address can't be found."""
    text = _norm(text)
    mls_m = MLS_RE.search(text)
    if not mls_m:
        return None
    mls = mls_m.group(1).upper()

    # Skip listings with hidden addresses
    upper_text = text.upper()
    if any(p in upper_text for p in ADDRESS_HIDDEN_PATTERNS):
        log.debug("Skipping %s: address withheld", mls)
        return None

    price = 0.0
    pm = PRICE_RE.search(text)
    if pm:
        try:
            price = float(pm.group(1).replace(",", ""))
        except ValueError:
            pass

    # Property type (longest match wins so "Single Family Residence" wins over "Single Family")
    ptype = ""
    for kw in TYPE_KWS:
        if kw.lower() in text.lower():
            if len(kw) > len(ptype):
                ptype = kw

    # City / state / zip — and rebuild the street address
    cm = CITY_RE.search(text)
    if not cm:
        return None  # No FL address found in this card
    raw_city = _norm(cm.group(1))
    zip_ = cm.group(3)
    street_trailing, city = _split_raw_city(raw_city)
    street = _extract_full_street(text, cm.start(1), street_trailing)

    if not city or not zip_:
        return None
    # Sanity: reject if street looks like a UI label (no digit start)
    if not re.match(r"^\d", street):
        return None

    # Status tag (longest match wins)
    status = ""
    for kw in STATUS_KWS:
        if kw.lower() in text.lower():
            if len(kw) > len(status):
                status = kw

    # Beds + sqft
    beds, sqft = 0, 0
    bm = BBS_RE.search(text)
    if bm:
        try: beds = int(bm.group(1))
        except: pass
        try: sqft = int(bm.group(3).replace(",", ""))
        except: pass

    return {
        "mls": mls, "price": price, "property_type": ptype,
        "street": street, "city": city, "zip": zip_,
        "status_tag": status, "beds": beds, "sqft": sqft,
    }


# =========================================================================
# Main scrape function
# =========================================================================
def scrape_onehome_portal(
    portal_url: str,
    headless: bool = True,
    max_scroll_attempts: int = 60,
    settle_ms: int = 1500,
) -> list[Lead]:
    """Load the OneHome portal at `portal_url`, scroll through all results,
    and return one Lead per listing.

    Args:
        portal_url: full URL from a 'View All Properties' link in a OneHome
            email — includes the ?token=... JWT
        headless: run browser without UI (default True)
        max_scroll_attempts: cap on how many scrolls before giving up
        settle_ms: pause between scrolls to let lazy-loaded cards render
    """
    if sync_playwright is None:
        raise ImportError(
            "playwright not installed. Run: pip3 install playwright --break-system-packages"
            " && python3 -m playwright install chromium"
        )

    today = date.today()
    leads: list[Lead] = []
    seen_mls: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=0)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        log.info("Loading OneHome portal …")
        page.goto(portal_url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)

        # ── Read saved search name (used to infer category) ──────────────
        # Look ONLY at text matching "101 Advisors <CATEGORY> - Daily Alert"
        # so we don't pick up listing tags (e.g. "Foreclosure For Sale" status
        # on individual cards) and infer the wrong category.
        search_name = page.evaluate(
            r"""
            () => {
                const re = /101\s*Advisors[^\n]{0,60}(?:REO|Auction|Short\s*Sale|Foreclosure|Lis\s*Pendens|Probate)[^\n]{0,40}Daily\s*Alert/i;
                // Search visible elements with short text first
                for (const el of document.querySelectorAll('h1,h2,h3,h4,div,span,p,a')) {
                    const txt = (el.innerText || '').trim();
                    if (txt.length > 0 && txt.length < 200) {
                        const m = txt.match(re);
                        if (m) return m[0].trim();
                    }
                }
                // Fallback: scan the whole body for the same pattern
                const body = (document.body.innerText || '');
                const m = body.match(re);
                return m ? m[0].trim() : '';
            }
            """
        )
        if not search_name:
            search_name = _norm(page.title())
        category = infer_category_from_search_name(search_name) or "Foreclosure"
        log.info("Saved search: %r → category=%s", search_name, category)

        # ── Switch to list view if we landed on map view ─────────────────
        # Three view-toggle icons appear after the result count: list, grid, map.
        # We try clicking the "list" icon by looking for a button with title.
        for sel in (
            'button[title="List View"]',
            'button[aria-label*="list" i]',
            '[data-testid*="list" i]',
            'svg[aria-label*="list" i]',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    log.info("Switched to list view via %s", sel)
                    break
            except Exception:
                pass

        # ── Initialize JS-side accumulator (survives DOM virtualization) ──
        # OneHome uses virtualized scrolling: cards far from the viewport
        # are removed from the DOM. So we must extract cards INCREMENTALLY
        # during scrolling, not just once at the end.
        page.evaluate(
            """
            () => {
                window.__ohCards = window.__ohCards || new Map();  // mls -> text
                window.__ohExtractCurrent = () => {
                    document.querySelectorAll('*').forEach(el => {
                        const t = el.innerText || '';
                        if (!/MLS\\s*#/.test(t)) return;
                        if (!/\\$\\s?\\d/.test(t)) return;
                        let node = el;
                        // Walk up until parent has 2+ MLS# entries → we hit
                        // the LIST container; current `node` is one card.
                        while (node && node.parentElement) {
                            const pt = node.parentElement.innerText || '';
                            const mlsCount = (pt.match(/MLS\\s*#/g) || []).length;
                            if (mlsCount > 1) break;
                            node = node.parentElement;
                        }
                        const txt = (node.innerText || '').slice(0, 2000);
                        const m = txt.match(/MLS\\s*#\\s*([A-Z][0-9]+)/i);
                        if (!m) return;
                        const mls = m[1];
                        if (!window.__ohCards.has(mls)) {
                            window.__ohCards.set(mls, txt);
                        }
                    });
                    return window.__ohCards.size;
                };
                window.__ohScroll = () => {
                    let best = null;
                    let bestCount = 0;
                    document.querySelectorAll('*').forEach(el => {
                        const text = el.innerText || '';
                        const c = (text.match(/MLS\\s*#/g) || []).length;
                        const style = getComputedStyle(el);
                        if (c > bestCount && (style.overflowY === 'auto' || style.overflowY === 'scroll')) {
                            best = el; bestCount = c;
                        }
                    });
                    if (best) {
                        best.scrollTop += best.clientHeight * 0.85;
                    } else {
                        window.scrollBy(0, window.innerHeight * 0.85);
                    }
                };
            }
            """
        )

        # ── Scroll incrementally, extracting cards each step ─────────────
        prev_total = 0
        stagnant = 0
        target_total: int | None = None

        # Try to read total result count from the page ("244 Results")
        try:
            txt = page.locator('body').inner_text(timeout=2000)
            tm = re.search(r"(\d+)\s+Results?", txt, re.IGNORECASE)
            if tm:
                target_total = int(tm.group(1))
                log.info("Page reports %d total results", target_total)
        except Exception:
            pass

        # Initial extract (top of list)
        page.evaluate("window.__ohExtractCurrent()")
        prev_total = page.evaluate("window.__ohCards.size")
        log.info("Initial cards captured: %d", prev_total)

        # OneHome paginates with a "LOAD MORE" button (not infinite scroll).
        # We need to: scroll the list to the bottom, click LOAD MORE if visible,
        # wait for new cards to load, extract them, repeat.
        for attempt in range(max_scroll_attempts):
            page.evaluate("window.__ohScroll()")
            page.wait_for_timeout(400)

            # Try to click LOAD MORE button if it's visible
            clicked = False
            for sel in (
                'button:has-text("LOAD MORE")',
                'button:has-text("Load More")',
                'a:has-text("LOAD MORE")',
                '[role="button"]:has-text("LOAD MORE")',
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.scroll_into_view_if_needed(timeout=2000)
                        btn.click(timeout=3000)
                        clicked = True
                        break
                except Exception:
                    pass

            wait = settle_ms if clicked else 600
            page.wait_for_timeout(wait)
            current_total = page.evaluate("window.__ohExtractCurrent()")

            if current_total == prev_total:
                stagnant += 1
                if stagnant >= 6:
                    log.info("No new cards after 6 attempts → stopping")
                    break
            else:
                stagnant = 0
            prev_total = current_total
            tag = "click+scroll" if clicked else "scroll"
            log.info("%-12s %02d: %d cards captured%s",
                     tag, attempt+1, current_total,
                     f" / {target_total}" if target_total else "")
            if target_total and current_total >= target_total:
                log.info("Reached target count → stopping")
                break

        # Final pull: get all accumulated cards
        cards_data = page.evaluate("Array.from(window.__ohCards.values())")
        log.info("Captured %d unique listing cards total", len(cards_data))

        for raw in cards_data:
            parsed = _parse_listing_card_text(raw)
            if not parsed:
                continue
            if parsed["mls"] in seen_mls:
                continue
            seen_mls.add(parsed["mls"])

            lead = Lead(
                lead_id=f"onehome-{parsed['mls']}",
                first_seen=today,
                last_updated=today,
                county=_county_for(parsed["city"]),
                category=category,
                property_address=parsed["street"],
                city=parsed["city"],
                zip=parsed["zip"],
                property_type=parsed["property_type"],
                bedrooms=parsed["beds"],
                outstanding_debt=parsed["price"],
                status="New",
                notes=f"MLS#{parsed['mls']}" + (
                    f" · {parsed['status_tag']}" if parsed["status_tag"] else ""
                ),
                source="onehome-portal",
            )
            leads.append(lead)

        browser.close()

    log.info("OneHome portal: produced %d Lead objects (category=%s)",
             len(leads), category)
    return leads
