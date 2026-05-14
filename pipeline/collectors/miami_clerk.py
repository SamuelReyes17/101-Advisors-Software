"""
Miami-Dade Clerk of Court — case search via OCS API.

Endpoints (discovered via Playwright XHR capture in probe_clerk_v2.py):
    POST /ocs/api/CaseInfo/PostSearchByPartyName
        body: {"sC_partyName1": "BAEZ", ...}
        returns: {"success": true, "qs": "<encrypted_token>"}

    GET /ocs/api/CaseInfo/GetMultipleCaseResult?qs=<token>
        returns: {"caseListResult": [<cases>], ...}

Each case has:
    caseNumber, filingDate, caseStyle ("Plaintiff\\nvs\\nDefendant"),
    caseType, caseTypeCode, caseStatus, courtLocation, juditialSection

Usage:
    from pipeline.collectors.miami_clerk import search_cases, find_foreclosure_case

    cases = search_cases("BAEZ")
    foreclosure = find_foreclosure_case("BAEZ")  # returns most recent foreclosure-type case
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

log = logging.getLogger(__name__)

POST_URL = "https://www2.miamidadeclerk.gov/ocs/api/CaseInfo/PostSearchByPartyName"
GET_URL = "https://www2.miamidadeclerk.gov/ocs/api/CaseInfo/GetMultipleCaseResult"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www2.miamidadeclerk.gov",
    "Referer": "https://www2.miamidadeclerk.gov/ocs/",
}

# Case types that indicate foreclosure or Lis Pendens activity.
# We match against caseType (text) since caseTypeCode varies per case category.
FORECLOSURE_KEYWORDS = (
    "FORECLOSURE", "LIS PENDENS", "MORTGAGE", "REAL ESTATE",
    "QUIET TITLE", "RECEIVERSHIP",
)

# Plaintiff name patterns that indicate a bank/lender
BANK_PATTERNS = re.compile(
    r"\b(BANK|MORTGAGE|TRUST|TRUSTEE|N\.?A\.?|JPMORGAN|CHASE|"
    r"WELLS FARGO|US BANK|CITIBANK|BANK OF AMERICA|FEDERAL|"
    r"FANNIE|FREDDIE|HSBC|WILMINGTON|DEUTSCHE|HOA|ASSOCIATION|CONDOMINIUM)\b",
    re.IGNORECASE,
)


def _make_session() -> requests.Session:
    """Create a session with cookies seeded by visiting the OCS home page
    + the settings endpoints. Without this, the search POST may fail or
    return 0 results because the server expects an active session."""
    s = requests.Session()
    s.headers.update(HEADERS)
    # Establish session by hitting home page and supporting endpoints
    try:
        s.get("https://www2.miamidadeclerk.gov/ocs/", timeout=15)
        s.get("https://www2.miamidadeclerk.gov/ocs/api/home/UserLogin", timeout=15)
        s.get("https://www2.miamidadeclerk.gov/ocs/api/home/PageStatus", timeout=15)
        s.get("https://www2.miamidadeclerk.gov/ocs/api/home/OCSTypes", timeout=15)
        s.get("https://www2.miamidadeclerk.gov/ocs/api/settings/basketcounter", timeout=15)
        s.get("https://www2.miamidadeclerk.gov/ocs/api/settings/loggedin?requestUserInfo=true",
              timeout=15)
    except Exception as e:
        log.debug("Session warm-up failed: %s", e)
    return s


def search_cases(party_name: str, party_name_2: str = "",
                 case_type_code: str | None = None,
                 timeout: int = 20,
                 session: requests.Session | None = None,
                 verbose: bool = False) -> list[dict[str, Any]]:
    """Search Miami-Dade Clerk for cases involving this party.

    `party_name` is matched as Last Name for people, or as part of the
    entity name for LLCs / corps. The Clerk API does a fuzzy match.

    For batch operations, pass a pre-warmed `session` to avoid re-establishing
    cookies on every call.

    Returns a list of case dicts, or [] on failure or no results.
    """
    if not party_name:
        return []

    s = session or _make_session()

    body = {
        "sC_partyName1": party_name.strip().upper(),
        "sC_partyName2": (party_name_2 or "").strip().upper(),
        "sC_partyType": "",
        "sC_dateFrom": "0001-01-01T00:00:00",
        "sC_dateTo": "0001-01-01T00:00:00",
        "sC_caseType": case_type_code,
        "sC_section": None,
    }

    # Step 1: POST to get encrypted query string
    try:
        r = s.post(POST_URL, json=body, timeout=timeout)
        if verbose:
            print(f"  POST {POST_URL}")
            print(f"  → HTTP {r.status_code}, body: {r.text[:300]}")
        r.raise_for_status()
        post_data = r.json()
    except Exception as e:
        if verbose:
            print(f"  ❌ POST exception: {e}")
        log.debug("Clerk POST failed for %s: %s", party_name, e)
        return []

    if not post_data.get("success"):
        if verbose:
            print(f"  ❌ success=false. message: {post_data.get('message')}")
        return []
    qs = post_data.get("qs")
    if not qs:
        if verbose:
            print(f"  ❌ no qs token in response")
        return []
    if verbose:
        print(f"  ✓ got qs token ({len(qs)} chars)")

    # Step 2: GET with the token to retrieve cases
    try:
        r = s.get(GET_URL, params={"qs": qs}, timeout=timeout)
        if verbose:
            print(f"  GET {GET_URL}?qs=...")
            print(f"  → HTTP {r.status_code}, len: {len(r.content)}")
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        if verbose:
            print(f"  ❌ GET exception: {e}")
        log.debug("Clerk GET failed for %s: %s", party_name, e)
        return []

    cases = result.get("caseListResult") or []
    if verbose:
        print(f"  ✓ caseListResult: {len(cases)} cases")
    return cases


def parse_case_style(case_style: str) -> tuple[str, str]:
    """Parse 'Plaintiff\\nvs\\nDefendant' → (plaintiff, defendant)."""
    if not case_style:
        return "", ""
    # The separator varies: '\nvs\n', '\n vs \n', ' vs ', etc.
    for sep in ("\nvs\n", "\n vs \n", "\nVS\n", " vs ", " VS "):
        if sep in case_style:
            parts = case_style.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", case_style.strip()


def is_foreclosure_case(case: dict) -> bool:
    """Check if a case is a foreclosure / Lis Pendens / mortgage case."""
    ct = (case.get("caseType") or "").upper()
    if any(kw in ct for kw in FORECLOSURE_KEYWORDS):
        return True
    # Also check the case style — if plaintiff looks like a bank, likely foreclosure
    style = (case.get("caseStyle") or "").upper()
    plaintiff, _ = parse_case_style(style)
    if plaintiff and BANK_PATTERNS.search(plaintiff):
        return True
    return False


def find_foreclosure_case(party_name: str, party_name_2: str = "") -> dict | None:
    """Find the most-recent foreclosure-related case for this party.

    Returns a normalized dict with the fields we care about:
        case_number, filing_date, plaintiff (the bank), defendant (the owner),
        case_type, case_status, court_location, judicial_section, attorney (None).

    Note: attorney info is in the case docket — we'd need a second API call
    to GetSingleCaseResult?caseID=... to fetch it. For v1 we just return
    plaintiff and case info; attorney comes via a separate detail lookup.
    """
    cases = search_cases(party_name, party_name_2)
    foreclosure_cases = [c for c in cases if is_foreclosure_case(c)]

    if not foreclosure_cases:
        return None

    # Pick the most recent one (highest filingDateSort)
    foreclosure_cases.sort(
        key=lambda c: c.get("filingDateSort") or "0001-01-01",
        reverse=True,
    )
    best = foreclosure_cases[0]
    plaintiff, defendant = parse_case_style(best.get("caseStyle", ""))
    return {
        "case_number":      best.get("caseNumber", ""),
        "filing_date":      best.get("filingDate", ""),
        "plaintiff":        plaintiff,
        "defendant":        defendant,
        "case_type":        best.get("caseType", ""),
        "case_type_code":   best.get("caseTypeCode", ""),
        "case_status":      best.get("caseStatus", ""),
        "court_location":   best.get("courtLocation", ""),
        "judicial_section": best.get("juditialSection", ""),
        "case_id":          best.get("caseID", ""),
    }


# =========================================================================
# Smoke test
# =========================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import json as _json
    import sys

    test_name = sys.argv[1] if len(sys.argv) > 1 else "BAEZ"
    print(f"\n🔍 Searching Clerk for: {test_name}")
    print(f"   (verbose mode — showing every API call)\n")

    all_cases = search_cases(test_name, verbose=True)
    print(f"\nFound {len(all_cases)} total cases")

    foreclosure = [c for c in all_cases if is_foreclosure_case(c)]
    print(f"  ↳ {len(foreclosure)} foreclosure-related\n")

    for c in foreclosure[:5]:
        plaintiff, defendant = parse_case_style(c.get("caseStyle", ""))
        print(f"  📋 {c.get('caseNumber')} ({c.get('filingDate')})")
        print(f"     Type: {c.get('caseType')}")
        print(f"     Plaintiff: {plaintiff}")
        print(f"     Defendant: {defendant}")
        print(f"     Status: {c.get('caseStatus')}")
        print(f"     Section: {c.get('juditialSection')}")
        print()

    # Test the high-level function
    print("\nTesting find_foreclosure_case:")
    result = find_foreclosure_case(test_name)
    if result:
        print(_json.dumps(result, indent=2))
    else:
        print("  (no foreclosure case found)")
