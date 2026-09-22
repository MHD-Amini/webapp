#!/usr/bin/env python3
"""v7 step 4 - portfolio backtest of the trader + sensitivity grid + charts + markdown report.

    python run_trader_study.py --csv data.csv [--sel "study_results/sel_v7_*.pkl"] [--out study_results/trader_v7]

Resumable: every variant's result is cached as <out>_var_<name>.json (+ _trades.csv) and skipped when present;
each finished variant is committed (save.sh).  Produces study_results/TRADER_BACKTEST.md and charts/trader_*.png.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_trader import load_selections, report, run, spec_override
from lubot import load_mt5_csv
from lubot.execution import SymbolSpec, TraderConfig, expected_outcomes

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)

BASE_TRADER = "risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5"
BASE_SPEC = "commission_per_lot=7.0,swap_long_per_lot=-50.0,swap_short_per_lot=15.0"
NO_COST_SPEC = "commission_per_lot=0,swap_long_per_lot=0,swap_short_per_lot=0"

#: name -> (trader overrides, spec overrides, be_delay_minutes)
VARIANTS = {
    "base":                  (BASE_TRADER, BASE_SPEC, 0),
    "no_costs":              (BASE_TRADER + ",sl_slippage=0,market_slippage=0,spread_multiplier=0", NO_COST_SPEC, 0),
    "spread_x1.5":           (BASE_TRADER + ",spread_multiplier=1.5", BASE_SPEC, 0),
    "spread_x2":             (BASE_TRADER + ",spread_multiplier=2.0", BASE_SPEC, 0),
    "slippage_x3":           (BASE_TRADER + ",sl_slippage=0.30,market_slippage=0.15", BASE_SPEC, 0),
    "worst_intrabar":        (BASE_TRADER + ",intrabar=worst", BASE_SPEC, 0),
    "be_delay_2min":         (BASE_TRADER, BASE_SPEC, 2),
    "netting":               (BASE_TRADER + ",exec_mode=netting", BASE_SPEC, 0),
    "persist_orders":        (BASE_TRADER + ",order_policy=persist,max_pending_bars=300", BASE_SPEC, 0),
    "risk_0.5":              (BASE_TRADER + ",risk_pct=0.5", BASE_SPEC, 0),
    "risk_2.0":              (BASE_TRADER + ",risk_pct=2.0", BASE_SPEC, 0),
    "fixed_risk_balance":    (BASE_TRADER + ",size_on=balance", BASE_SPEC, 0),
    "max_open_1":            (BASE_TRADER + ",max_open_positions=1", BASE_SPEC, 0),
    "max_open_2":            (BASE_TRADER + ",max_open_positions=2", BASE_SPEC, 0),
    "max_open_8":            (BASE_TRADER + ",max_open_positions=8", BASE_SPEC, 0),
    "no_dedupe":             (BASE_TRADER + ",dedupe_overlap=1.01", BASE_SPEC, 0),
    "q0.55":                 (BASE_TRADER + ",min_quality=0.55", BASE_SPEC, 0),
    "q0.60":                 (BASE_TRADER + ",min_quality=0.60", BASE_SPEC, 0),
    "q0.65":                 (BASE_TRADER + ",min_quality=0.65", BASE_SPEC, 0),
    "grades_AB":             (BASE_TRADER + ",grades=A|B", BASE_SPEC, 0),
    "tf_M5":                 (BASE_TRADER + ",timeframes=M5", BASE_SPEC, 0),
    "tf_M10":                (BASE_TRADER + ",timeframes=M10", BASE_SPEC, 0),
    "tf_M15":                (BASE_TRADER + ",timeframes=M15", BASE_SPEC, 0),
    "tf_M30":                (BASE_TRADER + ",timeframes=M30", BASE_SPEC, 0),
    "tf_H1":                 (BASE_TRADER + ",timeframes=H1", BASE_SPEC, 0),
    "tf_M15_M30_H1":         (BASE_TRADER + ",timeframes=M15|M30|H1", BASE_SPEC, 0),
    "tf_M10_M15_M30_H1":     (BASE_TRADER + ",timeframes=M10|M15|M30|H1", BASE_SPEC, 0),
    "buys_only":             (BASE_TRADER + ",sides=buy", BASE_SPEC, 0),
    "sells_only":            (BASE_TRADER + ",sides=sell", BASE_SPEC, 0),
    # alternative management - for comparison only (the deliverable is the user's spec = base)
    "mgmt_no_partial_tp1.5": (BASE_TRADER + ",partial_frac=0.0,tp2_r=1.5", BASE_SPEC, 0),
    "mgmt_partial0.5_tp1":   (BASE_TRADER + ",partial_r=0.5,tp2_r=1.0", BASE_SPEC, 0),
    "mgmt_partial0.4_tp2":   (BASE_TRADER + ",tp2_r=2.0", BASE_SPEC, 0),
    "mgmt_partial0.3_tp1.5": (BASE_TRADER + ",partial_r=0.3", BASE_SPEC, 0),
    "mgmt_sl_buffer0.3atr":  (BASE_TRADER + ",sl_buffer_atr=0.3", BASE_SPEC, 0),
    "mgmt_entry_25pct_in":   (BASE_TRADER + ",entry_offset_frac=0.25", BASE_SPEC, 0),
}

GRID_COLS = ["name", "trades", "win_%", "avg_R", "total_R", "profit_factor", "return_%", "max_dd_%", "max_dd_R",
             "sharpe_daily", "partial_hit_%", "tp2_%", "sl_%", "trades_per_day"]


def run_variant(name, m1, sel, out: Path, start, end):
    cache = Path(f"{out}_var_{name}.json")
    if cache.exists():
        return json.loads(cache.read_text())
    tr, sp, be = VARIANTS[name]
    tcfg = TraderConfig().override(tr)
    if tcfg.partial_frac == 0.0:
        tcfg.exec_mode = "netting"      # single leg, no partial close
    spec = spec_override(SymbolSpec(), sp)
    print(f"\n##### variant {name}: {tr} | {sp} | be_delay {be}", flush=True)
    res = run(m1, sel, tcfg, spec, start, end, be_delay=be)
    if name == "base":
        s = report(res, out, title="BASE (user spec)")
        res.trades.groupby("outcome").agg(n=("net", "size"), avg_R=("r_net", "mean"), net=("net", "sum")).to_csv(f"{out}_by_outcome.csv")
        res.skipped_reasons().to_csv(f"{out}_skipped.csv")
        res.cancel_reasons().to_csv(f"{out}_cancelled.csv")
    else:
        s = res.summary()
        res.trades.to_csv(f"{out}_var_{name}_trades.csv", index=False)
        print({k: s.get(k) for k in ("trades", "win_%", "total_R", "profit_factor", "return_%", "max_dd_%")}, flush=True)
    d = {"name": name, "trader": tr, "spec": sp, "be_delay": be, **s}
    cache.write_text(json.dumps(d, indent=1, default=str))
    return d


def charts(out: Path, trades: pd.DataFrame, equity: pd.DataFrame, grid: pd.DataFrame):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cdir = out.parent / "charts"
    cdir.mkdir(exist_ok=True)
    eq = equity.copy()
    eq.index = pd.to_datetime(eq.index)
    fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(eq.index, eq.equity, lw=0.8, label="equity")
    ax[0].plot(eq.index, eq.balance, lw=0.8, alpha=0.7, label="balance")
    ax[0].set_title("v7 trader OOS Mar-Sep 2026 | $10k, 1% risk | entry = zone start, SL = zone end | 50% @ +0.4R -> BE, TP2 +1.5R | net of costs")
    ax[0].legend(); ax[0].grid(alpha=0.3)
    dd = eq.equity / eq.equity.cummax() - 1
    ax[1].fill_between(eq.index, dd * 100, 0, color="red", alpha=0.4)
    ax[1].set_ylabel("drawdown %"); ax[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(cdir / "trader_equity.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    ax[0].hist(trades.r_net, bins=60, color="steelblue"); ax[0].set_title("net R per trade"); ax[0].axvline(0, color="k", lw=0.5)
    oc = trades.outcome.value_counts()
    ax[1].bar(oc.index, oc.values, color=["green" if o == "tp2" else "orange" if "partial" in o else "red" if o == "sl" else "grey" for o in oc.index])
    ax[1].set_title("outcome mix")
    m = trades.assign(month=trades.close_time.dt.strftime("%Y-%m")).groupby("month").r_net.sum()
    ax[2].bar(m.index, m.values, color=["green" if v > 0 else "red" for v in m.values]); ax[2].set_title("total net R by month")
    ax[2].tick_params(axis="x", rotation=45)
    fig.tight_layout(); fig.savefig(cdir / "trader_distribution.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5))
    for tf, g in trades.groupby("tf"):
        ax.plot(g.close_time, g.r_net.cumsum(), label=f"{tf} ({len(g)})", lw=1)
    ax.plot(trades.close_time, trades.r_net.cumsum(), color="k", lw=2, label="ALL")
    ax.set_title("cumulative net R by timeframe"); ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(cdir / "trader_cum_r_by_tf.png", dpi=110); plt.close(fig)

    g = grid.set_index("name")
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(g.index, g["return_%"], color=["green" if v > 0 else "red" for v in g["return_%"]])
    ax.set_xlabel("return % (Mar-Sep 2026, $10k)"); ax.set_title("sensitivity of the trader to costs / settings")
    ax.grid(alpha=0.3, axis="x"); ax.invert_yaxis()
    fig.tight_layout(); fig.savefig(cdir / "trader_sensitivity.png", dpi=110); plt.close(fig)


def tbl(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(floatfmt=".4g")
    except Exception:  # noqa: BLE001
        return "```\n" + df.to_string() + "\n```"


def write_report(out: Path, grid: pd.DataFrame, base: dict, trades: pd.DataFrame, sel: pd.DataFrame):
    rd = lambda n: pd.read_csv(f"{out}_by_{n}.csv", index_col=0)  # noqa: E731
    by_tf, by_kind, by_side, by_grade, by_month, by_outcome = (rd(n) for n in ("tf", "kind", "side", "grade", "month", "outcome"))
    eo = expected_outcomes(TraderConfig())
    g = grid.set_index("name")
    n_sel = int((sel.event == "set").sum())
    b = base
    txt = f"""# TRADER v7 - realistic out-of-sample backtest

