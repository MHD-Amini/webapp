#!/usr/bin/env python3
"""v9 - RISK-MANAGEMENT STUDY: which exit / management system makes the v8 trader most profitable?

The v7/v8 spec is "close 50 % at +0.4R, stop to break-even, TP2 = +1.5R".  This script keeps the v8
entry side (v8 M5 filter + min_quality 0.60 on the other timeframes, 1 % risk, real costs) fixed and
varies ONLY the management, on the realistic portfolio simulator (M1 precision, OOS 2026-03-02 -> 2026-09-04):

  A  two-leg partial systems   partial_r x partial_frac x tp2_r x (BE on/off)
  B  single target             tp x BE-trigger (stop -> BE once price has been >= X R on a closed bar)
  C  trailing stop             partial at X R + runner trailed by Y R (with / without fixed TP2, activation level)
  C2 trail the whole position  no partial, trailing stop from the fill / after X R
  D  target ladders            3 legs (levels x fractions), optional stop ratchet to the previous target
  E  time stops                on top of the base and the trail system
  F  BE offset                 lock +0.05 / +0.1 / +0.2 R (or give -0.1 R room) instead of exact entry

Resumable (one json per variant in study_results/rm_study/; finished variants are skipped).  Every
finished variant is written immediately, so a killed run loses at most the variants in flight.

    python run_rm_study.py --csv data/xauusd_m1.csv --workers 2
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402

FLT = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"
BASE = "risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5"
OUT = Path("study_results/rm_study")
KEYS = ["trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "max_dd_R", "sharpe_daily",
        "sl_%", "partial_be_%", "tp2_%", "partial_hit_%", "avg_hold_min", "expectancy_$", "end_balance"]


# ----------------------------------------------------------------------------- the grid
def grid() -> dict:
    g: dict[str, str] = {}
    g["base_v8"] = ""                                                    # 50 % @ 0.4R -> BE, TP2 1.5R
    # A. two-leg partial systems
    for pr, pf, tp in itertools.product((0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0), (0.25, 0.33, 0.5, 0.67, 0.75),
                                        (1.0, 1.5, 2.0, 2.5, 3.0)):
        if tp <= pr:
            continue
        g[f"A_p{pr}_f{pf}_tp{tp}"] = f"partial_r={pr},partial_frac={pf},tp2_r={tp}"
        if pf == 0.5 and tp in (1.5, 2.0, 3.0):
            g[f"A_p{pr}_f{pf}_tp{tp}_noBE"] = f"partial_r={pr},partial_frac={pf},tp2_r={tp},be_on_partial=false"
    # B. single target, optional BE trigger
    for tp in (0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0):
        g[f"B_tp{tp}"] = f"partial_frac=0,tp2_r={tp}"
        for bt in (0.3, 0.5, 0.8, 1.0):
            if bt < tp:
                g[f"B_tp{tp}_be{bt}"] = f"partial_frac=0,tp2_r={tp},be_trigger_r={bt}"
    # C. partial + trailed runner
    for pr in (0.3, 0.4, 0.5):
        for tr in (0.3, 0.5, 0.7, 1.0, 1.5):
            for tp in (0, 1.5, 2.0, 3.0):
                for ts in (0, 0.5, 1.0):
                    g[f"C_p{pr}_trail{tr}_tp{tp}_start{ts}"] = f"partial_r={pr},tp2_r={tp},trail_r={tr},trail_start_r={ts}"
    for tr in (0.5, 0.7, 1.0):
        for tp in (0, 2.0):
            g[f"C_p0.4_trail{tr}_tp{tp}_close"] = f"tp2_r={tp},trail_r={tr},trail_source=close"
    # C2. no partial, trail the whole position
    for tr in (0.5, 0.7, 1.0, 1.5, 2.0):
        for ts in (0, 0.5, 1.0):
            for tp in (0, 2.0, 3.0):
                g[f"C2_trail{tr}_start{ts}_tp{tp}"] = f"partial_frac=0,tp2_r={tp},trail_r={tr},trail_start_r={ts},trail_after_partial=false"
    # D. 3-leg ladders
    ladders = [(0.4, 1.0, 2.0), (0.4, 1.5, 3.0), (0.4, 1.0, 1.5), (0.5, 1.0, 1.5), (0.3, 0.8, 1.5), (0.4, 0.8, 1.5),
               (0.4, 1.0, 0), (0.4, 1.5, 0), (0.5, 1.5, 3.0), (0.6, 1.2, 2.0), (0.3, 1.0, 2.0)]
    fracs = {"eq": "0.34|0.33|0.33", "50_25_25": "0.5|0.25|0.25", "25_25_50": "0.25|0.25|0.5", "50_30_20": "0.5|0.3|0.2",
             "40_30_30": "0.4|0.3|0.3"}
    for lv in ladders:
        lvs = "|".join(str(x) for x in lv)
        for fn, fr in fracs.items():
            for ratchet in (False, True):
                over = f"tp_levels={lvs},tp_fracs={fr}" + (",ratchet_sl=true" if ratchet else "")
                if lv[-1] == 0:
                    over += ",trail_r=0.7"          # a 0 last level = runner: needs a trail to ever exit
                g[f"D_{lvs.replace('|', '-')}_{fn}{'_ratchet' if ratchet else ''}"] = over
    # E. time stops on the base and the trail system
    for mh in (15, 30, 60, 120, 240, 480):
        g[f"E_base_hold{mh}"] = f"max_hold_min={mh}"
        g[f"E_trail0.5_hold{mh}"] = f"trail_r=0.5,max_hold_min={mh}"
    # F. BE offset (lock a few ticks) on the base and the trail system
    for bo in (0.05, 0.1, 0.2, -0.1):
        g[f"F_base_beoff{bo}"] = f"be_offset_r={bo}"
        g[f"F_trail0.5_beoff{bo}"] = f"trail_r=0.5,be_offset_r={bo}"
    return g


# ----------------------------------------------------------------------------- runner
_M1 = None
_SEL = None


def _init(csv: str, start: str):
    global _M1, _SEL
    _M1 = load_mt5_csv(csv)[start:]
    _SEL = pd.concat([load_selections("study_results/sel_v8_M5.pkl")] +
                     [load_selections(f"study_results/sel_v7_{tf}.pkl") for tf in ("M10", "M15", "M30", "H1")],
                     ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)


def summarize(name: str, over: str, res, mid: str) -> dict:
    s = res.summary()
    row = {"name": name, "overrides": over, **{k: s.get(k) for k in KEYS}}
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        h1, h2 = tr[tr.close_time < mid], tr[tr.close_time >= mid]
        row.update({"H1_R": round(h1.r_net.sum(), 2), "H2_R": round(h2.r_net.sum(), 2), "H1_n": len(h1), "H2_n": len(h2),
                    "months_pos": int((tr.groupby("month").r_net.sum() > 0).sum()), "months": int(tr.month.nunique()),
                    "outcomes": tr.outcome.value_counts().to_dict(),
                    "M5_R": round(tr[tr.tf == "M5"].r_net.sum(), 2), "other_R": round(tr[tr.tf != "M5"].r_net.sum(), 2),
                    "buy_R": round(tr[tr.side == "buy"].r_net.sum(), 2), "sell_R": round(tr[tr.side == "sell"].r_net.sum(), 2),
                    "median_R": round(tr.r_net.median(), 4), "std_R": round(tr.r_net.std(), 4),
                    "t_stat": round(tr.r_net.mean() / (tr.r_net.std() / len(tr) ** 0.5), 2) if tr.r_net.std() > 0 else 0.0})
    return row


def run_variant(name: str, over: str, start: str, mid: str) -> dict:
    f = OUT / f"{name}.json"
    if f.exists():
        return json.load(open(f))
    t0 = time.time()
    tcfg = TraderConfig().override(BASE + ("," + over if over else ""))
    tcfg.trade_filter = FLT
    res = PortfolioSimulator(_M1, _SEL, tcfg, SymbolSpec(), start=start).run()
    row = summarize(name, over, res, mid)
    if len(res.trades):
        res.trades.to_csv(OUT / f"{name}_trades.csv", index=False)
    res.equity.to_csv(OUT / f"{name}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = OUT / f"{name}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)                       # atomic: a killed run never leaves a half-written json
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2026-03-01")
    ap.add_argument("--mid", default="2026-06-01")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default=None, help="prefix filter, e.g. A_ or C_")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    g = grid()
    if a.only:
        g = {k: v for k, v in g.items() if k.startswith(a.only) or k == "base_v8"}
    todo = {k: v for k, v in g.items() if not (OUT / f"{k}.json").exists()}
    print(f"{len(g)} variants, {len(todo)} to run", flush=True)
    rows = [json.load(open(OUT / f"{k}.json")) for k in g if k not in todo]
    t0 = time.time()
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.csv, a.start)) as ex:
            futs = {ex.submit(run_variant, k, v, a.start, a.mid): k for k, v in todo.items()}
            for i, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                rows.append(r)
                print(f"[{i}/{len(todo)} {time.time() - t0:5.0f}s] {r['name']:<42} n {r['trades']:4d} PF {r['profit_factor']:5.2f} "
                      f"R/tr {r['avg_R']:+.3f} tot {r['total_R']:+6.1f}R ret {r['return_%']:+6.1f}% DD {r['max_dd_%']:6.1f}%", flush=True)
    df = pd.DataFrame(rows)
    df["family"] = df.name.str.split("_").str[0]
    df["ret_dd"] = df["return_%"] / df["max_dd_%"].abs().clip(lower=0.5)
    df.to_csv("study_results/rm_study_grid.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["name", "trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "sharpe_daily", "H1_R", "H2_R", "months_pos"]
    print("\n=== top 30 by return ===\n" + df.sort_values("return_%", ascending=False)[cols].head(30).to_string(index=False))
    print("\n=== top 20 by return / max DD ===")
    print(df.sort_values("ret_dd", ascending=False)[cols + ["ret_dd"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
