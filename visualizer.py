"""
visualizer.py
Clean, readable liquidation heatmap.

Layout:
  Left  — horizontal bar chart: notional per price bucket (long=red, short=teal)
  Right — heatmap grid: time (x) × price level (y), cell color = dominant side,
          intensity = notional magnitude
"""

import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap


BG_COLOR       = "#0D0D0F"
SURFACE        = "#14141A"
GRID_COLOR     = "#252530"
TEXT_PRIMARY   = "#E8E6E1"
TEXT_SECONDARY = "#666680"
LONG_COLOR     = "#E05252"
SHORT_COLOR    = "#27AE7A"
HOT_COLOR      = "#FFD700"


def _fmt_price(p: float) -> str:
    return f"${p:,.0f}"


def _fmt_notional(n: float) -> str:
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"


def _trim_periods(periods, long_matrix, short_matrix):
    """Return only periods that have at least one event."""
    active = set()
    for d in (long_matrix, short_matrix):
        for bkt_map in d.values():
            active.update(bkt_map.keys())
    return [p for p in periods if p in active]


def plot_heatmap(
    data: dict,
    coin: str = "BTC",
    days: int = 7,
    bucket_size: int = 500,
    output: str | None = None,
) -> None:

    buckets = data["buckets"]
    periods = data["periods"]
    matrix  = data["matrix"]
    stats   = data["stats"]

    if not buckets:
        print("[viz] No data to render.")
        return

    # Trim to only periods with data
    periods = _trim_periods(periods, matrix["long"], matrix["short"])
    if not periods:
        print("[viz] No data to render.")
        return

    n_buckets = len(buckets)
    n_periods = len(periods)
    bucket_idx = {b: i for i, b in enumerate(buckets)}
    period_idx = {p: i for i, p in enumerate(periods)}

    # Build grids
    long_grid  = np.zeros((n_buckets, n_periods))
    short_grid = np.zeros((n_buckets, n_periods))

    for bkt, pmap in matrix["long"].items():
        if bkt in bucket_idx:
            for p, v in pmap.items():
                if p in period_idx:
                    long_grid[bucket_idx[bkt], period_idx[p]] = v

    for bkt, pmap in matrix["short"].items():
        if bkt in bucket_idx:
            for p, v in pmap.items():
                if p in period_idx:
                    short_grid[bucket_idx[bkt], period_idx[p]] = v

    total_grid = long_grid + short_grid
    max_val    = total_grid.max() or 1.0

    # ── figure setup ─────────────────────────────────────────────────────────
    plt.rcParams.update({
        "figure.facecolor": BG_COLOR,
        "axes.facecolor":   SURFACE,
        "axes.edgecolor":   GRID_COLOR,
        "text.color":       TEXT_PRIMARY,
        "xtick.color":      TEXT_SECONDARY,
        "ytick.color":      TEXT_PRIMARY,
        "font.family":      "monospace",
        "font.size":        9,
    })

    height = max(6, n_buckets * 0.55 + 3)
    width  = max(14, n_periods * 0.45 + 6)
    fig = plt.figure(figsize=(width, height), facecolor=BG_COLOR)

    # Left bar chart narrower, right heatmap wider
    gs = fig.add_gridspec(
        1, 2,
        width_ratios=[1, max(2, n_periods * 0.18)],
        left=0.01, right=0.97,
        top=0.84, bottom=0.14,
        wspace=0.02,
    )
    ax_bar  = fig.add_subplot(gs[0])
    ax_heat = fig.add_subplot(gs[1])

    y_pos = np.arange(n_buckets)
    price_labels = [f"${b:,}–${b+bucket_size:,}" for b in buckets]

    # ── left panel: bar chart ─────────────────────────────────────────────────
    long_totals  = [sum(matrix["long"].get(b, {}).values())  for b in buckets]
    short_totals = [sum(matrix["short"].get(b, {}).values()) for b in buckets]

    ax_bar.barh(y_pos, long_totals,  color=LONG_COLOR,  alpha=0.9,
                height=0.65, label="Long liq")
    ax_bar.barh(y_pos, short_totals, color=SHORT_COLOR, alpha=0.9,
                height=0.65, left=long_totals, label="Short liq")

    # Price labels on y-axis
    ax_bar.set_yticks(y_pos)
    ax_bar.set_yticklabels(price_labels, fontsize=8, color=TEXT_PRIMARY)
    ax_bar.set_ylim(-0.5, n_buckets - 0.5)

    # Highlight hot zone
    hot_bucket = stats["hot_zone"][0]
    if hot_bucket in bucket_idx:
        bi = bucket_idx[hot_bucket]
        ax_bar.get_yticklabels()[bi].set_color(HOT_COLOR)
        ax_bar.get_yticklabels()[bi].set_fontweight("bold")
        ax_bar.axhspan(bi - 0.4, bi + 0.4, color=HOT_COLOR, alpha=0.06, zorder=0)

    ax_bar.invert_xaxis()
    ax_bar.set_xlabel("Notional liquidated", fontsize=8, color=TEXT_SECONDARY, labelpad=6)
    ax_bar.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _fmt_notional(x)))
    ax_bar.tick_params(axis="x", labelsize=7, rotation=35, colors=TEXT_SECONDARY)
    ax_bar.tick_params(axis="y", length=0)
    ax_bar.set_facecolor(SURFACE)
    ax_bar.spines[:].set_color(GRID_COLOR)
    ax_bar.grid(axis="x", color=GRID_COLOR, linewidth=0.4, alpha=0.6)

    # ── right panel: heatmap ──────────────────────────────────────────────────
    # Build RGBA grid directly — no imshow blending artifacts
    # Each cell: color = long (red) if long > short, else short (teal)
    # Alpha = intensity relative to column max (so each time period is self-scaled)
    rgba = np.zeros((n_buckets, n_periods, 4))

    for pi in range(n_periods):
        col_max = total_grid[:, pi].max() or 1.0
        for bi in range(n_buckets):
            l = long_grid[bi, pi]
            s = short_grid[bi, pi]
            t = l + s
            if t == 0:
                continue
            intensity = min(t / col_max, 1.0) ** 0.55  # gamma for visibility
            if l >= s:
                r, g, b_ = mcolors.to_rgb(LONG_COLOR)
            else:
                r, g, b_ = mcolors.to_rgb(SHORT_COLOR)
            rgba[bi, pi] = [r, g, b_, intensity]

    ax_heat.imshow(
        rgba, aspect="auto", origin="lower",
        extent=[-0.5, n_periods - 0.5, -0.5, n_buckets - 0.5],
        interpolation="nearest",
    )

    # Grid lines between cells
    for xi in range(n_periods + 1):
        ax_heat.axvline(xi - 0.5, color=GRID_COLOR, linewidth=0.4, alpha=0.7)
    for yi in range(n_buckets + 1):
        ax_heat.axhline(yi - 0.5, color=GRID_COLOR, linewidth=0.4, alpha=0.7)

    # Hot zone line
    if hot_bucket in bucket_idx:
        bi = bucket_idx[hot_bucket]
        ax_heat.axhline(bi, color=HOT_COLOR, linewidth=1.0,
                        linestyle="--", alpha=0.7, zorder=5)

    # Notional labels inside cells for non-empty cells
    for bi in range(n_buckets):
        for pi in range(n_periods):
            t = total_grid[bi, pi]
            if t > 0:
                ax_heat.text(
                    pi, bi, _fmt_notional(t),
                    ha="center", va="center",
                    fontsize=6.5, color="white", alpha=0.85,
                    fontweight="bold",
                )

    # X-axis: time labels on all active periods
    ax_heat.set_xticks(range(n_periods))
    ax_heat.set_xticklabels(periods, rotation=45, ha="right", fontsize=8,
                             color=TEXT_SECONDARY)

    # Y-axis: price labels (right side of heatmap)
    ax_heat.set_yticks(y_pos)
    ax_heat.set_yticklabels(price_labels, fontsize=8, color=TEXT_PRIMARY)
    ax_heat.yaxis.set_label_position("right")
    ax_heat.yaxis.tick_right()

    # Highlight hot row
    if hot_bucket in bucket_idx:
        bi = bucket_idx[hot_bucket]
        ax_heat.get_yticklabels()[bi].set_color(HOT_COLOR)
        ax_heat.get_yticklabels()[bi].set_fontweight("bold")

    ax_heat.set_facecolor(SURFACE)
    ax_heat.spines[:].set_color(GRID_COLOR)
    ax_heat.tick_params(axis="y", length=0)
    ax_heat.set_ylim(-0.5, n_buckets - 0.5)

    # ── legend + titles ───────────────────────────────────────────────────────
    legend_handles = [
        mpatches.Patch(color=LONG_COLOR,  label=f"Long liq  {stats['long_pct']:.0f}%"),
        mpatches.Patch(color=SHORT_COLOR, label=f"Short liq {100-stats['long_pct']:.0f}%"),
        mpatches.Patch(color=HOT_COLOR,   label=f"Hot zone  {_fmt_price(stats['hot_zone'][0])}"),
    ]
    ax_bar.legend(
        handles=legend_handles, loc="lower left", fontsize=8,
        facecolor="#1A1A22", edgecolor=GRID_COLOR,
        labelcolor=TEXT_PRIMARY, framealpha=0.9,
    )

    window = f"{days}d" if days > 1 else "24h"
    fig.suptitle(
        f"{coin} Liquidation Heatmap  ·  {window}  ·  ${bucket_size} price buckets",
        fontsize=13, fontweight="bold", color=TEXT_PRIMARY, y=0.97,
    )
    fig.text(
        0.5, 0.925,
        f"Total: {_fmt_notional(stats['total_notional'])}  ·  "
        f"{stats['event_count']} events  ·  "
        f"Hot zone: {_fmt_price(stats['hot_zone'][0])}–{_fmt_price(stats['hot_zone'][1])}  ·  "
        f"Source: Hyperliquid activeAssetCtx OI-delta",
        ha="center", fontsize=8, color=TEXT_SECONDARY,
    )

    if output:
        plt.savefig(output, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    else:
        plt.show()

    plt.close(fig)
