#!/usr/bin/env python3
"""v8 step 1 - label every training candidate with the outcome of the v7 TRADE PLAN.

The quality model was trained on "P(bounce >= 1 ATR before violation)".  The trader,
however, risks the ZONE HEIGHT (limit at the near edge, SL at the far edge), takes half
at +0.4R, moves to break-even and targets +1.5R - on the ask/bid with the real spread.
Those two targets are different, especially on M5 where the zone is only a few dollars
and the spread + commission eat ~0.07R per trade.

For every row of models/train_<TF>.pkl (one row = one candidate at one sampling bar,
features known at that bar) this script replays the plan on the M1 bars:

    order live from the close of the sampling bar, fill accepted for ``wait`` TF bars
    (same horizon the bounce label used), position walked for ``hold`` TF bars,
    mechanics identical to lubot/portfolio_sim.py (verified by tests/test_plan_replay.py).

Output models/plan_labels_<TF>.pkl (aligned by position with the training frame) with:
    pl_filled, pl_fill_minute, pl_entry, pl_outcome, pl_r_gross, pl_hold_min, pl_mfe_r, pl_mae_r,
    pl_spread_fill, pl_cost_r (= (spread_at_fill + commission$/oz) / R), pl_r_net (commission
    subtracted; the spread is already inside r_gross through the ask/bid mechanics), pl_win, pl_partial

Resumable: per-TF output; a partial file <out>.part.pkl is written every ``--checkpoint``
rows and picked up on restart.

    python label_plan_outcomes.py --csv data/xauusd_m1.csv --tf M5
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pandas as pd

from lubot import load_mt5_csv
from lubot.config import TIMEFRAME_MINUTES
from lubot.plan_replay import PlanReplayer

COLS = ["pl_filled", "pl_fill_minute", "pl_entry", "pl_outcome", "pl_r_gross", "pl_hold_min", "pl_mfe_r", "pl_mae_r",
        "pl_spread_fill", "pl_cost_r", "pl_partial", "pl_through"]


def _frame(store, n):
    return pd.DataFrame({c: store[c] for c in COLS}, index=range(n))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--tf", required=True)
    ap.add_argument("--train", default=None, help="models/train_<TF>.pkl")
    ap.add_argument("--out", default=None, help="models/plan_labels_<TF>.pkl")
    ap.add_argument("--wait", type=int, default=300, help="fill window in TF bars (same as the bounce label)")
    ap.add_argument("--hold", type=int, default=300, help="max holding time in TF bars after the fill")
    ap.add_argument("--commission", type=float, default=7.0, help="$ per lot round turn -> $/oz = /100")
    ap.add_argument("--sl-slippage", type=float, default=0.10)
    ap.add_argument("--checkpoint", type=int, default=5000)
    a = ap.parse_args(argv)
    train = a.train or f"models/train_{a.tf}.pkl"
    out = a.out or f"models/plan_labels_{a.tf}.pkl"
    if os.path.exists(out):
        print(f"{out} exists - skip")
        return
    t0 = time.time()
    m1 = load_mt5_csv(a.csv)
    idx = m1.index.values.astype("datetime64[ns]")
    rep = PlanReplayer(m1.open.to_numpy(float), m1.high.to_numpy(float), m1.low.to_numpy(float),
                       m1.close.to_numpy(float), m1.spread.to_numpy(float), sl_slippage=a.sl_slippage)
    print(f"M1 {len(m1)} bars {m1.index[0]} -> {m1.index[-1]} ({time.time() - t0:.0f}s)", flush=True)
    d = pd.read_pickle(train)
    meta = d[["tf", "id", "kind", "direction", "top", "bottom", "sel_i", "sel_time", "reached"]].copy()
    del d
    meta["sel_time"] = pd.to_datetime(meta.sel_time)
    tfm = TIMEFRAME_MINUTES[a.tf]
    n = len(meta)
    part = out + ".part.pkl"
    store = {c: np.full(n, np.nan, dtype=object) for c in COLS}
    start = 0
    if os.path.exists(part):
        res = pd.read_pickle(part)
        start = int(res.attrs.get("done", 0))
        for c in COLS:
            store[c] = res[c].to_numpy(object)
        print(f"resuming at row {start}/{n}", flush=True)
    comm_oz = a.commission / 100.0
    sel_t = meta.sel_time.values.astype("datetime64[ns]")
    # order live from the CLOSE of the sampling bar (= first moment a live bot could act)
    live_from = np.searchsorted(idx, sel_t + np.timedelta64(tfm, "m"), side="left")
    tops, bots = meta.top.to_numpy(float), meta.bottom.to_numpy(float)
    dirs, reached = meta.direction.to_numpy(), meta.reached.to_numpy()
    tl = time.time()
    for r in range(start, n):
        if not reached[r]:
            store["pl_filled"][r] = False
            continue
        buy = dirs[r] == "bullish"
        limit = tops[r] if buy else bots[r]
        sl = bots[r] if buy else tops[r]
        m0 = int(live_from[r])
        rr = rep.replay(buy, limit, sl, m0, m0 + a.wait * tfm, m0 + (a.wait + a.hold) * tfm)
        store["pl_filled"][r] = rr.filled
        store["pl_through"][r] = rr.through_at_start
        if rr.filled:
            risk = abs(limit - sl)
            store["pl_fill_minute"][r] = rr.fill_minute
            store["pl_entry"][r] = rr.entry
            store["pl_outcome"][r] = rr.outcome
            store["pl_r_gross"][r] = rr.r_gross
            store["pl_hold_min"][r] = rr.close_minute - rr.fill_minute
            store["pl_mfe_r"][r] = rr.mfe_r
            store["pl_mae_r"][r] = rr.mae_r
            store["pl_spread_fill"][r] = rr.spread_fill
            store["pl_cost_r"][r] = (rr.spread_fill + comm_oz) / risk if risk > 0 else np.nan
            store["pl_partial"][r] = rr.partial
        if (r + 1) % a.checkpoint == 0:
            res = _frame(store, n)
            res.attrs["done"] = r + 1
            res.to_pickle(part + ".tmp")
            os.replace(part + ".tmp", part)
            nf = int(sum(1 for x in store["pl_filled"][:r + 1] if x is True))
            print(f"  [{a.tf}] {r + 1}/{n}  filled so far {nf}  {time.time() - tl:.0f}s", flush=True)
    res = _frame(store, n)
    res["pl_filled"] = res.pl_filled.map(lambda x: x is True).astype(bool)
    res["pl_partial"] = res.pl_partial.map(lambda x: x is True).astype(bool)
    res["pl_through"] = res.pl_through.map(lambda x: x is True).astype(bool)
    res["pl_outcome"] = res.pl_outcome.fillna("").astype(str)
    for c in ("pl_fill_minute", "pl_entry", "pl_r_gross", "pl_hold_min", "pl_mfe_r", "pl_mae_r", "pl_spread_fill", "pl_cost_r"):
        res[c] = pd.to_numeric(res[c], errors="coerce")
    risk = np.abs(tops - bots)
    res["pl_r_net"] = res.pl_r_gross - comm_oz / np.where(risk > 0, risk, np.nan)
    res["pl_win"] = res.pl_r_net > 0
    res.attrs = {"tf": a.tf, "wait": a.wait, "hold": a.hold, "commission_per_lot": a.commission, "sl_slippage": a.sl_slippage}
    res.to_pickle(out + ".tmp")
    os.replace(out + ".tmp", out)
    if os.path.exists(part):
        os.remove(part)
    f = res[res.pl_filled]
    print(f"[{a.tf}] rows {n}, reached {int(reached.sum())}, filled {len(f)}, skipped (price already through) "
          f"{int(res.pl_through.sum())} ({time.time() - t0:.0f}s)")
    if len(f):
        print(f"  outcome mix: {f.pl_outcome.value_counts(normalize=True).round(3).to_dict()}")
        print(f"  avg R gross {f.pl_r_gross.mean():.4f}  net {f.pl_r_net.mean():.4f}  win {f.pl_win.mean():.3f}  "
              f"cost_r median {f.pl_cost_r.median():.4f}")


if __name__ == "__main__":
    main()
