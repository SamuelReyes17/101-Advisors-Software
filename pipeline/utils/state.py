"""
State tracking — recordamos qué leads ya vimos, cuándo, y cuáles son nuevos.

SQLite local en data/state.sqlite. Usa una sola tabla `leads_seen`.
Se commitea al repo igual que el CSV — así GitHub Actions tiene memoria entre corridas.

Schema:
    leads_seen
      lead_id      TEXT PRIMARY KEY
      first_seen   DATE
      last_seen    DATE
      payload_json TEXT       -- snapshot del último JSON visto
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads_seen (
    lead_id TEXT PRIMARY KEY,
    first_seen DATE NOT NULL,
    last_seen DATE NOT NULL,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_first_seen ON leads_seen(first_seen);
"""


class StateDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def seen(self, lead_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM leads_seen WHERE lead_id = ?", (lead_id,)
        )
        return cur.fetchone() is not None

    def remember(self, lead_id: str, payload: dict[str, Any], today: date) -> bool:
        """Returns True if NEW (was not seen before), False if updating existing."""
        is_new = not self.seen(lead_id)
        if is_new:
            self.conn.execute(
                "INSERT INTO leads_seen (lead_id, first_seen, last_seen, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (lead_id, today, today, json.dumps(payload, default=str)),
            )
        else:
            self.conn.execute(
                "UPDATE leads_seen SET last_seen = ?, payload_json = ? WHERE lead_id = ?",
                (today, json.dumps(payload, default=str), lead_id),
            )
        self.conn.commit()
        return is_new

    def first_seen_for(self, lead_id: str) -> date | None:
        cur = self.conn.execute(
            "SELECT first_seen FROM leads_seen WHERE lead_id = ?", (lead_id,)
        )
        row = cur.fetchone()
        return date.fromisoformat(row[0]) if row else None

    def close(self):
        self.conn.close()
