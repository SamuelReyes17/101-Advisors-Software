"""
Miami-Dade Clerk Official Records — Lis Pendens scraper.

Florida law REQUIRES every Lis Pendens (notice of pending lawsuit affecting
real property) to be RECORDED in the Clerk's Official Records book. This is
a separate system from the OCS court-case search:

    Standard Search:
    https://www2.miamidadeclerk.gov/officialrecords/StandardSearch.aspx

The Standard Search lets us filter by:
    - Document Type:  LIS PENDENS (3-letter code "LIS" or "LP")
    - Recording Date: from/to range

This returns EVERY Lis Pendens filed in Miami-Dade for that period — typically
1,500–2,500 per month. Each result row has:
    - CFN (Clerk File Number)
    - Recording date
    - First Party (plaintiff — bank / HOA / lender)
    - Second Party (defendant — the homeowner)
    - Book / Page reference
    - Legal description (sometimes)

We extract the defendant name → cross-reference with Property Appraiser to
get the actual property street address + folio.

Usage:
    from pipeline.collectors.miami_official_records import scrape_lis_pendens

    recordings = scrape_lis_pendens(days=60, headless=True)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None
    Page = Any  # type: ignore

log = logging.getLogger(__name__)

STANDARD_SEARCH_URL = (
    "https://www2.miamidadeclerk.gov/officialrecords/StandardSearch.aspx"
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _date_str(d: date) -> str:
    """Format date as MM/DD/YYYY (what the Official Records UI expects)."""
    return d.strftime("%m/%d/%Y")


def scrape_lis_pendens(
    days: int = 60,
    headless: bool = True,
    page_limit: int = 50,
    settle_ms: int = 1200,
) -> list[dict[str, Any]]:
    """Scrape every LIS PENDENS recorded in Miami-Dade in the last `days` days.

    Args:
        days:        look-back window (default: 60 days)
        headless:    show browser if False (debug)
        page_limit:  max result pages to capture (safety cap)
        settle_ms:   pause between pages

    Returns list of dicts:
        {
            "cfn":            "2026R0123456",
            "recording_date": "04/15/2026",
            "doc_type":       "LIS PENDENS",
            "first_party":    "WELLS FARGO BANK ...",
            "second_party":   "GARCIA, JOSE",
            "book_page":      "32850/0123",
        }
    """
    if sync_playwright is None:
        raise ImportError(
            "playwright not installed. Run: pip3 install playwright --break-system-packages"
            " && python3 -m playwright install chromium"
        )

    today = date.today()
    date_from = today - timedelta(days=days)
    date_to = today
    log.info("Scraping Lis Pendens recorded %s → %s",
             _date_str(date_from), _date_str(date_to))

    recordings: list[dict[str, Any]] = []
    seen_cfn: set[str] = set()

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

        log.info("Loading Standard Search …")
        page.goto(STANDARD_SEARCH_URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)

        # ── Set Document Type to LIS PENDENS ──
        # The page typically has a dropdown for Document Type. Try several
        # ways to find and select it.
        log.info("Setting Document Type to LIS PENDENS …")
        set_doctype = False
        for sel in (
            'select[name*="DocType" i]',
            'select[id*="DocType" i]',
            'select[name*="document" i]',
            'select[id*="document" i]',
        ):
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    # Try selecting by label first
                    for label in ("LIS PENDENS", "Lis Pendens", "LP", "LIS"):
                        try:
                            el.select_option(label=label, timeout=3000)
                            set_doctype = True
                            log.info("  → selected by label '%s'", label)
                            break
                        except Exception:
                            pass
                    if not set_doctype:
                        # Try selecting by value
                        for val in ("LP", "LIS", "LISP"):
                            try:
                                el.select_option(value=val, timeout=3000)
                                set_doctype = True
                                log.info("  → selected by value '%s'", val)
                                break
                            except Exception:
                                pass
                    if set_doctype:
                        break
            except Exception:
                continue

        if not set_doctype:
            # Newer UIs sometimes use a "Document Type" autocomplete text input.
            for sel in (
                'input[name*="DocType" i]',
                'input[id*="DocType" i]',
                'input[placeholder*="document type" i]',
            ):
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        el.fill("LIS PENDENS")
                        page.wait_for_timeout(800)
                        # Try to click the autocomplete suggestion
                        try:
                            page.get_by_text("LIS PENDENS", exact=False).first.click(timeout=2000)
                            set_doctype = True
                            log.info("  → set via autocomplete input")
                            break
                        except Exception:
                            el.press("Enter")
                            set_doctype = True
                            break
                except Exception:
                    continue

        if not set_doctype:
            log.warning("Could NOT set document type filter. Results may "
                        "include all doc types. Continuing anyway …")

        # ── Set the date range ──
        log.info("Setting date range %s → %s …",
                 _date_str(date_from), _date_str(date_to))
        from_set = to_set = False
        for sel in (
            'input[name*="FromDate" i]',
            'input[id*="FromDate" i]',
            'input[name*="DateFrom" i]',
            'input[placeholder*="from" i]',
        ):
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    el.fill(_date_str(date_from))
                    from_set = True
                    break
            except Exception:
                continue
        for sel in (
            'input[name*="ToDate" i]',
            'input[id*="ToDate" i]',
            'input[name*="DateTo" i]',
            'input[placeholder*="to" i]',
        ):
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    el.fill(_date_str(date_to))
                    to_set = True
                    break
            except Exception:
                continue
        log.info("  date range set: from=%s to=%s", from_set, to_set)

        # ── Submit search ──
        log.info("Submitting search …")
        clicked = False
        for sel in (
            'input[type="submit"][value*="search" i]',
            'button[type="submit"]',
            'button:has-text("Search")',
            'input[value="Search"]',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            # Some forms submit on Enter in any field
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass

        page.wait_for_timeout(3500)

        # ── Scrape result pages ──
        for page_num in range(1, page_limit + 1):
            new_in_this_page = _extract_results_from_page(page, seen_cfn)
            log.info("Page %d: %d new recordings", page_num, len(new_in_this_page))
            recordings.extend(new_in_this_page)
            if not new_in_this_page:
                break
            # Try to click "Next"
            next_clicked = False
            for sel in (
                'a:has-text("Next")',
                'input[type="submit"][value*="next" i]',
                'a[id*="Next" i]',
                'button:has-text("Next")',
                'a:has-text(">")',
            ):
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        next_clicked = True
                        page.wait_for_timeout(settle_ms)
                        break
                except Exception:
                    continue
            if not next_clicked:
                log.info("No 'Next' button found — done at page %d", page_num)
                break

        browser.close()

    log.info("Scraped %d total Lis Pendens recordings", len(recordings))
    return recordings


def _extract_results_from_page(page, seen_cfn: set[str]) -> list[dict[str, Any]]:
    """Pull rows out of the result grid on the current page.

    The Official Records grid usually has columns:
        CFN | Date | Doc Type | First Party | Second Party | Book/Page

    We use a fairly generic extractor based on row text patterns since the
    exact CSS classes change between deployments.
    """
    out: list[dict[str, Any]] = []
    try:
        # Extract every table row in the page; filter to those that look like
        # recording rows (have a date-like cell and a 4+ char text in next).
        rows_text = page.evaluate(
            """
            () => {
                const out = [];
                document.querySelectorAll('table tr').forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td')).map(
                        td => (td.innerText || '').trim()
                    );
                    if (cells.length >= 4) out.push(cells);
                });
                return out;
            }
            """
        )
    except Exception as e:
        log.warning("DOM read failed: %s", e)
        return []

    for cells in rows_text:
        # Find which cells look like CFN / date / doc type / parties
        cfn = ""
        rec_date = ""
        doc_type = ""
        first_party = ""
        second_party = ""

        for c in cells:
            c = _norm(c)
            if not c:
                continue
            # CFN looks like 'YYYYR0123456' or pure digits
            if re.match(r"^\d{4}R\d{5,}$", c) and not cfn:
                cfn = c
                continue
            if re.match(r"^\d{10,}$", c) and not cfn:
                cfn = c
                continue
            # Date in MM/DD/YYYY
            if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", c) and not rec_date:
                rec_date = c
                continue
            # Doc type — short uppercase
            if c.upper() in ("LIS PENDENS", "LIS", "LP") and not doc_type:
                doc_type = "LIS PENDENS"
                continue
        # Parties — pick the two longest non-numeric cells
        text_cells = [_norm(c) for c in cells
                      if not re.match(r"^\d", _norm(c)) and len(_norm(c)) > 3]
        if len(text_cells) >= 2:
            # Skip ones that look like doc types or pure label
            party_cells = [t for t in text_cells
                            if t.upper() not in ("LIS PENDENS", "LIS", "LP")]
            if len(party_cells) >= 2:
                first_party = party_cells[0]
                second_party = party_cells[1]

        if not cfn or cfn in seen_cfn:
            continue
        if not (first_party or second_party):
            continue
        seen_cfn.add(cfn)
        out.append({
            "cfn": cfn,
            "recording_date": rec_date,
            "doc_type": doc_type or "LIS PENDENS",
            "first_party": first_party,
            "second_party": second_party,
        })

    return out
