#!/usr/bin/env python3
"""v4 follow-up: which price-action group helps (creation vs approach), and where (by distance).
train < 2025-12-01 · validate Dec-25..Feb-26 · test >= Mar-26.  Writes study_results/quality_v4_model_grid_b.csv"""
import time
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from lubot.quality import (FEATURE_ORDER, FEATURE_ORDER_V3, NUMERIC_V4_CREATION, NUMERIC_V4_CONTEXT, QualityScorer,
                           bagged_train, feature_importance)
from lubot.trainset import load_training
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)

meta, fx = load_training()
tr_m = (meta.sel_time < "2025-12-01").to_numpy()
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te_m = (meta.sel_time >= "2026-03-01").to_numpy()
kinds = meta.kind.to_numpy(); y = meta.ge1.to_numpy().astype(int); dist = fx["distance_atr"].to_numpy(dtype=float)
P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)

def ev(s, X, m, penalty=0.02):
    p = s.score_many(list(kinds[m]), X[m])
    d = meta.loc[m, ["tf", "sel_i", "side", "ge1", "bounce_atr"]].copy(); d["p"] = p; d["key"] = -p + penalty * dist[m]
    best = d.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1); k = best[best.p >= 0.5]
    return dict(auc=round(roc_auc_score(y[m], p), 4), best=round(best.ge1.mean(), 3), p50=round(k.ge1.mean(), 3), kept=round(len(k)/len(best), 2))

def auc_by_dist(s, X, m):
    p = s.score_many(list(kinds[m]), X[m]); d = dist[m]; yy = y[m]
    out = {}
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 9)):
        mm = (d >= lo) & (d < hi)
        out[f"auc_d{lo}-{hi}"] = round(roc_auc_score(yy[mm], p[mm]), 3) if mm.sum() > 100 and len(set(yy[mm])) == 2 else np.nan
    return out

sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
v3num = [f for f in FEATURE_ORDER_V3 if f not in sess]
GRID = {
    "v3": FEATURE_ORDER_V3,
    "v3+creationPA": v3num + NUMERIC_V4_CREATION + sess,
    "v3+approachPA": v3num + NUMERIC_V4_CONTEXT + sess,
    "v4": FEATURE_ORDER,
}
rows = []; models = {}
for name, feats in GRID.items():
    t0 = time.time(); sc = QualityScorer(features=list(feats)); X = sc.matrix_from_frame(fx, list(kinds))
    s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=5, gbm_params=P, scorer=sc)
    r = {"setting": name, "n_features": len(feats)}
    r.update({f"val_{k}": v for k, v in ev(s, X, va_m).items()}); r.update({f"test_{k}": v for k, v in ev(s, X, te_m).items()})
    r.update({f"val_{k}": v for k, v in auc_by_dist(s, X, va_m).items()}); r.update({f"test_{k}": v for k, v in auc_by_dist(s, X, te_m).items()})
    r["sec"] = round(time.time() - t0); rows.append(r); print(r, flush=True)
    if name == "v4":
        idx = np.flatnonzero(va_m | te_m); idx = np.random.default_rng(0).choice(idx, 10000, replace=False)
        imp = feature_importance(s, X[idx], [kinds[j] for j in idx], y[idx], n_repeats=2)
        pa = [(n, round(v, 4)) for n, v in imp if n in NUMERIC_V4_CREATION or n in NUMERIC_V4_CONTEXT]
        print("\nprice-action feature importance (val+test, AUC drop):"); [print(f"  {n:<24}{v:+.4f}") for n, v in pa]
        print("\ntop-15 overall:"); [print(f"  {n:<24}{v:+.4f}") for n, v in imp[:15]]
        pd.DataFrame(imp, columns=["feature", "auc_drop"]).to_csv("study_results/quality_v4_importance_valtest.csv", index=False)
    del X, s
out = pd.DataFrame(rows); out.to_csv("study_results/quality_v4_model_grid_b.csv", index=False); print(out.to_string(index=False))
