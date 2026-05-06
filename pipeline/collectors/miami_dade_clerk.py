"""
Miami-Dade Clerk of Court — Foreclosure & Lis Pendens collector.

DESCUBRE leads (a diferencia del Property Appraiser que solo enriquece).

Approach (sin Commercial Data Services subscription):
    Scrape el portal público de Online Case Search:
    https://www2.miamidadeclerk.gov/ocs/Search.aspx

Strategy:
    1. Search por case type "Foreclosure" filed en los últimos N días.
    2. Para cada match, parsea: case number, filing date, party names, address.
    3. Cruza dirección con Property Appraiser para enriquecer.
    4. Yield Lead objects.

STATUS: STUB — pendiente investigación de la estructura HTML del portal.

TODO antes de producción:
    [ ] Inspeccionar https://www2.miamidadeclerk.gov/ocs/ con browser dev tools
    [ ] Identificar el form POST que dispara la búsqueda
    [ ] Capturar el HTML de resultados, escribir parser con BeautifulSoup
    [ ] Manejar paginación (probablemente <100 cases por día — manageable)
    [ ] Test contra rangos de fecha conocidos para validar coverage
    [ ] Considerar dejar respetar robots.txt + rate limit (1 req/seg)

Si el scraping resulta inestable, fallback es activar Commercial Data Services API ($0.20/req)
y usar el endpoint oficial — el código del fetch cambiaría pero todo lo demás se mantiene.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

from .base import Collector, Lead, CollectorError

log = logging.getLogger(__name__)


class MiamiDadeForeclosureCollector(Collector):
    name = "miami_dade_foreclosure"
    county = "Miami-Dade"
    category = "Foreclosure"

    SEARCH_URL = "https://www2.miamidadeclerk.gov/ocs/Search.aspx"

    def fetch(self) -> Iterable[Lead]:
        log.info("MiamiDadeForeclosureCollector starting...")

        # =====================================================================
        # TODO: implementar el scraping real.
        #
        # Pasos previstos:
        # 1. session = requests.Session()
        # 2. Hacer GET a SEARCH_URL para obtener el __VIEWSTATE y __EVENTVALIDATION.
        # 3. Hacer POST con form data:
        #    - txtCaseType = "Foreclosure"
        #    - dtpFromDate = (today - 7 days)
        #    - dtpToDate = today
        # 4. Parsear tabla HTML de resultados con BeautifulSoup.
        # 5. Para cada row: navegar al detalle del caso, sacar property address.
        # 6. yield Lead(...)
        # =====================================================================

        log.warning(
            "MiamiDadeForeclosureCollector is a STUB — no leads will be returned. "
            "See the TODO list in the source file."
        )

        # Por ahora yield nada (devuelve generador vacío).
        return
        yield  # noqa: unreachable, makes it a generator


class MiamiDadeLisPendensCollector(Collector):
    name = "miami_dade_lispendens"
    county = "Miami-Dade"
    category = "Lis Pendens"

    def fetch(self) -> Iterable[Lead]:
        log.warning("MiamiDadeLisPendensCollector is a STUB.")
        return
        yield


class MiamiDadeProbateCollector(Collector):
    name = "miami_dade_probate"
    county = "Miami-Dade"
    category = "Probate"

    def fetch(self) -> Iterable[Lead]:
        log.warning("MiamiDadeProbateCollector is a STUB.")
        return
        yield
