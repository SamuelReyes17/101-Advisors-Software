"""
Base classes for data collectors.

Every collector inherits from `Collector` and implements `fetch()`.
The orchestrator (pipeline/run.py) iterates over all enabled collectors,
calls `fetch()`, normalizes the rows, and writes the output CSV.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Iterable

log = logging.getLogger(__name__)


@dataclass
class Lead:
    """Canonical schema. All collectors return rows in this shape."""

    lead_id: str
    first_seen: date
    last_updated: date
    county: str                          # Miami-Dade | Broward | Palm Beach
    category: str                        # Foreclosure | Probate | Lis Pendens | Tax Delinquent | Liens
    property_address: str
    city: str
    zip: str
    folio: str = ""                      # parcel ID (empty if not yet enriched)
    property_type: str = ""              # Single Family | Multi Family | Duplex | Triplex | Fourplex | (other)
    units: int = 0
    bedrooms: int = 0
    owner_first: str = ""
    owner_last: str = ""
    owner_phone: str = ""                # filled by skip-tracing
    owner_email: str = ""                # filled by skip-tracing
    lender_name: str = ""
    lender_phone: str = ""
    lender_email: str = ""
    bank_address: str = ""
    outstanding_debt: float = 0.0
    unpaid_taxes_2024: float = 0.0
    unpaid_taxes_2025: float = 0.0
    equity: float = 0.0
    status: str = "New"
    assigned_to: str = ""
    notes: str = ""
    source: str = ""                     # which collector produced this row

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Collector(ABC):
    """Abstract base. Subclass it for each new source."""

    name: str = "abstract"
    county: str = ""
    category: str = ""
    enabled: bool = True

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def fetch(self) -> Iterable[Lead]:
        """Return an iterable of Lead objects.

        Implementations should:
        - Make HTTP requests to the source.
        - Parse the response.
        - Yield Lead objects (one per match found).
        - Use logging (log.info / log.warning) for visibility.
        - On error: raise CollectorError with helpful message.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} county={self.county} category={self.category}>"


class CollectorError(Exception):
    """Raised when a collector fails non-recoverably."""
