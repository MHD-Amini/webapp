#!/usr/bin/env python3
"""v6 pilot: on the M15 v6 training set, do the level-memory features add signal?
Same rows, same learner (LightGBM, POI weights, early stopping on val), feature sets
v5 vs v6 vs v6-without-creation vs level features only.  Plus univariate quintiles."""
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V5, NUMERIC_V6_CREATION, NUMERIC_V6_CONTEXT, QualityScorer
from lubot.trainset import load_training
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
meta, fx = load_training("models/v6/train_M15.pkl")
print("rows", len(meta), "features", fx.shape[1], meta.sel_time.min(), "->", meta.sel_time.max())
tr = (meta.sel_time < "2025-12-01").to_numpy(); va = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy(); te = (meta.sel_time >= "2026-03-01").to_numpy()
y = meta.ge1.to_numpy().astype(int); kinds = list(meta.kind)
key = (meta.tf + "_" + meta.id.astype(str)); w = (1.0 / key.map(key.value_counts())).to_numpy()
new = [f for f in NUMERIC_V6_CREATION + NUMERIC_V6_CONTEXT if f in fx.columns]
print("v6 features present:", len(new))
# univariate
rows = []
m = va | te
for f in new:
    v = fx.loc[m, f].to_numpy(dtype=float)
    if len(np.unique(v)) < 3: 
        rows.append({"feature": f, "auc_alone": round(max(roc_auc_score(y[m], v), 1 - roc_auc_score(y[m], v)), 3), "q": "binary", "rate1": round(y[m][v > 0].mean(), 3) if (v > 0).any() else np.nan, "rate0": round(y[m][v <= 0].mean(), 3)})
        continue
    q = pd.qcut(v, 5, labels=False, duplicates="drop"); g = pd.Series(y[m]).groupby(q).mean()
    a = roc_auc_score(y[m], v)
    rows.append({"feature": f, "auc_alone": round(max(a, 1 - a), 3), "q": " ".join(f"{x:.3f}" for x in g.values), "spread": round(g.max() - g.min(), 3)})
uni = pd.DataFrame(rows).sort_values("auc_alone", ascending=False); print(uni.to_string(index=False))
uni.to_csv("study_results/quality_v6_pilot_univariate.csv", index=False)
P = dict(objective="binary", metric="auc", verbose=-1, num_threads=2, seed=7, bagging_freq=1, num_leaves=15, max_depth=4, learning_rate=0.02, min_data_in_leaf=150, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0)
sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
SETS = {"v5": FEATURE_ORDER_V5, "v6": FEATURE_ORDER, "v6_no_creation": [f for f in FEATURE_ORDER if f not in NUMERIC_V6_CREATION],
        "levels_only(+dist,zone,tf)": ["distance_atr", "zone_atr", "tf_minutes", "is_bull"] + new + sess}
res = []
for name, feats in SETS.items():
    X = QualityScorer(features=list(feats)).matrix_from_frame(fx, kinds).astype(np.float32)
    aucs_va, aucs_te, its = [], [], []
    for seed in range(3):
        p = dict(P, seed=seed, bagging_seed=seed, feature_fraction_seed=seed)
        b = lgb.train(p, lgb.Dataset(X[tr], y[tr], weight=w[tr]), 3000, valid_sets=[lgb.Dataset(X[va], y[va], weight=w[va])], callbacks=[lgb.early_stopping(150, verbose=False)])
        aucs_va.append(roc_auc_score(y[va], b.predict(X[va]), sample_weight=w[va])); aucs_te.append(roc_auc_score(y[te], b.predict(X[te]), sample_weight=w[te])); its.append(b.best_iteration)
    r = {"set": name, "n_feat": len(feats), "val_auc_w": round(np.mean(aucs_va), 4), "val_sd": round(np.std(aucs_va), 4), "test_auc_w": round(np.mean(aucs_te), 4), "iters": int(np.mean(its))}
    print(r, flush=True); res.append(r)
pd.DataFrame(res).to_csv("study_results/quality_v6_pilot_sets.csv", index=False)
