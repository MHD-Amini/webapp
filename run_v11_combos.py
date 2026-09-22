#!/usr/bin/env python3
"""v11 step 3/4 - LEVER GRID B (new simulator levers) + COMBINATIONS + stress of the finalists.

Grid B (single new levers): dedupe_cross_tf=false, overlap_mode=allow / share (0.25 / 0.5 / 0.75), cancel_grace_min 5..60.
Combos: the levers that held the loss profile in grid A (M30 q 0.55/0.57, H1 q 0.57, M15 q 0.57, M5 all sessions, M5 cost 0.12)
crossed with the grid-B winners.  Every run = full year Sep 2025 -> Sep 2026, judged on the OOS half (Mar -> Sep 2026).
Resumable (one json per run in study_results/v11_levers/), summary -> study_results/v11_combos.csv.

    python run_v11_combos.py --csv data/xauusd_m1.csv --workers 2 [--stress]
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v11_levers import OUT, _G, _init, make_filter, run_one, summarize  # noqa: E402

# ------------------------------------------------------------------ building blocks
# filter blocks (name -> kwargs of make_filter)
F_BLOCKS = {
    "": {},
    "m30q57": {"htf": {"M30": 0.57}},
    "m30q55": {"htf": {"M30": 0.55}},
    "h1q57": {"htf": {"H1": 0.57}},
    "m15q57": {"htf": {"M15": 0.57}},
    "m5sess": {"m5": {"sessions": None}},
    "m5c12": {"m5": {"max_cost_r": 0.12}},
}
# trader blocks (name -> override text)
T_BLOCKS = {
    "": "",
    "xtf": "dedupe_cross_tf=false",
    "allow": "overlap_mode=allow",
    "share25": "overlap_mode=share,overlap_risk_frac=0.25",
    "share50": "overlap_mode=share,overlap_risk_frac=0.5",
    "share75": "overlap_mode=share,overlap_risk_frac=0.75",
    "grace5": "cancel_grace_min=5",
    "grace10": "cancel_grace_min=10",
    "grace15": "cancel_grace_min=15",
    "grace30": "cancel_grace_min=30",
    "grace60": "cancel_grace_min=60",
}


def _merge_f(*names) -> str:
    m5, htf, extra = {}, {}, {}
    for n in names:
        b = F_BLOCKS[n]
        m5.update(b.get("m5", {}))
        htf.update(b.get("htf", {}))
        extra.update(b.get("extra", {}))
    return make_filter(m5=m5, htf=htf, extra=extra)


def _merge_t(*names) -> str:
    return ",".join(T_BLOCKS[n] for n in names if T_BLOCKS[n])


def variants() -> dict[str, tuple[str, str]]:
    v: dict[str, tuple[str, str]] = {}
    # --- grid B: single new levers
    for tn in T_BLOCKS:
        if tn:
            v[f"B_{tn}"] = (make_filter(), _merge_t(tn))
    # grace + cross-tf / share (the two order-handling families together)
    for g in ("grace10", "grace30"):
        for o in ("xtf", "share50", "allow"):
            v[f"B_{o}_{g}"] = (make_filter(), _merge_t(o, g))
    # --- combos: filter relaxations that held the loss profile, alone and stacked
    f_sets = [("m30q57",), ("m30q55",), ("m30q57", "h1q57"), ("m30q57", "h1q57", "m15q57"), ("m30q55", "h1q57", "m15q57"),
              ("m30q57", "m5sess"), ("m30q57", "h1q57", "m5sess"), ("m30q57", "h1q57", "m15q57", "m5sess"),
              ("m30q57", "m5c12"), ("m30q57", "h1q57", "m15q57", "m5sess", "m5c12")]
    t_sets = [(), ("xtf",), ("share50",), ("allow",), ("xtf", "grace10"), ("share50", "grace10"), ("allow", "grace10"),
              ("share25",), ("share75",)]
    for fs in f_sets:
        for ts in t_sets:
            name = "C_" + "+".join(fs) + ("__" + "+".join(ts) if ts else "")
            v[name] = (_merge_f(*fs), _merge_t(*ts))
    return v


def _job(args):
    name, flt, over, extra_s, tag = args
    return run_one(name, flt, over, _G["m1"], _G["sel"], extra_s=extra_s, tag=tag)


STRESS = {"spread_x2": ("spread_multiplier=2.0", ""), "commission_x2": ("", "commission_per_lot=14"),
          "slip_x3": ("sl_slippage=0.30,market_slippage=0.15", ""), "worst_intrabar": ("intrabar=worst", ""),
          "risk0.5": ("risk_pct=0.5", ""), "risk2": ("risk_pct=2.0", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--stress", default="", help="comma list of variant names to stress (from v11_combos.csv)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants()
    todo = [(k, f, o, "", "") for k, (f, o) in v.items()]
    todo.insert(0, ("ref", make_filter(), "", "", ""))
    if a.stress:
        names = a.stress.split(",")
        for n in names:
            f, o = ("ref", (make_filter(), "")) if n == "ref" else (n, v[n])
            f, o = v[n] if n != "ref" else (make_filter(), "")
            for tag, (et, es) in STRESS.items():
                todo.append((n, f, ",".join(x for x in (o, et) if x), es, tag))
    print(f"{len(todo)} runs, {sum(1 for k, _, _, _, tag in todo if not (OUT / (k + ('__' + tag if tag else '') + '.json')).exists())} to run", flush=True)
    rows = []

    def show(r):
        print(f"{r['key']:<58} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.2f} "
              f"win {r['win_%']:4.1f} wd {r.get('worst_day_%', 0):5.2f} OOS {r.get('OOS_R', 0):+6.1f}R/{r.get('OOS_PF', 0):4.2f}", flush=True)

    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.csv, a.start)) as ex:
            for r in ex.map(_job, todo):
                rows.append(r)
                show(r)
    else:
        _init(a.csv, a.start)
        for t in todo:
            r = _job(t)
            rows.append(r)
            show(r)
    base = [r for r in rows if not r["tag"]]
    df = summarize(base, path="study_results/v11_combos.csv")
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v11_stress.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["name", "trades", "d_trades", "return_%", "max_dd_%", "profit_factor", "win_%", "worst_day_%", "sl_%", "IS_R", "OOS_R",
            "OOS_PF", "OOS_win_%", "months_pos", "max_consec_losses", "hold_loss"]
    print("\n=== GRID B + COMBOS (sorted by trades) ===\n" + df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
