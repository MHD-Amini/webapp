#!/usr/bin/env python3
"""Train the approach-stage quality model (stage 2 of v4).

Rows: models/approach_rows.pkl (build_approach_set.py) - candidates seen with price within
2 ATR of the zone, features recomputed at that bar, label = outcome after the tap.
Strict time split on the candidate's selection time; ``--final`` refits on everything.

    python train_approach.py --split 2026-03-01 --final
        -> models/approach_model.json (+ _trainonly.json)
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, log_loss

from lubot.quality import FEATURE_ORDER, QualityScorer, bagged_train, feature_importance

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
GBM = dict(max_iter=400, learning_rate=0.02, max_depth=3, max_leaf_nodes=8, min_samples_leaf=200, l2_regularization=5.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="models/approach_rows.pkl")
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--bag", type=int, default=5)
    ap.add_argument("--out", default="models/approach_model.json")
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()

    d = pd.read_pickle(a.rows)
    fcols = [c for c in d.columns if c.startswith("f__")]
    fx = d[fcols].copy()
    fx.columns = [c[3:] for c in fcols]
    meta = d.drop(columns=fcols)
    meta["sel_time"] = pd.to_datetime(meta.sel_time)
    kinds = list(meta.kind)
    y = meta.ge1.to_numpy().astype(int)
    X = QualityScorer(features=list(FEATURE_ORDER)).matrix_from_frame(fx, kinds)
    dist = fx["distance_atr"].to_numpy(dtype=float)
    tr = (meta.sel_time < a.split).to_numpy()
    te = ~tr
    print(f"{len(meta)} near rows  train {tr.sum()}  test {te.sum()}  base ge1 {y.mean():.3f}")

    def fit(mask):
        return bagged_train(X[mask], y[mask], [k for k, m in zip(kinds, mask) if m], n_models=a.bag, gbm_params=GBM,
                            scorer=QualityScorer(features=list(FEATURE_ORDER)))

    s = fit(tr)
    for label, m in (("IN-SAMPLE", tr), ("OUT-OF-SAMPLE", te)):
        p = s.score_many([k for k, mm in zip(kinds, m) if mm], X[m])
        print(f"\n=== {label}: n={m.sum()} AUC={roc_auc_score(y[m], p):.3f} logloss={log_loss(y[m], np.clip(p, 1e-6, 1 - 1e-6)):.3f}")
        dd = meta[m].assign(p=p, key=-p + 0.02 * dist[m])
        best = dd.sort_values("key").groupby(["tf", "bar_i", "side"]).head(1)
        rows = []
        for q in (0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7):
            k = best[best.p >= q]
            rows.append({"min_quality": q, "slots_kept_%": round(100 * len(k) / len(best), 1), "n": len(k),
                         "ge1_%": round(100 * k.ge1.mean(), 1) if len(k) else np.nan,
                         "median_bounce_atr": round(k.bounce_atr.median(), 2) if len(k) else np.nan,
                         "ge2_%": round(100 * k.ge2.mean(), 1) if len(k) else np.nan})
        sweep = pd.DataFrame(rows)
        print(sweep.to_string(index=False))
        k = best[best.p >= 0.5]
        print("by tf (P>=0.5):", {tf: f"{g.ge1.mean():.3f} (n{len(g)})" for tf, g in k.groupby("tf")})
        cal = dd.assign(b=pd.cut(dd.p, [0, .3, .4, .45, .5, .55, .6, .7, .8, 1]))
        print(cal.groupby("b", observed=True).agg(n=("p", "size"), pred=("p", "mean"), actual=("ge1", "mean")).round(3).T.to_string())
        if label == "OUT-OF-SAMPLE":
            oos_auc = roc_auc_score(y[m], p)
            sweep.to_csv("study_results/quality_v4_approach_threshold_sweep.csv", index=False)
    idx = np.random.default_rng(0).choice(np.flatnonzero(te), min(8000, te.sum()), replace=False)
    imp = feature_importance(s, X[idx], [kinds[j] for j in idx], y[idx], n_repeats=2)
    print("\nPermutation importance (AUC drop, OOS):")
    for n, v in imp[:25]:
        print(f"  {n:<24} {v:+.4f}")
    pd.DataFrame(imp, columns=["feature", "auc_drop"]).to_csv("study_results/quality_v4_approach_importance.csv", index=False)
    s.meta.update({"stage": "approach", "target": "ge1", "trained_until": a.split, "oos_auc": round(oos_auc, 4), "version": "v4",
                   "feature_set": "v4", "near_atr": 2.0})
    s.save(a.out.replace(".json", "_trainonly.json"))
    if a.final:
        f = fit(np.ones(len(y), dtype=bool))
        f.meta.update({"stage": "approach", "target": "ge1", "trained_until": str(meta.sel_time.max()), "split_validated": a.split,
                       "oos_auc": round(oos_auc, 4), "version": "v4", "feature_set": "v4", "near_atr": 2.0})
        f.save(a.out)
        print(f"\nsaved {a.out} and {a.out.replace('.json', '_trainonly.json')}")


if __name__ == "__main__":
    main()
