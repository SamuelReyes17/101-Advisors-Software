"""
BatchSkipTracing — owner phone & email enrichment.

NOT a discovery collector. Takes a Lead and fills owner_phone / owner_email.

Endpoint: https://api.batchdata.com/api/v1/property/skip-trace
Auth: Bearer token (set BATCH_SKIP_API_KEY in environment / Streamlit secrets).
Pricing: pay-per-result, ~$0.10–0.25 per match.

USAGE:
    from pipeline.collectors.batch_skip import skip_trace

    enriched = skip_trace(lead)
    # lead.owner_phone, lead.owner_email now filled if BatchData found a match.

CAP & PRIORITIZATION:
    The orchestrator (pipeline/run.py) is responsible for limiting how many
    leads we send for skip-tracing this run, based on config.yaml limits.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from .base import Lead

log = logging.getLogger(__name__)

BATCH_API_URL = "https://api.batchdata.com/api/v1/property/skip-trace"


def skip_trace(lead: Lead) -> Lead:
    """Look up owner contact info for a lead. Mutates and returns the lead."""
    api_key = os.environ.get("BATCH_SKIP_API_KEY")
    if not api_key:
        log.warning("BATCH_SKIP_API_KEY not set — skipping skip-trace.")
        return lead

    body = {
        "requests": [
            {
                "propertyAddress": {
                    "street": lead.property_address,
                    "city": lead.city,
                    "state": "FL",
                    "zip": lead.zip,
                }
            }
        ]
    }

    req = urllib.request.Request(
        BATCH_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "101AdvisorsBot/0.2",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning("Skip-trace failed for lead %s: %s", lead.lead_id, e)
        return lead

    persons = data.get("results", {}).get("persons", [])
    if not persons:
        return lead

    person = persons[0]
    phones = person.get("phoneNumbers", [])
    emails = person.get("emails", [])

    if phones:
        # Prefer the highest-confidence dialable number.
        phones_sorted = sorted(phones, key=lambda p: p.get("score", 0), reverse=True)
        lead.owner_phone = phones_sorted[0].get("number", "")
    if emails:
        lead.owner_email = emails[0].get("email", "")

    if not lead.owner_first and not lead.owner_last and "name" in person:
        full = person["name"]
        parts = full.split(maxsplit=1)
        lead.owner_first = parts[0] if parts else ""
        lead.owner_last = parts[1] if len(parts) > 1 else ""

    return lead
