"""
Scrape Miami-Dade Official Records for LIS PENDENS recordings, cross-reference
defendants with Property Appraiser, and merge into data/leads.csv.

By Florida law every Lis Pendens (notice of pending foreclosure) MUST be
recorded in the Clerk's Official Records book. This is the authoritative
source for pre-foreclosure leads — much better than searching cases by
surname (the OCS caps at 200 hits per surname and dilutes with non-foreclosure
cases).

Usage:
    python3 -m scripts.scrape_official_records_lp                # last 60 days, headless
    python3 -m scripts.scrape_official_records_lp --days 30      # narrower window
    python3 -m scripts.scrape_official_records_lp --headed       # show browser (debug)
    python3 -m scripts.scrape_official_records_lp --dry-run      # print, don't merge

Timing:
    Phase 1 (scrape Official Records): ~3-6 min for 1500-2500 recordings
    Phase 2 (PA cross-ref):            ~1-2 sec per recording → 30-60 min for full lot
    To stay under 10 min total, use --days 30 first (≈ 750 recordings → 15-25 min).
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pipeline.collectors.miami_official_records import scrape_lis_pendens
from pipeline.collectors.property_appraiser import search_by_owner_name
from pipeline.collectors.base import Lead

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_official_records_lp")


def _county_from_zip(zip_: str) -> str:
    z = (zip_ or "").strip()[:3]
    if z in ("330", "331", "332"): return "Miami-Dade"
    if z in ("333",):              return "Broward"
    if z in ("334", "335"):        return "Palm Beach"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=60,
                        help="Look back this many days (default: 60)")
    parser.add_argument("--headed", action="store_true",
                        help="Show browser (default: headless)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to data/leads.csv")
    parser.add_argument("--max-pa-lookups", type=int, default=500,
                        help="Cap PA cross-reference calls (default: 500)")
    args = parser.parse_args()

    print("=" * 70)
    print(f"Miami-Dade Official Records — LIS PENDENS discovery")
    print(f"  Look-back:  {args.days} days")
    print(f"  Headless:   {not args.headed}")
    print("=" * 70)

    # ── Phase 1: Scrape Official Records ──
    t0 = time.time()
    try:
        recordings = scrape_lis_pendens(days=args.days, headless=not args.headed)
    except Exception as e:
        log.exception("Official Records scrape failed")
        print(f"\n❌ Scrape failed: {e}")
        print("Try --headed to see what's happening in the browser.")
        return 1

    t1 = time.time()
    print(f"\nPhase 1 done in {t1-t0:.0f}s — captured {len(recordings)} Lis Pendens recordings")

    if not recordings:
        print("\nNo Lis Pendens found. Possible causes:")
        print("  - Document Type filter didn't get set (run with --headed to verify)")
        print("  - Date range too narrow (try --days 90)")
        print("  - Site UI changed")
        return 1

    # ── Phase 2: Cross-reference with Property Appraiser ──
    print(f"\nPhase 2: Cross-referencing {len(recordings)} defendants with Property Appraiser …")
    print("(This calls Miami-Dade PA API once per defendant — Miami-Dade properties only)")
    print()

    today = date.today()
    leads: list[Lead] = []
    matched = no_match = 0
    for k, rec in enumerate(recordings[:args.max_pa_lookups], 1):
        defendant = rec.get("second_party", "")
        plaintiff = rec.get("first_party", "")
        if not defendant:
            continue
        try:
            properties = search_by_owner_name(defendant, max_results=3)
        except Exception as e:
            log.warning("PA lookup failed for %r: %s", defendant, e)
            continue
        if not properties:
            no_match += 1
            if k % 25 == 0:
                print(f"  [{k}/{len(recordings)}] {defendant[:40]:40s} → no PA match")
            continue
        matched += 1
        for prop in properties:
            if not prop.get("property_address") or not prop.get("zip"):
                continue
            owner_parts = (prop.get("owner_name") or defendant).split()
            owner_first = owner_parts[0] if owner_parts else ""
            owner_last  = " ".join(owner_parts[1:]) if len(owner_parts) > 1 else ""
            zip_ = prop.get("zip", "")
            county = _county_from_zip(zip_) or "Miami-Dade"

            cfn = rec.get("cfn", "")
            lead = Lead(
                lead_id=f"or-lp-{cfn}-{prop.get('folio','')[:6]}",
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
                    f"Lis Pendens CFN {cfn} · "
                    f"recorded {rec.get('recording_date','')} · "
                    f"plaintiff {plaintiff[:50]}"
                ),
                source="official-records",
            )
            leads.append(lead)
        if k % 25 == 0:
            print(f"  [{k}/{len(recordings)}] {defendant[:40]:40s} "
                  f"→ {len(properties)} property(ies)")

    t2 = time.time()
    print(f"\nPhase 2 done in {t2-t1:.0f}s")
    print(f"  Defendants with PA match:    {matched}")
    print(f"  Defendants with NO PA match: {no_match} (likely Broward/PB-based)")
    print(f"  Lead records produced:       {len(leads)}")

    if args.dry_run:
        print("\nDRY-RUN — sample of leads:")
        for l in leads[:15]:
            print(f"  • {l.property_address}, {l.city} {l.zip}")
            print(f"      owner: {l.owner_first} {l.owner_last}")
            print(f"      plaintiff: {l.lender_name[:50]}")
            print(f"      notes: {l.notes[:80]}")
            print()
        return 0

    if not leads:
        print("\nNothing to merge.")
        return 0

    added = _merge_into_csv(leads)
    print(f"\n✅ Merged {added} new Lis Pendens leads into data/leads.csv")
    print(f"   Total recordings: {len(recordings)}  ·  with property: {matched}  ·  leads: {len(leads)}")
    print()
    print("Next steps:")
    print("  python3 -m scripts.scrape_clerk_for_leads --resume")
    print("    (adds attorney + FL Bar + hearing dates to the new Lis Pendens)")
    print()
    print("  git add data/leads.csv pipeline/ scripts/ streamlit_app.py")
    print("  git commit -m 'data: Lis Pendens from Official Records'")
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
