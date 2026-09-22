#!/usr/bin/env python3
"""v5 model selection: do classic indicators make the bounce ranking better?

Strict time split: train < 2025-12-01 · validate 2025-12-01..2026-03-01 · test >= 2026-03-01.
Hyper-parameters / feature groups are chosen on the VALIDATION window only; the test
window is reported for information (the final model is later validated again with
train_quality.py --split 2026-03-01 and at the bot level with run_v5_parts.sh).

Part A  univariate: bounce rate by quintile of each indicator feature (val+test rows)
Part B  feature-group ablation with the v4 production GBM (bagged x5):
          v4 · v4+creation indicators · v4+selection indicators · v4+HTF indicators · v5 (all)
          · v5 minus the volume group (volume scale break in the CSV) · indicators only
Part C  regularisation grid on the full v5 set (more features -> check depth / leaf size / L2)
Part D  permutation importance of the chosen model on val+test

Resumable: each part writes its own CSV and is skipped when the file exists.

    python experiments_v5.py            # writes study_results/quality_v5_*.csv
"""
import os
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.indicators import IndicatorSet
from lubot.quality import (FEATURE_ORDER, FEATURE_ORDER_V4, NUMERIC_V5_CONTEXT, NUMERIC_V5_CREATION, QualityScorer,
                           bagged_train, feature_importance, train)
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
OUT = "study_results"
os.makedirs(OUT, exist_ok=True)


def save(name, df):
    df.to_csv(f"{OUT}/{name}.csv", index=False)
    os.system(f'cd {os.path.dirname(os.path.abspath(__file__))} && bash save.sh "v5 step 5: {name}" >/dev/null 2>&1')


meta, fx = load_training()
tr_m = (meta.sel_time < "2025-12-01").to_numpy()
va_m = ((meta.sel_time >= "2025-12-01") & (meta.sel_time < "2026-03-01")).to_numpy()
te_m = (meta.sel_time >= "2026-03-01").to_numpy()
print("rows train/val/test", tr_m.sum(), va_m.sum(), te_m.sum(), "features in set:", fx.shape[1], flush=True)
kinds = meta.kind.to_numpy()
y = meta.ge1.to_numpy().astype(int)
dist = fx["distance_atr"].to_numpy(dtype=float)
P = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)


def ev(s: QualityScorer, X: np.ndarray, m: np.ndarray, penalty: float = 0.02) -> dict:
    p = s.score_many(list(kinds[m]), X[m])
    d = meta.loc[m, ["tf", "sel_i", "side", "ge1", "bounce_atr", "ge2"]].copy()
    d["p"] = p
    d["key"] = -p + penalty * dist[m]
    best = d.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
    k, k6, k65 = best[best.p >= 0.5], best[best.p >= 0.6], best[best.p >= 0.65]
    return dict(auc=round(roc_auc_score(y[m], p), 4),
                best=round(best.ge1.mean(), 3),
                p50=round(k.ge1.mean(), 3), kept50=round(len(k) / len(best), 3), bounce50=round(k.bounce_atr.median(), 2) if len(k) else np.nan,
                ge2_50=round(k.ge2.mean(), 3) if len(k) else np.nan,
                p60=round(k6.ge1.mean(), 3) if len(k6) else np.nan, kept60=round(len(k6) / len(best), 3),
                p65=round(k65.ge1.mean(), 3) if len(k65) else np.nan, kept65=round(len(k65) / len(best), 3))


def fit(feats, params=P, bag=5):
    sc = QualityScorer(features=list(feats))
    X = sc.matrix_from_frame(fx, list(kinds))
    if bag:
        s = bagged_train(X[tr_m], y[tr_m], list(kinds[tr_m]), n_models=bag, gbm_params=params, scorer=sc)
    else:
        s = train(X[tr_m], y[tr_m], list(kinds[tr_m]), gbm_params=params, scorer=sc)
    return s, X


# ------------------------------------------------------------------ Part A
if not os.path.exists(f"{OUT}/quality_v5_univariate.csv"):
    print("\n=== Part A: univariate bounce rate by quintile (val+test) ===", flush=True)
    m = va_m | te_m
    rows = []
    base = y[m].mean()
    for f in NUMERIC_V5_CREATION + NUMERIC_V5_CONTEXT:
        if f not in fx.columns:
            continue
        v = fx.loc[m, f].to_numpy(dtype=float)
        ok = np.isfinite(v)
        if ok.sum() < 1000 or len(np.unique(v[ok])) < 2:
            continue
        try:
            q = pd.qcut(v[ok], 5, labels=False, duplicates="drop")
        except ValueError:
            continue
        g = pd.Series(y[m][ok]).groupby(q).mean()
        auc = roc_auc_score(y[m][ok], v[ok]) if len(np.unique(y[m][ok])) == 2 else np.nan
        rows.append({"feature": f, "n_bins": len(g), **{f"q{k + 1}": round(x, 3) for k, x in enumerate(g.values)},
                     "spread": round(g.max() - g.min(), 3), "auc_alone": round(max(auc, 1 - auc), 3), "base": round(base, 3)})
    uni = pd.DataFrame(rows).sort_values("auc_alone", ascending=False)
    print(uni.head(30).to_string(index=False))
    save("quality_v5_univariate", uni)

