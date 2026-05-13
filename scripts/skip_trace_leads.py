"""
Batch skip-trace: rellena owner_phone, owner_email, y owner name (cuando
falte) para los leads de data/leads.csv usando BatchData.io.

Prioridad de skip-trace (caro, $0.20/lookup):
    1. Short Sale  (owner motivado a vender — lead más caliente)
    2. Auction     (acción judicial inminente — alto urgencia)
    3. Foreclosure (REO — bank-owned, menos urgencia personal)

Dentro de cada categoría, prioriza:
    a. Sin phone aún (necesita lookup)
    b. Con más equity (deal potencial más grande)

Cap configurable (default 100/run = $20 USD).

Setup:
    1. Crear cuenta en https://batchdata.io
    2. Generar API key en el dashboard
    3. Exportar antes de correr:
         export BATCH_SKIP_API_KEY=tu_key_aqui
       O ponerlo en .streamlit/secrets.toml:
         BATCH_SKIP_API_KEY = "tu_key_aqui"

Usage:
    python3 -m scripts.skip_trace_leads                # default cap=100
    python3 -m scripts.skip_trace_leads --cap 10       # solo 10 (testing, $2)
    python3 -m scripts.skip_trace_leads --dry-run      # mostrar a quién, sin llamar API
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT / "data" / "leads.csv"

# Try to load API key from .streamlit/secrets.toml as fallback
SECRETS_PATH = PROJECT / ".streamlit" / "secrets.toml"


def load_api_key() -> str:
    """Read from env var first, then .streamlit/secrets.toml."""
    key = os.environ.get("BATCH_SKIP_API_KEY", "").strip()
    if key:
        return key

    if SECRETS_PATH.exists():
        try:
            import tomllib  # py 3.11+
        except ImportError:
            try:
                import tomli as tomllib  # py < 3.11
            except ImportError:
                return ""
        try:
            with SECRETS_PATH.open("rb") as f:
                data = tomllib.load(f)
            return str(data.get("BATCH_SKIP_API_KEY", "")).strip()
        except Exception:
            return ""

    return ""


# Priority for skip-tracing — Short Sale > Auction > Foreclosure
PRIORITY = {"Short Sale": 3, "Auction": 2, "Foreclosure": 1}


def lead_priority(row: dict) -> tuple[int, float]:
    """Higher tuple sorts first. (category_priority, equity)."""
    cat_score = PRIORITY.get(row.get("category", ""), 0)
    try:
        equity = float(row.get("equity") or 0)
    except (ValueError, TypeError):
        equity = 0.0
    return (cat_score, equity)


def already_skip_traced(row: dict) -> bool:
    """Skip if we already have a phone (saves API quota)."""
    phone = (row.get("owner_phone") or "").strip()
    return phone not in ("", "0", "nan", "None")


def skip_trace_row(row: dict, api_key: str) -> tuple[bool, str]:
    """Call BatchData for one row. Mutates row, returns (success, summary)."""
    import json
    import urllib.request

    addr = (row.get("property_address") or "").strip()
    city = (row.get("city") or "").strip()
    zip_code = (row.get("zip") or "").strip()
    if not addr:
        return False, "no address"

    body = {
        "requests": [
            {
                "propertyAddress": {
                    "street": addr,
                    "city": city or "MIAMI",
                    "state": "FL",
                    "zip": zip_code or "33133",
                }
            }
        ]
    }

    req = urllib.request.Request(
        "https://api.batchdata.com/api/v1/property/skip-trace",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "101AdvisorsBot/0.2",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, f"API error: {e}"

    results = data.get("results", {})
    persons = results.get("persons", []) or []
    if not persons:
        return False, "no person match"

    person = persons[0]
    phones = person.get("phoneNumbers", []) or []
    emails = person.get("emails", []) or []
    full_name = person.get("name", {}) or {}

    if phones:
        phones_sorted = sorted(phones, key=lambda p: p.get("score", 0), reverse=True)
        row["owner_phone"] = phones_sorted[0].get("number", "") or ""

    if emails:
        emails_sorted = sorted(emails, key=lambda e: e.get("score", 0), reverse=True)
        row["owner_email"] = emails_sorted[0].get("email", "") or ""

    # Fill name if MLS/PA hadn't given it
    if not (row.get("owner_first") or "").strip():
        first = full_name.get("first") if isinstance(full_name, dict) else ""
        if not first and isinstance(full_name, str):
            first = full_name.split()[0] if full_name else ""
        if first:
            row["owner_first"] = first.strip()
    if not (row.get("owner_last") or "").strip():
        last = full_name.get("last") if isinstance(full_name, dict) else ""
        if not last and isinstance(full_name, str):
            parts = full_name.split(maxsplit=1)
            last = parts[1] if len(parts) > 1 else ""
        if last:
            row["owner_last"] = last.strip()

    summary_parts = []
    if row.get("owner_phone"):
        summary_parts.append(f"📞 {row['owner_phone']}")
    if row.get("owner_email"):
        summary_parts.append(f"✉️ {row['owner_email']}")
    return True, " · ".join(summary_parts) or "no contact info"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap", type=int, default=100,
                        help="Max leads to skip-trace this run (default: 100 = $20)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print who would be skip-traced, don't call API")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key and not args.dry_run:
        print("❌ BATCH_SKIP_API_KEY no encontrado.")
        print()
        print("Setup options:")
        print("  1) export BATCH_SKIP_API_KEY=tu_key && python3 -m scripts.skip_trace_leads")
        print("  2) Editar .streamlit/secrets.toml y agregar:")
        print('     BATCH_SKIP_API_KEY = "tu_key_aqui"')
        return 1

    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    # Filter: only leads without a phone yet, prioritized
    candidates = [r for r in rows if not already_skip_traced(r)]
    candidates.sort(key=lead_priority, reverse=True)
    to_trace = candidates[:args.cap]

    print(f"📋 Total leads:           {len(rows)}")
    print(f"📞 Sin phone:             {len(candidates)}")
    print(f"🎯 A skip-trace este run: {len(to_trace)} (cap={args.cap})")
    print(f"💵 Costo estimado:        ~${len(to_trace) * 0.20:.2f}")
    print()

    if args.dry_run:
        print("DRY RUN — los primeros 20 que se procesarían:")
        for i, r in enumerate(to_trace[:20], 1):
            print(f"  {i:3d}. {r.get('category','?'):<12} · {r.get('property_address','?')[:40]} "
                  f"· equity=${float(r.get('equity') or 0):,.0f}")
        return 0

    print(f"⏳ Skip-tracing {len(to_trace)} leads...")
    print()

    success = 0
    fail = 0
    for i, row in enumerate(to_trace, 1):
        addr = (row.get("property_address") or "")[:40]
        cat = row.get("category", "?")
        ok, summary = skip_trace_row(row, api_key)
        status = "✅" if ok else "⚪"
        print(f"  [{i:3d}/{len(to_trace)}] {status} {cat:<12} {addr:<40} {summary}")
        if ok:
            success += 1
        else:
            fail += 1
        time.sleep(0.5)  # Be polite to the API

    # Write back
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print("=" * 60)
    print(f"✅ Con phone/email: {success}/{len(to_trace)}")
    print(f"⚪ No match:        {fail}/{len(to_trace)}")
    print(f"💵 Costo real:      ~${success * 0.20:.2f}")
    print(f"💾 {CSV_PATH.relative_to(PROJECT)}")
    print()
    print("Push al repo:")
    print("  git add data/leads.csv")
    print(f"  git commit -m 'data: skip-traced {success} leads (phones + emails)'")
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
