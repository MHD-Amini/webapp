#!/usr/bin/env python3
"""v6 pooled ablation on the rebuilt training sets (all 5 timeframes, same rows):

    feature set   v5 (219)  ·  v6 (258)  ·  v6 minus profile densities  ·  v6 minus reaction memory
    learner       POI-weighted LightGBM (3 seeds, fixed rounds chosen on val) and the v6 ensemble
    windows       train < Dec-25 · val Dec-25..Feb-26 · test >= Mar-26   (choose on val, report test)

Writes study_results/quality_v6_ablation.csv and quality_v6_univariate.csv.  Resumable.
    python ablation_v6.py
"""
import os
import time

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V5, NUMERIC_V6_CONTEXT, NUMERIC_V6_CREATION, QualityScorer
from lubot.trainset import load_training
from train_v6 import GBM, LGB, poi_weights
from lubot.quality import bagged_train

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
OUT = "study_results"

meta, fx = load_training("models/v6/train_*.pkl")
tr = (meta.sel_time < "2025-12-01").to_numpy()
va = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te = (meta.sel_time >= "2026-03-01").to_numpy()
y = meta.ge1.to_numpy().astype(int)
kinds = list(meta.kind)
w = poi_weights(meta)
dist = fx["distance_atr"].to_numpy(dtype=float)
slot = (meta.tf + "_" + meta.sel_i.astype(str) + "_" + meta.side).to_numpy()
new = [f for f in NUMERIC_V6_CREATION + NUMERIC_V6_CONTEXT if f in fx.columns]
print(f"rows {len(meta)} | train {tr.sum()} val {va.sum()} test {te.sum()} | v6 features {len(new)}", flush=True)

# ------------------------------------------------------------ univariate (pooled)
if not os.path.exists(f"{OUT}/quality_v6_univariate.csv"):
    rows = []
    m = va | te
    for f in new:
        v = fx.loc[m, f].to_numpy(dtype=float)
        a = roc_auc_score(y[m], v, sample_weight=w[m])
        r = {"feature": f, "auc_alone_w": round(max(a, 1 - a), 3)}
        if len(np.unique(v)) >= 3:
            q = pd.qcut(v, 5, labels=False, duplicates="drop")
            g = pd.Series(y[m]).groupby(q).mean()
            r.update({f"q{k + 1}": round(x, 3) for k, x in enumerate(g.values)})
            r["spread"] = round(g.max() - g.min(), 3)
        else:
            r.update(rate_pos=round(y[m][v > 0].mean(), 3) if (v > 0).any() else np.nan, rate_zero=round(y[m][v <= 0].mean(), 3))
        rows.append(r)
    uni = pd.DataFrame(rows).sort_values("auc_alone_w", ascending=False)
    print(uni.to_string(index=False))
    uni.to_csv(f"{OUT}/quality_v6_univariate.csv", index=False)
    os.system('bash save.sh "v6 step 6: pooled univariate" >/dev/null 2>&1')


def slot_top1(p, m, penalty=0.02):
    d = pd.DataFrame({"slot": slot[m], "p": p, "y": y[m], "b": meta.bounce_atr.to_numpy()[m], "key": -p + penalty * dist[m]})
    best = d.sort_values("key").groupby("slot").head(1)
    out = {"top1": round(best.y.mean(), 3)}
    for q in (0.5, 0.6, 0.65):
        k = best[best.p >= q]
        out[f"p{int(q * 100)}"] = round(k.y.mean(), 3) if len(k) else np.nan
        out[f"kept{int(q * 100)}"] = round(len(k) / len(best), 3)
    return out


PROFILE = [f for f in new if any(s in f for s in ("density", "lvn", "poc", "va_", "_va", "path"))]
REACT = [f for f in new if any(s in f for s in ("rev_", "visit", "slice"))]
SETS = {
    "v5": list(FEATURE_ORDER_V5),
    "v6": list(FEATURE_ORDER),
    "v6_no_profile": [f for f in FEATURE_ORDER if f not in PROFILE],
    "v6_no_reaction": [f for f in FEATURE_ORDER if f not in REACT],
    "v6_no_creation": [f for f in FEATURE_ORDER if f not in NUMERIC_V6_CREATION],
}
if not os.path.exists(f"{OUT}/quality_v6_ablation.csv"):
    rows = []
    for name, feats in SETS.items():
        t0 = time.time()
        X = QualityScorer(features=feats).matrix_from_frame(fx, kinds).astype(np.float32)
        # rounds by early stopping on val (seed 0), then 3 fixed-round seeds
        b0 = lgb.train(dict(LGB, seed=0), lgb.Dataset(X[tr], y[tr], weight=w[tr]), 3000,
                       valid_sets=[lgb.Dataset(X[va], y[va], weight=w[va])], callbacks=[lgb.early_stopping(150, verbose=False)])
        it = max(int(b0.best_iteration), 100)
        pv, pt = [], []
        for s in range(3):
            b = lgb.train(dict(LGB, seed=s, bagging_seed=s, feature_fraction_seed=s), lgb.Dataset(X[tr], y[tr], weight=w[tr]), it)
            pv.append(b.predict(X[va])); pt.append(b.predict(X[te]))
        pv, pt = np.mean(pv, 0), np.mean(pt, 0)
        r = {"set": name, "n_feat": len(feats), "iters": it,
             "val_auc_w": round(roc_auc_score(y[va], pv, sample_weight=w[va]), 4), "test_auc_w": round(roc_auc_score(y[te], pt, sample_weight=w[te]), 4),
             "val_auc": round(roc_auc_score(y[va], pv), 4), "test_auc": round(roc_auc_score(y[te], pt), 4)}
        r.update({f"val_{k}": v for k, v in slot_top1(pv, va).items()})
        r.update({f"test_{k}": v for k, v in slot_top1(pt, te).items()})
        # per-TF test AUC
        for tf in ("M5", "M10", "M15", "M30", "H1"):
            mm = te & (meta.tf == tf).to_numpy()
            r[f"test_auc_{tf}"] = round(roc_auc_score(y[mm], pt[(meta.tf[te] == tf).to_numpy()], sample_weight=w[mm]), 4)
        r["sec"] = round(time.time() - t0)
        print(r, flush=True)
        rows.append(r)
        pd.DataFrame(rows).to_csv(f"{OUT}/quality_v6_ablation_partial.csv", index=False)
        del X
    ab = pd.DataFrame(rows)
    print(ab.to_string(index=False))
    ab.to_csv(f"{OUT}/quality_v6_ablation.csv", index=False)
    os.system('bash save.sh "v6 step 6: pooled ablation v5 vs v6" >/dev/null 2>&1')
print("=== ablation_v6 done")
