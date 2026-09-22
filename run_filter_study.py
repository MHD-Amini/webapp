#!/usr/bin/env python3
"""v8 step 6a - tune the M5 trade filter with the REAL portfolio simulator on the IN-SAMPLE stream
(study_results/sel_v8is_M5.pkl, Feb 2025 - Feb 2026), then verify the chosen rules OOS
(study_results/sel_v8_M5.pkl, Mar - Sep 2026).  Selection of the rule set uses in-sample numbers ONLY.

Every variant = the v7 trader (1 % risk, split legs, costs) with one ``trade_filter`` string.  Results
are appended to study_results/filter_study_<set>.csv (resumable: finished variants are skipped).

    python run_filter_study.py --set insample     # grid on sel_v8is_M5.pkl
    python run_filter_study.py --set oos          # the same grid on sel_v8_M5.pkl (report only)
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from pathlib import Path

import pandas as pd

from backtest_trader import load_selections
from lubot import load_mt5_csv
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

BASE = "risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5,timeframes=M5"


def grid():
    out = {"none": ""}
    for c in (0.05, 0.06, 0.08, 0.10, 0.12):
        out[f"cost{c}"] = f"M5:max_cost_r={c}"
    for q in (0.55, 0.60):
        out[f"q{q}"] = f"M5:min_quality={q}"
    out["no_nypm"] = "M5:sessions=asia|london|preny|ny|lclose"
    out["day_sessions"] = "M5:sessions=london|preny|ny|lclose"
    out["buys"] = "M5:sides=buy"
    out["no_OB"] = "M5:kinds=IMB|UW|HB|BB"
    out["zone_atr0.75"] = "M5:min_zone_atr=0.75"
    out["zone_atr0.75_2.5"] = "M5:min_zone_atr=0.75;max_zone_atr=2.5"
    for c, q in itertools.product((0.06, 0.08, 0.10), (0.55, 0.60)):
        out[f"cost{c}_q{q}"] = f"M5:max_cost_r={c};min_quality={q}"
    for c in (0.06, 0.08, 0.10):
        out[f"cost{c}_no_nypm"] = f"M5:max_cost_r={c};sessions=asia|london|preny|ny|lclose"
        out[f"cost{c}_q0.55_no_nypm"] = f"M5:max_cost_r={c};min_quality=0.55;sessions=asia|london|preny|ny|lclose"
        out[f"cost{c}_buys"] = f"M5:max_cost_r={c};sides=buy"
        out[f"cost{c}_q0.55_buys"] = f"M5:max_cost_r={c};min_quality=0.55;sides=buy"
    out["cost0.08_q0.55_no_nypm_buys"] = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose;sides=buy"
    # optional trade-outcome model (no bot-like skill expected; included for completeness)
    out["model0.55"] = "M5:model_path=models/trade_filter_M5_trainonly.json;model_min=0.55"
    out["model0.58_cost0.08"] = "M5:model_path=models/trade_filter_M5_trainonly.json;model_min=0.58;max_cost_r=0.08"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--set", default="insample", choices=["insample", "oos"])
    ap.add_argument("--only", default=None, help="comma list of variant names")
    a = ap.parse_args()
    if a.set == "insample":
        sel_glob, start, end = "study_results/sel_v8is_M5.pkl", "2025-02-15", "2026-03-01"
    else:
        sel_glob, start, end = "study_results/sel_v8_M5.pkl", "2026-03-01", None
    out = Path(f"study_results/filter_study_{a.set}.csv")
    done = set(pd.read_csv(out).name) if out.exists() else set()
    m1 = load_mt5_csv(a.csv)
    m1 = m1[start:end] if end else m1[start:]
    sel = load_selections(sel_glob)
    variants = grid()
    if a.only:
        variants = {k: v for k, v in variants.items() if k in a.only.split(",")}
    for name, flt in variants.items():
        if name in done:
            continue
        t0 = time.time()
        tcfg = TraderConfig().override(BASE)
        tcfg.trade_filter = flt
        res = PortfolioSimulator(m1, sel, tcfg, SymbolSpec(), start=start, end=end).run()
        s = res.summary()
        row = {"name": name, "filter": flt, **{k: s.get(k) for k in ("trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%",
                                                                       "max_dd_%", "sharpe_daily", "sl_%", "tp2_%", "partial_be_%",
                                                                       "commission_$", "expectancy_$", "trades_per_day")}}
        if len(res.trades):
            m = res.monthly()
            row["months_pos"] = int((m["total_R"] > 0).sum())
            row["months"] = int(len(m))
            row["buys_R"] = round(res.trades[res.trades.side == "buy"].r_net.sum(), 2)
            row["sells_R"] = round(res.trades[res.trades.side == "sell"].r_net.sum(), 2)
        pd.DataFrame([row]).to_csv(out, mode="a", header=not out.exists(), index=False)
        print(f"[{a.set}] {name:<28} trades {s.get('trades', 0):4d}  PF {s.get('profit_factor', 0):5.2f}  R/tr {s.get('avg_R', 0):+.3f}  "
              f"total {s.get('total_R', 0):+7.1f}R  ret {s.get('return_%', 0):+6.1f}%  DD {s.get('max_dd_%', 0):6.1f}%  ({time.time() - t0:.0f}s)", flush=True)
        res.trades.to_csv(f"study_results/filter_study_{a.set}_{name}_trades.csv", index=False)
        os.system(f'bash save.sh "v8 step 6: filter study {a.set} {name}" >/dev/null 2>&1')
    df = pd.read_csv(out).sort_values("total_R", ascending=False)
    print(f"\n===== {a.set} ranking =====\n" + df[["name", "trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%",
                                                   "sharpe_daily", "months_pos", "months", "buys_R", "sells_R"]].to_string(index=False))


if __name__ == "__main__":
    main()
