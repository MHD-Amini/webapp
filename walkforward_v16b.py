#!/usr/bin/env python3
"""v16b step 4 - walk-forward of the v16b grid, from the per-run trade lists in study_results/v16b_levers/ (no simulation).
Question: had the variant been chosen on the FIRST half only (Sep 2025 - Feb 2026) with the v16b criteria (less $ lost, stop rate down,
net >= 97 %, PF held, worst day in R held), how did that choice do on the SECOND half (Mar - Sep 2026, entry model out-of-sample)?
Also: Spearman IS->OOS rank correlation of the deltas vs ref (do the gains carry over?).  The split is on the CLOSE time of the
trades.  Writes study_results/v16b_walkforward.csv (one row per variant) + prints the IS-chosen top 10 and their OOS result.
    python3 walkforward_v16b.py
"""
import glob
import json
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

SR = Path("study_results")
RUNS = SR / "v16b_levers"
OOS = pd.Timestamp("2026-03-01")


def half(tr: pd.DataFrame, p: str) -> dict:
    n = len(tr)
    if n == 0:
        return {f"{p}_n": 0}
    net = tr.net
    losses, wins = net[net < 0], net[net > 0]
    cum = net.cumsum()
    daily = tr.groupby(pd.to_datetime(tr.close_time).dt.date).net.sum()
    daily_r = tr.groupby(pd.to_datetime(tr.close_time).dt.date).r_net.sum()
    return {f"{p}_n": n, f"{p}_net_$": round(net.sum(), 0), f"{p}_R": round(tr.r_net.sum(), 2),
            f"{p}_PF": round(wins.sum() / -losses.sum(), 3) if len(losses) else float("inf"),
            f"{p}_win_%": round(100 * (net > 0).mean(), 1), f"{p}_sl_%": round(100 * (tr.outcome == "sl").mean(), 1),
            f"{p}_lost_$": round(losses.sum(), 0), f"{p}_worst_day_$": round(daily.min(), 0), f"{p}_worst_day_R": round(daily_r.min(), 2),
            f"{p}_dd_$": round((cum - cum.cummax()).min(), 0)}


def main():
    rows = []
    for f in sorted(glob.glob(str(RUNS / "*_trades.csv"))):
        name = Path(f).name[:-len("_trades.csv")]
        if "__" in name:
            continue
        tr = pd.read_csv(f, parse_dates=["close_time"])
        r = {"name": name}
        r.update(half(tr[tr.close_time < OOS], "IS"))
        r.update(half(tr[tr.close_time >= OOS], "OOS"))
        rows.append(r)
    df = pd.DataFrame(rows).set_index("name")
    ref = df.loc["ref"]
    for p in ("IS", "OOS"):
        df[f"{p}_d_n"] = df[f"{p}_n"] - ref[f"{p}_n"]
        df[f"{p}_d_net"] = df[f"{p}_net_$"] - ref[f"{p}_net_$"]
        df[f"{p}_d_PF"] = df[f"{p}_PF"] - ref[f"{p}_PF"]
        df[f"{p}_d_lost"] = df[f"{p}_lost_$"] - ref[f"{p}_lost_$"]          # > 0 = fewer $ lost
        df[f"{p}_d_sl"] = df[f"{p}_sl_%"] - ref[f"{p}_sl_%"]
        # the v16b pass on this half: fewer $ lost AND stop rate below ref (less loss); net >= 97 % of ref, PF >= ref - 0.05 (profit held);
        # worst day in R >= ref - 0.25 R (scale-free: $ compound)
        df[f"{p}_less_loss"] = (df[f"{p}_lost_$"] > ref[f"{p}_lost_$"]) & (df[f"{p}_sl_%"] < ref[f"{p}_sl_%"])
        df[f"{p}_hold_profit"] = (df[f"{p}_net_$"] >= 0.97 * ref[f"{p}_net_$"]) & (df[f"{p}_PF"] >= ref[f"{p}_PF"] - 0.05)
        df[f"{p}_pass"] = (df[f"{p}_less_loss"] & df[f"{p}_hold_profit"] & (df[f"{p}_worst_day_R"] >= ref[f"{p}_worst_day_R"] - 0.25))
    v = df.drop(index="ref")
    out = {}
    for k in ("d_lost", "d_sl", "d_net", "d_PF"):
        rho, pval = spearmanr(v[f"IS_{k}"], v[f"OOS_{k}"])
        out[k] = (round(rho, 3), pval)
    both = int((v.IS_pass & v.OOS_pass).sum())
    print(f"variants {len(v)}: IS pass {int(v.IS_pass.sum())}, OOS pass {int(v.OOS_pass.sum())}, both {both}")
    print("Spearman IS->OOS of the deltas vs ref:", {k: f"rho {r} (p {p:.1e})" for k, (r, p) in out.items()})
    top = v[v.IS_pass].sort_values("IS_d_lost", ascending=False).head(12)
    cols = ["IS_n", "IS_net_$", "IS_PF", "IS_sl_%", "IS_lost_$", "IS_pass", "OOS_n", "OOS_net_$", "OOS_PF", "OOS_sl_%", "OOS_lost_$", "OOS_worst_day_R", "OOS_less_loss", "OOS_hold_profit", "OOS_pass"]
    pd.set_option("display.width", 250)
    print("\nChosen on the IS half (pass + most $ saved), judged OOS:\n", top[cols].to_string())
    print("\nref:", ref[[c for c in cols if not c.endswith(("pass", "less_loss", "hold_profit"))]].to_dict())
    df["IS_OOS_both_pass"] = df.IS_pass & df.OOS_pass
    df.to_csv(SR / "v16b_walkforward.csv")
    json.dump({"n_variants": len(v), "is_pass": int(v.IS_pass.sum()), "oos_pass": int(v.OOS_pass.sum()), "both": both,
               "spearman": {k: {"rho": r, "p": p} for k, (r, p) in out.items()},
               "is_top": top.index.tolist(), "is_top_oos_pass": top.OOS_pass.tolist()}, open(SR / "v16b_walkforward.json", "w"), indent=1)
    print("wrote study_results/v16b_walkforward.csv / .json")


if __name__ == "__main__":
    main()
