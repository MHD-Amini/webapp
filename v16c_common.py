#!/usr/bin/env python3
"""v16c shared helpers: the v16b-A trader exactly as shipped in run_trader.bat (strings frozen here AND cross-checked against the
bat by tests/test_v16c_levers.py), the v16b-A reference numbers (FINAL_BACKTEST_V16B.md / final_v16b/v16bA_summary.json) and the
v16c judge.

    from v16c_common import v16b_config, V16B_TRADER, EXPECT_V16B, REF16C, judge16c, fmt16c, load_year16

v16c spec: REDUCE THE MAX DRAWDOWN PERCENTAGE while MAINTAINING THE PROFITABILITY PERCENTAGE.
  less_dd      = max DD % better than ref by >= 0.25 pt (-5.55 -> >= -5.30)  AND  OOS max DD not worse than ref
                 AND ulcer index <= ref (the DD must be smaller on the whole path, not only at the one deepest point)
  hold_profit  = net $ >= 0.97 x ref  AND  PF >= ref - 0.10  AND  OOS net >= 0.97 x OOS ref   (the return % is the net $ / 10 k)
  hold_loss    = stop-out rate <= ref + 1 pt  AND  gross loss $ <= |ref| x 1.05  AND  worst day >= ref - 0.25 pt  (no regression of v16b)
  hold_oos     = OOS PF >= ref - 0.10  AND  OOS stop-out rate <= ref + 1 pt  AND  months_pos == months
  score 0-4.  Secondary readouts: return/DD ratio, 2nd / 3rd deepest DD episode, DD duration.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import TraderConfig  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from v14_common import OOS_SPLIT  # noqa: E402,F401
from v15_common import _max_dd_pct, judge15  # noqa: E402
from v16_common import load_year16  # noqa: E402,F401
from v16b_common import V16A_CF, V16A_FLT, V16A_TFS, V16A_TRADER  # noqa: E402

V16B_KEYS = "min_fill_age_min=2,regime_side_scale=range:sell:0.5"
V16B_TRADER = V16A_TRADER + "," + V16B_KEYS
V16B_FLT = V16A_FLT
V16B_CF = V16A_CF
V16B_TFS = V16A_TFS
EXPECT_V16B = (446, 338.31, -5.55)      # trades, return %, max DD %

# the v16b-A scorecard (final_v16b/v16bA_summary.json) used by judge16c
REF16C = {"trades": 446, "net_$": 33831.3, "OOS_net_$": 23958.36, "return_%": 338.31, "max_dd_%": -5.55, "max_dd_$": -2257.02,
          "profit_factor": 2.999, "win_%": 75.8, "sl_%": 23.8, "worst_day_%eq": -2.34, "OOS_PF": 3.124, "OOS_win_%": 78.9,
          "OOS_sl_%": 21.1, "OOS_max_dd_%": -5.55, "gross_loss_$": -16921.22, "avg_loss_$": -156.68, "months_pos": 13,
          "ulcer": 1.691, "return_over_dd": 60.96, "sharpe_daily": 5.98}
DD_IMPROVE_PT = 0.25        # the DD has to be better by at least this many points to count (noise band of one re-sized trade)


def v16b_config() -> TraderConfig:
    return TraderConfig(trade_filter=V16B_FLT, confluence_filter=V16B_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V16B_TRADER).override("timeframes=" + "|".join(V16B_TFS))


def dd_episodes(eq: pd.Series, top: int = 3) -> list[dict]:
    """the deepest drawdown episodes of an equity path: start (last peak), trough, recovery, depth %, duration (days)."""
    if not len(eq):
        return []
    dd = eq / eq.cummax() - 1.0
    eps, in_dd, start, mn, mt = [], False, None, 0.0, None
    for t, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start, mn, mt = True, t, v, t
        elif v < 0:
            if v < mn:
                mn, mt = v, t
        elif in_dd:
            in_dd = False
            eps.append({"start": start, "trough": mt, "end": t, "depth_%": round(100 * mn, 2),
                        "days": round((t - start).total_seconds() / 86400, 1)})
    if in_dd:
        eps.append({"start": start, "trough": mt, "end": None, "depth_%": round(100 * mn, 2),
                    "days": round((dd.index[-1] - start).total_seconds() / 86400, 1)})
    return sorted(eps, key=lambda e: e["depth_%"])[:top]


def judge16c(res, ref: dict | None = None) -> dict:
    """judge15 metrics (net, OOS, DD, PF, win, sl, worst day, gross loss, ulcer ...) + the v16c questions."""
    ref = ref or REF16C
    j = judge15(res, ref)
    s = res.summary()
    j["gross_loss_$"] = round(float(j.get("gross_loss_$", 0.0)), 2)
    j["avg_loss_$"] = round(float(j.get("avg_loss_$", 0.0)), 2)
    j["ulcer"] = float(j.get("ulcer", s.get("ulcer", 0.0)))
    j["return_over_dd"] = round(j["return_%"] / abs(j["max_dd_%"]), 2) if j["max_dd_%"] else float("inf")
    eps = dd_episodes(res.equity.equity, 3)
    for i, e in enumerate(eps):
        j[f"dd{i + 1}_%"] = e["depth_%"]
        j[f"dd{i + 1}_days"] = e["days"]
        j[f"dd{i + 1}_start"] = str(e["start"])[:10]
    for i in range(len(eps), 3):
        j[f"dd{i + 1}_%"], j[f"dd{i + 1}_days"], j[f"dd{i + 1}_start"] = 0.0, 0.0, ""
    j["fast_cancelled"] = int(s.get("fast_cancelled", 0))
    for k in ("dd_cancelled", "dd_scaled", "dd_days", "cluster_skipped", "cluster_scaled", "mfe_lock_hits", "cooldown_skipped"):
        j[k] = int(s.get(k, 0))
    j["d_dd_pt"] = round(j["max_dd_%"] - ref["max_dd_%"], 2)                # > 0 = less drawdown than the reference
    j["d_net_$"] = round(j["net_$"] - ref["net_$"], 2)
    j["d_sl_pt"] = round(j["sl_%"] - ref["sl_%"], 1)
    j["less_dd"] = bool(j["max_dd_%"] >= ref["max_dd_%"] + DD_IMPROVE_PT and j["OOS_max_dd_%"] >= ref["OOS_max_dd_%"]
                        and j["ulcer"] <= ref["ulcer"])
    j["hold_profit"] = bool(j["net_$"] >= 0.97 * ref["net_$"] and j["profit_factor"] >= ref["profit_factor"] - 0.10
                            and j["OOS_net_$"] >= 0.97 * ref["OOS_net_$"])
    j["hold_loss"] = bool(j["sl_%"] <= ref["sl_%"] + 1.0 and abs(j["gross_loss_$"]) <= abs(ref["gross_loss_$"]) * 1.05
                          and j["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.25)
    j["hold_oos"] = bool(j["OOS_PF"] >= ref["OOS_PF"] - 0.10 and j["OOS_sl_%"] <= ref["OOS_sl_%"] + 1.0
                         and j["months_pos"] == j["months"])
    j["score"] = int(j["less_dd"]) + int(j["hold_profit"]) + int(j["hold_loss"]) + int(j["hold_oos"])
    for k in ("more_trades", "more_profit"):      # the v15/v16 questions are not asked here
        j.pop(k, None)
    return j


def fmt16c(name: str, j: dict) -> str:
    return (f"{name:<34} n {j['trades']:4d} net {j['net_$']:8.0f} OOS {j['OOS_net_$']:7.0f} DD {j['max_dd_%']:6.2f} "
            f"dd2 {j.get('dd2_%', 0):5.2f} ulc {j['ulcer']:5.3f} PF {j['profit_factor']:5.3f} win {j['win_%']:4.1f} sl {j['sl_%']:4.1f} "
            f"gl {j['gross_loss_$']:7.0f} wd {j['worst_day_%eq']:5.2f} | OOS DD {j['OOS_max_dd_%']:5.2f} PF {j['OOS_PF']:4.2f} "
            f"sl {j['OOS_sl_%']:4.1f} | mo+ {j['months_pos']}/{j['months']} score {j['score']} "
            f"[{'D' if j['less_dd'] else '-'}{'P' if j['hold_profit'] else '-'}{'L' if j['hold_loss'] else '-'}{'O' if j['hold_oos'] else '-'}]")


__all__ = ["v16b_config", "V16B_TRADER", "V16B_FLT", "V16B_CF", "V16B_TFS", "V16B_KEYS", "EXPECT_V16B", "REF16C", "DD_IMPROVE_PT",
           "judge16c", "fmt16c", "dd_episodes", "load_year16", "OOS_SPLIT", "_max_dd_pct"]
