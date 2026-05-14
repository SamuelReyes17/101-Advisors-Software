"""
One-time script: merge today's NEW leads (current data/leads.csv)
with the historical 275 leads from git history.

The GitHub Actions cron viejo sobreescribió data/leads.csv con ~30 leads
nuevos del RealAuction calendar. Este script:
    1. Lee los 30 actuales y los marca con first_seen = HOY
    2. Lee los 275 históricos desde git (HEAD~1 o HEAD~2)
    3. Une los dos sets, dedup por lead_id (gana el histórico que está enriquecido)
    4. Escribe el merge final

Usage:
    python3 -m scripts.merge_today_with_history
"""
from __future__ import annotations

import csv
import io
import subprocess
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"
TODAY = date.today().isoformat()


def find_historical_csv() -> tuple[list[dict], list[str]]:
    """Look back through git history to find the CSV with 275 leads."""
    for n_back in range(1, 15):
        result = subprocess.run(
            ["git", "show", f"HEAD~{n_back}:data/leads.csv"],
            cwd=PROJECT, capture_output=True, text=True,
        )
        if result.returncode != 0:
            continue
        try:
            reader = csv.DictReader(io.StringIO(result.stdout))
            rows = list(reader)
            fieldnames = list(reader.fieldnames or [])
            if len(rows) > 100:  # we want the 275 version, not the 30
                print(f"✅ Found historical CSV at HEAD~{n_back} with {len(rows)} leads")
                return rows, fieldnames
            else:
                print(f"   HEAD~{n_back}: {len(rows)} leads (too few, looking further)")
        except Exception as e:
            print(f"   HEAD~{n_back}: parse error: {e}")

    print("❌ Couldn't find historical CSV with >100 leads in last 15 commits")
    return [], []


def main() -> int:
    # ── Step 1: Read CURRENT CSV (today's 30 new auction leads)
    if not CSV_PATH.exists():
        print(f"⚠️  {CSV_PATH} doesn't exist — nothing to preserve from today")
        today_leads, today_fields = [], []
    else:
        with CSV_PATH.open() as f:
            reader = csv.DictReader(f)
            today_leads = list(reader)
            today_fields = list(reader.fieldnames or [])

    # Mark today's leads with first_seen = TODAY so the dashboard
    # can highlight them as "🆕 new"
    for row in today_leads:
        if not (row.get("first_seen") or "").strip():
            row["first_seen"] = TODAY
        row["last_updated"] = TODAY
        # Set a marker that this is from today's auto batch
        if not (row.get("notes") or "").strip():
            row["notes"] = f"Auto-imported {TODAY} (RealAuction batch)"
    print(f"📅 Current data/leads.csv: {len(today_leads)} leads (today's batch)")

    # ── Step 2: Get historical CSV from git
    historical_leads, hist_fields = find_historical_csv()
    if not historical_leads:
        print("❌ Aborting — can't restore historical data")
        return 1

    # ── Step 3: Merge by lead_id
    # When same lead_id exists in both, prefer the historical one (more enriched).
    # But mark new auction leads (only in today's batch) with first_seen=TODAY.
    merged = {}

    # Add historical first (these are the canonical, enriched versions)
    for row in historical_leads:
        lid = (row.get("lead_id") or "").strip()
        if lid:
            merged[lid] = row

    # Process today's leads:
    #   - If duplicate (already in historical): keep the enriched version,
    #     BUT update first_seen to TODAY so it bubbles up with 🆕 marker
    #   - If brand new: add it with first_seen=TODAY
    new_added = 0
    re_appeared = 0
    for row in today_leads:
        lid = (row.get("lead_id") or "").strip()
        if not lid:
            continue
        if lid in merged:
            re_appeared += 1
            # The enriched historical version stays, but mark it as "seen today"
            merged[lid]["first_seen"] = TODAY
            merged[lid]["last_updated"] = TODAY
        else:
            merged[lid] = row
            new_added += 1

    # ── Step 4: Write the unified CSV
    # Use the union of fields from both sources
    all_fields_set = set()
    for row in merged.values():
        all_fields_set.update(row.keys())
    # Preserve order from historical fields where possible
    ordered_fields = list(hist_fields)
    for f in sorted(all_fields_set):
        if f not in ordered_fields:
            ordered_fields.append(f)

    # Sort by first_seen DESC so newest leads end up first
    rows_sorted = sorted(
        merged.values(),
        key=lambda r: (r.get("first_seen") or "1900-01-01"),
        reverse=True,
    )

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_sorted)

    print()
    print("=" * 60)
    print(f"✅ Total final: {len(merged)} leads")
    print(f"   📚 Históricos (con enriquecimiento): {len(historical_leads)}")
    print(f"   🆕 Nuevos agregados hoy: {new_added}")
    print(f"   🔁 Duplicados omitidos (ya estaban): {duplicates}")
    print(f"💾 Updated {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Push:")
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: merge {new_added} new auction leads with 275 historical'")
    print("  git push")
    return 0


if __name__ == "__main__":
    main()
