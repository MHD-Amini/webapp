#!/usr/bin/env python3
"""Train the POI quality model with a strict time split and report out-of-sample lift.

    python train_quality.py --split 2026-04-01                   # GBM, train < split, test >= split
    python train_quality.py --split 2026-04-01 --model logistic  # v1 family for comparison
    python train_quality.py --split 2026-04-01 --final           # also refit on everything -> models/quality_model.json

Targets (all labelled on M1 after the first tap of the zone edge):
    ge1          bounce >= 1 ATR before the far edge (+0.1 ATR) is violated   (default, what the bot displays)
    ge1_clean    same, but price never traded through the far edge at all
    ge05         bounce >= 0.5 ATR before violation
    bounce_first bounce >= 1 ATR happened BEFORE the SL level was ever touched
"""
import argparse
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

from lubot.quality import (FEATURE_ORDER, FEATURE_ORDER_V2, FEATURE_ORDER_V3, FEATURE_ORDER_V4, KINDS, QualityScorer,
                           bagged_train, feature_importance, train)
from lubot.trainset import load_training

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)


def load(pattern: str = "models/train_*.pkl"):
    """(meta, features) of the reached candidates - compact float32 layout, see lubot.trainset."""
    return load_training(pattern)


def evaluate(scorer: QualityScorer, meta: pd.DataFrame, X: np.ndarray, label: str, target: str, min_q: float) -> dict:
    from sklearn.metrics import roc_auc_score, log_loss
    p = scorer.score_many(list(meta.kind), X)
    y = meta[target].to_numpy().astype(int)
    auc = roc_auc_score(y, p)
    ll = log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))
    test = meta.assign(p=p)
    print(f"\n=== {label}: n={len(test)} base rate={y.mean():.3f} AUC={auc:.3f} logloss={ll:.3f}")
    test["dec"] = pd.qcut(test.p, 5, labels=False, duplicates="drop")
    lift = test.groupby("dec").agg(n=("p", "size"), p_mean=("p", "mean"), actual=(target, "mean"),
                                   bounce_atr=("bounce_atr", "median"))
    print(lift.round(3).to_string())
    rows = []
    for tf, g in test.groupby("tf"):
        closest = g[g.closest]
        best = g.sort_values("p", ascending=False).groupby(["sel_i", "side"]).head(1)
        thr = best[best.p >= min_q]
        rows.append({"tf": tf, "closest_n": len(closest), "closest_ge1": closest[target].mean(),
                     "closest_bounce": closest.bounce_atr.median(),
                     "bestq_n": len(best), "bestq_ge1": best[target].mean(), "bestq_bounce": best.bounce_atr.median(),
                     f"bestq>={min_q}_n": len(thr), f"bestq>={min_q}_ge1": thr[target].mean(),
                     f"bestq>={min_q}_bounce": thr.bounce_atr.median(),
                     f"slots_kept_%": round(100 * len(thr) / max(len(best), 1), 1)})
    res = pd.DataFrame(rows)
    print(res.round(3).to_string(index=False))
    cal = test.assign(b=pd.cut(test.p, [0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 1.0]))
    print("calibration:")
    print(cal.groupby("b", observed=True).agg(n=("p", "size"), pred=("p", "mean"), actual=(target, "mean")).round(3).T.to_string())
    return {"auc": auc, "logloss": ll, "table": res}


