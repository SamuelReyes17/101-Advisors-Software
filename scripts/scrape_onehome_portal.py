"""
Scrape OneHome saved-search portal URLs and merge results into data/leads.csv.

Each OneHome saved search has a unique URL with a JWT token. The token is in
the "View All Properties" link of every OneHome auto-email. Copy that URL
from your browser address bar after clicking the email link, then pass it
to this script.

Usage:
    # One saved search (e.g. REO/Foreclosure)
    python3 -m scripts.scrape_onehome_portal "https://portal.onehome.com/en-US/properties/map?token=..."

    # Multiple in one shot (REO + Auction + Short Sale)
    python3 -m scripts.scrape_onehome_portal "URL1" "URL2" "URL3"

    # Show browser while scraping (useful for debugging)
    python3 -m scripts.scrape_onehome_portal --headed "URL"

    # Override category (skip auto-detection from page header)
    python3 -m scripts.scrape_onehome_portal --category Foreclosure "URL"
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path

from pipeline.collectors.onehome_portal import scrape_onehome_portal
from pipeline.collectors.base import Lead

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_onehome_portal")


def merge_with_existing_csv(new_leads: list[Lead]) -> tuple[int, int, int]:
    """Merge new_leads into data/leads.csv.

    Returns (added, updated, total).
    Dedupes by lead_id (which is onehome-{MLS#}).
    """
    if not CSV_PATH.exists():
        log.warning("data/leads.csv not found — creating new file")
        existing_rows = []
        fieldnames = list(new_leads[0].to_dict().keys()) if new_leads else []
    else:
        with CSV_PATH.open() as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
            fieldnames = list(reader.fieldnames or [])

    # Ensure all Lead fields are in fieldnames
    sample_lead_keys = list(new_leads[0].to_dict().keys()) if new_leads else []
    for k in sample_lead_keys:
        if k not in fieldnames:
            fieldnames.append(k)

    by_id = {r.get("lead_id", ""): r for r in existing_rows}
    added = updated = 0
    today_iso = date.today().isoformat()

    for lead in new_leads:
        d = lead.to_dict()
        # Convert date fields to ISO strings
        for k in ("first_seen", "last_updated"):
            if k in d and not isinstance(d[k], str):
                d[k] = d[k].isoformat()

        existing = by_id.get(lead.lead_id)
        if existing:
            # Only update fields that are still empty in the existing row,
            # and bump last_updated. Never overwrite enriched data (folio,
            # owner_*, clerk_*, etc.) that we got from later pipeline steps.
            UPDATE_IF_EMPTY = (
                "property_address", "city", "zip", "property_type",
                "bedrooms", "outstanding_debt", "category", "county",
                "notes",
            )
            for k in UPDATE_IF_EMPTY:
                if not (existing.get(k) or "").strip() and d.get(k):
                    existing[k] = d[k]
            existing["last_updated"] = today_iso
            updated += 1
        else:
            # Brand-new lead — fill all fields from the Lead dataclass,
            # leave any extra CSV-only columns blank.
            row = {fn: "" for fn in fieldnames}
            for k, v in d.items():
                row[k] = v
            by_id[lead.lead_id] = row
            added += 1

    # Write back, preserving original CSV column order + appending new ones
    final_rows = list(by_id.values())
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_rows)

    return added, updated, len(final_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="+",
                        help="OneHome portal URLs (with ?token=... in them)")
    parser.add_argument("--headed", action="store_true",
                        help="Show the browser (default: headless)")
    parser.add_argument("--category", default="",
                        help="Override auto-detected category (Foreclosure / "
                             "Auction / Short Sale / Lis Pendens)")
    parser.add_argument("--no-merge", action="store_true",
                        help="Don't write to data/leads.csv — just print the leads")
    args = parser.parse_args()

    print("=" * 70)
    print(f"OneHome portal scraper — {len(args.urls)} URL(s)")
    print("=" * 70)

    all_leads: list[Lead] = []
    for i, url in enumerate(args.urls, 1):
        print(f"\n[{i}/{len(args.urls)}] {url[:90]}...")
        try:
            leads = scrape_onehome_portal(url, headless=not args.headed)
        except Exception as e:
            log.exception("Scrape failed for URL %d", i)
            continue
        if args.category:
            for l in leads:
                l.category = args.category
        log.info("  → %d listings extracted", len(leads))
        all_leads.extend(leads)

    if not all_leads:
        print("\nNo leads extracted. Maybe the URL expired? "
              "Try clicking the email link again to get a fresh token.")
        return 1

    # Dedupe across URLs by lead_id (in case the same MLS# appears in 2 saved searches)
    deduped = {}
    for l in all_leads:
        if l.lead_id not in deduped:
            deduped[l.lead_id] = l
    all_leads = list(deduped.values())

    # Summary
    by_cat: dict[str, int] = {}
    by_county: dict[str, int] = {}
    for l in all_leads:
        by_cat[l.category] = by_cat.get(l.category, 0) + 1
        c = l.county or "(unknown)"
        by_county[c] = by_county.get(c, 0) + 1

    print("\n" + "=" * 70)
    print(f"TOTAL unique listings: {len(all_leads)}")
    print("=" * 70)
    print("\nBy category:")
    for k in sorted(by_cat, key=by_cat.get, reverse=True):
        print(f"  {k:20} {by_cat[k]:4d}")
    print("\nBy county:")
    for k in sorted(by_county, key=by_county.get, reverse=True):
        print(f"  {k:20} {by_county[k]:4d}")

    if args.no_merge:
        print("\n--no-merge: nothing written to data/leads.csv")
        return 0

    added, updated, total = merge_with_existing_csv(all_leads)
    print(f"\nMerged into data/leads.csv:")
    print(f"  Added (new MLS#):     {added}")
    print(f"  Updated (existing):   {updated}")
    print(f"  Total rows in file:   {total}")
    print()
    print("Next steps:")
    print("  python3 -m scripts.enrich_leads               # PA + Census + Tax estimates")
    print("  python3 -m scripts.scrape_clerk_for_leads --resume   # Clerk cases for new leads")
    print()
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: OneHome portal scrape {date.today().isoformat()}'")
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
