"""
CSV writer — exporta leads a data/leads.csv en el schema que el dashboard espera.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..collectors.base import Lead


# Column order matches data/sample_leads.csv (the dashboard reads this).
COLUMNS = [
    "lead_id", "first_seen", "last_updated", "county", "category",
    "property_address", "city", "zip", "property_type", "units", "bedrooms",
    "owner_first", "owner_last", "owner_phone", "owner_email",
    "lender_name", "lender_phone", "lender_email", "bank_address",
    "outstanding_debt", "unpaid_taxes_2024", "unpaid_taxes_2025", "equity",
    "status", "assigned_to", "notes",
]


def write_csv(leads: Iterable[Lead], path: str | Path) -> int:
    """Write leads to CSV. Returns count written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_dict())
            count += 1
    return count


def append_csv(leads: Iterable[Lead], path: str | Path) -> int:
    """Append to history CSV (creates file with header on first call)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()

    count = 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_dict())
            count += 1
    return count
