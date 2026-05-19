"""
Florida Division of Corporations (Sunbiz) scraper — Playwright-based.

The plain `requests` approach hits HTTP 403 (Sunbiz has an aggressive WAF).
Playwright runs a real Chromium that loads cookies / JS-challenge tokens
automatically, so we don't get blocked.

For every Lis Pendens lead where the property OWNER is an LLC / Corp / Trust,
we query sunbiz.org to surface:
    - PRINCIPAL OFFICERS (the real humans behind the entity)
    - REGISTERED AGENT
    - PRINCIPAL + MAILING addresses
    - Status (ACTIVE / INACTIVE / DISSOLVED)

Usage:
    from pipeline.collectors.sunbiz import SunbizSession

    with SunbizSession() as s:
        for llc in llc_names:
            info = s.lookup(llc)
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    sync_playwright = None
    Page = Any  # type: ignore

log = logging.getLogger(__name__)

SEARCH_HOME = "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName"
SEARCH_RESULTS = (
    "https://search.sunbiz.org/Inquiry/CorporationSearch/"
    "SearchResults?inquiryType=EntityName&searchNameOrder={query}"
)


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _entity_search_key(name: str) -> str:
    """Sunbiz expects the search term URL-encoded, uppercased, no punctuation."""
    cleaned = re.sub(r"[,\.\(\)/]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    return urllib.parse.quote_plus(cleaned)


class SunbizSession:
    """A reusable Playwright browser session for Sunbiz lookups.

    Reuses the same Chromium tab across queries so cookies / WAF tokens
    persist. ~2-4 seconds per lookup.
    """

    def __init__(self, headless: bool = True):
        if sync_playwright is None:
            raise ImportError(
                "playwright not installed. Run:\n"
                "  pip3 install playwright --break-system-packages\n"
                "  python3 -m playwright install chromium"
            )
        self.headless = headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page: Page | None = None

    def __enter__(self) -> "SunbizSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            viewport={"width": 1200, "height": 800},
        )
        self._page = self._ctx.new_page()
        # Visit the home page once to seed cookies and any WAF tokens
        log.info("Initializing Sunbiz session (visiting home page) …")
        self._page.goto(SEARCH_HOME, wait_until="domcontentloaded", timeout=20000)
        self._page.wait_for_timeout(1500)
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def lookup(self, entity_name: str, settle_ms: int = 800) -> dict[str, Any] | None:
        """Search Sunbiz for an LLC/Corp by name, return its public record.

        Returns None on miss or error.
        """
        if not self._page or not entity_name:
            return None
        page = self._page

        query = _entity_search_key(entity_name)
        if not query:
            return None

        # ── Navigate to results page directly via GET URL ──
        results_url = SEARCH_RESULTS.format(query=query)
        try:
            page.goto(results_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            log.warning("Sunbiz goto failed for %r: %s", entity_name, e)
            return None
        page.wait_for_timeout(settle_ms)

        # ── Pick the best matching entity row ──
        # The results page has a table with rows: <a>Name</a> | Type | Status
        detail_url = self._pick_best_match(entity_name)
        if not detail_url:
            log.info("Sunbiz: no results for %r", entity_name)
            return None

        # ── Navigate to entity detail page ──
        try:
            page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            log.warning("Sunbiz detail goto failed for %r: %s", entity_name, e)
            return None
        page.wait_for_timeout(settle_ms)

        return self._parse_entity_detail()

    # ── Internal helpers ────────────────────────────────────────────────
    def _pick_best_match(self, query_name: str) -> str | None:
        """From the search-results page, find the link to the best matching entity."""
        page = self._page
        q_norm = re.sub(r"[^A-Z0-9 ]", "", query_name.upper()).strip()
        try:
            rows = page.evaluate(
                """
                () => {
                    const out = [];
                    document.querySelectorAll('table tr').forEach(tr => {
                        const link = tr.querySelector('a');
                        if (!link) return;
                        const href = link.getAttribute('href') || '';
                        if (!href.includes('SearchResultDetail')) return;
                        const cells = Array.from(tr.querySelectorAll('td')).map(td => (td.innerText||'').trim());
                        out.push({
                            name: (link.innerText || '').trim(),
                            href: link.getAttribute('href'),
                            status: cells.length > 2 ? cells[2] : '',
                        });
                    });
                    return out;
                }
                """
            )
        except Exception as e:
            log.warning("Sunbiz results-parse failed: %s", e)
            return None

        if not rows:
            return None

        # 1) Exact name match (preferring ACTIVE)
        exact = [r for r in rows
                 if re.sub(r"[^A-Z0-9 ]","", (r["name"] or "").upper()).strip() == q_norm]
        if exact:
            active = [r for r in exact if "ACTIVE" in (r.get("status","") or "").upper()]
            best = (active or exact)[0]
        else:
            active = [r for r in rows if "ACTIVE" in (r.get("status","") or "").upper()]
            best = (active or rows)[0]

        href = best["href"]
        if href.startswith("/"):
            return f"https://search.sunbiz.org{href}"
        return href

    def _parse_entity_detail(self) -> dict[str, Any]:
        """Pull the entity detail off the current page."""
        page = self._page
        try:
            data = page.evaluate(
                """
                () => {
                    const out = {
                        entity_name: '',
                        document_number: '',
                        filing_date: '',
                        state: '',
                        status: '',
                        principal_address: '',
                        mailing_address: '',
                        registered_agent: '',
                        ra_address: '',
                        officers: [],
                    };

                    // Entity name (in a top heading)
                    const titleEl = document.querySelector(
                        'div.searchTitleSection, div.detail-header, h3, h2'
                    );
                    out.entity_name = (titleEl ? titleEl.innerText : '').trim();

                    // Helper: find label "X" and return value of the next sibling block
                    const valueFor = (label) => {
                        const nodes = document.querySelectorAll('span,label,div,th,td');
                        for (const n of nodes) {
                            const t = (n.innerText || '').trim();
                            if (t === label || t.startsWith(label)) {
                                // Try sibling
                                let v = n.nextElementSibling;
                                if (v && v.innerText) {
                                    const txt = v.innerText.trim();
                                    if (txt) return txt;
                                }
                                // Try parent's next
                                if (n.parentElement) {
                                    const pn = n.parentElement.nextElementSibling;
                                    if (pn && pn.innerText) {
                                        const txt = pn.innerText.trim();
                                        if (txt) return txt;
                                    }
                                }
                            }
                        }
                        return '';
                    };

                    out.document_number = valueFor('Document Number');
                    out.filing_date     = valueFor('Date Filed');
                    out.state           = valueFor('State');
                    out.status          = valueFor('Status');

                    // Principal / Mailing addresses + Registered Agent
                    // The detail page uses <div class="detailSection"> blocks
                    // each with a header <span class="popupTriggerHorizontal">
                    document.querySelectorAll('div.detailSection, .detailSection, .detail-section').forEach(sec => {
                        const heading = (sec.querySelector('span') || sec.querySelector('h4') || {}).innerText || '';
                        const text = (sec.innerText || '').replace(/^[^\\n]+\\n/, '').trim();
                        if (heading.includes('Principal Address')) {
                            out.principal_address = text;
                        } else if (heading.includes('Mailing Address')) {
                            out.mailing_address = text;
                        } else if (heading.includes('Registered Agent Name & Address')) {
                            // First line is the name, the rest is the address
                            const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                            if (lines.length >= 1) {
                                out.registered_agent = lines[0];
                                out.ra_address = lines.slice(1).join(', ');
                            }
                        } else if (heading.includes('Officer/Director Detail')) {
                            // Sequence of (Title <TITLE>, <NAME>, <ADDR1>, <ADDR2>)
                            const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                            let i = 0;
                            while (i < lines.length) {
                                const titleMatch = lines[i].match(/^Title\\s+(.+)$/);
                                if (titleMatch) {
                                    const title = titleMatch[1].trim();
                                    const name = lines[i+1] || '';
                                    const a1 = lines[i+2] || '';
                                    const a2 = lines[i+3] || '';
                                    const a3 = lines[i+4] || '';
                                    // Address typically 2-3 lines (street / city,state zip / country)
                                    const addr = [a1, a2, a3].filter(Boolean).join(', ');
                                    if (name && !/^Title\\s+/.test(name)) {
                                        out.officers.push({title, name, address: addr});
                                        i += 5;
                                        continue;
                                    }
                                }
                                i += 1;
                            }
                        }
                    });

                    return out;
                }
                """
            )
        except Exception as e:
            log.warning("Sunbiz detail-parse failed: %s", e)
            return {}

        # Normalize whitespace in every string
        out: dict[str, Any] = {}
        for k, v in (data or {}).items():
            if isinstance(v, str):
                out[k] = _norm(v)
            elif isinstance(v, list):
                out[k] = [
                    {kk: _norm(vv) for kk, vv in item.items()}
                    for item in v if isinstance(item, dict)
                ]
            else:
                out[k] = v
        return out


# Backwards-compatible single-shot helper
def lookup_entity(entity_name: str, session=None, sleep_after: float = 0.0):
    """One-off lookup. Less efficient than reusing a SunbizSession."""
    if session is not None:
        # Old-style requests-based session passed in — caller probably has
        # an old script. Open a fresh Playwright session anyway.
        pass
    with SunbizSession(headless=True) as s:
        return s.lookup(entity_name)
