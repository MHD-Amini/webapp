#!/usr/bin/env python3
"""Rolling-origin comparison of feature sets (more robust than one split).

For every test month m in Dec-2025 .. Sep-2026: train on all candidates selected before m,
score the candidates of month m.  Reports per-month AUC and the hit-rate of the best-ranked
candidate per (tf, bar, side) slot with P >= 0.5, averaged over months, for
  v3 (97 features) · v3+approachPA · v3+geometry · v4 (125).

    python experiments_v4d.py    ->  study_results/quality_v4_rolling.csv
"""
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V3, NUMERIC_V4_CONTEXT, NUMERIC_V4_CREATION, QualityScorer, bagged_train
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

meta, fx = load_training()
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)
month = meta.sel_time.dt.to_period("M")
months = [m for m in sorted(month.unique()) if str(m) >= "2025-12"]
P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)

sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
v3num = [f for f in FEATURE_ORDER_V3 if f not in sess]
AP = [f for f in NUMERIC_V4_CONTEXT if f.startswith("ap_")]
GEO = ["edge_to_key_atr", "zone_vs_bar_range"]
SETS = {
    "v3": FEATURE_ORDER_V3,
    "v3+geo": v3num + GEO + sess,
    "v3+approachPA+geo": v3num + AP + GEO + sess,
    "v4": FEATURE_ORDER,
}
rows = []
for name, feats in SETS.items():
    sc = QualityScorer(features=list(feats))
    X = sc.matrix_from_frame(fx, list(kinds))
    for m in months:
        t0 = time.time()
        tr_m = (month < m).to_numpy()
        te_m = (month == m).to_numpy()
        if te_m.sum() < 200:
            continue
        s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=3, gbm_params=P, scorer=QualityScorer(features=list(feats)))
        p = s.score_many(list(kinds[te_m]), X[te_m])
        d = meta.loc[te_m, ["tf", "sel_i", "side", "ge1", "bounce_atr"]].copy()
        d["p"] = p
        d["key"] = -p + 0.02 * dist[te_m]
        best = d.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
        k, k6 = best[best.p >= 0.5], best[best.p >= 0.6]
        r = {"setting": name, "month": str(m), "n": int(te_m.sum()), "auc": round(roc_auc_score(y[te_m], p), 4),
             "best": round(best.ge1.mean(), 3), "p50": round(k.ge1.mean(), 3) if len(k) else np.nan,
             "kept": round(len(k) / len(best), 3), "n50": len(k),
             "p60": round(k6.ge1.mean(), 3) if len(k6) else np.nan, "kept60": round(len(k6) / len(best), 3),
             "bounce50": round(k.bounce_atr.median(), 2) if len(k) else np.nan, "sec": round(time.time() - t0)}
        rows.append(r)
        print(r, flush=True)
        del s
    del X
out = pd.DataFrame(rows)
out.to_csv("study_results/quality_v4_rolling.csv", index=False)
print("\n=== per month (p50 hit-rate) ===")
print(out.pivot(index="month", columns="setting", values="p50").round(3).to_string())
print("\n=== per month (AUC) ===")
print(out.pivot(index="month", columns="setting", values="auc").round(3).to_string())
agg = out.groupby("setting").apply(lambda g: pd.Series({
    "auc_mean": g.auc.mean(), "best_mean": g.best.mean(),
    "p50_pooled": np.nansum(g.p50 * g.n50) / g.n50.sum(), "kept_mean": g.kept.mean(),
    "p60_mean": g.p60.mean(), "kept60_mean": g.kept60.mean(),
    "months_beat_v3_auc": np.nan}), include_groups=False)
v3 = out[out.setting == "v3"].set_index("month")
for name in SETS:
    o = out[out.setting == name].set_index("month")
    agg.loc[name, "months_beat_v3_auc"] = int((o.auc > v3.auc.reindex(o.index)).sum())
    agg.loc[name, "months_beat_v3_p50"] = int((o.p50 > v3.p50.reindex(o.index)).sum())
print("\n=== averaged over months ===")
print(agg.round(4).to_string())
agg.to_csv("study_results/quality_v4_rolling_summary.csv")
