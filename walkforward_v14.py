#!/usr/bin/env python3
"""v14 step 4a - walk-forward + half-split robustness of the martingale variants, from the per-run trade lists in
study_results/v14_levers/ (no simulation).  Writes study_results/v14_walkforward.csv and v14_halves.csv.
    python walkforward_v14.py
Question answered: had the sizing rule been chosen on the FIRST half only (Sep 2025 - Feb 2026) with the v14 criteria
(reduce the $ lost, hold the loss band, keep the PF), how did that choice do on the SECOND half (Mar - Sep 2026)?
The split is on the CLOSE time of the trades; dollar figures in each half are the actual compounding dollars of the run.
"""
import glob
import json
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

SR = Path("study_results")
RUNS = SR / "v14_levers"
OOS = pd.Timestamp("2026-03-01")
REF = "ref"


def half_metrics(tr: pd.DataFrame, prefix: str) -> dict:
    n = len(tr)
    if n == 0:
        return {f"{prefix}_n": 0}
    net = tr.net
    losses = net[net < 0]
    wins = net[net > 0]
    cum = net.cumsum()
    dd = (cum - cum.cummax()).min()
    daily = tr.groupby(pd.to_datetime(tr.close_time).dt.date).net.sum()
    return {f"{prefix}_n": n,
            f"{prefix}_net_$": round(net.sum(), 0),
            f"{prefix}_R": round(tr.r_net.sum(), 2),
            f"{prefix}_PF": round(wins.sum() / -losses.sum(), 3) if len(losses) else float("inf"),
            f"{prefix}_win_%": round(100 * (net > 0).mean(), 1),
            f"{prefix}_lost_$": round(losses.sum(), 0),
            f"{prefix}_avg_loss_$": round(losses.mean(), 1) if len(losses) else 0.0,
            f"{prefix}_worst_trade_$": round(net.min(), 0),
            f"{prefix}_worst_day_$": round(daily.min(), 0),
            f"{prefix}_dd_$": round(dd, 0),
            f"{prefix}_up": int((tr.mart_scale > 1.0).sum()) if "mart_scale" in tr else 0,
            f"{prefix}_dn": int((tr.mart_scale < 1.0).sum()) if "mart_scale" in tr else 0}


