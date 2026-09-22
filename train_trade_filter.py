#!/usr/bin/env python3
"""v8 step 3 - train the TRADE FILTER: P(the v7 plan is NOT stopped out | features at selection).

Differences to the quality model (train_v6.py):
  * label = outcome of the actual trade plan replayed on M1 (models/plan_labels_<TF>.pkl):
    win = partial hit (partial_be or tp2) -> r_net > 0;  loss = stopped at the zone's far edge
  * plan-specific features added: zone_usd (zone height in $), cost_r_est ((typical spread +
    commission) / zone height) - the same two numbers the live engine attaches to every POI
  * trained on ALL filled candidates (more data), POI-weighted, but the threshold is chosen on the
    BOT-LIKE rows of the validation window (best of slot with quality >= 0.50 = what the trader sees)
  * chronological splits: train < --val-from, val [--val-from, --split), test >= --split (report only)

Outputs
  models/trade_filter_<TAG>_trainonly.json   (trained on everything before --split = OOS-safe for the backtest)
  models/trade_filter_<TAG>_trainwindow.json (trained before --val-from; used for the honest val sweep)
  study_results/trade_filter_<TAG>_sweep.csv, _importance.csv, _oos_by_quintile.csv

    python train_trade_filter.py --tfs M5 --tag M5
    python train_trade_filter.py --tfs M5,M10,M15,M30,H1 --eval-tf M5 --tag pooled
"""
from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from lubot.lgbm_export import export_lgbm
from lubot.quality import FEATURE_ORDER, KINDS, QualityScorer

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

PLAN_FEATURES = ["zone_usd", "cost_r_est"]
EST_SPREAD = 0.28          # median XAUUSD spread of the export ($); the live engine uses the current spread
EST_COMMISSION_OZ = 0.07   # $7 per lot round turn / 100 oz
LGB = dict(objective="binary", metric="auc", verbose=-1, num_threads=2, bagging_freq=1, num_leaves=15, max_depth=4,
           learning_rate=0.02, min_data_in_leaf=200, feature_fraction=0.6, bagging_fraction=0.8, lambda_l2=10.0)


def plan_features(zone_usd, spread=EST_SPREAD, commission_oz=EST_COMMISSION_OZ):
    """The two plan features, identical in training and in the live engine."""
    z = max(float(zone_usd), 0.01)
    return {"zone_usd": z, "cost_r_est": (spread + commission_oz) / z}


def load(tfs, model_q: str):
    parts = []
    for tf in tfs:
        d = pd.read_pickle(f"models/train_{tf}.pkl")
        L = pd.read_pickle(f"models/plan_labels_{tf}.pkl")
        assert len(d) == len(L), tf
        d = pd.concat([d, L], axis=1)
        d = d[d.pl_filled].reset_index(drop=True)
        parts.append(d)
        print(f"  {tf}: {len(d)} filled plans", flush=True)
    d = pd.concat(parts, ignore_index=True)
    del parts
    d["sel_time"] = pd.to_datetime(d.sel_time)
    d["poi_key"] = d.tf + "_" + d.id.astype(str)
    d["side"] = np.where(d.direction == "bullish", "below", "above")
    d["slot"] = d.tf + "_" + d.sel_i.astype(str) + "_" + d.side
    d["f__zone_usd"] = (d.top - d.bottom).clip(lower=0.01).astype("float32")
    d["f__cost_r_est"] = ((EST_SPREAD + EST_COMMISSION_OZ) / d.f__zone_usd).astype("float32")
    fcols = [c for c in d.columns if c.startswith("f__")]
    fx = d[fcols].copy()
    fx.columns = [c[3:] for c in fcols]
    meta = d.drop(columns=fcols)
    del d
    # the quality model's score (train-only v6) -> which rows the v7 bot would actually show
    sc = QualityScorer.load(model_q)
    meta["q"] = sc.score_many(list(meta.kind), fx)
    meta["key"] = -meta.q + 0.02 * fx["distance_atr"].to_numpy()
    best = meta.sort_values("key").groupby("slot").head(1).index
    meta["bot_like"] = False
    meta.loc[best, "bot_like"] = meta.loc[best, "q"] >= 0.50
    meta["w"] = 1.0 / meta.poi_key.map(meta.poi_key.value_counts())
    return meta, fx


