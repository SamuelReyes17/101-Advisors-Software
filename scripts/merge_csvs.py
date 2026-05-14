"""
Merge 3 Matrix CSV exports (REO + Short Sale + Auction) into data/leads.csv.

Each CSV is parsed with the correct default_category and they are combined
into a single dataframe that the dashboard reads.

Usage:
    python3 -m scripts.merge_csvs

By default it looks for these files (configurable below):
    ~/Downloads/REO.csv          → category="Foreclosure"
    ~/Downloads/Short Sale.csv   → category="Short Sale"
    ~/Downloads/Auction.csv      → category="Foreclosure"  (auction = foreclosure auction)

If you renamed your files, edit the SOURCES dict below or pass paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pipeline.collectors.matrix_csv import parse_matrix_csv
from pipeline.utils.csv_writer import write_csv
from pipeline.collectors.base import Lead

HOME = Path.home()
PROJECT = Path(__file__).resolve().parent.parent

# Default file locations — Matrix downloads CSVs with these names.
# IMPORTANT: el orden de descarga determina el sufijo (1), (2).
# Verificá manualmente qué archivo corresponde a qué Auto Email antes de correr.
#
# Para el caso típico del cliente: REO=25 leads, Auction=9 leads, Short Sale=80+ leads.
# Por el tamaño podés identificar cuál es cuál.
SOURCES = [
    (HOME / "Downloads" / "Agent Single Line (4).csv",   "Foreclosure"),   # REO COMPLETO paginado (246 leads)
    (HOME / "Downloads" / "Agent Single Line (1).csv",   "Auction"),       # Auction (9 leads — DAISY SUB)
    (HOME / "Downloads" / "Agent Single Line (2).csv",   "Short Sale"),    # Short Sale (25 leads — CORAL RIDGE)
]


def main(argv: list[str]) -> int:
    # If user passed paths, override defaults
    if len(argv) >= 4:
        sources = [
            (Path(argv[1]), "Foreclosure"),
            (Path(argv[2]), "Short Sale"),
            (Path(argv[3]), "Foreclosure"),
        ]
    else:
        sources = SOURCES

    all_leads: list[Lead] = []
    for path, category in sources:
        print(f"\n📄 {path.name} → category={category}")
        if not path.exists():
            print(f"   ⚠️  no encontrado, skipping")
            continue

        content = path.read_text(encoding="utf-8", errors="ignore")
        leads = parse_matrix_csv(content, default_category=category)
        print(f"   ✅ {len(leads)} leads detectados")
        all_leads.extend(leads)

    # ── Load EXISTING leads from data/leads.csv first so we MERGE instead of REPLACE.
    # Daily Matrix emails only contain INCREMENTAL new listings (~5-30/day),
    # so we must preserve the historical leads or we lose them.
    target = PROJECT / "data" / "leads.csv"
    existing_count = 0
    if target.exists():
        try:
            import csv as _csv
            from datetime import date as _date
            with target.open(newline="") as _f:
                reader = _csv.DictReader(_f)
                for row in reader:
                    try:
                        # Reconstruct Lead from CSV row (only critical fields)
                        l = Lead(
                            lead_id=row.get("lead_id", ""),
                            first_seen=_date.fromisoformat(row.get("first_seen", "")) if row.get("first_seen") else _date.today(),
                            last_updated=_date.fromisoformat(row.get("last_updated", "")) if row.get("last_updated") else _date.today(),
                            county=row.get("county", ""),
                            category=row.get("category", ""),
                            property_address=row.get("property_address", ""),
                            city=row.get("city", ""),
                            zip=row.get("zip", ""),
                            property_type=row.get("property_type", ""),
                            units=int(row.get("units") or 0),
                            bedrooms=int(row.get("bedrooms") or 0),
                            owner_first=row.get("owner_first", ""),
                            owner_last=row.get("owner_last", ""),
                            owner_phone=row.get("owner_phone", ""),
                            owner_email=row.get("owner_email", ""),
                            lender_name=row.get("lender_name", ""),
                            lender_phone=row.get("lender_phone", ""),
                            lender_email=row.get("lender_email", ""),
                            bank_address=row.get("bank_address", ""),
                            outstanding_debt=float(row.get("outstanding_debt") or 0),
                            unpaid_taxes_2024=float(row.get("unpaid_taxes_2024") or 0),
                            unpaid_taxes_2025=float(row.get("unpaid_taxes_2025") or 0),
                            equity=float(row.get("equity") or 0),
                            status=row.get("status", "New"),
                            assigned_to=row.get("assigned_to", ""),
                            notes=row.get("notes", ""),
                        )
                        all_leads.append(l)
                        existing_count += 1
                    except Exception as e:
                        print(f"   ⚠️  Skipped existing row {row.get('lead_id')}: {e}")
            print(f"\n📚 {existing_count} leads existentes preservados de data/leads.csv")
        except Exception as e:
            print(f"⚠️  No pude leer leads existentes: {e}")

    # Deduplicate by lead_id (same MLS# may appear in multiple Saved Searches)
    # Priority for cold calling: Short Sale > Auction > Foreclosure (REO)
    PRIORITY = {"Short Sale": 3, "Auction": 2, "Foreclosure": 1}
    seen: dict[str, Lead] = {}
    for lead in all_leads:
        if lead.lead_id not in seen:
            seen[lead.lead_id] = lead
        else:
            existing = seen[lead.lead_id]
            # Prefer category with higher priority; if same priority, keep the newer one
            if PRIORITY.get(lead.category, 0) > PRIORITY.get(existing.category, 0):
                seen[lead.lead_id] = lead

    deduped = list(seen.values())
    write_csv(deduped, target)

    print("\n" + "=" * 50)
    new_count = len(deduped) - existing_count
    print(f"💾 Wrote {len(deduped)} leads to {target.relative_to(PROJECT)}")
    print(f"   📚 {existing_count} existentes preservados")
    print(f"   🆕 {new_count} leads nuevos agregados hoy")
    print()
    print("Distribución por categoría:")
    from collections import Counter
    counts = Counter(l.category for l in deduped)
    for cat, n in counts.most_common():
        print(f"   {cat}: {n}")
    print()
    print("✅ Listo. Ahora corré: git add data/leads.csv && git commit -m 'data' && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