def threshold_sweep(scorer: QualityScorer, meta: pd.DataFrame, X: np.ndarray, dist: np.ndarray, target: str,
                    penalty: float) -> pd.DataFrame:
    """For each min_quality: share of slots kept and hit-rate of the chosen POI (best score − penalty·distance)."""
    p = scorer.score_many(list(meta.kind), X)
    d = meta.assign(p=p)
    d["rank_key"] = -d.p + penalty * dist
    best = d.sort_values("rank_key").groupby(["tf", "sel_i", "side"]).head(1)
    rows = []
    for q in (0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        k = best[best.p >= q]
        rows.append({"min_quality": q, "slots_kept_%": round(100 * len(k) / len(best), 1), "n": len(k),
                     f"{target}_%": round(100 * k[target].mean(), 1) if len(k) else np.nan,
                     "median_bounce_atr": round(k.bounce_atr.median(), 2) if len(k) else np.nan,
                     "ge2_%": round(100 * k.ge2.mean(), 1) if len(k) else np.nan})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2026-04-01")
    ap.add_argument("--target", default="ge1", choices=["ge1", "bounce_first", "ge2", "ge05", "ge1_clean"])
    ap.add_argument("--model", default="gbm", choices=["gbm", "logistic"])
    ap.add_argument("--C", type=float, default=0.3)
    ap.add_argument("--min-quality", type=float, default=0.50)
    ap.add_argument("--penalty", type=float, default=0.02)
    ap.add_argument("--per-kind", action="store_true", help="one model per POI type instead of the pooled model with type dummies")
    ap.add_argument("--importance", action="store_true", help="permutation importance on the test set (slow-ish)")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--features", default="v5", choices=["v2", "v3", "v4", "v5"],
                    help="feature set (v2 = 64 columns, v3 = 97, v4 = 125 incl. price action, v5 = +94 indicator features)")
    ap.add_argument("--gbm", default=None, help="GBM overrides as key=value,key=value (e.g. max_iter=400,max_depth=4)")
    ap.add_argument("--tag", default="v5")
    ap.add_argument("--bag", type=int, default=0, help="bagged GBM: number of boosters on 80%% row subsets (0 = single model)")
    ap.add_argument("--out", default="models/quality_model.json")
    a = ap.parse_args()
    meta, fx = load()
    print(f"{len(meta)} reached candidates, {meta.sel_time.min()} -> {meta.sel_time.max()}")
    print(meta.groupby("kind")[a.target].agg(["mean", "size"]).round(3).T.to_string())
    print(meta.groupby("tf")[a.target].agg(["mean", "size"]).round(3).T.to_string())
    split = pd.Timestamp(a.split)
    tr_m = (meta.sel_time < split).to_numpy()
    te_m = ~tr_m
    print(f"train {tr_m.sum()}  test {te_m.sum()}  ({a.model})")
    gbm_params = None
    if a.gbm:
        gbm_params = {}
        for kv in a.gbm.split(","):
            k, v = kv.split("=")
            gbm_params[k.strip()] = float(v) if "." in v else int(v)
    feats = list({"v2": FEATURE_ORDER_V2, "v3": FEATURE_ORDER_V3, "v4": FEATURE_ORDER_V4, "v5": FEATURE_ORDER}[a.features])
    kinds = list(meta.kind)
    X = QualityScorer(features=feats).matrix_from_frame(fx, kinds)
    dist = fx["distance_atr"].to_numpy(dtype=float)
    y_all = meta[a.target].to_numpy().astype(int)
    del fx

    def fit(mask):
        sc = QualityScorer(features=list(feats))
        km = [k for k, m in zip(kinds, mask) if m]
        if a.bag and a.model == "gbm":
            return bagged_train(X[mask], y_all[mask], km, n_models=a.bag, gbm_params=gbm_params, scorer=sc)
        return train(X[mask], y_all[mask], km, C=a.C, model=a.model, per_kind=a.per_kind, gbm_params=gbm_params,
                     scorer=sc)
    scorer = fit(tr_m)
    if a.model == "gbm":
        print("trees per model:", {k: m.get("n_trees") for k, m in scorer.models.items()})
    tr, te = meta[tr_m].reset_index(drop=True), meta[te_m].reset_index(drop=True)
    evaluate(scorer, tr, X[tr_m], "IN-SAMPLE (train)", a.target, a.min_quality)
    oos = evaluate(scorer, te, X[te_m], "OUT-OF-SAMPLE (test)", a.target, a.min_quality)
    print("\nOOS threshold sweep (best-ranked candidate per slot):")
    sweep = threshold_sweep(scorer, te, X[te_m], dist[te_m], a.target, a.penalty)
    print(sweep.to_string(index=False))
    if a.model == "logistic":
        w = np.array(scorer.models["ALL"]["w"])
        order = np.argsort(-np.abs(w))[:16]
        print("\nPooled model - strongest standardised coefficients:")
        for j in order:
            print(f"  {scorer.features[j]:<24} {w[j]:+.3f}")
    if a.importance or a.model == "gbm":
        rng = np.random.default_rng(0)
        idx = np.flatnonzero(te_m)
        idx = rng.choice(idx, size=min(len(idx), 8000), replace=False)
        imp = feature_importance(scorer, X[idx], [kinds[j] for j in idx], y_all[idx], n_repeats=2)
        print("\nPermutation importance (AUC drop, OOS):")
        for name, v in imp[:25]:
            print(f"  {name:<24} {v:+.4f}")
        Path("study_results").mkdir(exist_ok=True)
        pd.DataFrame(imp, columns=["feature", "auc_drop"]).to_csv(f"study_results/quality_{a.tag}_importance.csv", index=False)
    Path("study_results").mkdir(exist_ok=True)
    sweep.to_csv(f"study_results/quality_{a.tag}_threshold_sweep.csv", index=False)
    oos["table"].to_csv(f"study_results/quality_{a.tag}_oos_by_tf.csv", index=False)
    if a.final:
        final = fit(np.ones(len(meta), dtype=bool))
        final.meta.update({"target": a.target, "trained_until": str(meta.sel_time.max()), "split_validated": a.split,
                           "oos_auc": round(oos["auc"], 4), "version": a.tag, "feature_set": a.features})
        final.save(a.out)
        scorer.meta.update({"target": a.target, "trained_until": a.split, "oos_auc": round(oos["auc"], 4),
                            "version": a.tag, "feature_set": a.features})
        scorer.save(a.out.replace(".json", "_trainonly.json"))
        print(f"\nsaved {a.out} (all data) and {a.out.replace('.json', '_trainonly.json')} (validated)")


if __name__ == "__main__":
    main()