**Strategy**: v6 POI scanner (quality model, `min_quality 0.50`, model trained on data **before 2026-03-01**) ->
for every POI the bot shows: **limit entry at the start of the zone** (top of a bullish zone / bottom of a bearish
zone), **stop at the end of the zone** (far edge, no buffer) -> **1R = zone height**.
**Management (user spec)**: at **+0.4R close 50 %** and move the stop of the rest to **break-even**; **TP2 = +1.5R**.
Possible gross results per trade: stop before the partial **-1R**; partial then BE **{eo['partial_then_breakeven']:+.2f}R**;
partial then TP2 **{eo['partial_then_tp2']:+.2f}R**.

**Data**: MT5 M1 export, out-of-sample **{sel.t.min().date()} -> {sel.t.max().date()}**, {n_sel} POI selections shown by the
scanner on M5 / M10 / M15 / M30 / H1 (the recorded stream is exactly what the live bot would have displayed at every bar
close).  Bars before 2026-04-06 carry no exported spread and were given the spread of the same weekday / NY-hour of the
bars that do (median $0.28).

**Realism** (`lubot/portfolio_sim.py`, M1 precision): limit fills on the **ask** (buys) / **bid** (sells); stops and
targets on the correct side (long on bid, short on ask); MT5-tester intrabar path (O -> L -> H -> C for bullish minutes,
O -> H -> L -> C for bearish); the TP1 leg is a **server-side take-profit** (no slippage), stop-outs are market executions
with **$0.10 slippage**; **$7 / lot round-turn commission**; **swaps** -$50 / +$15 per lot per night (3x Wednesday);
pending orders are cancelled when the scanner stops showing the POI (what the live bot does); one trade per POI;
overlapping zones (>= 50 %) are not traded twice; max 4 open trades; size **1 % of current equity** rounded down to 0.01
lots and split into two equal legs (hedging account); $10 000 start, leverage 1:100.

