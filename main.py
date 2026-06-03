"""
hl-liquidation-heatmap — BTC liquidation heatmap, Hyperliquid perps
"""

import argparse
from fetcher import fetch_local_liquidations, db_count, DB_PATH
from processor import build_heatmap_data
from visualizer import plot_heatmap


def main():
    parser = argparse.ArgumentParser(description="BTC liquidation heatmap — Hyperliquid")
    parser.add_argument("--coin",   default="BTC", choices=["BTC", "ETH", "SOL"])
    parser.add_argument("--days",   type=int, default=7)
    parser.add_argument("--bucket", type=int, default=500)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print(f"\n=== HL Liquidation Heatmap | {args.coin} | {args.days}d | ${args.bucket} buckets ===\n")

    total_in_db = db_count(args.coin)
    print(f"[db]   {args.coin} liquidations in local DB: {total_in_db}")

    if total_in_db == 0:
        print("\n[!] No data yet. Start the streamer first:")
        print(f"    python stream.py --coins {args.coin}")
        print("    Let it run for a while, then re-run main.py")
        return

    fills = fetch_local_liquidations(coin=args.coin, days=args.days)
    print(f"       → {len(fills)} events in last {args.days}d\n")

    print(f"[proc] Building heatmap...")
    data = build_heatmap_data(fills, bucket_size=args.bucket, days=args.days)
    s = data["stats"]
    print(f"       Notional  : ${s['total_notional']:,.0f}")
    print(f"       Long/Short: {s['long_pct']:.0f}% / {100-s['long_pct']:.0f}%")
    print(f"       Hot zone  : ${s['hot_zone'][0]:,}–${s['hot_zone'][1]:,}")

    print("\n[viz]  Rendering...")
    plot_heatmap(data, coin=args.coin, days=args.days,
                 bucket_size=args.bucket, output=args.output)

    if args.output:
        print(f"       Saved → {args.output}")


if __name__ == "__main__":
    main()
