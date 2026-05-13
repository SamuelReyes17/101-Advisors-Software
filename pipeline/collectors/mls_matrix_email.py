"""
SEF MLS Matrix — Email-based collector.

Strategy:
    1. Matrix sends daily emails for each Saved Search.
    2. Those emails arrive at samuelreyesespinal02+101mls@gmail.com.
    3. A Gmail filter labels them "101 Advisors MLS".
    4. This collector logs into Gmail via IMAP (using App Password),
       reads UNREAD emails with that label, parses listings, marks as read.

Schema in the typical Matrix email:
    - Subject like "Matrix: 101 Advisors - REO" indicates category.
    - HTML body contains a table or list of listings.
    - Each listing has: MLS#, Address, Price, Bedrooms, Bathrooms, Sqft,
      DOM, Photos link, Listing Agent.

Required environment variables (set in GitHub Secrets):
    GMAIL_USER         → samuelreyesespinal02@gmail.com
    GMAIL_APP_PASSWORD → 16-character app password (from Google Account)
    GMAIL_LABEL        → "101 Advisors MLS" (or whatever label you set)

USAGE:
    from pipeline.collectors.mls_matrix_email import MLSMatrixEmailCollector

    collector = MLSMatrixEmailCollector(config)
    for lead in collector.fetch():
        print(lead.property_address)
"""
from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import date, datetime
from email.header import decode_header
from typing import Iterable

from .base import Collector, Lead

log = logging.getLogger(__name__)

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993


# =========================================================================
# Email reading via IMAP
# =========================================================================
def _connect_gmail() -> imaplib.IMAP4_SSL | None:
    """Connect to Gmail IMAP. Returns None if credentials missing."""
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        log.warning(
            "GMAIL_USER or GMAIL_APP_PASSWORD not set. "
            "Cannot fetch MLS Matrix emails. Skipping collector."
        )
        return None

    try:
        conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        conn.login(user, password)
        return conn
    except Exception as e:
        log.error("Gmail IMAP login failed: %s", e)
        return None


def _list_unread_emails(conn: imaplib.IMAP4_SSL, label: str) -> list[bytes]:
    """Return UIDs of UNREAD emails in the given Gmail label."""
    # Gmail labels are folders accessed via IMAP. Special chars need quoting.
    folder = f'"{label}"' if " " in label else label
    status, _ = conn.select(folder)
    if status != "OK":
        # Fallback: try INBOX with from:@matrix sender filter
        log.warning("Could not select label '%s'. Falling back to INBOX.", label)
        conn.select("INBOX")
        status, data = conn.search(None, '(UNSEEN FROM "matrix")')
    else:
        status, data = conn.search(None, "UNSEEN")

    if status != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _fetch_email(conn: imaplib.IMAP4_SSL, uid: bytes) -> email.message.Message | None:
    """Fetch a single email by UID."""
    status, data = conn.fetch(uid, "(RFC822)")
    if status != "OK" or not data or not data[0]:
        return None
    raw = data[0][1]
    return email.message_from_bytes(raw)


def _mark_as_read(conn: imaplib.IMAP4_SSL, uid: bytes) -> None:
    """Mark email as read so we don't process it twice."""
    conn.store(uid, "+FLAGS", "\\Seen")


def _decode_subject(msg: email.message.Message) -> str:
    raw = msg.get("Subject", "")
    decoded = decode_header(raw)
    parts = []
    for text, charset in decoded:
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", errors="ignore"))
            except (LookupError, UnicodeDecodeError):
                parts.append(text.decode("utf-8", errors="ignore"))
        else:
            parts.append(text)
    return " ".join(parts).strip()


