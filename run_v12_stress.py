#!/usr/bin/env python3
"""v12 step 4 - STRESS + WALK-FORWARD of the finalists.

Stress (full year, same simulator): spread x2, commission x2, slippage x3, worst intrabar, risk 0.5 %, risk 2 %.
Walk-forward: rank every finished variant on the IN-SAMPLE half only (Sep25-Feb26), see where the finalists land, and the
Spearman correlation of IS R vs OOS R over all variants (are in-sample picks predictive at all?).
Resumable via run_v12_levers.run_one (one json per run in study_results/v12_levers/).
Outputs: study_results/v12_stress.csv, v12_walkforward.csv

    python run_v12_stress.py --csv data/xauusd_m1.csv --workers 2 [--finalists a,b,c]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v12_levers import OUT, STRESS, _init, _job, variants_combos, variants_single  # noqa: E402

FINALISTS = ["ref", "KR_htf_b1", "X_CF_m10_q0.5+KR_htf_b1", "X_CF_m10_q0.5+KR_htf_b1+F_m10_q0.57",
             "X_CF_m10m15_q0.5+KR_htf_b1+F_m10_q0.57", "RE_m10m15_b1"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--finalists", default=",".join(FINALISTS))
    a = ap.parse_args()
    allv = {**variants_single(), **variants_combos(None)}
    names = a.finalists.split(",")
    todo = []
    for n in names:
        f, o = allv[n]
        for tag, (et, es) in STRESS.items():
            todo.append((n, f, ",".join(x for x in (o, et) if x), es, tag))
    print(f"{len(todo)} stress runs, {sum(1 for k, _, _, _, tag in todo if not (OUT / f'{k}__{tag}.json').exists())} to run", flush=True)

    def show(r):
        print(f"{r['key']:<64} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.2f} "
              f"OOS PF {r.get('OOS_PF', 0):4.2f}", flush=True)

    rows = []
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
    # add the base runs of the finalists (already computed) for the table
    for n in names:
        f = OUT / f"{n}.json"
        if f.exists():
            r = json.load(open(f))
            r["tag"] = "base"
            rows.append(r)
    st = pd.DataFrame(rows)
    st.to_csv("study_results/v12_stress.csv", index=False)
    pd.set_option("display.width", 260)
    cell = st.apply(lambda r: f"{r['return_%']:+.0f}% / {r['max_dd_%']:.1f}% / {r.get('OOS_PF', 0):.2f}", axis=1)
    piv = st.assign(cell=cell).pivot(index="name", columns="tag", values="cell")[["base"] + list(STRESS)]
    print("\n=== STRESS (return / max DD / OOS PF) ===\n" + piv.loc[[n for n in names if n in piv.index]].to_string())
    # ---- walk-forward over every finished base variant
    base = [json.load(open(f)) for f in glob.glob(str(OUT / "*.json")) if "__" not in f]
    df = pd.DataFrame(base)
    df = df[df.trades > 0].copy()
    df["IS_rank"] = df.IS_R.rank(ascending=False).astype(int)
    df["OOS_rank"] = df.OOS_R.rank(ascending=False).astype(int)
    rho, p = spearmanr(df.IS_R, df.OOS_R)
    rho_pf, p_pf = spearmanr(df.IS_PF, df.OOS_PF)
    wf = df.sort_values("IS_R", ascending=False)[["name", "trades", "IS_R", "IS_PF", "OOS_R", "OOS_PF", "max_dd_%", "IS_rank", "OOS_rank"]]
    wf.to_csv("study_results/v12_walkforward.csv", index=False)
    print(f"\n=== WALK-FORWARD over {len(df)} variants: Spearman(IS_R, OOS_R) = {rho:.2f} (p {p:.1e}); "
          f"Spearman(IS_PF, OOS_PF) = {rho_pf:.2f} (p {p_pf:.1e}) ===")
    print("top 15 by IN-SAMPLE R (what a naive optimiser would pick):")
    print(wf.head(15).to_string(index=False))
    print("\nfinalists:")
    print(wf[wf.name.isin(names)].to_string(index=False))
    # IS-only selection with the loss band applied on the IS half -> which of them hold OOS?
    ref = df[df.name == "ref"].iloc[0]
    is_ok = df[(df.IS_PF >= ref.IS_PF - 0.05) & (df["max_dd_%"] >= ref["max_dd_%"] - 0.7) & (df.trades > ref.trades)]
    is_ok = is_ok.sort_values("IS_R", ascending=False).head(10)
    print("\nIS-band picks (IS PF >= ref-0.05, DD <= ref+0.7, more trades), top 10 by IS R -> their OOS PF:")
    print(is_ok[["name", "trades", "IS_R", "IS_PF", "OOS_R", "OOS_PF", "max_dd_%"]].to_string(index=False))


if __name__ == "__main__":
    main()
