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
