"""
fetcher.py

Two modes:

  stream  — WebSocket listener: captures liquidations live, saves to local SQLite.
            Run once in background: python stream.py
            Builds up history over time.

  local   — Reads from the local SQLite written by the streamer.
            Used by main.py to render the heatmap.

Why: There is no free, no-auth HTTP endpoint for historical HL liquidations.
  - HL REST API:          no liquidation flag on any public endpoint
  - Dune free tier:       no fills table, ad-hoc SQL is paid-only
  - swell-network Dune:   wallet leaderboard only (addy, id columns)
  - Hydromancer S3:       requester-pays, needs AWS credentials
  - HL official S3:       needs AWS CLI + LZ4, monthly updates, may be missing
  - QuickNode SQL:        paid
"""

import json
import sqlite3
import time
import os
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(os.getenv("LIQUIDATION_DB", "liquidations.db"))


# ── database ─────────────────────────────────────────────────────────────────

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS liquidations (
            tid      TEXT PRIMARY KEY,
            coin     TEXT NOT NULL,
            px       REAL NOT NULL,
            sz       REAL NOT NULL,
            notional REAL NOT NULL,
            side     TEXT NOT NULL,
            ts       INTEGER NOT NULL,
            raw      TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_coin_ts ON liquidations (coin, ts)")
    conn.commit()
    return conn


def fetch_local_liquidations(coin: str = "BTC", days: int = 7) -> list[dict]:
    """Read captured liquidations from local SQLite."""
    if not DB_PATH.exists():
        return []

    cutoff_ms = int((time.time() - days * 86400) * 1000)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT px, notional, side, ts
        FROM liquidations
        WHERE coin = ? AND ts >= ?
        ORDER BY ts DESC
    """, (coin, cutoff_ms)).fetchall()
    conn.close()

    return [
        {"px": r[0], "notional": r[1], "side": r[2], "ts": r[3], "source": "ws"}
        for r in rows
    ]


def db_count(coin: str = "BTC") -> int:
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM liquidations WHERE coin=?", (coin,)).fetchone()[0]
    conn.close()
    return n
