#!/usr/bin/env python3
"""v8 step 6b - final realistic OOS comparison (Mar-Sep 2026, $10k, 1 % risk, costs):

  v7_base             all TFs, no filter                     (the -14 % of the v7 report)
  v7_q060             all TFs, min_quality 0.60              (the user's workaround)
  v7_noM5             M10/M15/M30/H1 only
  v8_M5only           M5 alone with the chosen filter
  v8_all              all TFs, M5 filtered with the chosen rules (the v8 default)
  v8_all_q060         v8_all + min_quality 0.60 on every TF
  v8_all_others_q060  M5 filtered, the other TFs at min_quality 0.60

Streams: sel_v8_M5.pkl (M5 with features) + sel_v7_{M10,M15,M30,H1}.pkl.  Also splits the OOS
period in two halves and writes the equity chart.  Resumable per variant (summary json cached).

    python run_v8_compare.py --filter "M5:max_cost_r=0.08;min_quality=0.55"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from backtest_trader import load_selections
from lubot import load_mt5_csv
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

pd.set_option("display.width", 250)
BASE = "risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5"
KEYS = ["trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "sharpe_daily", "sl_%", "partial_be_%",
        "tp2_%", "commission_$", "expectancy_$", "trades_per_day"]


def variants(flt: str):
    return {
        "v7_base": ("", ""),
        "v7_q060": ("min_quality=0.60", ""),
        "v7_noM5": ("timeframes=M10|M15|M30|H1", ""),
        "v8_M5only": ("timeframes=M5", flt),
        "v8_all": ("", flt),
        "v8_all_q060": ("min_quality=0.60", flt),
        "v8_all_others_q060": ("", flt + "/M10|M15|M30|H1:min_quality=0.60"),
    }


def run_one(m1, sel, over, flt, start, end):
    tcfg = TraderConfig().override(BASE + ("," + over if over else ""))
    tcfg.trade_filter = flt
    return PortfolioSimulator(m1, sel, tcfg, SymbolSpec(), start=start, end=end).run()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--filter", required=True, help="chosen M5 trade filter string")
    ap.add_argument("--from", dest="start", default="2026-03-01")
    ap.add_argument("--mid", default="2026-06-01")
    ap.add_argument("--out", default="study_results/trader_v8")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    m1 = load_mt5_csv(a.csv)[a.start:]
    sel = pd.concat([load_selections("study_results/sel_v8_M5.pkl")] +
                    [load_selections(f"study_results/sel_v7_{tf}.pkl") for tf in ("M10", "M15", "M30", "H1")],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    rows, curves = [], {}
    for name, (over, flt) in variants(a.filter).items():
        if a.only and name not in a.only.split(","):
            continue
        f = Path(f"{out}_{name}_summary.json")
        if f.exists():
            rows.append(json.load(open(f)))
            curves[name] = pd.read_csv(f"{out}_{name}_equity.csv", index_col=0, parse_dates=True)
            print(f"{name}: cached")
            continue
        res = run_one(m1, sel, over, flt, a.start, None)
        s = res.summary()
        row = {"name": name, "overrides": over, "filter": flt, **{k: s.get(k) for k in KEYS}}
        for lab, (s0, e0) in (("H1", (a.start, a.mid)), ("H2", (a.mid, None))):
            s2 = run_one(m1, sel, over, flt, s0, e0).summary()
            row.update({f"{lab}_trades": s2.get("trades"), f"{lab}_total_R": s2.get("total_R"),
                        f"{lab}_return_%": s2.get("return_%"), f"{lab}_PF": s2.get("profit_factor")})
        if len(res.trades):
            bt = res.by("tf")
            for tf in bt.index:
                row[f"{tf}_n"] = int(bt.loc[tf, "trades"]); row[f"{tf}_R"] = float(bt.loc[tf, "total_R"])
            m = res.monthly(); row["months_pos"] = int((m["total_R"] > 0).sum()); row["months"] = int(len(m))
            res.trades.to_csv(f"{out}_{name}_trades.csv", index=False)
            bt.to_csv(f"{out}_{name}_by_tf.csv"); res.by("side").to_csv(f"{out}_{name}_by_side.csv")
            res.by("kind").to_csv(f"{out}_{name}_by_kind.csv"); m.to_csv(f"{out}_{name}_by_month.csv")
            res.filter_reasons().to_csv(f"{out}_{name}_filter_reasons.csv")
        res.equity.to_csv(f"{out}_{name}_equity.csv")
        json.dump(row, open(f, "w"), indent=1, default=str)
        rows.append(row); curves[name] = res.equity
        print(f"{name:<20} trades {s.get('trades', 0):4d} PF {s.get('profit_factor', 0):5.2f} R/tr {s.get('avg_R', 0):+.3f} "
              f"total {s.get('total_R', 0):+7.1f}R ret {s.get('return_%', 0):+6.1f}% DD {s.get('max_dd_%', 0):6.1f}%", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(f"{out}_compare.csv", index=False)
    cols = [c for c in ["name", "trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "sharpe_daily",
                        "H1_return_%", "H2_return_%", "months_pos", "months"] if c in df.columns]
    print("\n" + df[cols].to_string(index=False))
    Path("study_results/charts").mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 6))
    for name, eq in curves.items():
        plt.plot(eq.index, eq["equity"], label=name, lw=1.6 if name.startswith("v8_all") else 0.9)
    plt.axhline(10000, color="k", lw=0.5); plt.legend(); plt.grid(alpha=0.3)
    plt.title(f"OOS equity Mar-Sep 2026, $10k, 1% risk, real costs | M5 filter: {a.filter}")
    plt.tight_layout(); plt.savefig("study_results/charts/trader_v8_equity.png", dpi=120)
    print("chart -> study_results/charts/trader_v8_equity.png")


if __name__ == "__main__":
    main()
