#!/usr/bin/env python3
"""v9 step 4 - STRESS TESTS of the risk-management finalists (OOS Mar-Sep 2026, realistic portfolio simulator).

Finalists are picked automatically (not hard-coded): base_v8 + the managements that rank in the top-8 of BOTH the OOS
grid (return / max-DD) and the in-sample replay (avg R), plus the OOS return winner and the in-sample winner.
Each finalist is re-run under: spread x1.5 / x2, slippage x3, worst-case intrabar path, 2-minute BE delay, netting
account, commission x2, risk 0.5 % / 2 %, max 2 open positions, no costs.  -> study_results/rm_stress.csv
Resumable: one json per (finalist, scenario) in study_results/rm_stress/.

    python rm_stress.py --csv data/xauusd_m1.csv [--names a,b,c]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections, spec_override  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import BASE, FLT, KEYS, grid  # noqa: E402

OUT = Path("study_results/rm_stress")
# name -> (trader overrides, symbol-spec overrides, BE delay in bars)
SCEN = {
    "normal": ("", "", 0),
    "spread_x1.5": ("spread_multiplier=1.5", "", 0),
    "spread_x2": ("spread_multiplier=2.0", "", 0),
    "slippage_x3": ("sl_slippage=0.30,market_slippage=0.15", "", 0),
    "worst_intrabar": ("intrabar=worst", "", 0),
    "be_delay_2min": ("", "", 2),
    "netting": ("exec_mode=netting", "", 0),
    "commission_x2": ("", "commission_per_lot=14", 0),
    "risk_0.5": ("risk_pct=0.5", "", 0),
    "risk_2.0": ("risk_pct=2.0", "", 0),
    "max_open_2": ("max_open_positions=2", "", 0),
    "no_costs": ("sl_slippage=0,market_slippage=0,spread_multiplier=0",
                 "commission_per_lot=0,swap_long_per_lot=0,swap_short_per_lot=0", 0),
}


def pick_finalists(k: int = 8) -> list[str]:
    oos = pd.read_csv("study_results/rm_study_grid.csv")
    names = ["base_v8"]
    top_oos = set(oos.sort_values("ret_dd", ascending=False).name.head(k))
    names.append(oos.sort_values("return_%", ascending=False).name.iloc[0])
    ins_f = Path("study_results/rm_insample.csv")
    if ins_f.exists():
        ins = pd.read_csv(ins_f)
        names.append(ins.sort_values("avg_R", ascending=False).name.iloc[0])
        top_is = set(ins.sort_values("avg_R", ascending=False).name.head(k))
        both = [n for n in ins.sort_values("avg_R", ascending=False).name if n in top_oos and n in top_is]
        names += both[:4]
        # best "balanced" score: rank-sum of OOS ret/DD and IS avg_R over the variants present in both
        m = ins.merge(oos[["name", "ret_dd", "return_%"]], on="name", suffixes=("", "_oos"))
        m["score"] = m.ret_dd.rank(ascending=False) + m.avg_R.rank(ascending=False)
        names += m.sort_values("score").name.head(3).tolist()
        # balanced: also reward a small IN-SAMPLE drawdown (total R / max DD in R)
        m["is_ret_dd"] = m.total_R / m.max_dd_R.abs()
        m["score3"] = m.score + m.is_ret_dd.rank(ascending=False)
        names += m.sort_values("score3").name.head(4).tolist()
        names += m.sort_values("is_ret_dd", ascending=False).name.head(2).tolist()
    else:
        names += oos.sort_values("ret_dd", ascending=False).name.head(3).tolist()
    return list(dict.fromkeys(n for n in names if isinstance(n, str)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--names", default=None)
    ap.add_argument("--from", dest="start", default="2026-03-01")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    g = grid()
    names = a.names.split(",") if a.names else pick_finalists()
    names = [n for n in names if n in g]
    print("finalists:", names, flush=True)
    m1 = load_mt5_csv(a.csv)[a.start:]
    sel = pd.concat([load_selections("study_results/sel_v8_M5.pkl")] +
                    [load_selections(f"study_results/sel_v7_{tf}.pkl") for tf in ("M10", "M15", "M30", "H1")],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    rows = []
    for n in names:
        for sc, (over, sp, bed) in SCEN.items():
            f = OUT / f"{n}__{sc}.json"
            if f.exists():
                rows.append(json.load(open(f)))
                continue
            t0 = time.time()
            full = ",".join(x for x in (BASE, g[n], over) if x)
            t = TraderConfig().override(full)
            t.trade_filter = FLT
            res = PortfolioSimulator(m1, sel, t, spec_override(SymbolSpec(), sp), be_delay_bars=bed, start=a.start).run()
            s = res.summary()
            row = {"name": n, "scenario": sc, "overrides": g[n], **{k: s.get(k) for k in KEYS}, "secs": round(time.time() - t0, 1)}
            tmp = OUT / f"{n}__{sc}.json.tmp"
            json.dump(row, open(tmp, "w"), indent=1, default=str)
            os.replace(tmp, f)
            rows.append(row)
            print(f"{n:<34} {sc:<16} n {s['trades']:4d} PF {s['profit_factor']:5.2f} R/tr {s['avg_R']:+.3f} "
                  f"ret {s['return_%']:+6.1f}% DD {s['max_dd_%']:6.1f}%", flush=True)
    # the csv always holds EVERY finished (finalist, scenario) json, also from earlier runs with other --names
    df = pd.DataFrame([json.load(open(f)) for f in sorted(OUT.glob("*.json"))])
    df.to_csv("study_results/rm_stress.csv", index=False)
    piv = df.pivot(index="scenario", columns="name", values="return_%").reindex(list(SCEN))
    pd.set_option("display.width", 250)
    print("\n=== return % by scenario ===\n" + piv.round(1).to_string())
    piv2 = df.pivot(index="scenario", columns="name", values="max_dd_%").reindex(list(SCEN))
    print("\n=== max DD % by scenario ===\n" + piv2.round(1).to_string())


if __name__ == "__main__":
    main()
