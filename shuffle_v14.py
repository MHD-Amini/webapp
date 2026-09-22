#!/usr/bin/env python3
"""v14 step 4a - SHUFFLE / BOOTSTRAP test of the sequence-sizing finalists.

A martingale's result depends on the ORDER of the trades.  Question: is the gain of a variant over the reference a property of
the trade population (robust) or of the one historical order (luck)?

Method (sequence-only re-sizing, no re-simulation; the same approximation as the classic-martingale table of the diagnosis):
  take the REFERENCE trade list (r_net per trade, in close order); for a variant's sizing rule (mode / mult / cap / max risk /
  gates / ungated scale) replay the sizing rule on the sequence with compounding on equity -> return, max DD, gross loss.
  Then (a) shuffle the order N times, (b) block-bootstrap (blocks of 10 trades) N times -> distribution of return / DD /
  gross loss for the variant AND for flat sizing on the SAME shuffled sequences -> the paired difference is what matters.
Reports the p-value of "variant beats flat" on return/DD and on gross loss, and the rank of the historical order inside the
shuffled distribution (a historical rank in the top 5 % = the historical order was lucky).

    python3 shuffle_v14.py --variants MU_1.5_c3_r3_htfbuy_dn0.5,FIB_c3_r3_htfbuy -n 2000  -> study_results/v14_shuffle.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import TraderConfig  # noqa: E402
from lubot.martingale import Martingale  # noqa: E402
from run_v14_levers import variants  # noqa: E402
from v14_common import v13a_config  # noqa: E402

OUT = Path("study_results/v14_levers")


class _P:
    """Minimal plan stand-in for Martingale.gated / scale."""
    __slots__ = ("tf", "side", "quality", "regime", "risk_scale")

    def __init__(self, tf, side, quality, regime, risk_scale):
        self.tf, self.side, self.quality, self.regime, self.risk_scale = tf, side, quality, regime, risk_scale


def replay_sizing(tr: pd.DataFrame, tcfg: TraderConfig, order: np.ndarray, start: float = 10_000.0) -> dict:
    """Re-size the reference trades in the given order with the variant's martingale rule.  Returns return %, max DD %, gross loss $."""
    m = Martingale(tcfg)
    eq, peak, dd, loss = start, start, 0.0, 0.0
    r = tr.r_net.to_numpy()
    tf = tr.tf.to_numpy()
    side = tr.side.to_numpy()
    q = tr.quality.to_numpy()
    rg = tr.regime.to_numpy()
    rs = tr.risk_scale.to_numpy()
    base = tcfg.risk_pct / 100.0
    for i in order:
        p = _P(tf[i], side[i], q[i], rg[i], rs[i])
        scale, step = m.scale(p, eq) if m.on else (1.0, 0)
        risk = eq * base * rs[i] * scale
        pnl = risk * r[i]
        eq += pnl
        if pnl < 0:
            loss += pnl
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
        m.on_close(tf[i], pnl, r[i], step)
    return {"ret": 100 * (eq / start - 1), "dd": 100 * dd, "loss": loss}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", required=True)
    ap.add_argument("-n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    ref = pd.read_csv(OUT / "ref_trades.csv", parse_dates=["close_time"]).sort_values("close_time").reset_index(drop=True)
    ref["risk_scale"] = (ref.risk_money / (ref.risk_money.max()))          # placeholder, replaced below
    # risk_scale of the reference plan = risk_money / (1 % of the equity at entry) -> range_risk_scale etc. (all 1.0 in v13-A)
    ref["risk_scale"] = 1.0
    allv = variants()
    rng = np.random.default_rng(a.seed)
    n = len(ref)
    orders_shuf = [rng.permutation(n) for _ in range(a.n)]
    blocks = [np.arange(i, min(i + 10, n)) for i in range(0, n, 10)]
    orders_boot = [np.concatenate([blocks[k] for k in rng.integers(0, len(blocks), len(blocks))]) for _ in range(a.n)]
    hist = np.arange(n)
    flat = v13a_config()
    rows = []
    for name in a.variants.split(","):
        tcfg = v13a_config().override(allv[name])
        if not tcfg.mart_mode:
            print(f"{name}: not a sequence-sizing variant (grid only) - skipped")
            continue
        h_v, h_f = replay_sizing(ref, tcfg, hist), replay_sizing(ref, flat, hist)
        res = {"name": name, "hist_ret": round(h_v["ret"], 1), "hist_dd": round(h_v["dd"], 2), "hist_loss": round(h_v["loss"], 0),
               "flat_ret": round(h_f["ret"], 1), "flat_dd": round(h_f["dd"], 2), "flat_loss": round(h_f["loss"], 0)}
        for tag, orders in (("shuf", orders_shuf), ("boot", orders_boot)):
            dv = np.array([[*replay_sizing(ref, tcfg, o).values()] for o in orders])
            df_ = np.array([[*replay_sizing(ref, flat, o).values()] for o in orders])
            rd_v, rd_f = dv[:, 0] / np.abs(dv[:, 1]), df_[:, 0] / np.abs(df_[:, 1])
            res.update({
                f"{tag}_ret_med": round(float(np.median(dv[:, 0])), 1), f"{tag}_dd_med": round(float(np.median(dv[:, 1])), 2),
                f"{tag}_loss_med": round(float(np.median(dv[:, 2])), 0),
                f"{tag}_flat_ret_med": round(float(np.median(df_[:, 0])), 1), f"{tag}_flat_dd_med": round(float(np.median(df_[:, 1])), 2),
                f"{tag}_p_ret>flat": round(float((dv[:, 0] > df_[:, 0]).mean()), 3),
                f"{tag}_p_dd_better": round(float((dv[:, 1] > df_[:, 1]).mean()), 3),
                f"{tag}_p_rd>flat": round(float((rd_v > rd_f).mean()), 3),
                f"{tag}_p_loss_less": round(float((dv[:, 2] > df_[:, 2]).mean()), 3),
                f"{tag}_hist_rank_ret": round(float((dv[:, 0] < h_v["ret"]).mean()), 3),        # 0.95 = historical order in the top 5 %
                f"{tag}_hist_rank_rd": round(float((rd_v < h_v["ret"] / abs(h_v["dd"])).mean()), 3),
                f"{tag}_dd_p95": round(float(np.percentile(dv[:, 1], 5)), 2), f"{tag}_flat_dd_p95": round(float(np.percentile(df_[:, 1], 5)), 2),
            })
        rows.append(res)
        print(json.dumps(res), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv("study_results/v14_shuffle.csv", index=False)
    pd.set_option("display.width", 300)
    print(df.T.to_string())


if __name__ == "__main__":
    main()
