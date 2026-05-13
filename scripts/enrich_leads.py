"""
Cross-reference cada lead en data/leads.csv contra el Miami-Dade Property Appraiser
para llenar ZIP, City, County, Owner name (first/last), Property Type y Folio.

Sólo enriquece leads cuya dirección matchea el Property Appraiser (Miami-Dade).
Leads fuera de Miami-Dade (Broward, Palm Beach) quedan intactos — los enriquecemos
después con sus respectivos appraisers.

Usage:
    python3 -m scripts.enrich_leads

Filosofía:
    - NO sobreescribe campos que ya tienen valor (MLS gana sobre PA en campos básicos).
    - SÍ enriquece campos vacíos: zip, city, county, owner_first, owner_last.
    - Property type: si MLS dijo "Single Family" pero PA dice algo más específico
      (Condominium, Townhouse, Multi Family), preferimos el de PA (más preciso).
    - Folio se guarda en notes para uso posterior (skip-trace, Clerk lookups).
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from pipeline.collectors.property_appraiser import enrich_by_address
from pipeline.collectors.census_geocoder import geocode_address

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

# Polite delay between requests so we don't get rate-limited.
REQUEST_DELAY_SEC = 0.25


def _is_empty(value: str) -> bool:
    """Treat empty strings, '0', and NaN-like as empty."""
    if value is None:
        return True
    s = str(value).strip()
    return s in ("", "0", "nan", "None")


def enrich_row(row: dict) -> tuple[str, str]:
    """Try to enrich a single row using two cascading sources:

      1. Miami-Dade Property Appraiser (full owner + property type + ZIP).
      2. Census Geocoder fallback (ZIP + City + County only) — covers Broward
         and Palm Beach where the PA doesn't expose attribute data publicly.

    Returns (source_tag, info_summary):
      source_tag ∈ {"pa", "census", "none"}
    """
    addr = (row.get("property_address") or "").strip()
    city = (row.get("city") or "").strip()
    if not addr:
        return "none", "no address"

    # --- Try Miami-Dade Property Appraiser first ---
    try:
        pa_info = enrich_by_address(addr, city)
    except Exception as e:
        pa_info = None
        pa_error = str(e)
    else:
        pa_error = ""

    if pa_info:
        # Fill in fields that are empty (preserve MLS data when present)
        if _is_empty(row.get("zip")):
            row["zip"] = pa_info.get("zip", "") or ""
        if _is_empty(row.get("city")):
            row["city"] = pa_info.get("city", "") or ""
        if _is_empty(row.get("county")):
            row["county"] = "Miami-Dade"

        if _is_empty(row.get("owner_first")):
            row["owner_first"] = pa_info.get("owner_first", "") or ""
        if _is_empty(row.get("owner_last")):
            row["owner_last"] = pa_info.get("owner_last", "") or ""

        pa_ptype = pa_info.get("property_type", "")
        if pa_ptype and (_is_empty(row.get("property_type")) or row.get("property_type") == "Single Family"):
            row["property_type"] = pa_ptype

        if _is_empty(row.get("units")) and pa_info.get("units"):
            row["units"] = str(pa_info["units"])
        if _is_empty(row.get("bedrooms")) and pa_info.get("bedrooms"):
            row["bedrooms"] = str(pa_info["bedrooms"])

        folio = pa_info.get("folio", "")
        if folio:
            notes = row.get("notes", "") or ""
            if "folio=" not in notes.lower():
                row["notes"] = f"{notes} · folio={folio}".strip(" ·")

        summary = f"ZIP={pa_info.get('zip','?')} · {pa_info.get('owner_name','?')} · {pa_ptype}"
        return "pa", summary

    # --- Fallback: Census Geocoder (works for Broward / Palm Beach) ---
    try:
        geo = geocode_address(addr, state="FL")
    except Exception as e:
        return "none", f"PA+Census both failed: {e}"

    if not geo:
        return "none", "no PA match, no Census match"

    if _is_empty(row.get("zip")) and geo.get("zip"):
        row["zip"] = geo["zip"]
    if _is_empty(row.get("city")) and geo.get("city"):
        row["city"] = geo["city"]
    if _is_empty(row.get("county")) and geo.get("county"):
        row["county"] = geo["county"]

    summary = f"ZIP={geo.get('zip','?')} · {geo.get('city','?')} · {geo.get('county','?')} (Census)"
    return "census", summary


def main() -> int:
    print(f"📂 Leyendo {CSV_PATH.relative_to(PROJECT)}")
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not rows:
        print("⚠️  CSV vacío, nada que hacer")
        return 0

    print(f"📋 {len(rows)} leads totales")
    print(f"🌐 Cascade: Miami-Dade Property Appraiser → Census Geocoder (Broward/PB)")
    print(f"   (espera ~{len(rows) * (REQUEST_DELAY_SEC + 0.5):.0f}s)")
    print()

    counts = {"pa": 0, "census": 0, "none": 0}
    for i, row in enumerate(rows, 1):
        addr = (row.get("property_address") or "")[:42]
        source, summary = enrich_row(row)
        counts[source] += 1
        icon = {"pa": "🏛️", "census": "📮", "none": "⚪"}[source]
        print(f"  [{i:3d}/{len(rows)}] {icon} {addr:<42}  {summary}")
        time.sleep(REQUEST_DELAY_SEC)

    # Write back
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    enriched = counts["pa"] + counts["census"]
    print()
    print("=" * 60)
    print(f"🏛️  Miami-Dade Property Appraiser: {counts['pa']}/{total}")
    print(f"📮  Census Geocoder (Broward/PB):  {counts['census']}/{total}")
    print(f"⚪  No match:                       {counts['none']}/{total}")
    print(f"💾  Total con ZIP/City poblados:    {enriched}/{total} ({100*enriched//total}%)")
    print(f"     {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Ahora corré:")
    print("  git add data/leads.csv")
    print("  git commit -m 'data: enriched with PA + Census Geocoder'")
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
