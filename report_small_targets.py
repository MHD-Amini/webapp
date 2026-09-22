#!/usr/bin/env python3
"""Charts + markdown for the small-target (0.3R / 0.4R / 0.5R) backtest of the quality bot."""
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from lubot.study import aggregate_scenarios  # noqa: E402

pd.set_option("display.width", 250)
q = pd.read_pickle("study_results/compare_quality.pkl")
c = pd.read_pickle("study_results/compare_closest.pkl")
q, c = q[q.reached].sort_values("touch_time"), c[c.reached].sort_values("touch_time")
TPS = [0.3, 0.4, 0.5, 1.0, 2.0]


def pf(x):
    return x[x > 0].sum() / abs(x[x < 0].sum()) if (x < 0).any() else float("inf")


# ---------------------------------------------------------------- chart 1: equity
fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
for tp in TPS:
    x = q[f"sc_mid_sl0.5_tp{tp:g}"].dropna()
    axes[0].plot(np.arange(len(x)), x.cumsum().values, label=f"TP {tp:g}R  (n={len(x)}, {x.sum():+.0f}R, PF {pf(x):.2f})")
axes[0].set_title("QUALITY bot - mid-zone entry, SL far edge + 0.5 ATR - OOS Apr-Sep 2026, net of spread")
axes[0].set_ylabel("cumulative R"); axes[0].legend(fontsize=8); axes[0].grid(alpha=.3); axes[0].axhline(0, color="k", lw=.7)
for tp in (0.4, 0.5):
    x = c[f"sc_mid_sl0.5_tp{tp:g}"].dropna()
    axes[1].plot(np.arange(len(x)), x.cumsum().values, "--", label=f"closest (old) TP {tp:g}R (n={len(x)}, {x.sum():+.0f}R)")
    x = q[f"sc_mid_sl0.5_tp{tp:g}"].dropna()
    axes[1].plot(np.arange(len(x)), x.cumsum().values, label=f"quality (new) TP {tp:g}R (n={len(x)}, {x.sum():+.0f}R)")
axes[1].set_title("old vs new selection, same period"); axes[1].legend(fontsize=8); axes[1].grid(alpha=.3)
axes[1].axhline(0, color="k", lw=.7); axes[1].set_xlabel("trade #")
fig.tight_layout(); fig.savefig("study_results/charts/small_targets_equity.png", dpi=115); plt.close(fig)

# ---------------------------------------------------------------- chart 2: win rate vs break-even
fig, ax = plt.subplots(figsize=(10, 5))
for entry, slb, col in [("edge", 0.1, "tab:red"), ("edge", 0.5, "tab:orange"), ("mid", 0.1, "tab:purple"), ("mid", 0.5, "tab:green")]:
    wins = [(q[f"sc_{entry}_sl{slb}_tp{tp:g}"].dropna() > 0).mean() * 100 for tp in TPS]
    ax.plot(TPS, wins, marker="o", color=col, label=f"{entry} entry, SL far edge +{slb} ATR")
ax.plot(TPS, [100 / (1 + tp) for tp in TPS], "k--", label="break-even win rate (before costs)")
ax.set_xscale("log"); ax.set_xticks(TPS); ax.set_xticklabels([f"{t:g}R" for t in TPS])
ax.set_xlabel("take profit"); ax.set_ylabel("win %"); ax.set_title("Quality bot: win rate vs target against the break-even line")
ax.grid(alpha=.3); ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig("study_results/charts/small_targets_winrate.png", dpi=115); plt.close(fig)

# ---------------------------------------------------------------- tables
def md(t):
    cols = list(t.columns)
    h = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return h + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in t.to_numpy()) + "\n"


sc = pd.concat([aggregate_scenarios(c).assign(mode="closest"), aggregate_scenarios(q).assign(mode="quality")])
small = sc[sc.tp_R <= 0.5].sort_values(["entry", "sl_buffer_atr", "tp_R", "mode"])
small = small[["mode", "entry", "sl_buffer_atr", "tp_R", "filled", "win_%", "avg_net_R", "total_net_R", "profit_factor", "max_dd_R"]]

rows = []
for tf in ["M5", "M10", "M15", "M30", "H1"]:
    g = q[q.tf == tf]
    r = {"tf": tf, "n": len(g), "median risk $": round((g.zone_h * 0.5 + 0.5 * g.atr_at_selection).median(), 2)}
    for tp in ("0.3", "0.4", "0.5", "1"):
        x = g[f"sc_mid_sl0.5_tp{tp}"].dropna()
        r[f"{tp}R avg"] = f"{x.mean():+.3f}"; r[f"{tp}R win%"] = round((x > 0).mean() * 100, 1)
    rows.append(r)
