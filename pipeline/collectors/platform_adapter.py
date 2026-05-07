"""
Platform Adapter — interface genérica para integrar con plataformas comerciales
de real estate data (PropStream, BatchLeads, Foreclosure.com, etc.).

DISEÑO:
    No sabemos todavía qué plataforma usa 101 Advisors. Para no perder tiempo
    cuando lo confirmen, este módulo define la INTERFACE estándar que todas
    las plataformas implementan. Cuando el cliente confirme, creamos una
    subclase que implementa los métodos específicos de esa plataforma.

USO FUTURO:
    from pipeline.collectors.platform_adapter import get_platform
    platform = get_platform()       # autodetecta basado en config
    leads = platform.search_distressed(
        county="Miami-Dade",
        categories=["Foreclosure", "Probate"],
        property_types=["Single Family", "Multi Family"],
    )

CONFIGURACIÓN:
    En config.yaml:
        platform:
          name: "propstream" | "batchleads" | "foreclosure_com" | "custom"
          api_key_env: "PLATFORM_API_KEY"        # nombre del env var
          base_url: "..."

    En GitHub Actions secrets:
        PLATFORM_API_KEY = <key del cliente>
        PLATFORM_USERNAME = <username, si scraping con login>
        PLATFORM_PASSWORD = <password, si scraping con login>
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from .base import Collector, Lead

log = logging.getLogger(__name__)


class PlatformAdapter(ABC):
    """Abstract interface for any commercial real-estate-data platform."""

    name: str = "abstract"

    @abstractmethod
    def authenticate(self) -> bool:
        """Login or set API key headers. Returns True if ready to query."""
        ...

    @abstractmethod
    def search_distressed(
        self,
        county: str,
        categories: list[str],
        property_types: list[str],
        days_back: int = 7,
    ) -> Iterable[Lead]:
        """Yield Lead objects matching the given criteria.

        Implementations:
        - Translate our categories (Foreclosure, Probate, Lis Pendens, Tax
          Delinquent, Liens) into the platform's filter terms.
        - Translate our property types into the platform's terms.
        - Page through results if needed.
        """
        ...


class _PlaceholderAdapter(PlatformAdapter):
    """No-op adapter — used until the real platform is configured.

    Logs a clear message and yields nothing. Pipeline keeps working;
    just produces zero leads from the platform until configured.
    """

    name = "placeholder"

    def authenticate(self) -> bool:
        log.warning(
            "Platform not yet configured. The pipeline runs but will not "
            "produce any leads until the client confirms which platform "
            "they pay for and shares credentials. See docs/CREDENTIALS_NEEDED.md"
        )
        return False

    def search_distressed(
        self,
        county: str,
        categories: list[str],
        property_types: list[str],
        days_back: int = 7,
    ) -> Iterable[Lead]:
        return
        yield  # noqa


# =========================================================================
# Adapter registry — add new platforms here when client confirms
# =========================================================================
_REGISTRY: dict[str, type[PlatformAdapter]] = {
    "placeholder": _PlaceholderAdapter,
    # "propstream": PropStreamAdapter,            # TODO when confirmed
    # "batchleads": BatchLeadsAdapter,            # TODO when confirmed
    # "foreclosure_com": ForeclosureComAdapter,   # TODO when confirmed
}


def get_platform(config: dict | None = None) -> PlatformAdapter:
    """Factory — returns the platform adapter configured for this run."""
    name = (config or {}).get("platform", {}).get("name", "placeholder")
    cls = _REGISTRY.get(name, _PlaceholderAdapter)
    return cls()


# =========================================================================
# Wrapper Collector — used by the pipeline orchestrator
# =========================================================================
class PlatformCollector(Collector):
    """Collector that delegates to the configured PlatformAdapter."""

    name = "platform"

    def __init__(self, config: dict):
        super().__init__(config)
        self.adapter = get_platform(config)
        # category from the FIRST configured category — informational only
        cats = [k for k, v in (config.get("categories") or {}).items() if v]
        self.category = cats[0].title() if cats else "Multiple"

    def fetch(self) -> Iterable[Lead]:
        if not self.adapter.authenticate():
            log.warning("Platform adapter '%s' not authenticated — skipping.", self.adapter.name)
            return

        cats = [k.replace("_", " ").title() for k, v in (self.config.get("categories") or {}).items() if v]
        ptypes = self.config.get("include_property_types", [])
        for county in self.config.get("counties", []):
            yield from self.adapter.search_distressed(
                county=county,
                categories=cats,
                property_types=ptypes,
                days_back=self.config.get("refresh", {}).get("days_back", 7),
            )
