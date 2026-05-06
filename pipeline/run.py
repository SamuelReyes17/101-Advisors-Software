"""
Pipeline orchestrator.

Run manually:
    python -m pipeline.run

Run from GitHub Actions:
    See .github/workflows/daily_pipeline.yml

Steps:
    1. Load config.yaml.
    2. Iterate over enabled collectors → fetch().
    3. For each lead: enrich with Property Appraiser (property type / units / beds).
    4. Filter by include/exclude property type rules.
    5. Dedup against state.sqlite — mark new vs. seen-before.
    6. Skip-trace top-N new leads (cap configurable).
    7. Write data/leads.csv (dashboard reads this).
    8. Append to data/history.csv.
    9. Commit state.sqlite back so GitHub Actions remembers next run.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import yaml

from .collectors.base import Collector, Lead
from .collectors.miami_dade_clerk import (
    MiamiDadeForeclosureCollector,
    MiamiDadeLisPendensCollector,
    MiamiDadeProbateCollector,
)
from .collectors.miami_dade_tax import MiamiDadeTaxDelinquentCollector
from .collectors.property_appraiser import enrich_by_address, is_target_property_type
from .collectors.batch_skip import skip_trace
from .utils.state import StateDB
from .utils.csv_writer import write_csv, append_csv

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "pipeline" / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def select_collectors(config: dict) -> list[Collector]:
    """Return the collectors enabled by config."""
    cats = config.get("categories", {})
    counties = set(config.get("counties", []))
    out: list[Collector] = []

    if "Miami-Dade" in counties:
        if cats.get("foreclosure"):
            out.append(MiamiDadeForeclosureCollector(config))
        if cats.get("lis_pendens"):
            out.append(MiamiDadeLisPendensCollector(config))
        if cats.get("probate"):
            out.append(MiamiDadeProbateCollector(config))
        if cats.get("tax_delinquent"):
            out.append(MiamiDadeTaxDelinquentCollector(config))

    # TODO: Broward, Palm Beach when those collectors are built
    return out


def enrich_lead(lead: Lead, config: dict) -> Lead:
    """Cross-reference with Property Appraiser to fill property_type, units, beds."""
    if lead.county != "Miami-Dade":
        return lead  # other counties get their own appraiser later

    info = enrich_by_address(lead.property_address, lead.city)
    if not info:
        return lead

    if not lead.folio and info.get("folio"):
        lead.folio = info["folio"]
    if not lead.property_type and info.get("property_type"):
        lead.property_type = info["property_type"]
    if not lead.units and info.get("units"):
        lead.units = info["units"]
    if not lead.bedrooms and info.get("bedrooms"):
        lead.bedrooms = info["bedrooms"]
    if not lead.owner_first and info.get("owner_name"):
        parts = info["owner_name"].split(maxsplit=1)
        lead.owner_first = parts[0] if parts else ""
        lead.owner_last = parts[1] if len(parts) > 1 else ""

    return lead


def passes_filter(lead: Lead, config: dict) -> bool:
    include = config.get("include_property_types", [])
    exclude = config.get("exclude_property_types", [])
    if lead.property_type in exclude:
        return False
    if lead.property_type in include:
        return True
    # If property_type couldn't be determined, keep it for human review.
    return lead.property_type == ""


def prioritize_for_skip_trace(leads: list[Lead], config: dict) -> list[Lead]:
    order = config.get("limits", {}).get("batch_skip_priority_order", [])
    rank = {cat: i for i, cat in enumerate(order)}

    def key(lead: Lead) -> int:
        return rank.get(lead.category, 99)

    return sorted(leads, key=key)


def run(today: date | None = None) -> int:
    today = today or date.today()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    config = load_config()
    log.info("Pipeline starting · today=%s", today)
    log.info("Counties: %s", config.get("counties"))

    state = StateDB(PROJECT_ROOT / config["output"]["state_db_path"])
    collectors = select_collectors(config)
    log.info("Enabled collectors: %s", [c.name for c in collectors])

    raw_leads: list[Lead] = []
    for collector in collectors:
        try:
            n = 0
            for lead in collector.fetch():
                raw_leads.append(lead)
                n += 1
            log.info("  %s → %d leads", collector.name, n)
        except Exception as e:
            log.error("Collector %s failed: %s", collector.name, e, exc_info=True)

    log.info("Total raw leads collected: %d", len(raw_leads))

    # Enrich
    enriched = [enrich_lead(l, config) for l in raw_leads]

    # Filter
    filtered = [l for l in enriched if passes_filter(l, config)]
    log.info("After property-type filter: %d leads", len(filtered))

    # Dedup → mark new vs. seen
    new_leads: list[Lead] = []
    for lead in filtered:
        is_new = state.remember(lead.lead_id, lead.to_dict(), today)
        if is_new:
            lead.first_seen = today
            new_leads.append(lead)
        # update last_updated regardless
        lead.last_updated = today

    log.info("New leads today: %d (rest already seen)", len(new_leads))

    # Skip-trace (cap)
    cap = config.get("limits", {}).get("batch_skip_max_lookups_per_month", 100)
    to_trace = prioritize_for_skip_trace(new_leads, config)[:cap]
    log.info("Skip-tracing %d leads...", len(to_trace))
    for lead in to_trace:
        skip_trace(lead)

    # Write outputs
    output_csv = PROJECT_ROOT / config["output"]["csv_path"]
    history_csv = PROJECT_ROOT / config["output"]["history_csv_path"]

    n_written = write_csv(filtered, output_csv)
    n_history = append_csv(new_leads, history_csv)
    log.info("Wrote %d leads to %s · appended %d to history", n_written, output_csv, n_history)

    state.close()
    log.info("Pipeline done.")
    return n_written


if __name__ == "__main__":
    run()