def _extract_html_body(msg: email.message.Message) -> str:
    """Extract HTML body from a multipart email."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="ignore")
        # Fallback to plain text
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="ignore")
        return ""

    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="ignore")
    return str(payload or "")


# =========================================================================
# HTML parsing — extract listings from a Matrix email body
# =========================================================================
def _category_from_subject(subject: str) -> str:
    """Detect category from email subject. E.g. '101 Advisors - REO' → 'Foreclosure'."""
    s = subject.upper()
    if "REO" in s or "BANK-OWNED" in s or "BANK OWNED" in s:
        return "Foreclosure"
    if "SHORT SALE" in s or "SHORTSALE" in s:
        return "Short Sale"
    if "AUCTION" in s:
        return "Foreclosure"  # Auction = pre-foreclosure auction
    if "FORECLOSURE" in s:
        return "Foreclosure"
    return "Foreclosure"  # Default for any MLS distressed email


def _parse_listings(html: str, category: str, today: date) -> list[Lead]:
    """Extract Lead objects from a Matrix email HTML body.

    Matrix emails typically contain a TABLE with one row per listing.
    Each row has columns: MLS#, Status, Address, City, Zip, Beds, Baths,
    Sqft, Price, DOM, etc.

    This parser uses BeautifulSoup if available, falls back to regex.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("beautifulsoup4 not installed. Using regex fallback.")
        return _parse_listings_regex(html, category, today)

    soup = BeautifulSoup(html, "lxml")
    leads: list[Lead] = []

    # Strategy 1: Look for listing tables. Matrix typically renders each
    # listing as a table with a class like "listing" or in a structured layout.
    # Different MLS configurations vary, so we try multiple patterns.

    # Pattern A: rows in a single big table (most common for Matrix emails)
    rows = soup.find_all("tr")
    for row in rows:
        lead = _try_parse_row_as_listing(row, category, today)
        if lead:
            leads.append(lead)

    if leads:
        log.info("Parsed %d listings from email (table rows pattern)", len(leads))
        return leads

    # Pattern B: each listing in its own div/table block
    blocks = soup.find_all(["div", "table"], class_=re.compile(r"listing|property|item", re.I))
    for block in blocks:
        lead = _try_parse_block_as_listing(block, category, today)
        if lead:
            leads.append(lead)

    if leads:
        log.info("Parsed %d listings from email (block pattern)", len(leads))
        return leads

    # Pattern C: regex fallback on raw text
    return _parse_listings_regex(html, category, today)


def _try_parse_row_as_listing(row, category: str, today: date) -> Lead | None:
    """Try to extract a listing from one <tr>. Returns None if not a listing row."""
    text = row.get_text(" ", strip=True)
    if not text or len(text) < 20:
        return None

    # Look for MLS# pattern (Florida: typically letter + 6-8 digits, e.g. A11234567, F10987654)
    mls_match = re.search(r"\b([A-Z]\d{6,9})\b", text)
    if not mls_match:
        return None

    mls_id = mls_match.group(1)

    # Address pattern
    addr_match = re.search(
        r"(\d{1,6}\s+(?:NW|NE|SW|SE|N|S|E|W\s+)?[A-Za-z0-9 .,#-]+?"
        r"(?:ST|AVE|RD|BLVD|DR|CT|PL|LN|WAY|TER|HWY|CIR|PKWY)\b[^,]*)",
        text,
        re.IGNORECASE,
    )
    address = addr_match.group(1).strip() if addr_match else ""

    # Price
    price_match = re.search(r"\$([0-9,]+(?:\.\d{2})?)", text)
    price = float(price_match.group(1).replace(",", "")) if price_match else 0.0

    # Beds / Baths (e.g. "3/2" or "3 BR / 2 BA")
    beds_match = re.search(r"\b(\d+)\s*(?:BR|/|bd|bed)", text, re.IGNORECASE)
    beds = int(beds_match.group(1)) if beds_match else 0

    # City + Zip — extract from address tail
    city, zip_code = _extract_city_zip(text, address)

    if not address:
        return None

    return Lead(
        lead_id=f"MLS-{mls_id}",
        first_seen=today,
        last_updated=today,
        county=_county_from_zip(zip_code) if zip_code else "",
        category=category,
        property_address=address,
        city=city,
        zip=zip_code,
        bedrooms=beds,
        outstanding_debt=price,  # asking price ≈ proxy for debt
        notes=f"MLS# {mls_id} via Matrix email",
        source="mls_matrix_email",
    )


def _try_parse_block_as_listing(block, category: str, today: date) -> Lead | None:
    """Similar to row parser but for div/block layout."""
    return _try_parse_row_as_listing(block, category, today)


