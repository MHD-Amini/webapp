#!/usr/bin/env python3
"""v4 model selection on a strict time split.

train < 2025-12-01 · validate 2025-12-01..2026-03-01 · test >= 2026-03-01

Compares the v3 feature set (97 columns) against the v4 set (125 columns = v3 + 28
price-action features of the base / impulse / approach) with the v3 production GBM
settings, bagged, plus regularisation variants.  Hyper-parameters are picked on the
validation window only; the test window is reported for information.

    python experiments_v4.py            # writes study_results/quality_v4_model_grid.csv
"""
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V3, QualityScorer, bagged_train, train
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

meta, fx = load_training()
tr_m = (meta.sel_time < "2025-12-01").to_numpy()
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te_m = (meta.sel_time >= "2026-03-01").to_numpy()
print("train/val/test", tr_m.sum(), va_m.sum(), te_m.sum(), flush=True)
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)


def ev(s: QualityScorer, X: np.ndarray, m: np.ndarray, penalty: float = 0.02):
    p = s.score_many(list(kinds[m]), X[m])
    d = meta.loc[m, ["tf", "sel_i", "side", "ge1", "bounce_atr"]].copy()
    d["p"] = p
    d["key"] = -p + penalty * dist[m]
    best = d.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
    k, k6 = best[best.p >= 0.5], best[best.p >= 0.6]
    return (round(roc_auc_score(y[m], p), 4), round(best.ge1.mean(), 3), round(k.ge1.mean(), 3),
            round(len(k) / len(best), 2), round(k.bounce_atr.median(), 2) if len(k) else np.nan,
            round(k6.ge1.mean(), 3) if len(k6) else np.nan, round(len(k6) / len(best), 2))


V3P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)
GRID = {
    "v3feat_bag5": (FEATURE_ORDER_V3, V3P, 5),
    "v4feat_bag5": (FEATURE_ORDER, V3P, 5),
    "v4feat_bag5_d4": (FEATURE_ORDER, dict(V3P, max_depth=4, max_leaf_nodes=12, min_samples_leaf=300, l2_regularization=10.0), 5),
    "v4feat_bag5_600": (FEATURE_ORDER, dict(V3P, max_iter=600, learning_rate=0.015), 5),
    "v4feat_single": (FEATURE_ORDER, V3P, 0),
}
rows = []
for name, (feats, params, bag) in GRID.items():
    t0 = time.time()
    sc = QualityScorer(features=list(feats))
    X = sc.matrix_from_frame(fx, list(kinds))
    if bag:
        s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=bag, gbm_params=params, scorer=sc)
    else:
        s = train(X[tr_m], y[tr_m], list(kinds[tr_m]), gbm_params=params, scorer=sc)
    r_tr, r_va, r_te = ev(s, X, tr_m), ev(s, X, va_m), ev(s, X, te_m)
    row = {"setting": name, "n_features": len(feats), "train_auc": r_tr[0],
           "val_auc": r_va[0], "val_best": r_va[1], "val_p50": r_va[2], "val_kept": r_va[3], "val_p60": r_va[5], "val_kept60": r_va[6],
           "test_auc": r_te[0], "test_best": r_te[1], "test_p50": r_te[2], "test_kept": r_te[3], "test_bounce": r_te[4],
           "test_p60": r_te[5], "test_kept60": r_te[6], "sec": round(time.time() - t0)}
    rows.append(row)
    print(row, flush=True)
    del X, s
out = pd.DataFrame(rows)
out.to_csv("study_results/quality_v4_model_grid.csv", index=False)
print(out.to_string(index=False))
