"""
processor.py
Takes raw liquidation fill events and builds the heatmap data structure:
  - price buckets (y-axis)
  - time periods (x-axis)
  - notional per (bucket, period, side)
"""

import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta


def _bucket(price: float, size: int) -> int:
    """Floor price to nearest bucket boundary."""
    return int(math.floor(price / size) * size)


def _period_label(ts_ms: int, days: int) -> str:
    """
    Map a timestamp to a human-readable period label.
    Granularity scales with the lookback window:
      ≤2d  → hourly   (e.g. "14:00")
      ≤14d → daily    (e.g. "Jun 01")
      >14d → weekly   (e.g. "W22")
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    if days <= 2:
        return dt.strftime("%H:00")
    elif days <= 14:
        return dt.strftime("%b %d")
    else:
        week = dt.isocalendar().week
        return f"W{week:02d}"


def _generate_period_labels(days: int) -> list[str]:
    """Generate ordered period labels for the full lookback window."""
    now = datetime.now(tz=timezone.utc)
    labels = []

    if days <= 2:
        hours = days * 24
        for i in range(hours, 0, -1):
            dt = now - timedelta(hours=i)
            labels.append(dt.strftime("%H:00"))
    elif days <= 14:
        for i in range(days, -1, -1):  # include today
            dt = now - timedelta(days=i)
            labels.append(dt.strftime("%b %d"))
    else:
        weeks = math.ceil(days / 7)
        for i in range(weeks, 0, -1):
            dt = now - timedelta(weeks=i)
            week = dt.isocalendar().week
            labels.append(f"W{week:02d}")

    seen = set()
    unique = []
    for l in labels:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    return unique


def build_heatmap_data(
    fills: list[dict],
    bucket_size: int = 500,
    days: int = 7,
) -> dict:
    """
    Process raw fill events into a heatmap-ready data structure.

    Returns:
    {
        "buckets":      sorted list of price bucket lower bounds,
        "periods":      ordered list of period labels (x-axis),
        "matrix": {
            "long":  { bucket: { period: notional } },
            "short": { bucket: { period: notional } },
        },
        "bucket_totals": { bucket: total_notional },
        "period_totals": { period: total_notional },
        "stats": {
            "total_notional": float,
            "long_notional":  float,
            "short_notional": float,
            "long_pct":       float,
            "hot_zone":       (low, high),
            "event_count":    int,
        }
    }
    """
    periods = _generate_period_labels(days)
    period_set = set(periods)

    long_matrix  = defaultdict(lambda: defaultdict(float))
    short_matrix = defaultdict(lambda: defaultdict(float))
    bucket_totals = defaultdict(float)
    period_totals = defaultdict(float)

    total_long  = 0.0
    total_short = 0.0
    event_count = 0

    for f in fills:
        try:
            px       = float(f["px"])
            notional = float(f["notional"])
            side     = f["side"]
            ts_ms    = int(f["ts"])
        except (KeyError, ValueError, TypeError):
            continue

        if px <= 0 or notional <= 0:
            continue

        bkt    = _bucket(px, bucket_size)
        period = _period_label(ts_ms, days)

        if period not in period_set:
            continue

        if side == "long":
            long_matrix[bkt][period]  += notional
            total_long += notional
        else:
            short_matrix[bkt][period] += notional
            total_short += notional

        bucket_totals[bkt] += notional
        period_totals[period] += notional
        event_count += 1

    all_buckets = sorted(set(long_matrix.keys()) | set(short_matrix.keys()))

    total_notional = total_long + total_short
    long_pct = (total_long / total_notional * 100) if total_notional > 0 else 50.0

    hot_bucket = max(bucket_totals, key=bucket_totals.get) if bucket_totals else 0
    hot_zone   = (hot_bucket, hot_bucket + bucket_size)

    return {
        "buckets": all_buckets,
        "periods": periods,
        "matrix": {
            "long":  dict(long_matrix),
            "short": dict(short_matrix),
        },
        "bucket_totals": dict(bucket_totals),
        "period_totals": dict(period_totals),
        "stats": {
            "total_notional": total_notional,
            "long_notional":  total_long,
            "short_notional": total_short,
            "long_pct":       long_pct,
            "hot_zone":       hot_zone,
            "event_count":    event_count,
        },
    }