## 1. Base result (user specification)

| metric | value |
|---|---|
"""
    for k in ["trades", "trades_per_day", "win_%", "profit_factor", "avg_R", "median_R", "total_R", "net_profit", "return_%",
              "max_dd_%", "max_dd_$", "max_dd_R", "sharpe_daily", "partial_hit_%", "tp2_%", "partial_be_%", "sl_%", "forced_%",
              "avg_hold_min", "median_hold_min", "avg_lots", "avg_risk_$", "expectancy_$", "commission_$", "swap_$",
              "pending_placed", "cancelled", "skipped", "end_balance"]:
        txt += f"| {k} | {b.get(k)} |\n"
    txt += f"""
`win_%` = trades with a positive net result (partial-then-break-even is a small win of ~+0.2R minus costs).
`partial_hit_%` = trades that reached +0.4R; `tp2_%` = trades that ran to +1.5R; `sl_%` = full -1R stops.

### Outcome mix
{tbl(by_outcome)}

### By timeframe
{tbl(by_tf)}

### By POI type
{tbl(by_kind)}

### By side
{tbl(by_side)}

### By grade
{tbl(by_grade)}

### Month by month
{tbl(by_month)}

![equity](charts/trader_equity.png)
![distribution](charts/trader_distribution.png)
![by tf](charts/trader_cum_r_by_tf.png)

## 2. Sensitivity (same selection stream, same period, one thing changed per row)

