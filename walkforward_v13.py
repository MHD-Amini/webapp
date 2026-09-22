#!/usr/bin/env python3
"""v13 step 4 - walk-forward + robustness summary from the per-run jsons in study_results/v13_levers/ (no simulation).
Writes study_results/v13_levers.csv (ALL variants incl. the session-2 neighbourhood), v13_walkforward.csv, v13_neighbourhood.csv.
    python walkforward_v13.py"""
import json, glob
import pandas as pd
from scipy.stats import spearmanr
from run_v13_levers import summarize

rows = [json.load(open(f)) for f in glob.glob("study_results/v13_levers/*.json") if "__" not in f.split("/")[-1]]
df = summarize(rows, path="study_results/v13_levers.csv")
ref = df[df.name == "ref"].iloc[0]
df["IS_rank"] = df.IS_R.rank(ascending=False).astype(int)
df["OOS_rank"] = df.OOS_R.rank(ascending=False).astype(int)
df["IS_PF_rank"] = df.IS_PF.rank(ascending=False).astype(int)
df["OOS_PF_rank"] = df.OOS_PF.rank(ascending=False).astype(int)
# walk-forward: what would a user have picked on the IS half alone (Sep25-Feb26) and how did it do OOS (Mar-Sep26)?
is_hold = (df.IS_PF >= ref.IS_PF - 0.05) & (df["max_dd_%"] >= ref["max_dd_%"] - 0.5)
wf = df[is_hold].sort_values("IS_R", ascending=False)
cols = ["name", "trades", "return_%", "max_dd_%", "profit_factor", "IS_R", "IS_PF", "OOS_R", "OOS_PF", "IS_rank", "OOS_rank", "apr26_R",
        "worst_month_R", "months_pos", "hold_loss", "hold_oos", "fix_weak"]
wf[cols].to_csv("study_results/v13_walkforward.csv", index=False)
sp_r, p_r = spearmanr(df.IS_R, df.OOS_R)
sp_pf, p_pf = spearmanr(df.IS_PF, df.OOS_PF)
sp_apr, p_apr = spearmanr(df.apr26_R, df.other_R)
rg = df[df.name.str.startswith("RG_")]
sp_rg, p_rg = spearmanr(rg.IS_R, rg.OOS_R)
print(f"{len(df)} variants | Spearman IS_R/OOS_R {sp_r:+.2f} (p {p_r:.3g}) | IS_PF/OOS_PF {sp_pf:+.2f} (p {p_pf:.3g}) | RG only {sp_rg:+.2f} (p {p_rg:.3g}) | Apr R vs other months {sp_apr:+.2f} (p {p_apr:.2g})")
print(f"IS-hold + top-12 by IS_R: OOS PF median {wf.OOS_PF.head(12).median():.3f} (ref {ref.OOS_PF:.3f}), fix_weak {int(wf.fix_weak.head(12).sum())}/12")
pd.set_option("display.width", 300)
print(wf[cols].head(12).to_string(index=False))
# neighbourhood of v13-A
nb = df[df.name.str.match(r"RG_adr(0\.8|0\.9|0\.95|1\.0|1\.05|1\.1)_tight(_l03|_be2|_l05|_l03_10|_l03_front|_l03_w\d+_\d+)?$|RG_adr1\.0_t2_l03|RG_adr0\.9_tight_w\d+_\d+")]
nb = nb.sort_values("name")
nb[["name", "trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "IS_R", "OOS_R", "OOS_PF", "apr26_R", "sep25_R", "worst_month_R",
    "months_pos", "d_other", "range_n", "range_R", "hold_loss", "hold_oos", "fix_weak"]].to_csv("study_results/v13_neighbourhood.csv", index=False)
print(f"\nneighbourhood of v13-A: {len(nb)} variants, April positive in {int((nb.apr26_R > 0).sum())}, 13/13 months in {int((nb.months_pos == 13).sum())}, "
      f"hold_loss {int(nb.hold_loss.sum())}, hold_oos {int(nb.hold_oos.sum())}, PF range {nb.profit_factor.min():.3f}-{nb.profit_factor.max():.3f} (ref {ref.profit_factor:.3f})")
print(nb[["name", "trades", "return_%", "max_dd_%", "profit_factor", "worst_day_%", "OOS_R", "OOS_PF", "apr26_R", "worst_month_R", "months_pos", "range_n", "range_R", "hold_loss", "hold_oos"]].to_string(index=False))
