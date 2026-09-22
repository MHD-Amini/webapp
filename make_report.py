#!/usr/bin/env python3
"""Build charts + a markdown report from study_results/touches.pkl."""
import argparse
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from lubot.study import BOUNCE_LEVELS_ATR, R_LEVELS, SCENARIOS, aggregate, aggregate_scenarios  # noqa: E402

TF_ORDER = ["M5", "M10", "M15", "M30", "H1"]


def charts(df: pd.DataFrame, out: Path) -> None:
    r = df[df.reached]
    out.mkdir(parents=True, exist_ok=True)

    # 1. bounce distribution per TF (clipped at 6 ATR)
    fig, ax = plt.subplots(figsize=(11, 5))
    data = [r[r.tf == tf].bounce_atr.clip(upper=6).to_numpy() for tf in TF_ORDER if (r.tf == tf).any()]
    labels = [f"{tf}\n(n={int((r.tf == tf).sum())})" for tf in TF_ORDER if (r.tf == tf).any()]
    ax.boxplot(data, labels=labels, showfliers=False, whis=(10, 90))
    for k, d in enumerate(data, start=1):
        ax.scatter(np.random.normal(k, 0.06, len(d)), d, s=3, alpha=0.15, color="tab:blue")
    ax.axhline(1, color="gray", ls="--", lw=0.8)
    ax.set_ylabel("bounce from POI edge (ATR, clipped at 6)")
    ax.set_title("How far does price bounce after touching a selected POI? (box = 25-75%, whiskers = 10-90%)")
    fig.tight_layout()
    fig.savefig(out / "bounce_distribution_by_tf.png", dpi=120)
    plt.close(fig)

    # 2. survival curve: P(bounce >= x ATR) per TF, plus P(bounce >= x ATR before SL)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    xs = np.linspace(0, 5, 101)
    for tf in TF_ORDER:
        g = r[r.tf == tf]
        if not len(g):
            continue
        axes[0].plot(xs, [(g.bounce_free_atr >= x).mean() * 100 for x in xs], label=tf)
        axes[1].plot(xs, [(g.bounce_atr >= x).mean() * 100 for x in xs], label=tf)
    axes[0].set_title("P(bounce ≥ x ATR) within the hold window (no stop)")
    axes[1].set_title("P(bounce ≥ x ATR) BEFORE stop (far edge + 0.1 ATR) is hit")
    for ax in axes:
        ax.set_xlabel("x (ATR of the timeframe)")
        ax.set_ylabel("%")
        ax.grid(alpha=0.3)
        ax.legend()
        ax.set_ylim(0, 100)
    fig.tight_layout()
    fig.savefig(out / "bounce_probability_curves.png", dpi=120)
    plt.close(fig)

    # 3. penetration distribution
    fig, ax = plt.subplots(figsize=(11, 5))
    pen = r.penetration_zone.clip(upper=4)
    ax.hist(pen, bins=40, color="tab:orange", alpha=0.8)
    ax.axvline(1, color="k", ls="--")
    ax.text(1.02, ax.get_ylim()[1] * 0.9, "far edge of the zone", fontsize=9)
    ax.set_xlabel("penetration into the zone before SL / end (1.0 = traded through the entire zone)")
    ax.set_ylabel("touches")
    ax.set_title(f"How deep does price go into the POI? median {r.penetration_zone.median():.2f} zone-heights; "
                 f"{(r.penetration_zone > 1).mean() * 100:.0f}% go all the way through")
    fig.tight_layout()
    fig.savefig(out / "penetration_distribution.png", dpi=120)
    plt.close(fig)

    # 4. by POI type
    agg = aggregate(df, ["kind"])
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(agg))
    w = 0.25
    ax.bar(x - w, agg["ge0.5ATR_%"], w, label="bounce ≥0.5 ATR")
    ax.bar(x, agg["ge1ATR_%"], w, label="bounce ≥1 ATR")
    ax.bar(x + w, agg["ge2ATR_%"], w, label="bounce ≥2 ATR")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{g}\n(n={n})" for g, n in zip(agg.group, agg.reached)])
    ax.set_ylabel("% of touches (before SL)")
    ax.set_title("Bounce probability by POI type")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "bounce_by_type.png", dpi=120)
    plt.close(fig)

    # 5. by session
    agg = aggregate(df, ["session"], min_n=10)
    order = ["Asia (17-01)", "London (01-05)", "Pre-NY (05-07)", "New York (07-10)", "London Close (10-12)", "NY PM (12-17)"]
    agg["o"] = agg.group.map({s: i for i, s in enumerate(order)})
    agg = agg.sort_values("o")
    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(len(agg))
    ax.bar(x - 0.2, agg["ge1ATR_%"], 0.4, label="bounce ≥1 ATR %")
    ax.bar(x + 0.2, agg["win_1R_%"], 0.4, label="1R reached before SL %")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{g}\n(n={n})" for g, n in zip(agg.group, agg.reached)], fontsize=8)
    ax.set_title("Reaction quality by session of the touch (New York time)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "bounce_by_session.png", dpi=120)
    plt.close(fig)

    # 6. monthly stability
    agg = aggregate(df, ["month"])
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(agg.group, agg.reached, color="lightgray", label="touches")
    ax1.set_ylabel("touches")
    ax2 = ax1.twinx()
    ax2.plot(agg.group, agg["ge1ATR_%"], marker="o", label="bounce ≥1 ATR %")
    ax2.plot(agg.group, agg["win_1R_%"], marker="s", label="1R before SL %")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("%")
    ax1.set_title("Month-by-month stability")
    ax1.tick_params(axis="x", rotation=45)
    fig.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "monthly_stability.png", dpi=120)
    plt.close(fig)

    # 7. equity curves of the scenarios (edge entry)
    fig, ax = plt.subplots(figsize=(12, 6))
    rs = r.sort_values("touch_time")
    for name, entry, slb, tp in SCENARIOS:
        if entry != "edge" and name not in ("mid_sl0.5_tp2",):
            continue
        s = rs[f"sc_{name}"].dropna()
        ax.plot(np.arange(len(s)), s.cumsum().to_numpy(), label=f"{name} (n={len(s)})", lw=1.2)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("touch # (chronological, all timeframes)")
    ax.set_ylabel("cumulative net R (after spread)")
    ax.set_title("Mechanical execution at the POI — equity in R, all 5 timeframes pooled")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "scenario_equity_curves.png", dpi=120)
    plt.close(fig)

    # 8. equity by TF for the best simple scenario
    fig, ax = plt.subplots(figsize=(12, 6))
    for tf in TF_ORDER:
        s = rs[rs.tf == tf]["sc_edge_sl0.5_tp2"].dropna()
        if len(s):
            ax.plot(np.arange(len(s)), s.cumsum().to_numpy(), label=f"{tf} (n={len(s)}, total {s.sum():.0f}R)")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title("edge entry, SL far edge + 0.5 ATR, TP 2R — equity per timeframe (net of spread)")
    ax.set_ylabel("cumulative R")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "scenario_equity_by_tf.png", dpi=120)
    plt.close(fig)


