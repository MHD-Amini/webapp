#!/usr/bin/env python3
"""Second round of v3 experiments: bagging, timeframe-balanced weights, per-type models."""
import glob, time
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score
from lubot.quality import QualityScorer, train, bagged_train

df = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob("models/train_*.pkl"))], ignore_index=True)
df = df[df.reached == True].copy(); df["sel_time"] = pd.to_datetime(df.sel_time)
df["side"] = np.where(df.direction == "bullish", "below", "above")
tr = df[df.sel_time < "2025-12-01"]; va = df[(df.sel_time >= "2025-12-01") & (df.sel_time < "2026-03-01")]; te = df[df.sel_time >= "2026-03-01"]
print("train/val/test", len(tr), len(va), len(te), flush=True)

def ev(s, d, penalty=0.02):
    p = s.score_many(list(d.kind), list(d.features)); y = d.ge1.astype(int).to_numpy()
    dd = d.assign(p=p); dd["key"] = -dd.p + penalty * dd.features.map(lambda f: float(f.get("distance_atr", 0.0)))
    best = dd.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1); k = best[best.p >= 0.5]
    per_tf = {tf: round(g[g.p >= 0.5].ge1.mean(), 3) for tf, g in best.groupby("tf")}
    return round(roc_auc_score(y, p), 4), round(best.ge1.mean(), 3), round(k.ge1.mean(), 3), round(len(k) / len(best), 2), per_tf

P3 = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)
P4 = dict(max_iter=600, learning_rate=0.015, max_depth=4, max_leaf_nodes=12, min_samples_leaf=400, l2_regularization=10.0)
tf_w = (1.0 / tr.tf.value_counts(normalize=True)).reindex(tr.tf).to_numpy(); tf_w = tf_w / tf_w.mean()
tf_w = np.sqrt(tf_w)   # soften: sqrt-balanced
EXP = {
    "d3_plain": lambda: train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), gbm_params=P3),
    "d3_tfw": lambda: train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), gbm_params=P3, sample_weight=tf_w),
    "d3_perkind": lambda: train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), gbm_params=P3, per_kind=True, min_rows=800),
    "d3_bag5": lambda: bagged_train(list(tr.features), tr.ge1.to_numpy(), list(tr.kind), n_models=5, gbm_params=P3),
    "d4_bag5": lambda: bagged_train(list(tr.features), tr.ge1.to_numpy(), list(tr.kind), n_models=5, gbm_params=P4),
    "d4_bag5_tfw": lambda: bagged_train(list(tr.features), tr.ge1.to_numpy(), list(tr.kind), n_models=5, gbm_params=P4, sample_weight=tf_w),
}
rows = []
for name, fn in EXP.items():
    t = time.time(); s = fn()
    r = {"model": name, "train_auc": round(roc_auc_score(tr.ge1.astype(int), s.score_many(list(tr.kind), list(tr.features))), 4)}
    for lab, d in (("val", va), ("test", te)):
        r[f"{lab}_auc"], r[f"{lab}_best"], r[f"{lab}_best>=.5"], r[f"{lab}_kept"], r[f"{lab}_per_tf"] = ev(s, d)
    r["sec"] = round(time.time() - t); rows.append(r); print(r, flush=True)
out = pd.DataFrame(rows); print(out.drop(columns=["val_per_tf", "test_per_tf"]).to_string(index=False))
out.to_csv("study_results/quality_v3_model_grid_b.csv", index=False)