def sweep(meta, p, label, thresholds=(0.0, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75)):
    """Bot-like rows only: what the trader keeps at each filter threshold."""
    b = meta[meta.bot_like].copy()
    b["p"] = p[meta.bot_like.to_numpy()]
    rows = []
    for th in thresholds:
        k = b[b.p >= th]
        rows.append({"set": label, "th": th, "n": len(k), "pois": k.poi_key.nunique(), "keep_%": round(100 * len(k) / max(len(b), 1), 1),
                     "avg_r": round(k.pl_r_net.mean(), 4) if len(k) else np.nan,
                     "avg_r_w": round(np.average(k.pl_r_net, weights=k.w), 4) if len(k) else np.nan,
                     "total_r": round(k.pl_r_net.sum(), 1), "win_%": round(100 * k.pl_win.mean(), 1) if len(k) else np.nan,
                     "sl_%": round(100 * (k.pl_outcome == "sl").mean(), 1) if len(k) else np.nan,
                     "tp2_%": round(100 * (k.pl_outcome == "tp2").mean(), 1) if len(k) else np.nan,
                     "median_cost_r": round(k.pl_cost_r.median(), 3) if len(k) else np.nan})
    return pd.DataFrame(rows)


def fit(X, y, w, n_iter, bag, seed=0):
    trees = []
    for k in range(bag):
        p = dict(LGB, seed=seed * 100 + k, bagging_seed=seed * 100 + k, feature_fraction_seed=seed * 100 + k)
        b = lgb.train(p, lgb.Dataset(X, y, weight=w), num_boost_round=n_iter)
        trees += export_lgbm(b, scale=1.0 / bag)["trees"]
    return trees, b


