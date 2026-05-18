"""
Discover PURE Lis Pendens leads from Miami-Dade Clerk OCS.

Unlike scrape_clerk_for_leads.py (which matches existing MLS listings against
the Clerk), this script does the REVERSE flow:

    1. Search Miami-Dade Clerk OCS by common surnames → get all cases
    2. Filter to OPEN + Mortgage/Real Property Foreclosure cases filed
       in the last N days (configurable, default 60)
    3. For each case, fetch detail (attorney, FL Bar, judge, hearing date)
    4. Cross-reference defendant name with Property Appraiser to find their
       property address + folio
    5. Append to data/leads.csv as category="Lis Pendens", source="clerk-discovery"

These are the HOTTEST leads for 101 Advisors because:
    - Case is OPEN (still in court, no auction held)
    - Defendant still owns the property (no transfer yet)
    - Filing date < 60d means homeowner has 6-12 months window
    - We have attorney + judge + next hearing info from the Clerk

Usage:
    # Default — last 60 days, top 50 surnames
    python3 -m scripts.discover_lis_pendens

    # Custom date window
    python3 -m scripts.discover_lis_pendens --days 90

    # Specific surnames only (debug)
    python3 -m scripts.discover_lis_pendens --names GARCIA,RODRIGUEZ

    # Dry-run (no CSV write)
    python3 -m scripts.discover_lis_pendens --dry-run

Timing: ~5-8 sec per surname × 50-100 surnames ≈ 8-13 min for Clerk pass,
        + ~1-2 sec per match × ~150 matches ≈ 3-5 min for PA cross-ref.
        Total: 15-20 min.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.collectors.miami_clerk_browser import (
    ClerkSession, is_foreclosure_case, parse_case_style,
)
from pipeline.collectors.property_appraiser import search_by_owner_name
from pipeline.collectors.base import Lead

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("discover_lis_pendens")


# Top ~80 surnames common in Miami-Dade (US Census 2020 + local skew toward
# Hispanic and Caribbean populations). Covers ~70-75% of homeowners.
DEFAULT_SURNAMES = [
    # Hispanic
    "GARCIA","RODRIGUEZ","MARTINEZ","HERNANDEZ","LOPEZ","GONZALEZ","PEREZ",
    "SANCHEZ","DIAZ","FERNANDEZ","CRUZ","REYES","TORRES","RAMIREZ","FLORES",
    "RIVERA","GOMEZ","ALVAREZ","ROMERO","SUAREZ","CASTILLO","GUTIERREZ",
    "MORALES","ORTIZ","RUIZ","ALONSO","CASTRO","VARGAS","JIMENEZ","MENDOZA",
    "MEDINA","AGUILAR","SANTOS","DOMINGUEZ","PENA","DELGADO","MUNOZ","ROJAS",
    "MORENO","ACOSTA","ESPINOZA","HERRERA","SOTO","CABRERA","BAEZ","SALAZAR",
    "VEGA","CARDENAS","NAVARRO",
    # English (Miami-Dade still has substantial English-surname homeowners)
    "SMITH","JOHNSON","WILLIAMS","BROWN","JONES","MILLER","DAVIS","WILSON",
    "ANDERSON","TAYLOR","THOMAS","MOORE","JACKSON","MARTIN","WHITE","HARRIS",
    "THOMPSON","ROBINSON","CLARK","LEWIS",
    # Caribbean / Haitian
    "PIERRE","JOSEPH","JEAN","LOUIS","CHARLES","LAURENT","FRANCOIS",
]


def passes_strict_filter(case: dict[str, Any], days: int) -> bool:
    """Filter to ONLY:
        - 'Mortgage/Real Property Foreclosure' case types (not auto liens)
        - caseStatus == 'OPEN'
        - filingDate within last <days> days
        - NOT a legacy 'Z DO NOT USE' case
    """
    case_type = (case.get("caseType") or "").upper()
    if not case_type:
        return False
    if any(k in case_type for k in ("Z DO NOT USE", "Z LEGACY", "Z OLD", "LEGACY")):
        return False
    # Must be foreclosure / lis pendens
    if not is_foreclosure_case(case):
        return False
    # Status must be OPEN
    status = (case.get("caseStatus") or "").upper()
    if status != "OPEN":
        return False
    # Filing date must be recent
    filing_iso = case.get("filingDateSort") or ""
    if not filing_iso:
        return False
    try:
        filed = datetime.fromisoformat(filing_iso.replace("Z", "")[:10])
    except ValueError:
        return False
    cutoff = datetime.today() - timedelta(days=days)
    return filed >= cutoff


def _county_from_zip(zip_: str) -> str:
    """Very rough mapping — Miami-Dade ZIPs start with 330-332."""
    if not zip_:
        return ""
    z = zip_.strip()[:3]
    if z in ("330","331","332"):
        return "Miami-Dade"
    if z in ("333",):
        return "Broward"
    if z in ("334","335"):
        return "Palm Beach"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=60,
                        help="Look back this many days for filings (default: 60)")
    parser.add_argument("--names", default="",
                        help="Comma-separated surnames to use instead of default top-80")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to data/leads.csv, just print")
    parser.add_argument("--headed", action="store_true",
                        help="Show Chrome window (default: headless)")
    args = parser.parse_args()

    surnames = (
        [s.strip().upper() for s in args.names.split(",") if s.strip()]
        if args.names
        else DEFAULT_SURNAMES
    )

    print("=" * 70)
    print(f"Lis Pendens DISCOVERY — Miami-Dade Clerk")
    print(f"  Date window: last {args.days} days")
    print(f"  Surnames:    {len(surnames)}")
    print("=" * 70)

    # ── Phase 1: Clerk search by surname ────────────────────────────────
    all_matched_cases: list[dict[str, Any]] = []
    seen_case_numbers: set[str] = set()

    with ClerkSession(headless=not args.headed) as session:
        for i, surname in enumerate(surnames, 1):
            print(f"\n[{i:3d}/{len(surnames)}] Searching '{surname}' …", end="", flush=True)
            try:
                cases = session.search(surname)
            except Exception as e:
                print(f" ❌ {e}")
                continue
            if not cases:
                print(" no cases")
                continue
            # Filter
            relevant = [c for c in cases if passes_strict_filter(c, args.days)]
            new = [c for c in relevant if c.get("caseNumber") not in seen_case_numbers]
            for c in new:
                seen_case_numbers.add(c.get("caseNumber", ""))
            print(f" {len(cases)} total, {len(relevant)} match filter, "
                  f"{len(new)} new")
            all_matched_cases.extend(new)

        print(f"\n{'='*70}")
        print(f"Phase 1 complete: {len(all_matched_cases)} candidate cases")
        print("=" * 70)

        if not all_matched_cases:
            print("\nNo cases match. Try widening --days or adjusting --names.")
            return 0

        # ── Phase 2: Get case detail (attorney, judge, hearings) ──────
        print(f"\nPhase 2: Fetching case detail for {len(all_matched_cases)} cases …")
        for k, case in enumerate(all_matched_cases, 1):
            case_id = case.get("caseID")
            if not case_id:
                continue
            try:
                detail = session.get_case_detail(case_id)
            except Exception as e:
                log.warning("case_detail %s failed: %s", case_id, e)
                detail = None
            case["_detail"] = detail or {}
            if k % 10 == 0:
                print(f"  detail {k}/{len(all_matched_cases)}")

    # ── Phase 3: Cross-reference with Property Appraiser ───────────────
    print(f"\n{'='*70}")
    print(f"Phase 3: Cross-referencing defendants with Property Appraiser …")
    print("=" * 70)

    leads: list[Lead] = []
    no_property = 0
    today = date.today()

    for k, case in enumerate(all_matched_cases, 1):
        plaintiff, defendant = parse_case_style(case.get("caseStyle", ""))
        if not defendant:
            continue

        properties = search_by_owner_name(defendant, max_results=3)
        if not properties:
            no_property += 1
            if k % 20 == 0:
                print(f"  [{k}/{len(all_matched_cases)}] {defendant[:40]}: no PA match")
            continue

        # Build a Lead per property (defendant may own multiple)
        detail = case.get("_detail") or {}
        for prop in properties:
            if not prop.get("property_address") or not prop.get("zip"):
                continue
            mls_like = f"clerk-{case.get('caseNumber','')}-{prop.get('folio','')[:6]}"
            owner_full = prop.get("owner_name") or defendant
            # Split owner from PA's normal order
            owner_parts = owner_full.split()
            owner_first = owner_parts[0] if owner_parts else ""
            owner_last  = " ".join(owner_parts[1:]) if len(owner_parts) > 1 else ""

            zip_ = prop.get("zip") or ""
            county = _county_from_zip(zip_) or "Miami-Dade"

            lead = Lead(
                lead_id=mls_like,
                first_seen=today,
                last_updated=today,
                county=county,
                category="Lis Pendens",
                property_address=prop.get("property_address", ""),
                city=prop.get("city", ""),
                zip=zip_,
                folio=prop.get("folio", ""),
                property_type=prop.get("property_type", ""),
                units=int(prop.get("units") or 0),
                bedrooms=int(prop.get("bedrooms") or 0),
                owner_first=owner_first,
                owner_last=owner_last,
                lender_name=plaintiff,
                status="New",
                notes=(
                    f"Case {case.get('caseNumber','')} OPEN · "
                    f"filed {case.get('filingDate','')} · "
                    f"attorney {detail.get('plaintiff_attorney','')}"
                ),
                source="clerk-discovery",
            )
            leads.append(lead)
        if k % 20 == 0:
            print(f"  [{k}/{len(all_matched_cases)}] {defendant[:40]}: "
                  f"+{len(properties)} property(ies)")

    print(f"\n{'='*70}")
    print(f"DISCOVERY SUMMARY")
    print(f"{'='*70}")
    print(f"  Cases found in Clerk:      {len(all_matched_cases)}")
    print(f"  Defendants with no PA hit: {no_property}")
    print(f"  Leads produced:            {len(leads)}")
    print()

    if args.dry_run:
        print("DRY-RUN — sample of leads (first 10):")
        for l in leads[:10]:
            print(f"  • {l.property_address}, {l.city} {l.zip} · "
                  f"owner: {l.owner_first} {l.owner_last} · "
                  f"plaintiff: {l.lender_name[:40]}")
        return 0

    if not leads:
        print("Nothing to merge.")
        return 0

    # ── Phase 4: Merge into CSV ────────────────────────────────────────
    written = _merge_into_csv(leads)
    print(f"Merged {written} leads into {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Next steps:")
    print("  python3 -m scripts.scrape_clerk_for_leads --resume")
    print("    (enriches with attorney/hearing detail for the new clerk-discovery leads)")
    print()
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: Lis Pendens discovery — {len(leads)} pure leads'")
    print("  git push")
    return 0


def _merge_into_csv(leads: list[Lead]) -> int:
    if not CSV_PATH.exists():
        existing_rows = []
        fieldnames = list(leads[0].to_dict().keys())
    else:
        with CSV_PATH.open() as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
            fieldnames = list(reader.fieldnames or [])

    for k in leads[0].to_dict().keys():
        if k not in fieldnames:
            fieldnames.append(k)

    by_id = {r.get("lead_id", ""): r for r in existing_rows}
    added = 0
    today_iso = date.today().isoformat()
    for lead in leads:
        d = lead.to_dict()
        for k in ("first_seen", "last_updated"):
            if not isinstance(d[k], str):
                d[k] = d[k].isoformat()
        if lead.lead_id not in by_id:
            row = {fn: "" for fn in fieldnames}
            for k, v in d.items():
                row[k] = v
            by_id[lead.lead_id] = row
            added += 1
        else:
            existing = by_id[lead.lead_id]
            # Update if-empty for key fields
            for k in ("property_address", "city", "zip", "folio",
                      "owner_first", "owner_last", "lender_name", "notes"):
                if not (existing.get(k) or "").strip() and d.get(k):
                    existing[k] = d[k]
            existing["last_updated"] = today_iso

    final = list(by_id.values())
    with CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(final)
    return added


if __name__ == "__main__":
    sys.exit(main())
