#!/usr/bin/env python3
"""v3 model selection on a strict time split.

train < 2025-12-01 · validate 2025-12-01..2026-03-01 · test >= 2026-03-01

Compares
  * the v2 feature set (64 columns) vs the v3 feature set (97 columns) with the same GBM,
  * a few GBM regularisation settings,
  * pooled vs. per-timeframe-group weighting.
Reports AUC, the hit-rate of the best-ranked candidate per (tf, bar, side) slot, and the
hit-rate / share of slots kept when only P >= 0.5 is accepted.  Hyper-parameters are picked on
the validation window only; the test window is reported for information.

    python experiments_v3.py            # writes study_results/quality_v3_model_grid.csv
"""
import glob
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.quality import FEATURE_ORDER_V2, QualityScorer, train

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

df = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob("models/train_*.pkl"))], ignore_index=True)
df = df[df.reached == True].copy()
df["sel_time"] = pd.to_datetime(df.sel_time)
df["side"] = np.where(df.direction == "bullish", "below", "above")
tr = df[df.sel_time < "2025-12-01"]
va = df[(df.sel_time >= "2025-12-01") & (df.sel_time < "2026-03-01")]
te = df[df.sel_time >= "2026-03-01"]
print("train/val/test", len(tr), len(va), len(te), flush=True)


def ev(s: QualityScorer, d: pd.DataFrame, penalty: float = 0.02):
    p = s.score_many(list(d.kind), list(d.features))
    y = d.ge1.astype(int).to_numpy()
    dd = d.assign(p=p)
    dd["key"] = -dd.p + penalty * dd.features.map(lambda f: float(f.get("distance_atr", 0.0)))
    best = dd.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
    k = best[best.p >= 0.5]
    return (round(roc_auc_score(y, p), 4), round(best.ge1.mean(), 3), round(k.ge1.mean(), 3),
            round(len(k) / len(best), 2), round(k.bounce_atr.median(), 2) if len(k) else np.nan)


def restrict(scorer: QualityScorer, features) -> QualityScorer:
    """Train-time helper: a scorer whose feature list is a subset (v2 columns only)."""
    scorer.features = list(features)
    return scorer


GRID = {
    "gbm_v2params": dict(),                                                                   # = GBM_DEFAULT
    "gbm_d3_400": dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0),
    "gbm_d4_300": dict(max_iter=300, learning_rate=0.03, max_depth=4, max_leaf_nodes=12, min_samples_leaf=300, l2_regularization=10.0),
    "gbm_d4_600slow": dict(max_iter=600, learning_rate=0.015, max_depth=4, max_leaf_nodes=12, min_samples_leaf=400, l2_regularization=10.0),
    "gbm_d5_reg": dict(max_iter=300, learning_rate=0.03, max_depth=5, max_leaf_nodes=16, min_samples_leaf=600, l2_regularization=20.0),
    "gbm_d2_wide": dict(max_iter=500, learning_rate=0.04, max_depth=2, max_leaf_nodes=4, min_samples_leaf=300, l2_regularization=5.0),
}

rows = []
for feat_set in ("v2", "v3"):
    feats = FEATURE_ORDER_V2 if feat_set == "v2" else None
    for name, g in GRID.items():
        t = time.time()
        s = QualityScorer() if feats is None else restrict(QualityScorer(), feats)
        s = train(list(tr.features), tr.ge1.to_numpy().astype(int), list(tr.kind), model="gbm",
                  gbm_params=g or None, scorer=s)
        r = {"features": feat_set, "model": name,
             "train_auc": round(roc_auc_score(tr.ge1.astype(int), s.score_many(list(tr.kind), list(tr.features))), 4)}
        for lab, d in (("val", va), ("test", te)):
            r[f"{lab}_auc"], r[f"{lab}_best"], r[f"{lab}_best>=.5"], r[f"{lab}_kept"], r[f"{lab}_med_bounce"] = ev(s, d)
        r["sec"] = round(time.time() - t)
        rows.append(r)
        print(r, flush=True)
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv("study_results/quality_v3_model_grid.csv", index=False)
