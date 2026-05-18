"""
Batch-scrape Miami-Dade Clerk for each Miami-Dade lead in data/leads.csv.

For each lead with owner data, searches the Clerk OCS for foreclosure-related
cases involving that party. If found, populates:
    - lender_name (the foreclosure plaintiff — usually the bank or HOA)
    - case_number
    - filing_date (as lis_pendens_date)
    - case_status
    - court_section
    - case_type
    - attorney_name (TODO: requires separate GetSingleCaseResult call)

Strategy:
    1. For persons (owner_first + owner_last both populated): search by owner_last
    2. For LLCs (owner_first empty, owner_last has entity name): search by first word of entity

Usage:
    python3 -m scripts.scrape_clerk_for_leads                # all Miami-Dade
    python3 -m scripts.scrape_clerk_for_leads --limit 10     # only first 10 (testing)
    python3 -m scripts.scrape_clerk_for_leads --dry-run      # show what would be done
    python3 -m scripts.scrape_clerk_for_leads --resume       # skip leads that already have lender_name

Timing: ~5-8 sec per lead. 172 leads ≈ 15-23 min.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from pipeline.collectors.miami_clerk_browser import (
    ClerkSession, is_foreclosure_case, parse_case_style,
)

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

# Save CSV every N leads so a crash doesn't lose progress
CHECKPOINT_EVERY = 10


def get_search_name(row: dict) -> str:
    """Return the best search term for this lead's owner.

    - If owner_first is empty → it's an LLC/Org, use owner_last (full entity name)
    - If both populated → person, use owner_last
    - Otherwise return ""
    """
    last = (row.get("owner_last") or "").strip()
    first = (row.get("owner_first") or "").strip()
    if not last and not first:
        return ""
    # For LLCs (no first name), the "last name" field has the full entity name.
    # We search using just the first word of the entity (e.g., "A20" from "A20 LLC")
    # because the Clerk's match is on individual tokens.
    if last and not first:
        words = last.split()
        if words:
            return words[0]
        return ""
    return last


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N Miami-Dade leads")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be searched, don't open browser")
    parser.add_argument("--resume", action="store_true",
                        help="Skip leads that already have lender_name populated")
    args = parser.parse_args()

    # ── Load CSV ─────────────────────────────────────────────────────
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    # Add Clerk-derived columns to schema if not present
    for col in ("clerk_case_number", "clerk_filing_date", "clerk_case_type",
                "clerk_case_status", "clerk_section", "clerk_plaintiff",
                "clerk_defendant", "clerk_match_confidence",
                # ── Case detail (parties + attorneys + hearings) ──
                "attorney_name", "attorney_bar_number",
                "defendant_attorney_name", "defendant_attorney_bar",
                "judge_name", "next_hearing_date", "next_hearing_time",
                "next_hearing_type", "clerk_disposition_date"):
        if col not in fieldnames:
            fieldnames.append(col)
            for row in rows:
                row.setdefault(col, "")

    # ── Filter to Miami-Dade leads with owner data ───────────────────
    candidates = []
    for i, row in enumerate(rows):
        if (row.get("county") or "").strip() != "Miami-Dade":
            continue
        name = get_search_name(row)
        if not name:
            continue
        if args.resume and (row.get("lender_name") or "").strip():
            continue
        candidates.append((i, name, row))

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"📋 Total leads: {len(rows)}")
    print(f"🎯 Miami-Dade with owner: {len(candidates)}")
    if args.dry_run:
        print("\nDRY RUN — would search Clerk for:\n")
        for i, name, row in candidates[:20]:
            print(f"  [{i:3d}] {row.get('owner_name','?'):<40} → search '{name}'")
        if len(candidates) > 20:
            print(f"  ... and {len(candidates) - 20} more")
        return 0

    if not candidates:
        print("\nNothing to do.")
        return 0

    est_minutes = len(candidates) * 7 / 60
    print(f"⏱️  Estimated time: ~{est_minutes:.1f} min ({len(candidates) * 7} sec)")
    print()

    # ── Run the batch ────────────────────────────────────────────────
    found_count = 0
    skipped_count = 0
    error_count = 0

    with ClerkSession() as session:
        for k, (lead_idx, search_name, row) in enumerate(candidates, 1):
            owner = (row.get("owner_name") or "")[:35]
            print(f"  [{k:3d}/{len(candidates)}] '{search_name}' "
                  f"({owner}) ", end="", flush=True)

            try:
                cases = session.search(search_name)
            except Exception as e:
                print(f"❌ search error: {e}")
                error_count += 1
                continue

            if not cases:
                print(f"⚪ no cases")
                skipped_count += 1
                continue

            # Filter to foreclosure-related cases
            foreclosure_cases = [c for c in cases if is_foreclosure_case(c)]

            # STRICT MATCH — fix false positives detected in audit (2026-05-18)
            #
            # For PERSONS (owner_first + owner_last both populated):
            #   Require defendant to contain BOTH our owner's last name AND
            #   first name (or first initial). Apellidos comunes (Cruz, Jones,
            #   Flores) by themselves are too broad.
            #
            # For LLCs (owner_first empty):
            #   Require defendant to contain ALL distinctive words of the LLC
            #   name (not just the first word). E.g. "PINE NEEDLE LANE SEC"
            #   → need defendant to contain both "PINE" AND "NEEDLE", not
            #   just "PINE" (which falsely matched "Pineda").
            #
            # Always reject:
            #   - Commercial plaintiff vs Financial company defendant
            #     (e.g. Auto Body Shop vs Westlake Financial = auto lien, not
            #     real estate foreclosure on a homeowner)

            owner_last  = (row.get("owner_last")  or "").strip()
            owner_first = (row.get("owner_first") or "").strip()
            is_person = bool(owner_first and owner_last)

            GENERIC_TOKENS = {
                "LLC", "INC", "CORP", "CORPORATION", "TRUST", "TRS", "LTD",
                "LLP", "LP", "FOUNDATION", "GROUP", "HOLDINGS", "PROPERTIES",
                "REAL", "ESTATE", "DEVELOPMENT", "INVESTMENTS", "INVESTMENT",
                "CAPITAL", "FINANCIAL", "FINANCE", "MANAGEMENT", "ASSOCIATES",
                "PARTNERS", "FUND", "ENTERPRISES", "REALTY", "BANK", "MORTGAGE",
                "NATIONAL", "FEDERAL", "ASSOC", "ASSN", "ASSOCIATION",
                "THE", "AND", "OF", "FOR", "IN", "AT", "ON", "INVESTMENT",
                # Street/place common words that fooled the old matcher
                "LANE", "LN", "STREET", "ST", "AVENUE", "AVE", "ROAD", "RD",
                "BLVD", "DRIVE", "DR", "WAY", "PLACE", "PL", "COURT", "CT",
                "TER", "TERRACE", "CIR", "CIRCLE", "SEC", "SECTION",
                "NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E", "W",
            }

            # Build distinctive word set for the OWNER
            if is_person:
                # For persons: last name + first name (must both match)
                last_words  = [w.upper() for w in owner_last.split()
                               if len(w) > 1 and w.upper() not in GENERIC_TOKENS]
                first_words = [w.upper() for w in owner_first.split()
                               if len(w) > 1 and w.upper() not in GENERIC_TOKENS]
            else:
                # For LLCs: ALL distinctive words (not just first)
                llc_words = [w.upper() for w in owner_last.split()
                             if len(w) > 2 and w.upper() not in GENERIC_TOKENS]
                last_words  = llc_words
                first_words = []

            if not last_words and not first_words:
                # Nothing distinctive to match on — skip
                pass

            # Commercial plaintiff indicators (cases that are NOT residential
            # foreclosure even though they show up as "Construction Lien Foreclosure")
            COMMERCIAL_PLAINTIFF_KEYWORDS = (
                "AUTO BODY", "AUTO REPAIR", "AUTO EXPRESS", "AUTO SALES",
                "AUTOMOTIVE", "TIRE", "TOWING", "BODY SHOP",
            )
            FINANCIAL_DEFENDANT_KEYWORDS = (
                "FINANCIAL SERVICES", "FINANCE LLC", "AUTO CREDIT",
                "MOTOR CREDIT", "LEASE", "LEASING",
            )

            best_match = None
            for c in foreclosure_cases:
                plaintiff, defendant = parse_case_style(c.get("caseStyle", ""))
                if not defendant:
                    continue
                defendant_upper = defendant.upper()
                plaintiff_upper = plaintiff.upper()

                # Reject obvious commercial/auto cases
                if (any(k in plaintiff_upper for k in COMMERCIAL_PLAINTIFF_KEYWORDS)
                    and any(k in defendant_upper for k in FINANCIAL_DEFENDANT_KEYWORDS)):
                    continue

                # Apply tight matching rules
                if is_person:
                    # Require BOTH last name AND first name to appear in defendant.
                    # We do NOT accept just a middle initial — that's how
                    # "Ahmed Cruz" falsely matched "John A. Cruz".
                    has_last  = any(w in defendant_upper for w in last_words)
                    has_first = any(w in defendant_upper for w in first_words)
                    if not (has_last and has_first):
                        continue
                else:
                    # LLC — need ALL distinctive words to appear in defendant
                    if not last_words:
                        continue
                    matches = sum(1 for w in last_words if w in defendant_upper)
                    # Require at least 2 distinctive words OR all of them if <2
                    needed = min(2, len(last_words)) if len(last_words) >= 2 else len(last_words)
                    if matches < needed:
                        continue
                    # If only 1 distinctive word AND that word is <5 chars, reject
                    # (catches "PINE" matching "Pineda")
                    if len(last_words) == 1 and len(last_words[0]) < 5:
                        continue

                # Passed all filters — candidate. Pick most recent.
                if not best_match or (c.get("filingDateSort") or "") > (best_match.get("filingDateSort") or ""):
                    best_match = c

            # NO fallback. Quality over quantity.

            if best_match:
                plaintiff, defendant = parse_case_style(best_match.get("caseStyle", ""))
                row["lender_name"] = plaintiff
                row["clerk_case_number"] = best_match.get("caseNumber", "")
                row["clerk_filing_date"] = best_match.get("filingDate", "")
                row["clerk_case_type"] = best_match.get("caseType", "")
                row["clerk_case_status"] = best_match.get("caseStatus", "")
                row["clerk_section"] = best_match.get("juditialSection", "")
                row["clerk_plaintiff"] = plaintiff
                row["clerk_defendant"] = defendant
                row["clerk_match_confidence"] = "verified"
                found_count += 1
                print(f"✅ {plaintiff[:35]} vs {defendant[:25]} · {best_match.get('caseNumber')}",
                      end="", flush=True)

                # ── Fetch case detail for attorney + judge + hearings ──
                case_id = best_match.get("caseID")
                if case_id:
                    try:
                        detail = session.get_case_detail(case_id)
                    except Exception as e:
                        detail = None
                        print(f"  · detail error: {e}", end="")
                    if detail:
                        row["attorney_name"] = detail.get("plaintiff_attorney", "")
                        row["attorney_bar_number"] = detail.get("plaintiff_attorney_bar", "")
                        row["defendant_attorney_name"] = detail.get("defendant_attorney", "")
                        row["defendant_attorney_bar"] = detail.get("defendant_attorney_bar", "")
                        row["judge_name"] = detail.get("judge_name", "")
                        row["next_hearing_date"] = detail.get("next_hearing_date", "")
                        row["next_hearing_time"] = detail.get("next_hearing_time", "")
                        row["next_hearing_type"] = detail.get("next_hearing_type", "")
                        row["clerk_disposition_date"] = detail.get("disposition_date", "")
                        atty = detail.get("plaintiff_attorney", "")
                        next_hr = detail.get("next_hearing_date", "")
                        extras = []
                        if atty:
                            extras.append(f"atty:{atty[:25]}")
                        if next_hr:
                            extras.append(f"hearing:{next_hr}")
                        if extras:
                            print(f"  · {' · '.join(extras)}", end="")
                print()  # newline
            else:
                # Clear any previous (potentially bad) data on re-run
                for col in ("lender_name", "clerk_case_number", "clerk_filing_date",
                            "clerk_case_type", "clerk_case_status", "clerk_section",
                            "clerk_plaintiff", "clerk_defendant", "clerk_match_confidence",
                            "attorney_name", "attorney_bar_number",
                            "defendant_attorney_name", "defendant_attorney_bar",
                            "judge_name", "next_hearing_date", "next_hearing_time",
                            "next_hearing_type", "clerk_disposition_date"):
                    row[col] = ""
                skipped_count += 1
                print(f"no match ({len(cases)} total cases, "
                      f"{len(foreclosure_cases)} foreclosure)")

            # Checkpoint save every N leads
            if k % CHECKPOINT_EVERY == 0:
                _write_csv(CSV_PATH, fieldnames, rows)
                print(f"      💾 checkpoint saved")

    # Final write
    _write_csv(CSV_PATH, fieldnames, rows)

    print()
    print("=" * 60)
    print(f"✅ Cases found:  {found_count}/{len(candidates)}")
    print(f"⚪ No match:     {skipped_count}/{len(candidates)}")
    print(f"❌ Errors:       {error_count}/{len(candidates)}")
    print(f"💾 Updated {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Push:")
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: Clerk foreclosure cases for {found_count} Miami-Dade leads'")
    print("  git push")
    return 0


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
