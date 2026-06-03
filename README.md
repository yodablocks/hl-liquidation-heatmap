# hl-liquidation-heatmap

Realized BTC (ETH/SOL) liquidation heatmap for Hyperliquid perps.

## Why a streamer, not a REST pull?

There is no free, no-auth HTTP endpoint for historical Hyperliquid liquidations:

| Source | Why it fails |
|--------|-------------|
| HL REST API | No liquidation flag on any public endpoint |
| Dune free tier | No fills table; ad-hoc SQL is paid-only |
| `swell-network` Dune dataset | Wallet leaderboard only — no trades |
| Hydromancer S3 | Requester-pays, needs AWS credentials |
| HL official S3 | Needs AWS CLI + LZ4, monthly updates, may be missing |

Solution: subscribe to the HL WebSocket trades feed, detect liquidation fills
in real-time, persist to local SQLite. Run `stream.py` in the background.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Step 1 — start the streamer (runs in background, Ctrl+C to stop)
python stream.py --coins BTC,ETH,SOL

# Step 2 — once you have data, render the heatmap
python main.py --coin BTC --days 7

# Save to file
python main.py --coin BTC --output btc_liqs.png
```

The streamer reconnects automatically on disconnect. Leave it running
during volatile periods for the best signal density.

## Structure

```
hl-liquidation-heatmap/
├── stream.py       # WebSocket daemon — captures live liquidations to SQLite
├── main.py         # CLI — renders heatmap from local DB
├── fetcher.py      # DB read/write helpers
├── processor.py    # Price bucketing + heatmap matrix builder
├── visualizer.py   # Matplotlib renderer (dark theme)
├── requirements.txt
└── liquidations.db # Created automatically by stream.py
```

## Liquidation detection

HL trades feed sends fill pairs. Liquidation fills are identified by:
1. `liquidation` key present in the fill dict
2. `dir` field containing `"liquidation"` (e.g. `"Buy (Liquidation)"`)

Side interpretation: `B` (buy) = HLP taking over a long position = long liquidation.
`A` (sell) = HLP taking over a short position = short liquidation.
