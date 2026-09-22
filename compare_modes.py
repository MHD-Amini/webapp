#!/usr/bin/env python3
"""Out-of-sample comparison: bot in 'closest' mode vs 'quality' mode (train-only model)."""
import argparse, pickle
import numpy as np, pandas as pd
from lubot import StrategyConfig, load_mt5_csv
from lubot.study import run_study
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)

ap = argparse.ArgumentParser()
ap.add_argument("--csv", required=True)
ap.add_argument("--from", dest="start", default="2026-02-01")
ap.add_argument("--oos", default="2026-04-01")
ap.add_argument("--model", default="models/quality_model_trainonly.json")
ap.add_argument("--model-v1", default=None, help="optional legacy model to run as a third mode 'quality_v1'")
ap.add_argument("--model-v2", default=None, help="optional previous model to run as mode 'quality_v2'")
ap.add_argument("--model-v3", default=None, help="optional previous model to run as mode 'quality_v3'")
ap.add_argument("--approach-model", default="", help="v4 stage-2 model for the 'quality' mode ('' = single stage)")
ap.add_argument("--min-quality", type=float, default=0.50)
ap.add_argument("--min-quality-v1", type=float, default=0.50)
ap.add_argument("--timeframes", default=None)
ap.add_argument("--out", default="study_results/compare")
ap.add_argument("--only", default=None, help="run only this mode (closest|quality|quality_v1) and exit; results are cached as pkl")
ap.add_argument("--summary-only", action="store_true", help="skip running; summarise the cached pkl files")
a = ap.parse_args()

m1 = load_mt5_csv(a.csv)[a.start:]
ohlc = m1[["open", "high", "low", "close", "volume"]]; spread = m1["spread"]
tfs = tuple(a.timeframes.split(",")) if a.timeframes else StrategyConfig().timeframes
modes = {"closest": dict(selection_mode="closest"),
         "quality": dict(selection_mode="quality", quality_model_path=a.model, min_quality=a.min_quality,
                         approach_model_path=a.approach_model)}
if a.model_v1:
    modes["quality_v1"] = dict(selection_mode="quality", quality_model_path=a.model_v1, min_quality=a.min_quality_v1, approach_model_path="")
if a.model_v2:
    modes["quality_v2"] = dict(selection_mode="quality", quality_model_path=a.model_v2, min_quality=a.min_quality, approach_model_path="")
if a.model_v3:
    modes["quality_v3"] = dict(selection_mode="quality", quality_model_path=a.model_v3, min_quality=a.min_quality, approach_model_path="")
import os
results = {}
for mode, kw in modes.items():
    if a.only and mode != a.only:
        continue
    cache = f"{a.out}_{mode}.pkl"
    if os.path.exists(cache) or a.summary_only:
        if os.path.exists(cache):
            results[mode] = pd.read_pickle(cache); print(f"[{mode}] cached {len(results[mode])}", flush=True)
        continue
    cfg = StrategyConfig(timeframes=tfs, **kw)
    res = run_study(ohlc, spread, cfg, progress=False)
    df = res["df"]; df = df[pd.to_datetime(df.selected_time) >= pd.Timestamp(a.oos)]
    results[mode] = df
    df.to_pickle(cache)
    print(f"[{mode}] selected {len(df)}", flush=True)
if a.only:
    raise SystemExit(0)

def summarize(df):
    r = df[df.reached]
    days = pd.to_datetime(df.selected_time).dt.date.nunique()
    out = {"selected": len(df), "per_day": round(len(df)/days, 1), "reached_%": round(100*len(r)/len(df), 1),
           "median_bounce_atr": round(r.bounce_atr.median(), 2), "mean_bounce_atr": round(r.bounce_atr.mean(), 2),
           "ge1ATR_%": round(100*r.ge_1ATR.mean(), 1), "ge2ATR_%": round(100*r.ge_2ATR.mean(), 1),
           "hit_0.3R_%": round(100*r["r_0.3R"].mean(), 1), "hit_0.4R_%": round(100*r["r_0.4R"].mean(), 1),
           "hit_0.5R_%": round(100*r["r_0.5R"].mean(), 1),
           "hit_1R_%": round(100*r.r_1R.mean(), 1), "hit_2R_%": round(100*r.r_2R.mean(), 1),
           "net_R_TP1": round(r.net_r_1.mean(), 3), "net_R_TP2": round(r.net_r_2.mean(), 3),
           "sc_mid_sl0.5_tp1": round(r["sc_mid_sl0.5_tp1"].mean(), 3), "sc_edge_sl0.5_tp2": round(r["sc_edge_sl0.5_tp2"].mean(), 3)}
    return out

rows = []
for mode, df in results.items():
    rows.append({"mode": mode, "tf": "ALL", **summarize(df)})
    for tf, g in df.groupby("tf"):
        rows.append({"mode": mode, "tf": tf, **summarize(g)})
tab = pd.DataFrame(rows).sort_values(["tf", "mode"])
print(tab.to_string(index=False))
# month-by-month (bounce >= 1 ATR) per mode
mon = pd.concat([pd.DataFrame({"mode": mode, "month": pd.to_datetime(df.selected_time).dt.strftime("%Y-%m"),
                               "ge1": df.ge_1ATR.where(df.reached)}) for mode, df in results.items()])
mon_tab = mon.dropna().groupby(["month", "mode"]).ge1.agg(["mean", "size"]).unstack("mode")
print("\n=== bounce >= 1 ATR by month ===\n" + (mon_tab["mean"] * 100).round(1).to_string())
mon_tab.to_csv(f"{a.out}_by_month.csv")
tab.to_csv(f"{a.out}_summary.csv", index=False)
q = results["quality"]; q = q[q.reached]
from lubot.study import aggregate_scenarios, SCENARIOS
def scen_table(df, label):
    t = aggregate_scenarios(df)
    t.insert(0, "mode", label)
    return t
sc = pd.concat([scen_table(df, mode) for mode, df in results.items()])
sc = sc[sc.tp_R <= 1.0].sort_values(["tp_R", "entry", "sl_buffer_atr", "mode"])
print("\n=== SCENARIOS (net of spread, OOS) - small targets vs 1R ===")
print(sc[["mode","scenario","entry","sl_buffer_atr","tp_R","filled","win_%","avg_net_R","total_net_R","profit_factor","max_dd_R"]].to_string(index=False))
sc.to_csv(f"{a.out}_scenarios.csv", index=False)
for mode in results:
    t = aggregate_scenarios(results[mode], ["tf"]); t = t[t.tp_R <= 0.5]
    t.to_csv(f"{a.out}_scenarios_by_tf_{mode}.csv", index=False)
print("\nquality mode - by POI type:"); print(q.groupby("kind").agg(n=("ge_1ATR","size"), ge1=("ge_1ATR","mean"), bounce=("bounce_atr","median")).round(3).to_string())
print("\nquality mode - calibration (predicted vs actual):")
q2 = q.assign(b=pd.cut(q.quality, [0,0.45,0.5,0.55,0.6,0.7,1.0]))
print(q2.groupby("b", observed=True).agg(n=("ge_1ATR","size"), pred=("quality","mean"), actual=("ge_1ATR","mean"), bounce=("bounce_atr","median")).round(3).to_string())
