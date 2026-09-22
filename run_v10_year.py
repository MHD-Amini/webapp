#!/usr/bin/env python3
"""v10 step 6 - FULL-YEAR realistic portfolio backtest, 2025-09-01 -> 2026-09-04 (sel_v10_<TF>.pkl streams).

Systems (entries = v8 recommended trader on every system, only the management differs):
  spec_v8        current spec  50 % @ 0.4R -> BE, TP2 1.5R
  v9             v9 recommendation 25 % @ 0.6R -> BE, TP2 2.5R        (+ twin TP2 3R)
  v10_best_*     the multi-TP finalists picked automatically from the v10 grid: best in-sample avg R among the systems that
                 are also in the OOS top-20 by return/DD (3-, 4- and 5-leg winners separately) + the OOS return winner
Each system is run  (a) WITHOUT the account protection  (b) WITH the user's rules: daily loss 4.5 % -> flat until the next
server day, total loss 9 % -> halt.  Plus the loss rules alone under stress (spread x2, risk 2 %, 3 %) to show when they bite.

IMPORTANT honesty note: the quality model (models/quality_model_trainonly.json) was trained on data until 2026-03-01, so
Sep 2025 -> Feb 2026 is IN-SAMPLE for the entry model and Mar -> Sep 2026 is OUT-OF-SAMPLE.  The report labels both halves.

Outputs (resumable, one json per run): study_results/v10_year/<system>__<rules>.json|_trades.csv|_equity.csv,
study_results/v10_year_summary.csv, v10_year_monthly.csv.
    python run_v10_year.py --csv data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections, spec_override  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import FLT, KEYS  # noqa: E402
from run_v10_study import BASE, grid, n_legs  # noqa: E402

OUT = Path("study_results/v10_year")
RULES = "max_daily_loss_pct=4.5,max_total_loss_pct=9.0"
OOS_SPLIT = "2026-03-01"


def pick_systems() -> dict[str, str]:
    g = grid()
    systems = {"spec_v8": "", "v9_p0.6_f0.25_tp2.5": g["v9_p0.6_f0.25_tp2.5"], "v9_p0.6_f0.25_tp3.0": g["v9_p0.6_f0.25_tp3.0"]}
    oos_f, is_f = Path("study_results/v10_study_grid.csv"), Path("study_results/v10_insample.csv")
    if not oos_f.exists():
        return systems
    oos = pd.read_csv(oos_f)
    oos = oos[oos.trades >= 100]
    systems[oos.sort_values("return_%", ascending=False).name.iloc[0]] = None       # OOS return winner
    if is_f.exists():
        ins = pd.read_csv(is_f)
        m = oos.merge(ins[["name", "avg_R", "PF", "max_dd_R", "t_stat"]], on="name", suffixes=("", "_is"))
        m["legs"] = m.overrides.fillna("").map(n_legs)
        top_oos = set(m.sort_values("ret_dd", ascending=False).name.head(40))
        multi = m[(m.legs >= 3) & m.name.isin(top_oos)]
        for k in (3, 4, 5):
            sub = multi[multi.legs == k].sort_values("avg_R_is", ascending=False)
            if len(sub):
                systems[sub.name.iloc[0]] = None
        # overall robust winner: best in-sample among the multi-leg systems in the OOS top-40
        if len(multi):
            systems[multi.sort_values("avg_R_is", ascending=False).name.iloc[0]] = None
    return {k: (g[k] if v is None else v) for k, v in systems.items()}


def run_one(name: str, over: str, rules: str, m1, sel, extra_t: str = "", extra_s: str = "", tag: str = "") -> dict:
    key = f"{name}__{'rules' if rules else 'norules'}{('__' + tag) if tag else ''}"
    f = OUT / f"{key}.json"
    if f.exists():
        return json.load(open(f))
    t0 = time.time()
    parts = [BASE] + [x for x in (over, rules, extra_t) if x]
    tcfg = TraderConfig().override(",".join(parts))
    tcfg.trade_filter = FLT
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    s = res.summary()
    row = {"key": key, "system": name, "rules": bool(rules), "tag": tag, "overrides": over, **{k: s.get(k) for k in KEYS}}
    row.update({"daily_halts": s.get("daily_halts"), "halted": s.get("halted"), "halt_time": s.get("halt_time")})
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        ins, oos = tr[tr.close_time < OOS_SPLIT], tr[tr.close_time >= OOS_SPLIT]
        for lab, part in (("IS", ins), ("OOS", oos)):
            row[f"{lab}_n"] = len(part)
            row[f"{lab}_R"] = round(part.r_net.sum(), 2)
            row[f"{lab}_net_$"] = round(part.net.sum(), 2)
            row[f"{lab}_win_%"] = round(100 * (part.net > 0).mean(), 1) if len(part) else np.nan
            row[f"{lab}_PF"] = round(part[part.net > 0].net.sum() / abs(part[part.net < 0].net.sum()), 3) if (part.net < 0).any() else np.inf
        row["months_pos"] = int((tr.groupby("month").net.sum() > 0).sum())
        row["months"] = int(tr.month.nunique())
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        row["by_tf_R"] = tr.groupby("tf").r_net.sum().round(2).to_dict()
        row["worst_day_%"] = round(100 * res.equity.equity.resample("1D").last().dropna().pct_change().min(), 2)
        eq = res.equity.equity
        row["max_dd_%"] = round(100 * (eq / eq.cummax() - 1).min(), 2)
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        row["monthly_R"] = tr.groupby("month").r_net.sum().round(2).to_dict()
        row["monthly_n"] = tr.groupby("month").size().to_dict()
        # intraday loss statistic: worst equity dip vs day-start (what the 4.5 % rule watches)
        e = res.equity.equity
        day_start = e.groupby(e.index.date).transform("first")
        row["worst_intraday_vs_daystart_%"] = round(100 * (e / day_start - 1).min(), 2)
        tr.to_csv(OUT / f"{key}_trades.csv", index=False)
    res.equity.to_csv(OUT / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = OUT / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    systems = pick_systems()
    print("systems:", json.dumps(systems, indent=1), flush=True)
    m1 = load_mt5_csv(a.csv)[a.start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in ("M5", "M10", "M15", "M30", "H1")],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    rows = []
    for name, over in systems.items():
        for rules in ("", RULES):
            r = run_one(name, over, rules, m1, sel)
            rows.append(r)
            print(f"{r['key']:<60} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.1f}% PF {r['profit_factor']:5.2f} "
                  f"IS {r.get('IS_R', 0):+6.1f}R OOS {r.get('OOS_R', 0):+6.1f}R halts {r['daily_halts']} halted {r['halted']}", flush=True)
    # stress: when do the loss rules bite?  (spec + v9 + best multi under harsher conditions, with rules)
    stress = {"risk2": ("risk_pct=2.0", ""), "risk3": ("risk_pct=3.0", ""), "spread_x2": ("spread_multiplier=2.0", ""),
              "risk2_spread_x2": ("risk_pct=2.0,spread_multiplier=2.0", ""), "open8": ("max_open_positions=8", ""),
              "worst_intrabar": ("intrabar=worst", ""), "commission_x2": ("", "commission_per_lot=14")}
    for name, over in systems.items():
        for tag, (et, es) in stress.items():
            for rules in ("", RULES):
                r = run_one(name, over, rules, m1, sel, et, es, tag)
                rows.append(r)
                print(f"{r['key']:<60} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.1f}% halts {r['daily_halts']} "
                      f"halted {r['halted']} {r['halt_time']}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("study_results/v10_year_summary.csv", index=False)
    mon = []
    for r in rows:
        if r.get("monthly_$") and not r["tag"]:
            for mth, v in r["monthly_$"].items():
                mon.append({"system": r["system"], "rules": r["rules"], "month": mth, "net_$": v,
                            "R": r["monthly_R"].get(mth), "n": r["monthly_n"].get(mth)})
    pd.DataFrame(mon).to_csv("study_results/v10_year_monthly.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["key", "trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sharpe_daily", "IS_R", "OOS_R", "months_pos", "daily_halts", "halted", "worst_day_%"]
    print("\n=== FULL YEAR Sep 2025 -> Sep 2026 ===\n" + df[df.tag == ""][cols].to_string(index=False))
    print("\n=== stress (rules on/off) ===\n" + df[df.tag != ""][["key", "return_%", "max_dd_%", "daily_halts", "halted", "halt_time"]].to_string(index=False))


if __name__ == "__main__":
    main()
