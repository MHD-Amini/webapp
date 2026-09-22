#!/usr/bin/env python3
"""v8 step 2 - what separates profitable M5 trade plans from losing ones?  (in-sample only)

Data = models/train_M5.pkl (features known at the sampling bar) + models/plan_labels_M5.pkl
(v7 plan replayed on M1: r_gross / r_net / outcome).  Only rows before --split (2026-03-01)
are used here; the OOS period is reserved for the portfolio backtest.

Two views:
  A. "bot-like" rows: candidates the v7 scanner would actually show (quality-model score of the
     train-only v6 model >= 0.50 and best of its slot) - the population the trader trades.
  B. all filled candidates (bigger sample, for feature ranking).

Reports (study_results/m5_filter_*.csv):
  * cost-aware rules: plan R by zone $ / cost_r / zone-ATR buckets
  * plan R by session, side, kind, quality bucket
  * univariate ranking of every feature: Spearman corr with r_net + top/bottom-quintile R gap
  * validation (Dec25-Feb26) check of the strongest rules to see which survive
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from lubot.quality import QualityScorer, session_of

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def load(tf: str):
    d = pd.read_pickle(f"models/train_{tf}.pkl")
    L = pd.read_pickle(f"models/plan_labels_{tf}.pkl")
    assert len(d) == len(L)
    d = pd.concat([d, L], axis=1)
    d = d[d.pl_filled].reset_index(drop=True)
    d["sel_time"] = pd.to_datetime(d.sel_time)
    d["zone"] = d.top - d.bottom
    d["zone_atr"] = d.zone / d.atr_sel
    d["side"] = np.where(d.direction == "bullish", "buy", "sell")
    d["ny_hour"] = d["f__ny_hour"]
    d["session"] = [session_of(h) for h in d.ny_hour]
    d["poi_key"] = d.tf + "_" + d.id.astype(str)
    return d


def bot_score(d: pd.DataFrame, model: str) -> np.ndarray:
    sc = QualityScorer.load(model)
    fx = d[[c for c in d.columns if c.startswith("f__")]].copy()
    fx.columns = [c[3:] for c in fx.columns]
    return sc.score_many(list(d.kind), fx)


def agg(g):
    return pd.Series({"n": len(g), "pois": g.poi_key.nunique(), "r_net": g.pl_r_net.mean(), "r_gross": g.pl_r_gross.mean(),
                      "win": g.pl_win.mean(), "sl": (g.pl_outcome == "sl").mean(), "tp2": (g.pl_outcome == "tp2").mean(),
                      "cost_r": g.pl_cost_r.median(), "r_net_w": np.average(g.pl_r_net, weights=g.w)})


def by(d, col, label, out):
    t = d.groupby(col, observed=True).apply(agg, include_groups=False).round(3)
    print(f"\n--- {label} ---\n{t.to_string()}")
    t.to_csv(out)
    return t


def univariate(d: pd.DataFrame, out: Path, min_n: int = 500):
    fcols = [c for c in d.columns if c.startswith("f__")]
    rows = []
    y = d.pl_r_net.to_numpy()
    w = d.w.to_numpy()
    for c in fcols:
        x = d[c].to_numpy(dtype=float)
        if np.nanstd(x) == 0 or np.isnan(x).all():
            continue
        rho, _ = spearmanr(x, y, nan_policy="omit")
        try:
            q = pd.qcut(x, 5, labels=False, duplicates="drop")
        except ValueError:
            continue
        if q is None or len(np.unique(q[~np.isnan(q)])) < 3:
            continue
        top = q == np.nanmax(q)
        bot = q == np.nanmin(q)
        rt = np.average(y[top], weights=w[top]) if top.sum() >= min_n else np.nan
        rb = np.average(y[bot], weights=w[bot]) if bot.sum() >= min_n else np.nan
        rows.append({"feature": c[3:], "spearman": rho, "r_top_q": rt, "r_bottom_q": rb, "gap": rt - rb,
                     "n_top": int(top.sum()), "n_bottom": int(bot.sum())})
    u = pd.DataFrame(rows).sort_values("gap", key=lambda s: -s.abs())
    u.to_csv(out, index=False)
    print(f"\n--- univariate (POI-weighted R of top vs bottom quintile), top 30 ---\n{u.head(30).round(4).to_string(index=False)}")
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="M5")
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--val-from", default="2025-12-01")
    ap.add_argument("--model", default="models/quality_model_trainonly.json")
    a = ap.parse_args()
    out = Path("study_results")
    split, vfrom = pd.Timestamp(a.split), pd.Timestamp(a.val_from)
    d = load(a.tf)
    d["q"] = bot_score(d, a.model)
    d["w"] = 1.0 / d.poi_key.map(d.poi_key.value_counts())
    ins = d[d.sel_time < split].copy()
    print(f"[{a.tf}] filled plans: all {len(d)}, in-sample {len(ins)} ({ins.poi_key.nunique()} POIs), "
          f"avg r_net {ins.pl_r_net.mean():.3f}, POI-weighted {np.average(ins.pl_r_net, weights=ins.w):.3f}")
    # ---------------- A. bot-like population
    ins["slot"] = ins.sel_i.astype(str) + "_" + ins.side
    ins["key"] = -ins.q + 0.02 * ins["f__distance_atr"]
    best = ins.sort_values("key").groupby("slot").head(1)
    bot = best[best.q >= 0.50].copy()
    print(f"\nbot-like rows (best of slot, q>=0.50): {len(bot)} ({bot.poi_key.nunique()} POIs)  avg r_net {bot.pl_r_net.mean():.3f}  "
          f"win {bot.pl_win.mean():.3f}  sl {(bot.pl_outcome == 'sl').mean():.3f}  median zone ${bot.zone.median():.2f}  "
          f"median cost_r {bot.pl_cost_r.median():.3f}")
    bot["zone_b"] = pd.cut(bot.zone, [0, 2, 3, 4, 5, 6, 8, 10, 15, 100])
    bot["cost_b"] = pd.cut(bot.pl_cost_r, [0, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.3, 5])
    bot["zatr_b"] = pd.cut(bot.zone_atr, [0, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 20])
    bot["q_b"] = pd.cut(bot.q, [0.5, 0.55, 0.6, 0.65, 1.0])
    by(bot, "zone_b", "bot-like: plan R by zone height $", out / f"{a.tf.lower()}_filter_by_zone.csv")
    by(bot, "cost_b", "bot-like: plan R by cost_r (spread+comm / R)", out / f"{a.tf.lower()}_filter_by_cost.csv")
    by(bot, "zatr_b", "bot-like: plan R by zone / ATR", out / f"{a.tf.lower()}_filter_by_zone_atr.csv")
    by(bot, "q_b", "bot-like: plan R by quality score", out / f"{a.tf.lower()}_filter_by_quality.csv")
    by(bot, "session", "bot-like: plan R by session", out / f"{a.tf.lower()}_filter_by_session.csv")
    by(bot, "side", "bot-like: plan R by side", out / f"{a.tf.lower()}_filter_by_side.csv")
    by(bot, "kind", "bot-like: plan R by kind", out / f"{a.tf.lower()}_filter_by_kind.csv")
    bot["month"] = bot.sel_time.dt.to_period("M").astype(str)
    by(bot, "month", "bot-like: plan R by month", out / f"{a.tf.lower()}_filter_by_month.csv")
    # ---------------- B. univariate ranking on the bot-like rows and on all in-sample rows
    print("\n=========== univariate on bot-like rows (in-sample) ===========")
    u_bot = univariate(bot, out / f"{a.tf.lower()}_filter_univariate_bot.csv", min_n=150)
    print("\n=========== univariate on ALL filled in-sample rows with cost_r <= 0.10 ===========")
    big = ins[ins.pl_cost_r <= 0.10]
    u_all = univariate(big, out / f"{a.tf.lower()}_filter_univariate_all.csv", min_n=500)
    # ---------------- C. do the top rules hold on the validation window?
    tr = bot[bot.sel_time < vfrom]
    va = bot[bot.sel_time >= vfrom]
    print(f"\n=========== rule stability: train(<{vfrom.date()}) n={len(tr)} vs val n={len(va)} ===========")
    rules = {
        "cost_r<=0.05": lambda x: x.pl_cost_r <= 0.05, "cost_r<=0.06": lambda x: x.pl_cost_r <= 0.06,
        "cost_r<=0.08": lambda x: x.pl_cost_r <= 0.08, "zone>=$4": lambda x: x.zone >= 4, "zone>=$5": lambda x: x.zone >= 5,
        "zone>=$6": lambda x: x.zone >= 6, "q>=0.55": lambda x: x.q >= 0.55, "q>=0.60": lambda x: x.q >= 0.60,
        "buy": lambda x: x.side == "buy", "kind!=IMB": lambda x: x.kind != "IMB",
        "zone_atr>=0.75": lambda x: x.zone_atr >= 0.75, "zone_atr<=1.5": lambda x: x.zone_atr <= 1.5,
        "session in london/preny/ny": lambda x: x.session.isin(["london", "preny", "ny"]),
    }
    rows = []
    for name, f in rules.items():
        mt, mv = f(tr), f(va)
        rows.append({"rule": name, "train_keep_%": round(100 * mt.mean(), 1), "train_r": round(tr[mt].pl_r_net.mean(), 3),
                     "train_r_rest": round(tr[~mt].pl_r_net.mean(), 3), "val_keep_%": round(100 * mv.mean(), 1),
                     "val_r": round(va[mv].pl_r_net.mean(), 3), "val_r_rest": round(va[~mv].pl_r_net.mean(), 3),
                     "val_n": int(mv.sum())})
    rs = pd.DataFrame(rows)
    print(rs.to_string(index=False))
    rs.to_csv(out / f"{a.tf.lower()}_filter_rules.csv", index=False)
    # top univariate features: stability of the quintile gap on val
    rows = []
    for feat in u_bot.head(25).feature:
        c = "f__" + feat
        for lab, x in (("train", tr), ("val", va)):
            try:
                q = pd.qcut(x[c], 5, labels=False, duplicates="drop")
            except ValueError:
                continue
            rows.append({"feature": feat, "set": lab, "r_top": x[q == q.max()].pl_r_net.mean(), "r_bottom": x[q == q.min()].pl_r_net.mean()})
    st = pd.DataFrame(rows).pivot(index="feature", columns="set", values=["r_top", "r_bottom"]).round(3)
    st["gap_train"] = st[("r_top", "train")] - st[("r_bottom", "train")]
    st["gap_val"] = st[("r_top", "val")] - st[("r_bottom", "val")]
    st = st.sort_values("gap_train", key=lambda s: -s.abs())
    print(f"\n--- top-25 univariate features: quintile gap train vs val ---\n{st.to_string()}")
    st.to_csv(out / f"{a.tf.lower()}_filter_univariate_stability.csv")


if __name__ == "__main__":
    main()
