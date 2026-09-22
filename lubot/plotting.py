"""Chart rendering of a timeframe with liquidity, POIs and the two selected POIs."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .engine import TimeframeEngine

COLORS = {"OB": "#1f77b4", "BB": "#9467bd", "IMB": "#8c564b", "HB": "#17becf", "UW": "#ff7f0e"}


def plot_engine(e: TimeframeEngine, selection: Dict, out: str | Path, bars: int = 250,
                show_all_alive: bool = True, title: Optional[str] = None) -> Path:
    c = e.candles
    i1 = e.i
    i0 = max(0, i1 - bars + 1)
    xs = range(i0, i1 + 1)
    fig, ax = plt.subplots(figsize=(16, 8))
    for i in xs:
        col = "#2ca02c" if c.close[i] >= c.open[i] else "#d62728"
        ax.plot([i, i], [c.low[i], c.high[i]], color=col, linewidth=0.8)
        ax.add_patch(Rectangle((i - 0.35, min(c.open[i], c.close[i])), 0.7,
                               abs(c.close[i] - c.open[i]) or 1e-9, color=col))
    ymin = min(c.low[i0:i1 + 1])
    ymax = max(c.high[i0:i1 + 1])
    pad = (ymax - ymin) * 0.05

    # active liquidity
    for l in e.structure.liquidity:
        if not l.active or l.created_at > i1 or l.index < i0 - 50:
            continue
        if not (ymin - pad <= l.price <= ymax + pad):
            continue
        ls = "--" if l.kind in ("SH", "SL") else "-."
        ax.hlines(l.price, max(i0, l.index), i1 + 3, colors="gray", linestyles=ls, linewidth=0.7, alpha=0.7)
        ax.text(i1 + 3, l.price, l.kind, fontsize=6, color="gray", va="center")

    # alive POIs
    if show_all_alive:
        for p in e.detector.alive_pois(i1):
            if p.created_at > i1 or not (ymin - pad <= p.mid <= ymax + pad):
                continue
            x0 = max(i0, p.index)
            ax.add_patch(Rectangle((x0, p.bottom), i1 + 2 - x0, p.size, color=COLORS.get(p.kind, "k"), alpha=0.15))
            ax.text(x0, p.top, f"{p.kind}", fontsize=6, color=COLORS.get(p.kind, "k"), va="bottom")

    # the two selected POIs
    for side in ("above", "below"):
        d = selection.get(side)
        if not d:
            continue
        x0 = max(i0, d["bar_index"])
        ax.add_patch(Rectangle((x0, d["bottom"]), i1 + 5 - x0, d["top"] - d["bottom"],
                               facecolor=COLORS.get(d["type"], "k"), alpha=0.45, edgecolor="black", linewidth=1.5))
        q = d.get("quality")
        qtxt = f"\n P(bounce)={q:.0%} [{d.get('grade', '')}]" if q is not None else ""
        ax.text(i1 + 5, (d["top"] + d["bottom"]) / 2,
                f" {side.upper()} {d['type']} {d['direction']}\n {d['bottom']:.2f}-{d['top']:.2f}\n OF x{d['orderflow_count']}{qtxt}",
                fontsize=8, va="center", fontweight="bold")
        ymin = min(ymin, d["bottom"])
        ymax = max(ymax, d["top"])

    ax.axhline(selection["price"], color="black", linewidth=1, linestyle=":")
    ax.text(i0, selection["price"], f" price {selection['price']:.2f}", fontsize=8, va="bottom")
    ax.set_xlim(i0 - 1, i1 + 25)
    ax.set_ylim(ymin - pad, ymax + pad)
    step = max(1, bars // 10)
    ax.set_xticks(list(range(i0, i1 + 1, step)))
    ax.set_xticklabels([str(c.index[i])[5:16] for i in range(i0, i1 + 1, step)], rotation=30, fontsize=7)
    ax.set_title(title or f"{e.tf}  {selection['time']}  bias={selection['range_bias']} ({selection['price_zone']})")
    ax.grid(alpha=0.2)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
