"""
One-time recovery script: rescatar los ~30 leads del court auction calendar
que el bot del GitHub Actions trajo esta mañana antes de que pisara los 275.

Esos leads vienen de miamidade.realforeclose.com (calendario oficial de
subastas judiciales) — son MUY accionables porque las propiedades están
literalmente a días de ser rematadas.

Estrategia:
    1. Busca en git history el commit del bot (commits con mensaje
       'chore(pipeline)' o autor '101advisors-bot')
    2. Extrae data/leads.csv de ese commit
    3. Marca cada lead con:
         - category = "Auction"
         - first_seen = HOY (para que aparezcan ARRIBA del dashboard)
         - notes = "Court auction calendar — imminent sale"
    4. Merge con data/leads.csv actual (dedup por lead_id)
    5. Los auction leads quedan PRIMERO en orden por first_seen

Usage:
    python3 -m scripts.recover_court_auctions
"""
from __future__ import annotations

import csv
import io
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"
TODAY = date.today().isoformat()


def find_bot_commits() -> list[str]:
    """Find recent bot commits that touched data/leads.csv."""
    result = subprocess.run(
        ["git", "log", "--all", "--oneline", "--pretty=format:%H %s",
         "--", "data/leads.csv"],
        cwd=PROJECT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    candidates = []
    for line in result.stdout.split("\n"):
        if "chore(pipeline)" in line or "101advisors-bot" in line:
            sha = line.split()[0]
            candidates.append(sha)
    return candidates


def get_csv_from_commit(sha: str) -> tuple[list[dict], list[str]]:
    """Extract data/leads.csv from a specific commit."""
    result = subprocess.run(
        ["git", "show", f"{sha}:data/leads.csv"],
        cwd=PROJECT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return [], []
    try:
        reader = csv.DictReader(io.StringIO(result.stdout))
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
        return rows, fieldnames
    except Exception:
        return [], []


def main() -> int:
    print(f"📅 Recovering court auction leads from git history\n")

    # Step 1: Find the bot commit
    bot_commits = find_bot_commits()
    if not bot_commits:
        print("❌ No bot commits found in git history")
        return 1

    print(f"📦 Bot commits encontrados: {len(bot_commits)}")
    for sha in bot_commits[:5]:
        rows, _ = get_csv_from_commit(sha)
        print(f"   • {sha[:8]} → {len(rows)} leads")

    # Pick the commit with the most leads (the bot's last successful run)
    best_sha = None
    best_count = 0
    for sha in bot_commits:
        rows, _ = get_csv_from_commit(sha)
        if 5 <= len(rows) <= 100 and len(rows) > best_count:
            # The bot brought small batches (court auction calendar has ~10-50)
            best_sha = sha
            best_count = len(rows)

    if not best_sha:
        print("❌ No suitable commit found (looking for one with 5-100 leads)")
        return 1

    print(f"\n✅ Selected commit {best_sha[:8]} with {best_count} auction leads\n")
    auction_leads, _ = get_csv_from_commit(best_sha)

    # Step 2: Read current data/leads.csv
    if not CSV_PATH.exists():
        print(f"❌ {CSV_PATH} doesn't exist")
        return 1

    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        current_leads = list(reader)
        current_fields = list(reader.fieldnames or [])

    print(f"📚 Current data/leads.csv: {len(current_leads)} leads")

    # Step 3: Index current leads by lead_id
    current_by_id = {(r.get("lead_id") or "").strip(): r for r in current_leads}

    # Step 4: Process auction leads — mark with TODAY + "Auction" category
    new_added = 0
    already_there = 0
    for row in auction_leads:
        lid = (row.get("lead_id") or "").strip()
        if not lid:
            continue
        # Mark as court auction lead
        row["category"] = "Auction"
        row["first_seen"] = TODAY
        row["last_updated"] = TODAY
        if not (row.get("notes") or "").strip() or "court auction" not in (row.get("notes") or "").lower():
            existing_notes = row.get("notes", "") or ""
            row["notes"] = f"{existing_notes} · Court auction calendar (imminent sale)".strip(" ·")

        if lid in current_by_id:
            # Already in our base — just mark it as fresh today + Auction category
            current_by_id[lid]["first_seen"] = TODAY
            current_by_id[lid]["last_updated"] = TODAY
            current_by_id[lid]["category"] = "Auction"
            old_notes = current_by_id[lid].get("notes", "") or ""
            if "court auction" not in old_notes.lower():
                current_by_id[lid]["notes"] = f"{old_notes} · Court auction calendar (imminent sale)".strip(" ·")
            already_there += 1
        else:
            current_by_id[lid] = row
            new_added += 1

    # Step 5: Write merged CSV
    merged_rows = list(current_by_id.values())

    # Determine all fields needed
    all_fields = set(current_fields)
    for row in merged_rows:
        all_fields.update(row.keys())
    # Preserve original field order
    ordered_fields = list(current_fields)
    for f in sorted(all_fields):
        if f not in ordered_fields:
            ordered_fields.append(f)

    # Sort: today's first (court auction leads especially) by first_seen DESC
    merged_rows.sort(
        key=lambda r: (r.get("first_seen") or "1900-01-01"),
        reverse=True,
    )

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ordered_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged_rows)

    print()
    print("=" * 60)
    print(f"✅ Recovery completado")
    print(f"   📦 Auction leads recuperados del bot: {len(auction_leads)}")
    print(f"   🆕 Brand new (no estaban): {new_added}")
    print(f"   🔄 Ya estaban (marcados como fresh): {already_there}")
    print(f"   📊 Total final en data/leads.csv: {len(merged_rows)}")
    print(f"💾 Updated {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Push:")
    print(f"  git add data/leads.csv scripts/recover_court_auctions.py")
    print(f"  git commit -m 'data: recover {len(auction_leads)} court auction leads from bot history'")
    print(f"  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
