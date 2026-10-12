#!/usr/bin/env python3
"""v16c step 4 - walk-forward of the v16c grid, from the per-run EQUITY paths + trade lists in study_results/v16c_levers/ (no simulation).
Question: had the variant been chosen on the FIRST half only (Sep 2025 - Feb 2026) with the v16c criteria (max DD of the half's equity
path better by >= 0.25 pt, ulcer of the half not worse, net >= 97 %, PF >= ref - 0.10), how did that choice do on the SECOND half
(Mar - Sep 2026, entry model out-of-sample)?  The max DD of a half is measured on the half's own equity path (peak reset at the
half's start); the trades split on their CLOSE time.  Also: Spearman IS->OOS rank correlation of the deltas vs ref.
Writes study_results/v16c_walkforward.csv (one row per variant) + .json, prints the IS-chosen top and their OOS result.
    python3 walkforward_v16c.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SR = Path("study_results")
RUNS = SR / "v16c_levers"
OOS = pd.Timestamp("2026-03-01")


def path_stats(eq: pd.Series, p: str) -> dict:
    if not len(eq):
        return {f"{p}_dd_%": 0.0, f"{p}_ulcer": 0.0}
    dd = 100.0 * (eq / eq.cummax() - 1.0)
    return {f"{p}_dd_%": round(float(dd.min()), 2), f"{p}_ulcer": round(float(np.sqrt((dd ** 2).mean())), 3)}


def half(tr: pd.DataFrame, p: str) -> dict:
    n = len(tr)
    if n == 0:
        return {f"{p}_n": 0, f"{p}_net_$": 0.0, f"{p}_PF": 0.0, f"{p}_sl_%": 0.0, f"{p}_lost_$": 0.0, f"{p}_worst_day_R": 0.0}
    net = tr.net
    losses, wins = net[net < 0], net[net > 0]
    daily_r = tr.groupby(pd.to_datetime(tr.close_time).dt.date).r_net.sum()
    return {f"{p}_n": n, f"{p}_net_$": round(net.sum(), 0), f"{p}_R": round(tr.r_net.sum(), 2),
            f"{p}_PF": round(wins.sum() / -losses.sum(), 3) if len(losses) else float("inf"),
            f"{p}_win_%": round(100 * (net > 0).mean(), 1), f"{p}_sl_%": round(100 * (tr.outcome == "sl").mean(), 1),
            f"{p}_lost_$": round(losses.sum(), 0), f"{p}_worst_day_R": round(daily_r.min(), 2)}


def main():
    rows = []
    for f in sorted(glob.glob(str(RUNS / "*_trades.csv"))):
        name = Path(f).name[:-len("_trades.csv")]
        if "__" in name:
            continue
        tr = pd.read_csv(f, parse_dates=["close_time"])
        eq = pd.read_csv(RUNS / f"{name}_equity.csv", parse_dates=["time"]).set_index("time").equity
        r = {"name": name}
        r.update(half(tr[tr.close_time < OOS], "IS"))
        r.update(path_stats(eq[eq.index < OOS], "IS"))
        r.update(half(tr[tr.close_time >= OOS], "OOS"))
        r.update(path_stats(eq[eq.index >= OOS], "OOS"))
        rows.append(r)
    df = pd.DataFrame(rows).set_index("name")
    ref = df.loc["ref"]
    for p in ("IS", "OOS"):
        df[f"{p}_d_dd"] = (df[f"{p}_dd_%"] - ref[f"{p}_dd_%"]).round(2)        # > 0 = less drawdown
        df[f"{p}_d_ulcer"] = (df[f"{p}_ulcer"] - ref[f"{p}_ulcer"]).round(3)
        df[f"{p}_d_net"] = df[f"{p}_net_$"] - ref[f"{p}_net_$"]
        df[f"{p}_d_PF"] = (df[f"{p}_PF"] - ref[f"{p}_PF"]).round(3)
        df[f"{p}_less_dd"] = (df[f"{p}_d_dd"] >= 0.25) & (df[f"{p}_d_ulcer"] <= 0)
        df[f"{p}_hold_profit"] = (df[f"{p}_net_$"] >= 0.97 * ref[f"{p}_net_$"]) & (df[f"{p}_PF"] >= ref[f"{p}_PF"] - 0.10)
        df[f"{p}_hold_loss"] = (df[f"{p}_sl_%"] <= ref[f"{p}_sl_%"] + 1.0) & (df[f"{p}_lost_$"] >= 1.05 * ref[f"{p}_lost_$"]) \
            & (df[f"{p}_worst_day_R"] >= ref[f"{p}_worst_day_R"] - 0.25)
        df[f"{p}_pass"] = df[f"{p}_less_dd"] & df[f"{p}_hold_profit"] & df[f"{p}_hold_loss"]
    v = df.drop(index="ref")
    out = {}
    for k in ("d_dd", "d_ulcer", "d_net", "d_PF"):
        rho, pval = spearmanr(v[f"IS_{k}"], v[f"OOS_{k}"])
        out[k] = (round(float(rho), 3), float(pval))
    both = int((v.IS_pass & v.OOS_pass).sum())
    print(f"variants {len(v)}: IS pass {int(v.IS_pass.sum())}, OOS pass {int(v.OOS_pass.sum())}, both {both}")
    print("Spearman IS->OOS of the deltas vs ref:", {k: f"rho {r} (p {p:.1e})" for k, (r, p) in out.items()})
    top = v[v.IS_pass].sort_values(["IS_d_dd", "IS_net_$"], ascending=False).head(15)
    cols = ["IS_n", "IS_net_$", "IS_PF", "IS_dd_%", "IS_ulcer", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_dd_%", "OOS_ulcer",
            "OOS_d_dd", "OOS_less_dd", "OOS_hold_profit", "OOS_hold_loss", "OOS_pass"]
    pd.set_option("display.width", 250)
    print("\nChosen on the IS half (pass + most DD pt gained), judged OOS:\n", top[cols].to_string())
    print("\nref:", ref[[c for c in cols if not c.endswith(("pass", "less_dd", "hold_profit", "hold_loss", "d_dd"))]].to_dict())
    df["IS_OOS_both_pass"] = df.IS_pass & df.OOS_pass
    df.to_csv(SR / "v16c_walkforward.csv")
    json.dump({"n_variants": len(v), "is_pass": int(v.IS_pass.sum()), "oos_pass": int(v.OOS_pass.sum()), "both": both,
               "spearman": {k: {"rho": r, "p": p} for k, (r, p) in out.items()},
               "is_top": top.index.tolist(), "is_top_oos_pass": [bool(x) for x in top.OOS_pass.tolist()],
               "ref": {k: (float(x) if isinstance(x, (int, float, np.floating, np.integer)) else x) for k, x in ref.to_dict().items()}},
              open(SR / "v16c_walkforward.json", "w"), indent=1, default=str)
    print("wrote study_results/v16c_walkforward.csv / .json")


if __name__ == "__main__":
    main()
