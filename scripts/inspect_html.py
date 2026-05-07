"""
Inspect captured HTML files and print a structured summary.

Run after `python3 -m scripts.probe_miami_dade` to get a digest of what's
inside each captured page — without pasting 23KB of raw HTML.

Usage:
    python3 -m scripts.inspect_html
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CAPTURES = Path(__file__).parent / "captures"


def inspect(path: Path) -> None:
    print()
    print("=" * 70)
    print(f"FILE: {path.name}  ({path.stat().st_size:,} bytes)")
    print("=" * 70)

    raw = path.read_text(encoding="utf-8", errors="ignore")

    # If it's small (<2KB), print it raw — usually JSON or error message
    if path.stat().st_size < 2000:
        print("[small file — printing raw]")
        print(raw)
        return

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("bs4 not installed. Run: pip3 install beautifulsoup4 lxml")
        return

    soup = BeautifulSoup(raw, "lxml")

    # CSS classes
    classes = set()
    for el in soup.find_all(class_=True):
        for c in el.get("class") or []:
            classes.add(c)

    # IDs
    ids = sorted({el.get("id") for el in soup.find_all(id=True) if el.get("id")})

    # Tables
    tables = soup.find_all("table")

    print(f"\n— Title: {soup.title.string.strip() if soup.title and soup.title.string else '(none)'}")
    print(f"— Tables: {len(tables)}  ·  CSS classes (unique): {len(classes)}  ·  IDs: {len(ids)}")

    # Top 30 CSS classes (alphabetical)
    print(f"\n— CSS classes (first 40):")
    for c in sorted(classes)[:40]:
        print(f"    .{c}")

    # IDs that look interesting (skip generic ASP.NET viewstate-y ones)
    interesting = [i for i in ids if not i.startswith("__")]
    print(f"\n— IDs (first 25):")
    for i in interesting[:25]:
        print(f"    #{i}")

    # Table structure preview
    print(f"\n— Tables structure:")
    for i, t in enumerate(tables[:10]):
        rows = t.find_all("tr")
        cls = " ".join(t.get("class") or [])
        tid = t.get("id") or ""
        print(f"  [{i}] rows={len(rows)}  class='{cls}'  id='{tid}'")
        if rows:
            cells = rows[0].find_all(["th", "td"])
            samples = [c.get_text(" ", strip=True)[:40] for c in cells[:6]]
            print(f"      header sample: {samples}")
            if len(rows) > 1:
                cells2 = rows[1].find_all(["th", "td"])
                samples2 = [c.get_text(" ", strip=True)[:40] for c in cells2[:6]]
                print(f"      data sample:   {samples2}")

    # Sniff for likely auction/foreclosure rows by content
    print(f"\n— Address-like patterns found:")
    addr_re = re.compile(
        r"\b\d{1,6}\s+[A-Za-z0-9 .,#-]+?(?:ST|AVE|RD|BLVD|DR|CT|PL|LN|WAY|TER|HWY|CIR)\b",
        re.IGNORECASE,
    )
    matches = addr_re.findall(soup.get_text(" ", strip=True))
    for m in matches[:8]:
        print(f"    {m.strip()[:80]}")
    if len(matches) > 8:
        print(f"    ... and {len(matches) - 8} more")

    # Sniff for case numbers
    print(f"\n— Case number patterns:")
    case_re = re.compile(r"\b\d{4}[-\s]?(?:CA|CC)[-\s]?\d{5,8}\b")
    cases = case_re.findall(soup.get_text(" "))
    for c in cases[:5]:
        print(f"    {c}")
    if len(cases) > 5:
        print(f"    ... and {len(cases) - 5} more")

    # Form actions (for ASP.NET POST scraping)
    forms = soup.find_all("form")
    if forms:
        print(f"\n— Forms ({len(forms)}):")
        for i, f in enumerate(forms[:3]):
            print(f"  [{i}] action='{f.get('action', '')}'  method='{f.get('method', '')}'")
            for inp in f.find_all("input")[:8]:
                print(f"        input: name='{inp.get('name', '')}'  type='{inp.get('type', '')}'  value='{(inp.get('value') or '')[:30]}'")


def main() -> int:
    if not CAPTURES.exists():
        print(f"No captures directory at {CAPTURES}. Run probe_miami_dade.py first.")
        return 1

    files = sorted(CAPTURES.glob("*.html"))
    if not files:
        print(f"No .html files in {CAPTURES}.")
        return 1

    # Prioritize the most useful files first
    priority = [
        "realauction_7d.html",
        "realauction_today.html",
        "foreclosure_registry.html",
        "property_appraiser_metadata.html",
        "ocs_home.html",
    ]
    files_sorted = sorted(files, key=lambda p: priority.index(p.name) if p.name in priority else 999)

    for f in files_sorted:
        inspect(f)

    return 0


if __name__ == "__main__":
    sys.exit(main())
