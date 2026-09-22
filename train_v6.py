#!/usr/bin/env python3
"""Train the v6 POI quality model.

What changed vs train_quality.py (v5):
  * POI-level sample weights (1 / rows of that POI) - the training set re-records a living
    POI every 25 bars, so without weights long-lived zones dominate the fit
  * learner = ensemble of a bagged LightGBM (5 seeds) and the bagged v5-style sklearn GBM,
    both POI-weighted, averaged in probability space and exported as ONE JSON model file
    (numpy inference in the bot; no lightgbm/sklearn needed at runtime)
  * feature set v6 (level memory) by default, v5 selectable for the ablation

    python train_v6.py --pattern "models/v6/train_*.pkl" --split 2026-03-01 --final
    -> models/quality_model.json (all data) + models/quality_model_trainonly.json (< split)
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, log_loss

from lubot.lgbm_export import export_lgbm
from lubot.quality import FEATURE_ORDER, FEATURE_ORDER_V5, KINDS, QualityScorer, bagged_train
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

LGB = dict(objective="binary", metric="auc", verbose=-1, num_threads=2, bagging_freq=1, num_leaves=15, max_depth=4,
           learning_rate=0.02, min_data_in_leaf=300, feature_fraction=0.7, bagging_fraction=0.8, lambda_l2=10.0)
GBM = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=300, l2_regularization=10.0)


def poi_weights(meta: pd.DataFrame) -> np.ndarray:
    key = meta.tf + "_" + meta.id.astype(str)
    return (1.0 / key.map(key.value_counts())).to_numpy(dtype=float)


def fit_v6(X: np.ndarray, y: np.ndarray, kinds, w: np.ndarray, feats, n_iter: int, bag: int = 5,
           lgb_weight: float = 0.5, seed: int = 0) -> QualityScorer:
    """Bagged LightGBM + bagged GBM -> one scorer.  Both members are plain additive tree
    ensembles, so the *raw scores* cannot simply be averaged (probabilities are averaged);
    we therefore store both as models "ALL" (lgb) and "ALL2" (gbm) and let the scorer mix."""
    trees = []
    for k in range(bag):
        p = dict(LGB, seed=seed * 100 + k, bagging_seed=seed * 100 + k, feature_fraction_seed=seed * 100 + k)
        b = lgb.train(p, lgb.Dataset(X, y, weight=w), num_boost_round=n_iter)
        trees += export_lgbm(b, scale=1.0 / bag)["trees"]
    sc = QualityScorer(features=list(feats))
    sc.models["ALL"] = {"kind": "gbm", "trees": trees, "baseline": 0.0, "n": int(len(y)), "rate": float(y.mean()),
                        "n_trees": len(trees), "bagged": bag, "learner": "lightgbm"}
    g = bagged_train(X, y, list(kinds), n_models=bag, gbm_params=GBM, scorer=QualityScorer(features=list(feats)),
                     sample_weight=w, seed=seed)
    sc.models["ALL2"] = {**g.models["ALL"], "learner": "sklearn_hgb"}
    sc.meta = {"model": "gbm", "ensemble": ["lightgbm", "sklearn_hgb"], "mix": [lgb_weight, 1.0 - lgb_weight],
               "lgb_params": LGB, "lgb_iter": n_iter, "gbm_params": GBM, "bagged": bag, "poi_weighted": True}
    kinds_arr = np.asarray(kinds)
    for k in KINDS:
        m = kinds_arr == k
        sc.base_rate[k] = float(y[m].mean()) if m.any() else float(y.mean())
    return sc


def evaluate(sc, meta, X, dist, w, label, penalty=0.02):
    p = sc.score_many(list(meta.kind), X)
    y = meta.ge1.to_numpy().astype(int)
    d = meta.assign(p=p, key=-p + penalty * dist)
    best = d.sort_values("key").groupby(["tf", "sel_i", "side"]).head(1)
    print(f"\n=== {label}: n={len(meta)} base={y.mean():.3f} AUC={roc_auc_score(y, p):.4f} AUC_w={roc_auc_score(y, p, sample_weight=w):.4f} "
          f"logloss={log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)):.4f}")
    rows = []
    for q in (0.0, 0.5, 0.55, 0.6, 0.65, 0.7):
        k = best[best.p >= q]
        rows.append({"min_quality": q, "slots_kept_%": round(100 * len(k) / len(best), 1), "n": len(k),
                     "ge1_%": round(100 * k.ge1.mean(), 1) if len(k) else np.nan,
                     "median_bounce_atr": round(k.bounce_atr.median(), 2) if len(k) else np.nan,
                     "ge2_%": round(100 * k.ge2.mean(), 1) if len(k) else np.nan})
    sweep = pd.DataFrame(rows)
    print(sweep.to_string(index=False))
    cal = d.assign(b=pd.cut(d.p, [0, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0]))
    print("calibration:\n" + cal.groupby("b", observed=True).agg(n=("p", "size"), pred=("p", "mean"), actual=("ge1", "mean")).round(3).T.to_string())
    per_tf = []
    for tf, g in best.groupby("tf"):
        k = g[g.p >= 0.5]
        per_tf.append({"tf": tf, "slots": len(g), "top1_ge1": round(g.ge1.mean(), 3), "p50_n": len(k), "p50_ge1": round(k.ge1.mean(), 3) if len(k) else np.nan})
    print(pd.DataFrame(per_tf).to_string(index=False))
    return {"auc": roc_auc_score(y, p), "sweep": sweep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="models/v6/train_*.pkl")
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--features", default="v6", choices=["v5", "v6"])
    ap.add_argument("--bag", type=int, default=5)
    ap.add_argument("--iters", type=int, default=0, help="LightGBM rounds; 0 = pick by early stopping on the last 3 months before --split")
    ap.add_argument("--mix", type=float, default=0.5, help="weight of the LightGBM member")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--out", default="models/quality_model.json")
    ap.add_argument("--tag", default="v6")
    a = ap.parse_args()
    meta, fx = load_training(a.pattern)
    feats = list(FEATURE_ORDER if a.features == "v6" else FEATURE_ORDER_V5)
    kinds = list(meta.kind)
    X = QualityScorer(features=feats).matrix_from_frame(fx, kinds).astype(np.float32)
    dist = fx["distance_atr"].to_numpy(dtype=float)
    del fx
    y = meta.ge1.to_numpy().astype(int)
    w = poi_weights(meta)
    split = pd.Timestamp(a.split)
    tr = (meta.sel_time < split).to_numpy()
    te = ~tr
    print(f"{len(meta)} rows ({len(feats)} features) | train {tr.sum()} test {te.sum()} | POIs {meta.groupby(['tf', 'id']).ngroups}")
    n_iter = a.iters
    if not n_iter:
        # early stopping on the last 3 months of the training window
        cut = split - pd.DateOffset(months=3)
        a_m = (meta.sel_time < cut).to_numpy()
        b_m = tr & ~a_m
        p = dict(LGB, seed=7)
        b = lgb.train(p, lgb.Dataset(X[a_m], y[a_m], weight=w[a_m]), 3000,
                      valid_sets=[lgb.Dataset(X[b_m], y[b_m], weight=w[b_m])], callbacks=[lgb.early_stopping(150, verbose=False)])
        n_iter = int(b.best_iteration * (tr.sum() / max(a_m.sum(), 1)) ** 0.5)      # a little more for the larger set
        print(f"early stopping on {cut.date()}..{split.date()}: best_iter {b.best_iteration} -> using {n_iter}")
    sc = fit_v6(X[tr], y[tr], [k for k, m in zip(kinds, tr) if m], w[tr], feats, n_iter, a.bag, a.mix)
    evaluate(sc, meta[tr].reset_index(drop=True), X[tr], dist[tr], w[tr], "IN-SAMPLE")
    oos = evaluate(sc, meta[te].reset_index(drop=True), X[te], dist[te], w[te], "OUT-OF-SAMPLE (test)")
    Path("study_results").mkdir(exist_ok=True)
    oos["sweep"].to_csv(f"study_results/quality_{a.tag}_threshold_sweep.csv", index=False)
    sc.meta.update({"target": "ge1", "trained_until": a.split, "oos_auc": round(oos["auc"], 4), "version": a.tag, "feature_set": a.features})
    if a.final:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        sc.save(a.out.replace(".json", "_trainonly.json"))
        final = fit_v6(X, y, kinds, w, feats, n_iter, a.bag, a.mix)
        final.meta.update({"target": "ge1", "trained_until": str(meta.sel_time.max()), "split_validated": a.split,
                           "oos_auc": round(oos["auc"], 4), "version": a.tag, "feature_set": a.features})
        final.save(a.out)
        print(f"\nsaved {a.out} (all data) and {a.out.replace('.json', '_trainonly.json')} (validated)")


if __name__ == "__main__":
    main()