# ------------------------------------------------------------------ Part B
sess = [f for f in FEATURE_ORDER if f.startswith("sess_") or f.startswith("kind_") or f == "ny_hour_raw"]
v4num = [f for f in FEATURE_ORDER_V4 if f not in sess]
VOL = [f for f in NUMERIC_V5_CREATION + NUMERIC_V5_CONTEXT if "vol" in f or "obv" in f or "mfi" in f or "climax" in f]
HTF5 = list(IndicatorSet.HTF)
SEL5 = list(IndicatorSet.SELECTION)
CR5 = list(IndicatorSet.CREATION)
GRID_B = {
    "v4": FEATURE_ORDER_V4,
    "v4+cr_ind": v4num + CR5 + sess,
    "v4+sel_ind": v4num + SEL5 + sess,
    "v4+htf_ind": v4num + HTF5 + sess,
    "v5_all": FEATURE_ORDER,
    "v5_no_volume": [f for f in FEATURE_ORDER if f not in VOL],
    "indicators_only": ["distance_atr", "tf_minutes", "zone_atr", "is_bull"] + CR5 + SEL5 + HTF5 + sess,
}
if not os.path.exists(f"{OUT}/quality_v5_model_grid.csv"):
    print("\n=== Part B: feature-group ablation (bagged x5, v4 params) ===", flush=True)
    rows = []
    for name, feats in GRID_B.items():
        t0 = time.time()
        s, X = fit(feats)
        r = {"setting": name, "n_features": len(feats)}
        r.update({f"val_{k}": v for k, v in ev(s, X, va_m).items()})
        r.update({f"test_{k}": v for k, v in ev(s, X, te_m).items()})
        r["train_auc"] = ev(s, X, tr_m)["auc"]
        r["sec"] = round(time.time() - t0)
        rows.append(r)
        print(r, flush=True)
        del X, s
    grid = pd.DataFrame(rows)
    print(grid.to_string(index=False))
    save("quality_v5_model_grid", grid)

# ------------------------------------------------------------------ Part C
GRID_C = {
    "d3_l200_L5 (v4 prod)": P,
    "d3_l300_L10": dict(P, min_samples_leaf=300, l2_regularization=10.0),
    "d4_l300_L10": dict(P, max_depth=4, max_leaf_nodes=12, min_samples_leaf=300, l2_regularization=10.0),
    "d3_600_lr015": dict(P, max_iter=600, learning_rate=0.015),
    "d2_l200_L5": dict(P, max_depth=2, max_leaf_nodes=4),
    "d3_l200_L5_colsub": dict(P, max_features=0.5),
}
if not os.path.exists(f"{OUT}/quality_v5_model_grid_c.csv"):
    print("\n=== Part C: regularisation grid on v5 features ===", flush=True)
    rows = []
    for name, params in GRID_C.items():
        t0 = time.time()
        try:
            s, X = fit(FEATURE_ORDER, params)
        except TypeError as e:          # older sklearn without max_features
            print("skip", name, e)
            continue
        r = {"setting": name}
        r.update({f"val_{k}": v for k, v in ev(s, X, va_m).items()})
        r.update({f"test_{k}": v for k, v in ev(s, X, te_m).items()})
        r["train_auc"] = ev(s, X, tr_m)["auc"]
        r["sec"] = round(time.time() - t0)
        rows.append(r)
        print(r, flush=True)
        del X, s
    gc = pd.DataFrame(rows)
    print(gc.to_string(index=False))
    save("quality_v5_model_grid_c", gc)

# ------------------------------------------------------------------ Part D
if not os.path.exists(f"{OUT}/quality_v5_importance_valtest.csv"):
    print("\n=== Part D: permutation importance of v5 (val+test) ===", flush=True)
    s, X = fit(FEATURE_ORDER)
    idx = np.flatnonzero(va_m | te_m)
    idx = np.random.default_rng(0).choice(idx, min(10000, len(idx)), replace=False)
    imp = feature_importance(s, X[idx], [kinds[j] for j in idx], y[idx], n_repeats=2)
    new = set(NUMERIC_V5_CREATION + NUMERIC_V5_CONTEXT)
    print("\ntop-25 overall (AUC drop):")
    for n, v in imp[:25]:
        print(f"  {n:<28}{v:+.4f}{'  <- v5' if n in new else ''}")
    print("\ntop-20 indicator features:")
    for n, v in [(n, v) for n, v in imp if n in new][:20]:
        print(f"  {n:<28}{v:+.4f}")
    save("quality_v5_importance_valtest", pd.DataFrame(imp, columns=["feature", "auc_drop"]))
print("=== experiments_v5 done")
