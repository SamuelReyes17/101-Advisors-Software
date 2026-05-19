"""
Enrich every LLC/Corp/Trust owner in data/leads.csv with Sunbiz data.

For each lead whose owner_name looks like a business entity (LLC, INC, CORP,
TRUST, etc.), query Sunbiz and populate new columns:

    sunbiz_officers          → "Aleida Izquierdo (MGRM); Jose Izquierdo (MGRM)"
    sunbiz_officer_1_name    → "Aleida Izquierdo"
    sunbiz_officer_1_addr    → "3162 NW 168 TER, MIAMI GARDENS, FL 33056"
    sunbiz_officer_2_name    → "Jose Izquierdo"
    sunbiz_officer_2_addr    → ""
    sunbiz_registered_agent  → "John Smith, ESQ"
    sunbiz_ra_address        → "123 Main St, Miami, FL 33125"
    sunbiz_status            → "ACTIVE"
    sunbiz_doc_number        → "L24000123456"
    sunbiz_mailing           → "PO Box 12345, Miami, FL 33055"

These give Leon's team REAL PEOPLE TO CALL — they search TruePeople with
the officer name (not the LLC) and get much better phone/email hit rates.

Usage:
    python3 -m scripts.enrich_with_sunbiz                     # all LLC leads
    python3 -m scripts.enrich_with_sunbiz --limit 10          # test on first 10
    python3 -m scripts.enrich_with_sunbiz --dry-run           # don't write CSV
    python3 -m scripts.enrich_with_sunbiz --resume            # skip leads already enriched

Timing: ~6-10 sec per UNIQUE LLC (78 unique → ~8-13 min).
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from pathlib import Path

from pipeline.collectors.sunbiz import SunbizSession

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("enrich_with_sunbiz")

ORG_RE = re.compile(
    r"\b(LLC|INC|CORP|CORPORATION|TRUST|TRS|LTD|LP|LLP|HOLDINGS|GROUP|"
    r"ASSOCIATES|PROPERTIES|PARTNERS|INVESTMENT|INVESTMENTS|FUND|"
    r"ENTERPRISES|REALTY|MANAGEMENT|CAPITAL|DEVELOPMENT|FOUNDATION)\b",
    re.IGNORECASE,
)

SUNBIZ_COLUMNS = (
    "sunbiz_status",
    "sunbiz_doc_number",
    "sunbiz_filing_date",
    "sunbiz_principal_address",
    "sunbiz_mailing",
    "sunbiz_registered_agent",
    "sunbiz_ra_address",
    "sunbiz_officers",
    "sunbiz_officer_1_name",
    "sunbiz_officer_1_title",
    "sunbiz_officer_1_addr",
    "sunbiz_officer_2_name",
    "sunbiz_officer_2_title",
    "sunbiz_officer_2_addr",
    "sunbiz_officer_3_name",
    "sunbiz_officer_3_title",
    "sunbiz_officer_3_addr",
)


def is_org(name: str) -> bool:
    return bool(ORG_RE.search(name or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N unique LLCs (debug)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write data/leads.csv")
    parser.add_argument("--resume", action="store_true",
                        help="Skip leads that already have sunbiz_status filled")
    args = parser.parse_args()

    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    # Ensure all Sunbiz columns are in fieldnames
    for col in SUNBIZ_COLUMNS:
        if col not in fieldnames:
            fieldnames.append(col)
            for r in rows:
                r.setdefault(col, "")

    # ── Collect unique LLC names from leads ────────────────────────────
    name_to_indices: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        first = (r.get("owner_first", "") or "").strip()
        last  = (r.get("owner_last", "") or "").strip()
        name  = (first + " " + last).strip()
        if not name or not is_org(name):
            continue
        if args.resume and (r.get("sunbiz_status", "") or "").strip():
            continue
        name_to_indices.setdefault(name.upper(), []).append(i)

    unique_names = sorted(name_to_indices.keys())
    if args.limit:
        unique_names = unique_names[:args.limit]
    total = len(unique_names)

    print("=" * 70)
    print(f"Sunbiz enrichment — {total} unique LLC/Corp/Trust names")
    print(f"  Total leads to update: {sum(len(name_to_indices[n]) for n in unique_names)}")
    print("=" * 70)
    print()

    if not unique_names:
        print("Nothing to do. (All leads either have no LLC owner or already enriched.)")
        return 0

    found = miss = err = 0
    rows_updated = 0

    with SunbizSession(headless=True) as session:
        for k, name in enumerate(unique_names, 1):
            print(f"[{k:3d}/{total}] {name[:60]:<60} ", end="", flush=True)
            try:
                info = session.lookup(name)
            except Exception as e:
                print(f"❌ {e}")
                err += 1
                continue

            if not info or not info.get("entity_name"):
                print("⚪ no Sunbiz match")
                miss += 1
                continue

            found += 1
            officers = info.get("officers") or []
            officer_summary = "; ".join(
                f"{o['name']} ({o.get('title','')})".strip()
                for o in officers[:3]
            )
            print(f"✅ {len(officers)} officer(s) · {info.get('status','')[:10]}")

            update = {
                "sunbiz_status":            info.get("status", ""),
                "sunbiz_doc_number":        info.get("document_number", ""),
                "sunbiz_filing_date":       info.get("filing_date", ""),
                "sunbiz_principal_address": info.get("principal_address", ""),
                "sunbiz_mailing":           info.get("mailing_address", ""),
                "sunbiz_registered_agent":  info.get("registered_agent", ""),
                "sunbiz_ra_address":        info.get("ra_address", ""),
                "sunbiz_officers":          officer_summary,
            }
            for n in (1, 2, 3):
                idx = n - 1
                if idx < len(officers):
                    update[f"sunbiz_officer_{n}_name"]  = officers[idx]["name"]
                    update[f"sunbiz_officer_{n}_title"] = officers[idx].get("title", "")
                    update[f"sunbiz_officer_{n}_addr"]  = officers[idx].get("address", "")

            for row_idx in name_to_indices[name]:
                for col, val in update.items():
                    if val:
                        rows[row_idx][col] = val
                rows_updated += 1

    print()
    print("=" * 70)
    print(f"SUMMARY")
    print(f"  Sunbiz hits:        {found}/{total}")
    print(f"  No match:           {miss}")
    print(f"  Errors:             {err}")
    print(f"  CSV rows updated:   {rows_updated}")
    print("=" * 70)

    if args.dry_run:
        print("\nDRY-RUN — nothing written to data/leads.csv")
        return 0

    if rows_updated == 0:
        print("\nNothing changed.")
        return 0

    with CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n✅ Saved to {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Next steps:")
    print("  git add data/leads.csv pipeline/ scripts/ streamlit_app.py")
    print("  git commit -m 'feat: Sunbiz officers for LLC-owner leads'")
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