`no_costs` = zero spread / commission / slippage / swap (pure price path); `worst_intrabar` = the stop is always
assumed to be hit first when stop and target are both inside one minute; `be_delay_2min` = the bot needs 2 minutes to
move the stop to break-even after leg A closes; `netting` = one position, the bot closes half at market when +0.4R
prints; `persist_orders` = pending orders stay until filled / 300 bars instead of following the scanner; `mgmt_*` rows
are alternative managements for comparison (the delivered bot uses the user's spec = `base`).

{tbl(g[GRID_COLS[1:]])}

![sensitivity](charts/trader_sensitivity.png)

## 3. Reading the numbers

"""
    if "no_costs" in g.index:
        nc = g.loc["no_costs"]
        txt += (f"* Costs (spread + commission + slippage + swap) take **{(nc['total_R'] - b['total_R']) / max(b['trades'], 1):.3f} R per trade**: "
                f"{nc['total_R']:.1f} R gross price path -> {b['total_R']:.1f} R net.\n")
    for nm, label in (("worst_intrabar", "stop-first intrabar assumption"), ("be_delay_2min", "2-minute break-even latency"),
                      ("spread_x2", "double spread"), ("slippage_x3", "3x slippage"), ("netting", "netting account"),
                      ("persist_orders", "persistent pending orders")):
        if nm in g.index:
            w = g.loc[nm]
            txt += f"* {label}: {w['total_R']:+.1f} R / {w['return_%']:+.1f} % (base {b['total_R']:+.1f} R / {b['return_%']:+.1f} %).\n"
    best_tf = by_tf.sort_values("total_R", ascending=False)
    txt += (f"* Timeframes: best {', '.join(f'{i} ({r.total_R:+.1f} R, PF {r.PF})' for i, r in best_tf.head(2).iterrows())}; "
            f"worst {best_tf.index[-1]} ({best_tf.total_R.iloc[-1]:+.1f} R, PF {best_tf.PF.iloc[-1]}).\n")
    txt += f"* {int((by_month.total_R > 0).sum())} of {len(by_month)} months positive.\n"
    for nm in ("q0.55", "q0.60", "grades_AB", "tf_M15_M30_H1", "tf_M10_M15_M30_H1", "max_open_2", "risk_0.5",
               "mgmt_no_partial_tp1.5", "mgmt_partial0.4_tp2", "mgmt_partial0.5_tp1", "mgmt_sl_buffer0.3atr", "mgmt_entry_25pct_in"):
        if nm in g.index:
            w = g.loc[nm]
            txt += f"* `{nm}`: {int(w['trades'])} trades, {w['total_R']:+.1f} R, PF {w['profit_factor']}, return {w['return_%']:+.1f} %, max DD {w['max_dd_%']:.1f} %.\n"
    txt += """
## 4. Caveats

* The quality model was trained on data before March 2026, so the whole period is out-of-sample for the model; the PDF
  rule set and the management numbers (0.4R / 50 % / 1.5R) were fixed by the user, not fitted here.
* 6 months of one instrument; monthly results vary - size risk so the observed max drawdown is comfortable.
* Limit orders are assumed to fill in full when the ask / bid trades through the level (no partial fills); news spikes
  can skip a level.  `spread_x2` / `slippage_x3` / `worst_intrabar` show the direction of that risk.
* Swaps are a broker constant here (-$50 / +$15 per lot per night); use your broker's symbol specification.

Reproduce: `bash run_v7_record.sh` (selection streams, resumable) then `python run_trader_study.py --csv <csv>`.
Single run with your own settings: `python backtest_trader.py --csv <csv> --trader risk_pct=0.5,min_quality=0.6`.
"""
    Path("study_results/TRADER_BACKTEST.md").write_text(txt)
    print("-> study_results/TRADER_BACKTEST.md")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--sel", default="study_results/sel_v7_*.pkl")
    ap.add_argument("--from", dest="start", default="2026-03-01")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--out", default="study_results/trader_v7")
    ap.add_argument("--only", default=None, help="comma list of variants")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    m1 = load_mt5_csv(a.csv)
    sel = load_selections(a.sel)
    names = [n.strip() for n in a.only.split(",")] if a.only else list(VARIANTS)
    rows = []
    for n in names:
        cached = Path(f"{out}_var_{n}.json").exists()
        rows.append(run_variant(n, m1, sel, out, a.start, a.end))
        if not cached and not a.no_save:
            os.system(f'bash save.sh "v7 step 4: trader variant {n}" >/dev/null 2>&1')
    grid = pd.DataFrame(rows)
    grid.to_csv(f"{out}_sensitivity.csv", index=False)
    print("\n=== SENSITIVITY ===")
    print(grid[GRID_COLS].to_string(index=False))
    if not a.no_report and "base" in grid.name.values:
        trades = pd.read_csv(f"{out}_trades.csv", parse_dates=["entry_time", "close_time"])
        equity = pd.read_csv(f"{out}_equity.csv", index_col=0)
        charts(out, trades, equity, grid)
        write_report(out, grid, grid[grid.name == "base"].iloc[0].to_dict(), trades, sel)


if __name__ == "__main__":
    main()