def _parse_listings_regex(html: str, category: str, today: date) -> list[Lead]:
    """Last resort regex parser for when BS4 fails."""
    leads = []
    seen_mls = set()

    # Find all MLS#s as anchors and capture surrounding text
    text = re.sub(r"<[^>]+>", " ", html)  # strip HTML tags
    text = re.sub(r"\s+", " ", text)

    for match in re.finditer(r"\b([A-Z]\d{6,9})\b", text):
        mls_id = match.group(1)
        if mls_id in seen_mls:
            continue
        seen_mls.add(mls_id)

        # Look around the MLS# for context
        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 200)
        context = text[start:end]

        addr_match = re.search(
            r"(\d{1,6}\s+[A-Za-z0-9 .,#-]+?(?:ST|AVE|RD|BLVD|DR|CT|PL|LN|WAY|TER)\b[^,]*)",
            context,
            re.IGNORECASE,
        )
        if not addr_match:
            continue

        leads.append(
            Lead(
                lead_id=f"MLS-{mls_id}",
                first_seen=today,
                last_updated=today,
                county="",
                category=category,
                property_address=addr_match.group(1).strip(),
                city="",
                zip="",
                notes=f"MLS# {mls_id} (regex fallback)",
                source="mls_matrix_email",
            )
        )
    return leads


# =========================================================================
# Helpers
# =========================================================================
def _extract_city_zip(text: str, address: str) -> tuple[str, str]:
    """Find city + zip after the address in the row text."""
    after_addr = ""
    if address and address in text:
        after_addr = text.split(address, 1)[1]
    else:
        after_addr = text

    # ZIP is easy: 5 digits
    zip_match = re.search(r"\b(\d{5})\b", after_addr)
    zip_code = zip_match.group(1) if zip_match else ""

    # City: between address and FL/zip
    city_match = re.search(r",?\s*([A-Z][a-zA-Z .]+?)(?:,?\s+FL)?\s+\d{5}", after_addr)
    city = city_match.group(1).strip() if city_match else ""
    return city, zip_code


# Miami-Dade ZIPs start with 331-, 332-, 333- (parts)
# Broward ZIPs: 330-, 333-
# Palm Beach ZIPs: 334-
def _county_from_zip(zip_code: str) -> str:
    """Heuristic — accurate enough for tri-county Florida."""
    if not zip_code or len(zip_code) < 3:
        return ""
    prefix = zip_code[:3]
    miami_dade = {"331", "332"}
    broward = {"330", "333"}
    palm_beach = {"334"}
    if prefix in miami_dade:
        return "Miami-Dade"
    if prefix in broward:
        return "Broward"
    if prefix in palm_beach:
        return "Palm Beach"
    return ""


# =========================================================================
# Collector class
# =========================================================================
class MLSMatrixEmailCollector(Collector):
    """Collector that reads SEF MLS Matrix email alerts from Gmail."""

    name = "mls_matrix_email"
    county = "Multi"
    category = "Foreclosure"  # Default, overridden per email

    def fetch(self) -> Iterable[Lead]:
        conn = _connect_gmail()
        if not conn:
            return

        label = os.environ.get("GMAIL_LABEL", "101 Advisors MLS")
        uids = _list_unread_emails(conn, label)
        log.info("Found %d unread emails in label '%s'", len(uids), label)

        today = date.today()
        all_leads: list[Lead] = []

        for uid in uids:
            msg = _fetch_email(conn, uid)
            if not msg:
                continue

            subject = _decode_subject(msg)
            log.info("Processing email: %s", subject[:80])

            category = _category_from_subject(subject)
            html = _extract_html_body(msg)
            if not html:
                log.warning("No HTML body found in email '%s'", subject)
                continue

            leads = _parse_listings(html, category, today)
            log.info("  → extracted %d listings", len(leads))
            all_leads.extend(leads)

            # Mark as read so we don't process again tomorrow
            _mark_as_read(conn, uid)

        conn.logout()

        # Deduplicate by lead_id (same listing might appear in multiple emails)
        seen: set[str] = set()
        for lead in all_leads:
            if lead.lead_id in seen:
                continue
            seen.add(lead.lead_id)
            yield lead


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print("Testing MLSMatrixEmailCollector...")
    print(f"GMAIL_USER: {os.environ.get('GMAIL_USER', '(not set)')}")
    print(f"GMAIL_APP_PASSWORD: {'(set)' if os.environ.get('GMAIL_APP_PASSWORD') else '(not set)'}")
    print(f"GMAIL_LABEL: {os.environ.get('GMAIL_LABEL', '101 Advisors MLS')}")
    print()

    collector = MLSMatrixEmailCollector({})
    leads = list(collector.fetch())
    print(f"\nExtracted {len(leads)} leads:")
    for lead in leads[:5]:
        print(f"  • {lead.lead_id} · {lead.property_address}, {lead.city} {lead.zip} · {lead.category}")
    if len(leads) > 5:
        print(f"  ... and {len(leads) - 5} more")
