"""
One-time cleanup: fix duplicated street suffixes in data/leads.csv that came
from a bug in the Matrix CSV parser ("Way Way", "Street Street", "Drive Drive").

After running this, re-run scripts/enrich_leads.py so the previously-failed
addresses get their ZIP/City/County filled in.

Usage:
    python3 -m scripts.fix_address_suffixes
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

SUFFIX_DEDUP_RE = re.compile(
    r'\b(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Court|Ct|'
    r'Place|Pl|Lane|Ln|Way|Terrace|Ter|Highway|Hwy|Circle|Cir|Parkway|Pkwy|'
    r'Trail|Trl|Square|Sq|Loop|Run|Path|Walk|Crescent|Cres|Plaza|Plz)'
    r'\s+\1\b',
    re.IGNORECASE,
)


def main() -> int:
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    fixed = 0
    for row in rows:
        addr = row.get("property_address", "") or ""
        new_addr = SUFFIX_DEDUP_RE.sub(r'\1', addr).strip()
        if new_addr != addr:
            print(f"  • {addr}")
            print(f"    → {new_addr}")
            row["property_address"] = new_addr
            fixed += 1

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"✅ Fixed {fixed} addresses in {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Ahora re-corré el enrichment para los que antes fallaban:")
    print("  python3 -m scripts.enrich_leads")
    return 0


if __name__ == "__main__":
    main()
