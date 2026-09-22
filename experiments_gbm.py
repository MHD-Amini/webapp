#!/usr/bin/env python3
"""Hyper-parameter sanity check for the quality model: train < 2025-12, validate 2025-12..2026-02, test >= 2026-03.
Prints AUC and the hit-rate of the best-ranked candidate per slot (all / above 0.5) for a few GBM settings and the
v1 logistic family.  Used to pick the regularisation of models/quality_model.json."""
import glob, time
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from lubot.quality import train

df = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob("models/train_*.pkl"))], ignore_index=True)
df = df[df.reached == True].copy(); df["sel_time"] = pd.to_datetime(df.sel_time)
df["side"] = np.where(df.direction == "bullish", "below", "above")
tr = df[df.sel_time < "2025-12-01"]; va = df[(df.sel_time >= "2025-12-01") & (df.sel_time < "2026-03-01")]; te = df[df.sel_time >= "2026-03-01"]
print("train/val/test", len(tr), len(va), len(te), flush=True)

def ev(s, d):
    p = s.score_many(list(d.kind), list(d.features)); y = d.ge1.astype(int).to_numpy()
    dd = d.assign(p=p); best = dd.sort_values("p", ascending=False).groupby(["tf", "sel_i", "side"]).head(1)
    k = best[best.p >= 0.5]
    return round(roc_auc_score(y, p), 3), round(best.ge1.mean(), 3), round(k.ge1.mean(), 3), round(len(k) / len(best), 2)

GRID = {
    "gbm_default": None,   # = lubot.quality.GBM_DEFAULT
    "gbm_deep": dict(max_iter=300, learning_rate=0.04, max_depth=4, max_leaf_nodes=15, min_samples_leaf=60, l2_regularization=1.0, early_stopping=True, validation_fraction=0.15, n_iter_no_change=30),
    "gbm_reg_d3": dict(max_iter=200, learning_rate=0.03, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0, early_stopping=False),
    "gbm_reg_d2": dict(max_iter=150, learning_rate=0.05, max_depth=2, max_leaf_nodes=4, min_samples_leaf=300, l2_regularization=5.0, early_stopping=False),
    "gbm_slow_d4": dict(max_iter=400, learning_rate=0.01, max_depth=4, max_leaf_nodes=12, min_samples_leaf=400, l2_regularization=10.0, early_stopping=False),
    "gbm_tiny": dict(max_iter=80, learning_rate=0.05, max_depth=3, max_leaf_nodes=8, min_samples_leaf=500, l2_regularization=20.0, early_stopping=False),
}
rows = []
for per_kind in (False, True):
    for name, g in GRID.items():
        t = time.time()
        s = train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), model="gbm", gbm_params=g, per_kind=per_kind)
        a_tr = round(roc_auc_score(tr.ge1.astype(int), s.score_many(list(tr.kind), list(tr.features))), 3)
        r = {"model": name, "per_kind": per_kind, "train_auc": a_tr}
        for lab, d in (("val", va), ("test", te)):
            r[f"{lab}_auc"], r[f"{lab}_best"], r[f"{lab}_best>=.5"], r[f"{lab}_kept"] = ev(s, d)
        r["sec"] = round(time.time() - t)
        rows.append(r); print(r, flush=True)
    s = train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), model="logistic", per_kind=per_kind)
    r = {"model": "logistic", "per_kind": per_kind, "train_auc": round(roc_auc_score(tr.ge1.astype(int), s.score_many(list(tr.kind), list(tr.features))), 3)}
    for lab, d in (("val", va), ("test", te)):
        r[f"{lab}_auc"], r[f"{lab}_best"], r[f"{lab}_best>=.5"], r[f"{lab}_kept"] = ev(s, d)
    rows.append(r); print(r, flush=True)
out = pd.DataFrame(rows); print(out.to_string(index=False))
out.to_csv("study_results/quality_v2_model_grid.csv", index=False)