def main():
    rows = []
    for f in sorted(glob.glob(str(RUNS / "*.json"))):
        if "__" in Path(f).name:
            continue  # stress runs
        j = json.load(open(f))
        tf = RUNS / (Path(f).stem + "_trades.csv")
        if not tf.exists():
            continue
        tr = pd.read_csv(tf, parse_dates=["close_time"])
        eq = pd.read_csv(RUNS / (Path(f).stem + "_equity.csv"), parse_dates=["time"])
        eq_oos = float(eq[eq.time >= OOS].balance.iloc[0]) if (eq.time >= OOS).any() else float("nan")
        tr = tr[~tr.get("grid_leg", pd.Series(False, index=tr.index)).astype(bool)] if "grid_leg" in tr else tr
        is_, oos = tr[tr.close_time < OOS], tr[tr.close_time >= OOS]
        r = {"name": j["name"], "trades": j["trades"], "return_%": j["return_%"], "max_dd_%": j["max_dd_%"],
             "profit_factor": j["profit_factor"], "gross_loss_$": j["gross_loss_$"], "OOS_PF": j["OOS_PF"], "months_pos": j["months_pos"]}
        r.update(half_metrics(is_, "IS"))
        r.update(half_metrics(oos, "OOS"))
        r["OOS_start_eq"] = round(eq_oos, 0)
        r["IS_lost_%eq"] = round(100 * r["IS_lost_$"] / 10000.0, 2)          # $ lost in the half / equity at the start of the half
        r["OOS_lost_%eq"] = round(100 * r["OOS_lost_$"] / eq_oos, 2)
        r["IS_dd_%eq"] = round(100 * r["IS_dd_$"] / 10000.0, 2)
        r["OOS_dd_%eq"] = round(100 * r["OOS_dd_$"] / eq_oos, 2)
        r["OOS_net_%eq"] = round(100 * r["OOS_net_$"] / eq_oos, 1)
        rows.append(r)
    df = pd.DataFrame(rows)
    ref = df[df.name == REF].iloc[0]
    # the v14 criteria, applied to the IS half only (what a user could have seen in Feb 2026)
    df["IS_reduce_loss"] = (df["IS_lost_$"] > ref["IS_lost_$"]) & (df["IS_avg_loss_$"] > ref["IS_avg_loss_$"])
    df["IS_hold_loss"] = (df["IS_dd_$"] >= ref["IS_dd_$"] * 1.1) & (df["IS_worst_day_$"] >= ref["IS_worst_day_$"] * 1.25)
    df["IS_keep_pf"] = df.IS_PF >= ref.IS_PF - 0.05
    df["IS_keep_net"] = df["IS_net_$"] >= ref["IS_net_$"] * 0.95
    df["IS_score"] = df.IS_reduce_loss.astype(int) + df.IS_hold_loss.astype(int) + df.IS_keep_pf.astype(int) + df.IS_keep_net.astype(int)
    # ... and how those choices did OOS
    df["OOS_reduce_loss"] = (df["OOS_lost_$"] > ref["OOS_lost_$"]) & (df["OOS_avg_loss_$"] > ref["OOS_avg_loss_$"])
    df["OOS_hold_loss"] = (df["OOS_dd_$"] >= ref["OOS_dd_$"] * 1.1) & (df["OOS_worst_day_$"] >= ref["OOS_worst_day_$"] * 1.25)
    df["OOS_keep_pf"] = df.OOS_PF >= ref.OOS_PF - 0.05
    df["OOS_keep_net"] = df["OOS_net_$"] >= ref["OOS_net_$"] * 0.95
    df["OOS_score"] = df.OOS_reduce_loss.astype(int) + df.OOS_hold_loss.astype(int) + df.OOS_keep_pf.astype(int) + df.OOS_keep_net.astype(int)
    df["d_IS_lost_%"] = (100 * (df["IS_lost_$"] / ref["IS_lost_$"] - 1)).round(1)
    df["d_OOS_lost_%"] = (100 * (df["OOS_lost_$"] / ref["OOS_lost_$"] - 1)).round(1)
    # compounding-free view: $ lost in the half relative to the equity at the start of that half
    df["d_OOS_lost_eq_%"] = (100 * (df["OOS_lost_%eq"] / ref["OOS_lost_%eq"] - 1)).round(1)
    df["d_IS_PF"] = (df.IS_PF - ref.IS_PF).round(3)
    df["d_OOS_PF"] = (df.OOS_PF - ref.OOS_PF).round(3)
    df = df.sort_values(["IS_score", "IS_PF"], ascending=False)
    df.to_csv(SR / "v14_halves.csv", index=False)
    cols = ["name", "trades", "return_%", "max_dd_%", "profit_factor", "IS_n", "IS_PF", "IS_lost_$", "d_IS_lost_%", "IS_dd_$", "IS_score",
            "OOS_n", "OOS_PF", "OOS_lost_$", "d_OOS_lost_%", "OOS_lost_%eq", "d_OOS_lost_eq_%", "OOS_dd_%eq", "OOS_net_%eq", "OOS_score", "months_pos"]
    wf = df[df.IS_score >= 3][cols]
    wf.to_csv(SR / "v14_walkforward.csv", index=False)
    pd.set_option("display.width", 320)
    nz = df[df.name != REF]
    sp_pf, p_pf = spearmanr(nz.IS_PF, nz.OOS_PF)
    sp_loss, p_loss = spearmanr(nz["d_IS_lost_%"], nz["d_OOS_lost_%"])
    sp_dd, p_dd = spearmanr(nz["IS_dd_$"], nz["OOS_dd_$"])
    print(f"{len(df)} variants | ref IS PF {ref.IS_PF:.3f} lost {ref['IS_lost_$']:,.0f} $ dd {ref['IS_dd_$']:,.0f} $ | ref OOS PF {ref.OOS_PF:.3f} "
          f"lost {ref['OOS_lost_$']:,.0f} $ dd {ref['OOS_dd_$']:,.0f} $")
    print(f"Spearman IS->OOS: PF {sp_pf:+.2f} (p {p_pf:.2g}) | d$lost {sp_loss:+.2f} (p {p_loss:.2g}) | DD$ {sp_dd:+.2f} (p {p_dd:.2g})")
    print(f"IS score >= 3: {len(wf)} variants; of those OOS score >= 3: {int((wf.OOS_score >= 3).sum())}, OOS lost less than ref ($): "
          f"{int((wf['d_OOS_lost_%'] < 0).sum())}, OOS lost less than ref (% of OOS-start equity): {int((wf['d_OOS_lost_eq_%'] < 0).sum())}, "
          f"OOS PF >= ref: {int((df.loc[wf.index, 'd_OOS_PF'] >= 0).sum())}")
    print(wf.head(20).to_string(index=False))
    fin = ["TF_1.5_c3_htfbuy_dn0.5", "MU_1.25_c3_r3_htf_dn0.5", "FIB_c3_r3_htfbuy_dn0.5", "MU_1.0_c3_r3_htf_dn0.5", "GR_0.5_0.6/0.4_own",
           "MU_1.5_c3_r3_htfbuy_dn0.5"]
    print("\nfinalists:")
    print(df[df.name.isin(fin + [REF])][cols].to_string(index=False))


if __name__ == "__main__":
    main()
