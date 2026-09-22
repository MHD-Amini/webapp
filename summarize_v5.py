#!/usr/bin/env python3
"""Bot-level OOS summary (Mar 2 - Sep 4 2026): closest vs v3 vs v4 vs v5 (indicator features).
Reads the cached per-TF pickles and writes study_results/compare_v5_summary.csv / compare_v5_by_month.csv."""
import glob

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def load(pattern):
    fs = sorted(glob.glob(pattern))
    return pd.concat([pd.read_pickle(p) for p in fs], ignore_index=True) if fs else None


modes = {
    "closest": pd.read_pickle("study_results/compare_closest.pkl"),
    "quality_v2": pd.read_pickle("study_results/compare_quality_v2.pkl"),
    "quality_v3": pd.read_pickle("study_results/compare_quality.pkl"),
    "quality_v4": load("study_results/compare_v4single_*_quality.pkl"),
    "quality_v5": load("study_results/compare_v5parts_*_quality.pkl"),
    "quality_v5ens": load("study_results/compare_v5ens_*_quality.pkl"),
}
modes = {k: v for k, v in modes.items() if v is not None and len(v)}
tfs_v4 = set(modes["quality_v5"].tf.unique())
print("v5 timeframes available:", sorted(tfs_v4))


def summarize(df):
    r = df[df.reached]
    days = pd.to_datetime(df.selected_time).dt.date.nunique()
    out = {"selected": len(df), "per_day": round(len(df) / days, 1), "reached_%": round(100 * len(r) / len(df), 1),
           "median_bounce_atr": round(r.bounce_atr.median(), 2), "ge1ATR_%": round(100 * r.ge_1ATR.mean(), 1),
           "ge2ATR_%": round(100 * r.ge_2ATR.mean(), 1), "hit_0.3R_%": round(100 * r["r_0.3R"].mean(), 1),
           "hit_0.4R_%": round(100 * r["r_0.4R"].mean(), 1), "hit_1R_%": round(100 * r.r_1R.mean(), 1)}
    a = r[r.quality >= 0.65] if "quality" in r else r.iloc[0:0]
    out["A_n"] = len(a)
    out["A_ge1_%"] = round(100 * a.ge_1ATR.mean(), 1) if len(a) else np.nan
    b = r[r.quality >= 0.60] if "quality" in r else r.iloc[0:0]
    out["P60_n"] = len(b)
    out["P60_ge1_%"] = round(100 * b.ge_1ATR.mean(), 1) if len(b) else np.nan
    for sc in ("sc_edge_sl0.1_tp0.3", "sc_mid_sl0.5_tp0.4", "sc_edge_sl0.5_tp0.5"):
        if sc in r:
            v = r[sc].dropna()
            out[sc + "_avgR"] = round(v.mean(), 3)
            out[sc + "_PF"] = round(v[v > 0].sum() / max(-v[v < 0].sum(), 1e-9), 2)
    return out


rows = []
for mode, df in modes.items():
    df = df[df.tf.isin(tfs_v4)]
    rows.append({"mode": mode, "tf": "ALL", **summarize(df)})
    for tf, g in df.groupby("tf"):
        rows.append({"mode": mode, "tf": tf, **summarize(g)})
tab = pd.DataFrame(rows)
order = {"ALL": 0, "M5": 1, "M10": 2, "M15": 3, "M30": 4, "H1": 5}
tab["o"] = tab.tf.map(order)
tab = tab.sort_values(["o", "mode"]).drop(columns="o")
print(tab.to_string(index=False))
tab.to_csv("study_results/compare_v5_summary.csv", index=False)

mon = pd.concat([pd.DataFrame({"mode": mode, "month": pd.to_datetime(df.selected_time).dt.strftime("%Y-%m"),
                               "ge1": df.ge_1ATR.where(df.reached)}) for mode, df in modes.items() if True])
mon_tab = mon.dropna().groupby(["month", "mode"]).ge1.agg(["mean", "size"]).unstack("mode")
print("\n=== bounce >= 1 ATR by month (%) ===")
print((mon_tab["mean"] * 100).round(1).to_string())
print("\n=== n reached by month ===")
print(mon_tab["size"].to_string())
mon_tab.to_csv("study_results/compare_v5_by_month.csv")

# v5 vs v4 at matched thresholds
for mode in ("quality_v4", "quality_v5", "quality_v5ens"):
    if mode not in modes:
        continue
    v = modes[mode]
    r = v[v.reached]
    print(f"\n{mode} calibration (predicted vs actual):")
    q2 = r.assign(b=pd.cut(r.quality, [0, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0]))
    print(q2.groupby("b", observed=True).agg(n=("ge_1ATR", "size"), pred=("quality", "mean"), actual=("ge_1ATR", "mean"),
                                             bounce=("bounce_atr", "median")).round(3).to_string())
    print(f"{mode} threshold sweep (bot level):")
    for q in (0.50, 0.55, 0.60, 0.65, 0.70):
        k = v[v.quality >= q]
        kr = k[k.reached]
        if len(k):
            print(f"  min_quality {q:.2f}: selected {len(k):5d}  reached {100 * len(kr) / len(k):.1f}%  ge1 {100 * kr.ge_1ATR.mean():.1f}%  "
                  f"ge2 {100 * kr.ge_2ATR.mean():.1f}%  median {kr.bounce_atr.median():.2f} ATR")
    print(f"{mode} by POI type:")
    print(r.groupby("kind").agg(n=("ge_1ATR", "size"), ge1=("ge_1ATR", "mean"), bounce=("bounce_atr", "median")).round(3).T.to_string())
