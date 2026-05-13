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

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

# Polite delay between requests to gisweb.miamidade.gov so we don't get rate-limited.
REQUEST_DELAY_SEC = 0.25


def _is_empty(value: str) -> bool:
    """Treat empty strings, '0', and NaN-like as empty."""
    if value is None:
        return True
    s = str(value).strip()
    return s in ("", "0", "nan", "None")


def enrich_row(row: dict) -> tuple[bool, str]:
    """Try to enrich a single row. Returns (success, info_summary)."""
    addr = (row.get("property_address") or "").strip()
    city = (row.get("city") or "").strip()
    if not addr:
        return False, "no address"

    try:
        info = enrich_by_address(addr, city)
    except Exception as e:
        return False, f"error: {e}"

    if not info:
        return False, "no PA match"

    # Fill in fields that are empty (preserve MLS data when present)
    if _is_empty(row.get("zip")):
        row["zip"] = info.get("zip", "") or ""
    if _is_empty(row.get("city")):
        row["city"] = info.get("city", "") or ""
    if _is_empty(row.get("county")):
        row["county"] = "Miami-Dade"

    if _is_empty(row.get("owner_first")):
        row["owner_first"] = info.get("owner_first", "") or ""
    if _is_empty(row.get("owner_last")):
        row["owner_last"] = info.get("owner_last", "") or ""

    # Property type: PA classifies better than MLS (sabe distinguir Condo vs Single)
    # Solo overrideamos si MLS había puesto "Single Family" (el default) o vacío.
    pa_ptype = info.get("property_type", "")
    if pa_ptype and (_is_empty(row.get("property_type")) or row.get("property_type") == "Single Family"):
        row["property_type"] = pa_ptype

    # Units (PA es autoritativo)
    if _is_empty(row.get("units")) and info.get("units"):
        row["units"] = str(info["units"])

    # Bedrooms — solo si MLS no lo trajo
    if _is_empty(row.get("bedrooms")) and info.get("bedrooms"):
        row["bedrooms"] = str(info["bedrooms"])

    # Folio: guardamos en notes para skip-trace futuro y referencia al Clerk
    folio = info.get("folio", "")
    if folio:
        notes = row.get("notes", "") or ""
        if "folio=" not in notes.lower():
            row["notes"] = f"{notes} · folio={folio}".strip(" ·")

    summary = f"ZIP={info.get('zip','?')} · {info.get('owner_name','?')} · {pa_ptype}"
    return True, summary


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
    print(f"🌐 Cross-referenciando contra Miami-Dade Property Appraiser...")
    print(f"   (espera ~{len(rows) * (REQUEST_DELAY_SEC + 0.3):.0f}s)")
    print()

    enriched = 0
    skipped = 0
    for i, row in enumerate(rows, 1):
        addr = (row.get("property_address") or "")[:45]
        ok, summary = enrich_row(row)
        status = "✅" if ok else "⚪"
        print(f"  [{i:3d}/{len(rows)}] {status} {addr:<45}  {summary}")
        if ok:
            enriched += 1
        else:
            skipped += 1
        time.sleep(REQUEST_DELAY_SEC)

    # Write back
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print("=" * 60)
    print(f"✅ Enriquecidos: {enriched}/{len(rows)} (Miami-Dade)")
    print(f"⚪ Skipped:      {skipped}/{len(rows)} (Broward/Palm Beach o no match)")
    print(f"💾 Updated {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Ahora corré:")
    print("  git add data/leads.csv")
    print("  git commit -m 'data: enriched with Property Appraiser (ZIP, owner, type)'")
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