by_tf = pd.DataFrame(rows)
B = "sc_mid_sl0.5_tp0.4"
agg = dict(n=(B, "size"), avg_net_R=(B, "mean"), win_pct=(B, lambda x: round((x > 0).mean() * 100, 1)), total_R=(B, "sum"))
by_month = q.groupby(q.selected_time.str[:7]).agg(**agg).round(3).reset_index().rename(columns={"selected_time": "month"})
by_kind = q.groupby("kind").agg(**agg).round(3).reset_index()
by_sess = q.groupby("session").agg(**agg).round(3).reset_index()
risk_mid = q.zone_h * 0.5 + 0.5 * q.atr_at_selection
spread_share = (q.spread / (0.4 * risk_mid)).median()
hit = {tp: (q[f"r_{tp}R"].mean() * 100, c[f"r_{tp}R"].mean() * 100) for tp in ("0.3", "0.4", "0.5", "1", "2")}
bq = sc[sc["mode"] == "quality"].sort_values("avg_net_R", ascending=False).iloc[0]
hit_rows = "\n".join(f"| {tp}R | **{hit[tp][0]:.1f}%** | {hit[tp][1]:.1f}% | {100/(1+float(tp)):.0f}% |" for tp in hit)

text = f"""# Small-target backtest: 0.3R / 0.4R / 0.5R on the quality bot

**Setup.** Bot v2 (`selection_mode=quality`, model trained on Sep 2025 - Mar 2026 only) run **out-of-sample on Apr 1 - Sep 4 2026** across M5/M10/M15/M30/H1. Every selected POI that price reached is one trade. Limit entries (`edge` = near edge of the zone, `mid` = 50% of the zone), SL = far edge + buffer (0.1 or 0.5 ATR), TP = fixed R multiple. Same-minute ambiguity resolved against the trade (stop first); every fill pays the recorded spread (median $0.28). Open positions after 300 bars are marked to market. The old `closest` selection is run on the same period as control.

## 1. Does price reach small targets before the stop? (SL = far edge + 0.1 ATR)

| target | quality bot (new) | closest (old) | break-even win % |
|---|---|---|---|
{hit_rows}

Small targets are reached **74-84%** of the time - above their 67-77% break-even lines. 1R (54%) sits on its 50% line and 2R (34%) on its 33% line. **The reaction at a quality POI is reliable but small: 0.3-0.5R captures it, 1R+ gives it back.**

![](charts/small_targets_winrate.png)

## 2. Scenario grid (net of spread, OOS Apr-Sep 2026)

{md(small)}
Best quality-bot scenario: **`{bq.scenario}`** -> **{bq.avg_net_R:+.3f} R/trade**, win {bq["win_%"]}%, **PF {bq.profit_factor}**, max drawdown {bq.max_dd_R} R over {bq.filled} trades (vs +0.05 R / PF 1.11 for the best 1R-2R scenario in the previous study).

![](charts/small_targets_equity.png)

Observations
- **The stop buffer matters more than the target.** With SL only 0.1 ATR beyond the zone, small-target trades lose (old bot: -0.09 to -0.24 R/trade); with +0.5 ATR they win at every TP. Price sweeps ~1.3 zone-heights before turning, so the stop has to sit beyond the sweep.
- **Mid-zone entry + 0.5 ATR buffer** is the robust combination: PF 1.4-1.6 at 0.3-0.5R for both selections; quality mode adds ~+0.02 R/trade while cutting the trade count by 60% (fewer, better POIs).
- **Quality selection removes the disasters.** Every tight-stop scenario that was deeply negative with `closest` (-385 to -1000 R total) is flat or positive with `quality`.
- **Costs.** Median risk is ${risk_mid.median():.2f}/oz, so the spread is ~{spread_share*100:.0f}% of a 0.4R target - material on M5 (risk ~$4), negligible on M30/H1. Slippage is *not* modelled; on M5 it would eat a good part of the edge.

## 3. Quality bot, mid entry / SL +0.5 ATR, by timeframe

{md(by_tf)}
## 4. Stability - `mid_sl0.5_tp0.4` by month

{md(by_month)}
Positive every full month; Jul-Aug (+0.05-0.06 R) weaker than Apr-Jun (+0.14 R). Sep is 4 trading days.

## 5. By POI type and session (`mid_sl0.5_tp0.4`)

{md(by_kind)}
{md(by_sess)}
London and London-Close touches are best (+0.16-0.18 R, 85% win); NY-PM and Asia weakest but still positive.

## 6. Bottom line

- With **TP 0.3-0.5R, mid-zone limit entry, SL = far edge + 0.5 ATR**, the quality bot is **positive out-of-sample on every timeframe and every full month**: about **+0.10 R/trade, ~80% win rate, PF ~1.5, ~14 trades/day across 5 TFs**, max drawdown ~10 R.
- Versus 1R/2R targets (~0 R/trade) the small targets turn the same POIs from break-even into a consistent low-variance edge. The trade-off is the classic scalper's one: many small wins, occasional -1R losses (0.80 x 0.4R - 0.20 x 1R = +0.12 R gross).
- It is an execution-sensitive edge: gross +0.12 R, net of spread +0.10 R, realistic slippage on M5 would remove roughly half of what is left. **M10-M30 are the sweet spot** (risk $6-11, win 80-84%).

Files: `compare_scenarios.csv`, `compare_scenarios_by_tf_quality.csv`, `compare_scenarios_by_tf_closest.csv`, `compare_summary.csv`, `charts/small_targets_*.png`.
"""
open("study_results/SMALL_TARGETS.md", "w").write(text)
print(small.to_string(index=False)); print(by_tf.to_string(index=False)); print(by_month.to_string(index=False))