def md_table(t: pd.DataFrame, cols) -> str:
    t = t[cols]
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in t.to_numpy())
    return head + body + "\n"


def report(df: pd.DataFrame, out: Path, meta: dict) -> str:
    r = df[df.reached]
    n_sel, n_reached = len(df), len(r)
    core = ["group", "selected", "reached", "reached_%", "median_bounce_atr", "mean_bounce_atr", "p75_bounce_atr",
            "median_bounce_usd", "ge0.5ATR_%", "ge1ATR_%", "ge2ATR_%", "ge3ATR_%", "median_penetration_zone",
            "closed_through_%", "hit_1R_%", "hit_2R_%", "exp_R_TP1", "net_R_TP1", "exp_R_TP2", "net_R_TP2"]
    sc_cols = ["scenario", "entry", "sl_buffer_atr", "tp_R", "filled", "win_%", "avg_net_R", "total_net_R",
               "profit_factor", "max_dd_R"]

    by_tf = aggregate(df, ["tf"])
    by_tf["o"] = by_tf.group.map({t: i for i, t in enumerate(TF_ORDER)})
    by_tf = by_tf.sort_values("o")
    by_type = aggregate(df, ["kind"])
    by_dir = aggregate(df, ["direction"])
    by_sess = aggregate(df, ["session"], min_n=10)
    by_zone = aggregate(df, ["poi_zone"], min_n=10)
    by_of = aggregate(df.assign(of=pd.cut(df.orderflow_count, [0, 2, 5, 10, 20, 1000],
                                          labels=["1-2", "3-5", "6-10", "11-20", "20+"])), ["of"], min_n=10)
    by_dist = aggregate(df.assign(d=pd.cut(df.distance_atr, [0, 1, 2, 4, 8, 1000],
                                           labels=["<1", "1-2", "2-4", "4-8", "8+"])), ["d"], min_n=10)
    by_month = aggregate(df, ["month"])
    sc_all = aggregate_scenarios(df)
    sc_tf = aggregate_scenarios(df, ["tf"])
    overall = aggregate(df).iloc[0]

    pct = lambda x: f"{x * 100:.0f}%"
    q = r.bounce_atr.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    qf = r.bounce_free_atr.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    qu = r.bounce_usd.quantile([0.25, 0.5, 0.75])
    pen = r.penetration_zone

    best = sc_all.sort_values("avg_net_R", ascending=False).iloc[0]
    worst = sc_all.sort_values("avg_net_R").iloc[0]

    lines = []
    A = lines.append
    A("# POI bounce study — XAUUSD.t, Liquidity University rules\n")
    A(f"**Data:** {meta['bars']:,} M1 bars, {meta['start']} → {meta['end']} (broker time), "
      f"price range {meta['lo']:.0f}–{meta['hi']:.0f}, spread: broker value where recorded (Apr–Sep 2026, median $0.28), floored at $0.28 for the months where the export has no spread. "
      f"Timeframes M5 · M10 · M15 · M30 · H1, all built from M1.\n")
    A("**Method (walk-forward, no look-ahead):** on every closed bar of every timeframe the bot ran the exact "
      "selection logic (unmitigated OB / BB / IMB / HB / UW → liquidity must rest between price and the POI → "
      "≥1 order-flow mitigation → closest above / closest below). Every *newly selected* POI became one "
      "observation. Only after selection were the following bars used to measure what price did: first touch "
      "of the zone edge (found on M1), how deep it went into the zone, and how far it bounced back — measured in "
      "**ATR(14) of the timeframe** so all timeframes are comparable, and in dollars. "
      "Stops in the trade scenarios are checked *before* targets on the same minute (conservative), and every "
      "fill pays the recorded spread at the touch minute.\n")

    A("## 1. Headline numbers\n")
    A(f"- **{n_sel:,} POIs selected**, **{n_reached:,} reached** by price within 300 bars ({pct(n_reached / n_sel)}). "
      f"The rest were never tapped (price left in the other direction or the POI aged out).")
    A(f"- **Median bounce before the stop is hit: {q[0.5]:.2f} ATR** (25–75%: {q[0.25]:.2f}–{q[0.75]:.2f} ATR; "
      f"10% of touches bounce ≥ {q[0.9]:.1f} ATR). In dollars: median **${qu[0.5]:.1f}**, 25–75%: ${qu[0.25]:.1f}–${qu[0.75]:.1f}.")
    A(f"- Ignoring any stop (pure 'does it ever come back?'), the median max bounce inside the 300-bar window is "
      f"**{qf[0.5]:.2f} ATR** (75th pct {qf[0.75]:.1f} ATR).")
    A(f"- **{overall['ge0.5ATR_%']:.0f}%** of touches bounce ≥ 0.5 ATR, **{overall['ge1ATR_%']:.0f}%** ≥ 1 ATR, "
      f"**{overall['ge2ATR_%']:.0f}%** ≥ 2 ATR, **{overall['ge3ATR_%']:.0f}%** ≥ 3 ATR — before the far edge of the zone (+0.1 ATR) is violated.")
    A(f"- **Penetration:** median {pen.median():.2f} zone-heights. **{pct((pen > 1).mean())} of touches trade through the "
      f"entire zone** at some point, {pct((pen > 0.5).mean())} go past the mid-point, only {pct((pen <= 0.25).mean())} "
      f"stop in the first quarter of the zone. The typical 'tap' is therefore a full sweep of the zone, not a kiss of the edge.")
    A(f"- **1R before SL (edge entry, SL far edge+0.1 ATR): {overall['hit_1R_%']:.0f}%**, 2R: {overall['hit_2R_%']:.0f}%, "
      f"3R: {aggregate(df).iloc[0]['hit_3R_%']:.0f}%. Expectancy of a mechanical TP-1R trade: {overall['exp_R_TP1']:+.3f} R gross, "
      f"**{overall['net_R_TP1']:+.3f} R net of spread**; TP-2R: {overall['exp_R_TP2']:+.3f} gross / **{overall['net_R_TP2']:+.3f} net**.")
    A(f"- {overall['retraced_to_origin_%']:.0f}% of touches eventually retraced all the way back to where price was "
      f"when the POI was selected (i.e. the full leg that brought price to the POI was retraced).\n")

    A("## 2. By timeframe\n")
    A(md_table(by_tf, core))
    A("![](charts/bounce_distribution_by_tf.png)\n![](charts/bounce_probability_curves.png)\n")

    A("## 3. By POI type\n")
    A(md_table(by_type, core))
    A("![](charts/bounce_by_type.png)\n")

    A("## 4. Bullish vs bearish POIs\n")
    A(md_table(by_dir, core))

    A("## 5. By session of the touch (New York time, PDF sessions)\n")
    A(md_table(by_sess, core))
    A("![](charts/bounce_by_session.png)\n")

    A("## 6. Premium / discount position of the POI inside the current trading range\n")
    A(md_table(by_zone, core))

    A("## 7. Amount of order-flow support (number of previously respected same-direction POIs)\n")
    A(md_table(by_of, core))

    A("## 8. Distance from price to the POI at selection (ATR)\n")
    A(md_table(by_dist, core))

    A("## 9. How deep does price go into the POI?\n")
    A("![](charts/penetration_distribution.png)\n")
    A("| penetration (zone heights) | share of touches |\n|---|---|")
    for lo, hi, lbl in [(0, 0.25, "≤ 0.25 (edge only)"), (0.25, 0.5, "0.25–0.5"), (0.5, 1.0, "0.5–1.0 (deep, inside)"),
                        (1.0, 2.0, "1–2 (through the zone)"), (2.0, 1e9, "> 2 (blew through)")]:
        A(f"| {lbl} | {pct(((pen > lo) & (pen <= hi)).mean())} |")
    A("")

    A("## 10. Month by month\n")
    A(md_table(by_month, ["group", "selected", "reached", "reached_%", "median_bounce_atr", "ge1ATR_%", "ge2ATR_%",
                          "hit_1R_%", "net_R_TP1", "net_R_TP2"]))
    A("![](charts/monthly_stability.png)\n")

    A("## 11. Mechanical execution scenarios (all timeframes pooled, net of spread)\n")
    A("Entry `edge` = limit at the near edge of the zone; `mid` = limit at 50% of the zone (fills less often). "
      "SL = far edge + buffer (ATR). TP = fixed R multiple. Positions still open after 300 bars are marked to market.\n")
    A(md_table(sc_all, sc_cols))
    A("![](charts/scenario_equity_curves.png)\n![](charts/scenario_equity_by_tf.png)\n")
    A("Per timeframe (best 3 scenarios by average net R each):\n")
    rows = []
    for tf in TF_ORDER:
        g = sc_tf[sc_tf.group == tf].sort_values("avg_net_R", ascending=False).head(3)
        rows.append(g)
    A(md_table(pd.concat(rows), ["group"] + sc_cols))

    A("## 12. Reading the results honestly\n")
    A(f"1. **Price does come back to these POIs and does react** — {pct(n_reached / n_sel)} of selections are reached and "
      f"about {overall['ge1ATR_%']:.0f}% bounce at least one ATR before the zone is violated. That is meaningful "
      f"information: the POI + liquidity + order-flow filter finds levels where the market pauses.")
    A(f"2. **But the typical reaction is a wick, not a reversal.** Median bounce ≈ {q[0.5]:.2f} ATR; the median touch "
      f"penetrates {pen.median():.1f} zone-heights, i.e. the entire zone gets swept before/while the bounce happens. "
      f"Tight stops just beyond the far edge get hit constantly ({overall['closed_through_%']:.0f}% of touches see a "
      f"candle close through the zone).")
    A(f"3. **Mechanically fading every POI is roughly break-even after spread.** Best pooled scenario: "
      f"`{best.scenario}` avg {best.avg_net_R:+.3f} R/trade, PF {best.profit_factor}, max drawdown {best.max_dd_R} R; "
      f"worst: `{worst.scenario}` {worst.avg_net_R:+.3f} R. Neither is a system on its own — the PDF never claims it is: "
      f"the POI is *where* to look for a setup, the entry is meant to come from a Confirmation / PA entry on the LTF.")
    A("4. **Where the edge concentrates** (see tables above): look at which timeframes, POI types, sessions and "
      "order-flow buckets have the highest `ge1ATR_%` / `net_R_TP2`. Those are the filters worth adding before "
      "any live execution — H1/M30 vs M5, OB/HB vs IMB, London/NY vs Asia.")
    A("5. **Caveats.** Single instrument, one year (a strong bull year for gold, so bullish POIs are structurally "
      "favoured). No slippage beyond spread. Zones use candle bodies (PDF author preference); full-candle zones would "
      "be wider (fewer stop-outs, smaller R). All thresholds (ATR multiples for OB displacement, wick size, 'respected' "
      "= 1 ATR move-away) are my reading of the PDF and can be changed in `lubot/config.py`.\n")
    A("## Files\n- `touches.csv` — one row per selected POI with every measurement\n- `agg_*.csv` — all aggregation tables\n- `charts/` — figures above\n")
    text = "\n".join(lines)
    (out / "REPORT.md").write_text(text)
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="study_results")
    p.add_argument("--csv", required=True)
    p.add_argument("--charts-only", action="store_true", help="only regenerate charts, keep REPORT.md")
    a = p.parse_args()
    out = Path(a.dir)
    with open(out / "touches.pkl", "rb") as f:
        df = pickle.load(f)
    from lubot import load_mt5_csv
    m1 = load_mt5_csv(a.csv)
    meta = {"bars": len(m1), "start": str(m1.index[0]), "end": str(m1.index[-1]), "lo": m1.low.min(),
            "hi": m1.high.max(), "spread": float(m1["spread"].median()) if "spread" in m1 else 0.0}
    charts(df, out / "charts")
    if a.charts_only:
        print("charts regenerated")
        return
    text = report(df, out, meta)
    print(text[:3000])


if __name__ == "__main__":
    main()
