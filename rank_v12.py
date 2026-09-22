#!/usr/bin/env python3
"""v12: rank every finished variant (singles + combos) against the v11-B reference.  -> study_results/v12_rank.csv + stdout.
    python rank_v12.py [--dd 0.5]   (allowed extra drawdown in pt; default the v11 band 0.5)
"""
import argparse
import glob
import json

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--dd", type=float, default=0.5)
ap.add_argument("--top", type=int, default=30)
a = ap.parse_args()
pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 300)
rows = [json.load(open(f)) for f in glob.glob("study_results/v12_levers/*.json") if "__" not in f]
df = pd.DataFrame(rows)
ref = df[df.name == "ref"].iloc[0]
# full-year band (v11 definition) and the OOS band (what we trust)
df["hold_loss"] = (df["max_dd_%"] >= ref["max_dd_%"] - a.dd) & (df.profit_factor >= ref.profit_factor - 0.05) & \
                  (df["win_%"] >= ref["win_%"] - 3.0) & (df["worst_day_%"] >= ref["worst_day_%"] - 0.5)
df["hold_oos"] = (df.OOS_PF >= ref.OOS_PF - 0.05) & (df["OOS_win_%"] >= ref["OOS_win_%"] - 3) & \
                 (df["OOS_sl_%"] <= ref["OOS_sl_%"] + 2) & (df["max_dd_%"] >= ref["max_dd_%"] - a.dd)
df["d_trades"] = df.trades - ref.trades
df["ret_dd"] = (df["return_%"] / df["max_dd_%"].abs()).round(2)
df = df.sort_values("trades", ascending=False)
cols = ["name", "trades", "d_trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "IS_R", "OOS_R", "OOS_PF",
        "OOS_win_%", "OOS_sl_%", "months_pos", "hold_loss", "hold_oos"]
df[cols + ["filter", "overrides"]].to_csv("study_results/v12_rank.csv", index=False)
print(f"{len(df)} variants finished.  ref: {ref.trades} tr, {ref['return_%']:+.1f}%, DD {ref['max_dd_%']}, PF {ref.profit_factor}, "
      f"win {ref['win_%']}, OOS PF {ref.OOS_PF}, OOS win {ref['OOS_win_%']}, OOS sl {ref['OOS_sl_%']}")
print(f"\n=== hold BOTH bands (DD tolerance {a.dd} pt), by trades ===")
print(df[df.hold_loss & df.hold_oos][cols].head(a.top).to_string(index=False))
print(f"\n=== hold the OOS band only, by trades ===")
print(df[df.hold_oos & ~df.hold_loss][cols].head(a.top).to_string(index=False))
print(f"\n=== most trades overall (any loss profile) ===")
print(df[cols].head(12).to_string(index=False))
