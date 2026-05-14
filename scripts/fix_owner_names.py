"""
One-time fix: clear owner_first/owner_last so the enrichment can re-populate
them with the new (correct) splitting logic.

The previous _split_owner_name was REVERSING names (treating first word as
last name). For 'CYNTHIA NIEVES' it was returning ('NIEVES', 'CYNTHIA') which
is wrong. The fix is in pipeline/collectors/property_appraiser.py — but the
existing data in data/leads.csv has the broken splits.

This script clears those fields. Then run enrich_leads.py to repopulate
them correctly.

Usage:
    python3 -m scripts.fix_owner_names
    python3 -m scripts.enrich_leads
"""
from __future__ import annotations

import csv
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"


def main() -> int:
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    cleared = 0
    for row in rows:
        # Only clear if we had a value (so we re-enrich it)
        if (row.get("owner_first") or "").strip() or (row.get("owner_last") or "").strip():
            row["owner_first"] = ""
            row["owner_last"] = ""
            cleared += 1

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Cleared owner_first/last for {cleared} rows")
    print(f"💾 {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Ahora corré: python3 -m scripts.enrich_leads")
    return 0


if __name__ == "__main__":
    main()
