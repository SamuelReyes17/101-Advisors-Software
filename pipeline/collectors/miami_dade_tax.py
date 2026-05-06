"""
Miami-Dade Tax Collector — Delinquent property collector.

Source: https://mdctaxcollector.gov/delinquent-taxes-current-year-and-prior-years

Strategy:
    1. Descargar la lista oficial de delinquent properties (PDF o HTML).
       El Tax Collector publica reportes legales — algunos como PDF en miamidade.gov.
    2. Parsear las filas: folio, owner of record, amount due.
    3. Cruzar con Property Appraiser por folio → property type / address.
    4. Filter: solo single family / multi family / duplex / triplex / fourplex.
    5. Yield Lead objects.

NOTA: 2025 unpaid taxes son delinquentes desde el 1 de abril 2026.
La lista actualizada típicamente sale a fines de mayo / junio cada año.

STATUS: STUB — pendiente confirmar formato exacto del archivo descargable.

TODO:
    [ ] Investigar https://www.miamidade.gov/resources/legal-ads/county/tax-collector/
        para encontrar el delinquent list PDF más reciente.
    [ ] Si es PDF: usar pdfplumber para extraer la tabla.
    [ ] Si es HTML: usar BeautifulSoup.
    [ ] Si requiere public records request: documentar el proceso en README.
    [ ] Implementar parser → yield Lead(category="Tax Delinquent")
"""
from __future__ import annotations

import logging
from typing import Iterable

from .base import Collector, Lead

log = logging.getLogger(__name__)


class MiamiDadeTaxDelinquentCollector(Collector):
    name = "miami_dade_tax_delinquent"
    county = "Miami-Dade"
    category = "Tax Delinquent"

    LIST_URL = "https://mdctaxcollector.gov/delinquent-taxes-current-year-and-prior-years"

    def fetch(self) -> Iterable[Lead]:
        log.warning("MiamiDadeTaxDelinquentCollector is a STUB. See TODOs.")
        return
        yield
