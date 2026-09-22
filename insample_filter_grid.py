#!/usr/bin/env python3
"""v8 step 6 - IN-SAMPLE evaluation of the filter grid on the bot-like plan labels (Jan 2025 - Feb 2026).
Same rules as run_filter_study.grid(), applied to the rows the v7 scanner would show (best of slot, q>=0.50),
outcome = the plan replayed on M1 (models/plan_labels_M5.pkl).  This is what the rule choice is based on;
the OOS portfolio numbers only verify it.  -> study_results/filter_grid_insample_labels.csv"""
import numpy as np, pandas as pd
from experiments_m5_filter import load, bot_score
from run_filter_study import grid
from lubot.trade_filter import TradeFilter

d = load("M5"); d["q"] = bot_score(d, "models/quality_model_trainonly.json")
d["w"] = 1.0 / d.poi_key.map(d.poi_key.value_counts())
ins = d[d.sel_time < "2026-03-01"].copy()
ins["slot"] = ins.sel_i.astype(str) + "_" + ins.side
ins["key"] = -ins.q + 0.02 * ins["f__distance_atr"]
bot = ins.sort_values("key").groupby("slot").head(1)
bot = bot[bot.q >= 0.50].copy()
bot["feats"] = [dict() for _ in range(len(bot))]
print(f"bot-like in-sample rows {len(bot)} ({bot.poi_key.nunique()} POIs)  avg R {bot.pl_r_net.mean():+.3f}")
rows = []
for name, flt in grid().items():
    if "model_path" in flt:
        continue
    f = TradeFilter.parse(flt)
    keep = []
    for r in bot.itertuples():
        dd = {"top": r.top, "bottom": r.bottom, "quality": r.q, "type": r.kind, "direction": r.direction, "atr": r.atr_sel,
              "time": r.sel_time}
        keep.append(f.check(dd, "M5", spread=r.pl_spread_fill, when=r.sel_time) is None)
    k = bot[np.array(keep)]
    tr, va = k[k.sel_time < "2025-12-01"], k[k.sel_time >= "2025-12-01"]
    rows.append({"name": name, "filter": flt, "n": len(k), "keep_%": round(100 * len(k) / len(bot), 1),
                 "avg_r": round(k.pl_r_net.mean(), 4), "avg_r_w": round(np.average(k.pl_r_net, weights=k.w), 4) if len(k) else np.nan,
                 "total_r": round(k.pl_r_net.sum(), 1), "win_%": round(100 * k.pl_win.mean(), 1), "sl_%": round(100 * (k.pl_outcome == "sl").mean(), 1),
                 "train_avg_r": round(tr.pl_r_net.mean(), 4), "val_avg_r": round(va.pl_r_net.mean(), 4), "val_n": len(va),
                 "months_pos": int((k.groupby(k.sel_time.dt.to_period("M")).pl_r_net.sum() > 0).sum()),
                 "months": int(k.sel_time.dt.to_period("M").nunique())})
df = pd.DataFrame(rows).sort_values("avg_r", ascending=False)
df.to_csv("study_results/filter_grid_insample_labels.csv", index=False)
pd.set_option("display.width", 250)
print(df.to_string(index=False))
