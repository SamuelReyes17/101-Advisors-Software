"""
Miami-Dade Clerk OCS — browser-based search via Playwright.

The OCS API is protected by Google reCAPTCHA v3 (site key 6Le7np8qAAAAAAEMezDvhuXyKV4EA6BWZTvdK_E6).
Direct API calls return 400 "Captcha token is missing or invalid".
A real browser is required to execute the Google reCAPTCHA JS and obtain
a valid token. Playwright Chromium handles this transparently.

Flow per session:
    1. Open Chromium headless once
    2. Navigate to /ocs/#/Search → click "Party Name" option
    3. For each name: fill Last Name, click Search, wait for response
    4. Intercept GetMultipleCaseResult and parse JSON

Typical timing: ~3-5 seconds per lookup, browser stays open across all leads.

Usage:
    from pipeline.collectors.miami_clerk_browser import ClerkSession

    with ClerkSession() as session:
        cases_for_baez = session.search("BAEZ")
        cases_for_smith = session.search("SMITH")
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    raise ImportError(
        "Playwright is required. Run:\n"
        "  pip3 install playwright --break-system-packages\n"
        "  playwright install chromium"
    )

log = logging.getLogger(__name__)

OCS_SEARCH_URL = "https://www2.miamidadeclerk.gov/ocs/#/Search"

# Strict foreclosure keywords — must appear in caseType text.
# We deliberately EXCLUDE:
#   - "Consumer Debt" (credit card debt, not real property)
#   - "Replevin" (recovery of personal property — usually cars, not real estate)
FORECLOSURE_KEYWORDS = (
    "FORECLOSURE",        # Mortgage Foreclosure, Foreclosure Residential, etc.
    "LIS PENDENS",        # Lis Pendens filings
    "REAL PROPERTY",      # Real property disputes
    "QUIET TITLE",        # Title disputes
)

# Case types to EXCLUDE even if a bank is plaintiff (these are NOT foreclosures)
EXCLUDE_PATTERNS = (
    "CONSUMER DEBT",      # Credit card debt
    "AUTO NEGLIGENCE",    # Car accidents
    "DOMESTIC",           # Family law
    "DIVORCE", "DISS OF MARRIAGE",
    "PERSONAL INJURY", "AUTO TORT",
    "PROBATE", "ESTATE", "GUARDIAN",
    "SP",                 # Small claims (most are debt)
    # Legacy cases — Clerk marks these with "z DO NOT USE" prefix
    # to indicate they're historical records, often pre-2010.
    "Z DO NOT USE", "Z LEGACY", "Z OLD", "LEGACY",
)

import re


def parse_case_style(case_style: str) -> tuple[str, str]:
    """Parse 'Plaintiff\\nvs\\nDefendant' → (plaintiff, defendant)."""
    if not case_style:
        return "", ""
    for sep in ("\nvs\n", "\n vs \n", "\nVS\n", " vs ", " VS "):
        if sep in case_style:
            parts = case_style.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", case_style.strip()


def is_foreclosure_case(case: dict) -> bool:
    """Strict match: caseType must contain a foreclosure keyword AND no
    exclusion keyword."""
    ct = (case.get("caseType") or "").upper()
    if not ct:
        return False
    # Hard exclude
    if any(ex in ct for ex in EXCLUDE_PATTERNS):
        return False
    # Match foreclosure
    return any(kw in ct for kw in FORECLOSURE_KEYWORDS)


class ClerkSession:
    """A single Playwright browser session for searching the Clerk multiple times.

    Designed to be used as a context manager:

        with ClerkSession() as session:
            for name in names:
                cases = session.search(name)
                ...
    """

    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self.headless = headless
        self.slow_mo = slow_mo
        self._playwright = None
        self._browser = None
        self._context = None
        self._page: Page | None = None

    def __enter__(self) -> "ClerkSession":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )
        self._context = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0 Safari/537.36"),
            viewport={"width": 1400, "height": 900},
        )
        self._page = self._context.new_page()

        # Navigate to search page once
        log.info("Opening OCS search page...")
        self._page.goto(OCS_SEARCH_URL, wait_until="networkidle", timeout=30000)
        self._page.wait_for_timeout(3000)

        # Click the "Party Name" option in sidebar
        try:
            self._page.get_by_text("Party Name", exact=False).first.click()
            self._page.wait_for_timeout(2000)
            log.info("Clicked Party Name option")
        except Exception as e:
            log.warning("Couldn't click Party Name: %s", e)

        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    def _ensure_search_form(self):
        """Re-navigate to the Party Name search form. Called between searches
        so the form is ready for the next input. We do a hard navigation
        because in-app clicks from the results page are unreliable."""
        page = self._page
        try:
            # Hard reload to OCS search page
            page.goto(OCS_SEARCH_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(1500)
            # Click "Party Name" option in the sidebar
            page.get_by_text("Party Name", exact=False).first.click(timeout=5000)
            page.wait_for_timeout(2000)
            # Verify the Last Name input is now visible
            page.locator('input[id*="lastName" i]').first.wait_for(
                state="visible", timeout=5000
            )
        except Exception as e:
            log.warning("Couldn't navigate to search form: %s", e)

    def search(self, last_name: str, first_name: str = "",
               timeout_ms: int = 15000) -> list[dict[str, Any]]:
        """Search the Clerk for cases involving this party.

        Returns the raw caseListResult or [] on failure.
        """
        if not last_name or not self._page:
            return []

        page = self._page

        # Find Last Name input — if not visible, we're probably on results page
        last_input = None
        for sel in (
            'input[id*="lastName" i]',
            'input[formcontrolname*="last" i]',
            'input[placeholder*="Last" i]',
        ):
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    last_input = el
                    break
            except Exception:
                continue

        if not last_input:
            # Probably on results page — navigate back and try again
            log.debug("No Last Name input visible, navigating back to search form")
            self._ensure_search_form()
            for sel in (
                'input[id*="lastName" i]',
                'input[formcontrolname*="last" i]',
                'input[placeholder*="Last" i]',
            ):
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        last_input = el
                        break
                except Exception:
                    continue

        if not last_input:
            log.warning("Could not find Last Name input after re-nav")
            return []

        # Clear and fill
        try:
            last_input.click()
            last_input.fill("")
            page.wait_for_timeout(200)
            last_input.fill(last_name.strip().upper())
        except Exception as e:
            log.warning("Couldn't fill Last Name: %s", e)
            return []

        # Optional first name
        if first_name:
            for sel in (
                'input[id*="firstName" i]',
                'input[formcontrolname*="first" i]',
                'input[placeholder*="First" i]',
            ):
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        el.fill("")
                        el.fill(first_name.strip().upper())
                        break
                except Exception:
                    continue

        # Click Search button while waiting for the case result response
        try:
            with page.expect_response(
                lambda r: "GetMultipleCaseResult" in r.url,
                timeout=timeout_ms,
            ) as resp_info:
                # Find and click the Search button
                clicked = False
                for label in ("Search", "Find", "Submit"):
                    try:
                        btn = page.get_by_role("button", name=label).first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    # Fallback: press Enter on the last name input
                    last_input.press("Enter")

            response = resp_info.value
            data = response.json()
            cases = data.get("caseListResult") or []
            log.info("Search '%s' → %d cases", last_name, len(cases))
            return cases
        except Exception as e:
            log.warning("Clerk search for '%s' failed: %s", last_name, e)
            return []

    def get_case_detail(self, case_id: int | str,
                        timeout_ms: int = 20000) -> dict[str, Any] | None:
        """Fetch the full case detail (parties, attorneys, hearings) for one case.

        Uses the same Playwright page (cookies + recaptcha already set up).
        Internally calls:
            POST /ocs/api/CaseInfo/PostSearchByCaseID?caseID=X
            GET  /ocs/api/CaseInfo/GetSingleCaseResult?qs=...

        Returns parsed dict with:
            plaintiff_name, plaintiff_attorney, plaintiff_attorney_bar
            defendant_name, defendant_attorney, defendant_attorney_bar
            judge_name, court_location, disposition_date
            next_hearing_date, next_hearing_time, next_hearing_type
        """
        if not case_id or not self._page:
            return None
        page = self._page

        # Use the browser's fetch to call the endpoints (preserves cookies + captcha).
        # NOTE: PostSearchByCaseID returns the qs token as PLAIN TEXT (not JSON),
        # different from PostSearchByPartyName which wraps it in {success, qs}.
        try:
            result = page.evaluate(
                """
                async (caseId) => {
                    // Step 1: POST returns the encrypted qs as plain text
                    const postResp = await fetch(
                        `/ocs/api/CaseInfo/PostSearchByCaseID?caseID=${caseId}`,
                        { method: 'POST', credentials: 'include' }
                    );
                    if (!postResp.ok) return { error: 'POST failed', status: postResp.status };
                    let qs = (await postResp.text()).trim();
                    // Strip surrounding quotes if the server wrapped the string
                    if (qs.startsWith('"') && qs.endsWith('"')) {
                        qs = qs.slice(1, -1);
                    }
                    if (!qs) return { error: 'Empty qs from POST' };

                    // Step 2: GET case detail with the qs token
                    const getResp = await fetch(
                        `/ocs/api/CaseInfo/GetSingleCaseResult?qs=${encodeURIComponent(qs)}`,
                        { credentials: 'include' }
                    );
                    if (!getResp.ok) return { error: 'GET failed', status: getResp.status };
                    return await getResp.json();
                }
                """,
                case_id,
            )
        except Exception as e:
            log.warning("Case detail fetch failed for %s: %s", case_id, e)
            return None

        if not result or result.get("error"):
            log.debug("Case detail error for %s: %s", case_id, result)
            return None

        # Parse parties — find plaintiff + defendant + their attorneys
        plaintiff_name = ""
        plaintiff_attorney = ""
        plaintiff_attorney_bar = ""
        defendant_name = ""
        defendant_attorney = ""
        defendant_attorney_bar = ""

        for party in result.get("parties") or []:
            ptype = (party.get("partyTypeCode") or "").upper()
            if ptype == "PN":  # Plaintiff
                if not plaintiff_name:
                    plaintiff_name = party.get("partyName", "")
                    plaintiff_attorney = party.get("leadAttName", "")
                    plaintiff_attorney_bar = party.get("leadAttBarnumber", "")
            elif ptype == "DN":  # Defendant
                if not defendant_name:
                    defendant_name = party.get("partyName", "")
                    defendant_attorney = party.get("leadAttName", "")
                    defendant_attorney_bar = party.get("leadAttBarnumber", "")

        # Find the NEXT hearing (or most recent if all past)
        hearings = result.get("hearings") or []
        next_hearing_date = ""
        next_hearing_time = ""
        next_hearing_type = ""
        judge_name = ""
        if hearings:
            # Sort by courtSessionDate descending (most recent first)
            # Then optionally find the next future one
            from datetime import datetime as _dt
            today = _dt.today()
            future_hearings = []
            past_hearings = []
            for h in hearings:
                date_str = h.get("courtSessionDate", "")
                try:
                    h_date = _dt.strptime(date_str, "%m/%d/%Y")
                    if h_date >= today:
                        future_hearings.append((h_date, h))
                    else:
                        past_hearings.append((h_date, h))
                except Exception:
                    pass
            if future_hearings:
                future_hearings.sort(key=lambda x: x[0])
                _, h = future_hearings[0]
            elif past_hearings:
                past_hearings.sort(key=lambda x: x[0], reverse=True)
                _, h = past_hearings[0]
            else:
                h = hearings[0]
            next_hearing_date = h.get("courtSessionDate", "")
            next_hearing_time = h.get("hearingTime", "").strip()
            next_hearing_type = h.get("hearingTypeDesc", "")
            judge_name = h.get("judgeName", "")

        return {
            "plaintiff_name":          plaintiff_name,
            "plaintiff_attorney":      plaintiff_attorney,
            "plaintiff_attorney_bar":  plaintiff_attorney_bar,
            "defendant_name":          defendant_name,
            "defendant_attorney":      defendant_attorney,
            "defendant_attorney_bar":  defendant_attorney_bar,
            "judge_name":              judge_name,
            "court_location":          result.get("courtLocation", ""),
            "disposition_date":        result.get("dispositionDate", ""),
            "next_hearing_date":       next_hearing_date,
            "next_hearing_time":       next_hearing_time,
            "next_hearing_type":       next_hearing_type,
        }

    def find_foreclosure(self, last_name: str, first_name: str = "",
                          cases: list[dict] | None = None) -> dict | None:
        """Find the most-recent foreclosure-related case for this party.

        Optional `cases` parameter avoids re-querying (use the cases from
        a previous .search() call).
        """
        if cases is None:
            cases = self.search(last_name, first_name)
        foreclosure_cases = [c for c in cases if is_foreclosure_case(c)]
        if not foreclosure_cases:
            return None
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
# Smoke test — run with a name as argument
# =========================================================================
if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test_name = sys.argv[1] if len(sys.argv) > 1 else "BAEZ"
    print(f"\n🔍 Searching Clerk for: {test_name}")

    with ClerkSession() as session:
        all_cases = session.search(test_name)
        print(f"\n✅ Found {len(all_cases)} total cases")

        foreclosure = [c for c in all_cases if is_foreclosure_case(c)]
        print(f"   ↳ {len(foreclosure)} foreclosure-related\n")

        for c in foreclosure[:5]:
            plaintiff, defendant = parse_case_style(c.get("caseStyle", ""))
            print(f"  📋 {c.get('caseNumber')} ({c.get('filingDate')})")
            print(f"     Type: {c.get('caseType')}")
            print(f"     Plaintiff: {plaintiff[:60]}")
            print(f"     Defendant: {defendant[:60]}")
            print(f"     Status: {c.get('caseStatus')}")
            print()

        print("\nFind foreclosure helper (reusing cases from above):")
        result = session.find_foreclosure(test_name, cases=all_cases)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("  (none found)")

        # NEW: test case detail fetch for the found case
        if result and result.get("case_id"):
            print(f"\n--- Fetching case detail for caseID={result['case_id']} ---")
            detail = session.get_case_detail(result["case_id"])
            if detail:
                print(json.dumps(detail, indent=2))
            else:
                print("  (no detail returned)")
