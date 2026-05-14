"""
Flujo diario simple — corre TODO en un comando.

Paso 1: Bajá los 3 CSVs desde los 3 emails de MLS Matrix (REO + Short Sale + Auction).
        Quedan en ~/Downloads con nombres tipo "Agent Single Line.csv", "(1).csv", "(2).csv"

Paso 2: Corré:
    python3 -m scripts.daily_update

Eso:
    1. Detecta los 3 CSVs más recientes en ~/Downloads
    2. Identifica cuál es cuál por tamaño (REO=más grande, Auction=más chico, Short Sale=medio)
    3. Merge con data/leads.csv existente (preserva los 263, agrega los nuevos del día)
    4. Enriquece con Property Appraiser + Census + Tax estimates
    5. Te dice qué push hacer al final
"""
from __future__ import annotations

import csv
import subprocess
import sys
from datetime import date
from pathlib import Path

HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"


def find_today_csvs() -> list[Path]:
    """Find the 3 most recent 'Agent Single Line*.csv' files in Downloads."""
    candidates = sorted(
        DOWNLOADS.glob("Agent Single Line*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[:3]


def count_data_rows(path: Path) -> int:
    """Count data rows in a CSV (excluding header)."""
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f) - 1
    except Exception:
        return 0


def identify_categories(csvs: list[Path]) -> list[tuple[Path, str]]:
    """Heuristic: REO (biggest), Short Sale (medium), Auction (smallest).
    This works because REO bulk export usually has the most listings.
    """
    sized = [(p, count_data_rows(p)) for p in csvs]
    sized.sort(key=lambda x: x[1], reverse=True)  # biggest first

    if len(sized) == 3:
        result = [
            (sized[0][0], "Foreclosure"),   # biggest = REO/Foreclosure
            (sized[1][0], "Short Sale"),    # middle = Short Sale
            (sized[2][0], "Auction"),       # smallest = Auction
        ]
    elif len(sized) == 2:
        result = [
            (sized[0][0], "Foreclosure"),
            (sized[1][0], "Short Sale"),
        ]
    elif len(sized) == 1:
        result = [(sized[0][0], "Foreclosure")]
    else:
        result = []
    return result


def main() -> int:
    today = date.today().isoformat()
    print(f"📅 Daily update — {today}")
    print(f"📂 Buscando CSVs en {DOWNLOADS}")
    print()

    csvs = find_today_csvs()
    if not csvs:
        print("❌ No encontré ningún 'Agent Single Line*.csv' en Downloads.")
        print("   Bajá los CSVs desde los 3 emails de MLS Matrix y corré esto otra vez.")
        return 1

    print(f"📄 Encontrados {len(csvs)} CSVs (ordenados por más reciente):")
    sized = [(p, count_data_rows(p)) for p in csvs]
    for p, n in sized:
        print(f"   • {p.name}  ({n} leads)")
    print()

    assignments = identify_categories(csvs)
    print("📋 Asignación automática por tamaño:")
    for p, cat in assignments:
        n = count_data_rows(p)
        print(f"   • {cat:12} ← {p.name} ({n} leads)")
    print()
    print("(Si la asignación está mal, edita scripts/merge_csvs.py manualmente)")
    print()

    # Update SOURCES dynamically by passing args
    args = ["python3", "-m", "scripts.merge_csvs"]
    if len(assignments) >= 3:
        # The merge_csvs.py expects: (foreclosure, short_sale, auction) in that arg order
        fc = next((p for p, c in assignments if c == "Foreclosure"), None)
        ss = next((p for p, c in assignments if c == "Short Sale"), None)
        au = next((p for p, c in assignments if c == "Auction"), None)
        if fc and ss and au:
            args.extend([str(fc), str(ss), str(au)])

    print("=" * 60)
    print("▶️  PASO 1: merge_csvs.py (preserva los existentes + agrega nuevos)")
    print("=" * 60)
    r = subprocess.run(args, cwd=PROJECT)
    if r.returncode != 0:
        print(f"\n❌ merge_csvs.py falló")
        return 1

    print()
    print("=" * 60)
    print("▶️  PASO 2: enrich_leads.py (PA + Census + Tax estimates)")
    print("=" * 60)
    r = subprocess.run(
        ["python3", "-m", "scripts.enrich_leads"],
        cwd=PROJECT,
    )
    if r.returncode != 0:
        print(f"\n❌ enrich_leads.py falló")
        return 1

    print()
    print("=" * 60)
    print("✅ Daily update completado")
    print("=" * 60)
    print()
    print("Próximos pasos manuales:")
    print()
    print("  cd ~/Documents/Claude/Projects/101\\ Advisor\\ Real\\ State\\ Project/")
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: daily update {today}'")
    print("  git push")
    print()
    print("(Opcional) Si querés re-correr el Clerk scraper para los nuevos leads:")
    print("  python3 -m scripts.scrape_clerk_for_leads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