def make_scorer(feats, trees, n, rate, kinds_arr=None, y=None, mask=None):
    sc = QualityScorer(features=list(feats))
    sc.models["ALL"] = {"kind": "gbm", "trees": trees, "baseline": 0.0, "n": int(n), "rate": float(rate), "n_trees": len(trees),
                        "learner": "lightgbm"}
    if kinds_arr is not None:
        for k in KINDS:
            m = (kinds_arr == k) & mask
            sc.base_rate[k] = float(y[m].mean()) if m.any() else float(rate)
    return sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", default="M5")
    ap.add_argument("--eval-tf", default="M5")
    ap.add_argument("--val-from", default="2025-12-01")
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--model-q", default="models/quality_model_trainonly.json")
    ap.add_argument("--bag", type=int, default=3)
    ap.add_argument("--max-cost-r", type=float, default=0.5, help="drop training plans whose cost_r is above this (hopeless zones)")
    ap.add_argument("--tag", default="M5")
    ap.add_argument("--iters", type=int, default=0)
    a = ap.parse_args()
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    meta, fx = load(tfs, a.model_q)
    feats = list(FEATURE_ORDER) + PLAN_FEATURES
    X = QualityScorer(features=feats).matrix_from_frame(fx, list(meta.kind)).astype(np.float32)
    del fx
    y = meta.pl_win.to_numpy().astype(int)
    w = meta.w.to_numpy(dtype=float)
    kinds_arr = meta.kind.to_numpy()
    vfrom, split = pd.Timestamp(a.val_from), pd.Timestamp(a.split)
    keep = (meta.pl_cost_r <= a.max_cost_r).to_numpy()
    tr = (meta.sel_time < vfrom).to_numpy() & keep
    va = ((meta.sel_time >= vfrom) & (meta.sel_time < split)).to_numpy() & keep
    te = (meta.sel_time >= split).to_numpy()
    ev = (meta.tf == a.eval_tf).to_numpy()
    bl = meta.bot_like.to_numpy()
    print(f"{len(meta)} plans, {len(feats)} features | train {tr.sum()} val {va.sum()} test {te.sum()} | "
          f"bot-like {a.eval_tf}: train {(tr & ev & bl).sum()} val {(va & ev & bl).sum()} test {(te & ev & bl).sum()}")
    # ---------------- early stopping on the validation window
    n_iter = a.iters
    if not n_iter:
        b = lgb.train(dict(LGB, seed=7), lgb.Dataset(X[tr], y[tr], weight=w[tr]), 3000,
                      valid_sets=[lgb.Dataset(X[va], y[va], weight=w[va])], callbacks=[lgb.early_stopping(150, verbose=False)])
        n_iter = max(int(b.best_iteration), 50)
        print(f"early stopping: best_iter {b.best_iteration} (val AUC {b.best_score['valid_0']['auc']:.4f}) -> {n_iter}")
    out = Path("study_results")
    out.mkdir(exist_ok=True)
    # ---------------- model A: train window only -> honest val + test numbers
    trees, last = fit(X[tr], y[tr], w[tr], n_iter, a.bag)
    scA = make_scorer(feats, trees, tr.sum(), y[tr].mean(), kinds_arr, y, tr)
    pA = scA.score_many(list(meta.kind), X)
    rows = []
    for lab, m in (("train", tr), ("val", va), ("test", te)):
        mm = m & ev
        auc = roc_auc_score(y[mm], pA[mm], sample_weight=w[mm])
        auc_bot = roc_auc_score(y[mm & bl], pA[mm & bl]) if (mm & bl).sum() > 50 else np.nan
        print(f"\n[{lab} {a.eval_tf}] n={mm.sum()} base win {y[mm].mean():.3f} AUC_w {auc:.4f} | bot-like AUC {auc_bot:.4f}")
        s = sweep(meta[mm].reset_index(drop=True), pA[mm], lab)
        print(s.to_string(index=False))
        rows.append(s)
    pd.concat(rows, ignore_index=True).to_csv(out / f"trade_filter_{a.tag}_sweep.csv", index=False)
    bt = meta[te & ev & bl].assign(p=pA[te & ev & bl])
    if len(bt) > 50:
        bt["dec"] = pd.qcut(bt.p, 5, labels=False, duplicates="drop")
        dec = bt.groupby("dec").agg(n=("p", "size"), p_min=("p", "min"), p_mean=("p", "mean"), win=("pl_win", "mean"),
                                    avg_r=("pl_r_net", "mean"), sl=("pl_outcome", lambda s: (s == "sl").mean())).round(3)
        print(f"\n--- OOS (test) bot-like {a.eval_tf} by score quintile (model A) ---\n{dec.to_string()}")
        dec.to_csv(out / f"trade_filter_{a.tag}_oos_by_quintile.csv")
    imp = pd.DataFrame({"feature": feats, "gain": last.feature_importance("gain")}).sort_values("gain", ascending=False)
    imp.to_csv(out / f"trade_filter_{a.tag}_importance.csv", index=False)
    print(f"\n--- top features (gain) ---\n{imp.head(25).to_string(index=False)}")
    # ---------------- model B: everything before the split -> the deployable train-only model
    trv = tr | va
    nB = int(n_iter * 1.1)
    treesB, _ = fit(X[trv], y[trv], w[trv], nB, a.bag)
    scB = make_scorer(feats, treesB, trv.sum(), y[trv].mean(), kinds_arr, y, trv)
    pB = scB.score_many(list(meta.kind), X)
    auc_te = roc_auc_score(y[te & ev], pB[te & ev], sample_weight=w[te & ev])
    print(f"\nmodel B (train+val, {nB} it): test {a.eval_tf} AUC_w {auc_te:.4f}")
    sB = sweep(meta[te & ev].reset_index(drop=True), pB[te & ev], "test_modelB")
    print(sB.to_string(index=False))
    sB.to_csv(out / f"trade_filter_{a.tag}_sweep_modelB_test.csv", index=False)
    common = {"model": "gbm", "learner": "lightgbm", "target": "plan_win (partial hit before the zone SL; v7 plan 0.4R/50%/BE/1.5R)",
              "tfs": tfs, "eval_tf": a.eval_tf, "val_window": [a.val_from, a.split], "lgb_params": LGB, "bagged": a.bag,
              "poi_weighted": True, "plan_features": PLAN_FEATURES, "est_spread": EST_SPREAD, "est_commission_oz": EST_COMMISSION_OZ,
              "max_cost_r_train": a.max_cost_r, "version": "v8"}
    scB.meta = {**common, "trained_until": a.split, "lgb_iter": nB, "test_auc_w": round(float(auc_te), 4)}
    scA.meta = {**common, "trained_until": a.val_from, "lgb_iter": n_iter, "note": "train window only (before val)"}
    Path("models").mkdir(exist_ok=True)
    scB.save(f"models/trade_filter_{a.tag}_trainonly.json")
    scA.save(f"models/trade_filter_{a.tag}_trainwindow.json")
    print(f"\nsaved models/trade_filter_{a.tag}_trainonly.json (< {a.split}) and _trainwindow.json (< {a.val_from})")


if __name__ == "__main__":
    main()
