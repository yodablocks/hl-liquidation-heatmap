"""
stream.py — Liquidation inference via OI delta + markPx

Instead of trying to catch fill-level liquidation flags (not exposed on
the public trades feed), we infer liquidations from open interest drops
on the activeAssetCtx feed.

Logic:
  - Subscribe to activeAssetCtx per coin (~1s updates)
  - When OI drops by > threshold in one tick, a liquidation likely occurred
  - Record: price = markPx at that tick, notional = OI_drop * markPx
  - Side inference: if price falling → longs liquidated; rising → shorts

This is chain-native data (same source as the HL UI liquidation display)
and requires no fill metadata or special permissions.

Threshold tuning:
  BTC: 0.01 BTC minimum drop (~$670 at $67k) — filters noise
  ETH: 0.1 ETH minimum drop
  SOL: 1 SOL minimum drop
"""

import argparse
import json
import logging
import signal
import sqlite3
import sys
import time
from pathlib import Path

try:
    import websocket
except ImportError:
    print("pip install websocket-client")
    sys.exit(1)

from fetcher import init_db, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HL_WS = "wss://api.hyperliquid.xyz/ws"

# Minimum OI drop (in coin units) to count as a liquidation event
MIN_DROP = {
    "BTC": 0.01,   # ~$670
    "ETH": 0.1,    # ~$250
    "SOL": 1.0,    # ~$130
}
DEFAULT_MIN_DROP = 0.01

_prev: dict[str, dict] = {}   # coin → {oi, px, ts}
_stats = {"ticks": 0, "liqs": 0, "saved": 0}
_conn: sqlite3.Connection | None = None
_running = True


def _infer_side(px_now: float, px_prev: float) -> str:
    """Price falling → longs getting liquidated. Rising → shorts."""
    return "long" if px_now <= px_prev else "short"


def _process_ctx(coin: str, ctx: dict, ts_ms: int):
    global _conn

    oi    = float(ctx.get("openInterest", 0))
    px    = float(ctx.get("markPx", 0))
    _stats["ticks"] += 1

    prev = _prev.get(coin)
    _prev[coin] = {"oi": oi, "px": px, "ts": ts_ms}

    if prev is None or oi <= 0 or px <= 0:
        return

    oi_drop = prev["oi"] - oi   # positive = OI decreased = positions closed
    threshold = MIN_DROP.get(coin, DEFAULT_MIN_DROP)

    if oi_drop < threshold:
        return

    # OI dropped meaningfully — infer liquidation
    notional = oi_drop * px
    side     = _infer_side(px, prev["px"])
    tid      = f"{coin}_{ts_ms}"

    _stats["liqs"] += 1
    log.info("LIQ  %-6s  %-5s  OI_drop=%.4f  px=%-10.1f  notional=$%.0f",
             coin, side.upper(), oi_drop, px, notional)

    if _conn is None:
        return

    try:
        _conn.execute("""
            INSERT OR IGNORE INTO liquidations
              (tid, coin, px, sz, notional, side, ts, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tid, coin, px, oi_drop, notional, side, ts_ms,
              json.dumps({"oi_drop": oi_drop, "oi_after": oi,
                          "oi_before": prev["oi"], "px": px})))
        _conn.commit()
        _stats["saved"] += 1
    except Exception as e:
        log.warning("save error: %s", e)


def on_open(ws, coins):
    log.info("Connected to %s", HL_WS)
    for coin in coins:
        ws.send(json.dumps({
            "method": "subscribe",
            "subscription": {"type": "activeAssetCtx", "coin": coin, "dex": ""}
        }))
        log.info("Subscribed activeAssetCtx:%s", coin)


def on_message(ws, message):
    msg = json.loads(message)
    if msg.get("channel") != "activeAssetCtx":
        return
    data = msg.get("data", {})
    coin = data.get("coin", "")
    ctx  = data.get("ctx", {})
    ts   = int(time.time() * 1000)
    _process_ctx(coin, ctx, ts)

    if _stats["ticks"] % 100 == 0:
        log.info("ticks=%d  liq_events=%d  saved=%d",
                 _stats["ticks"], _stats["liqs"], _stats["saved"])


def on_error(ws, e): log.error("WS error: %s", e)
def on_close(ws, *a): log.info("WS closed")


def run(coins: list[str]):
    global _conn, _running

    _conn = init_db()
    log.info("DB: %s", DB_PATH.resolve())
    log.info("Streaming OI-delta liquidation inference for: %s", ", ".join(coins))
    log.info("Press Ctrl+C to stop\n")

    def _sigint(sig, frame):
        log.info("Stopping — saved %d inferred liquidations", _stats["saved"])
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    while _running:
        try:
            ws = websocket.WebSocketApp(
                HL_WS,
                on_open=lambda ws: on_open(ws, coins),
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            log.error("Connection error: %s — reconnecting in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    args = parser.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",")]
    run(coins)
