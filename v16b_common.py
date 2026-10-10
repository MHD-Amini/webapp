#!/usr/bin/env python3
"""v16b shared helpers: the v16-A trader exactly as shipped in run_trader.bat (strings frozen here AND cross-checked against the
bat by tests/test_v16b_levers.py), the v16-A reference numbers (FINAL_BACKTEST_V16.md) and the v16b judge.

    from v16b_common import v16a_config, V16A_TRADER, V16A_FLT, V16A_CF, EXPECT_V16A, REF16B, judge16b, fmt16b, load_year16

v16b spec: REDUCE THE LOSS PERCENTAGE while MAINTAINING THE PROFITABILITY PERCENTAGE.
  less_loss    = stop-out rate < ref  AND  max DD better than ref (less negative)  AND  gross loss $ smaller than ref (|.|)
  hold_profit  = net $ >= 0.97 x ref  AND  PF >= ref - 0.05  AND  OOS net >= 0.97 x OOS ref     (the return % is the net $ / 10 k)
  hold_oos     = OOS stop-out rate < ref  AND  OOS PF >= ref - 0.10  AND  OOS max DD >= ref - 0.5 pt
  no_worse_day = worst day (% eq) >= ref - 0.25 pt
  score 0-4.  Secondary readouts: gross loss $, avg loss $, $ saved vs ref, win %.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import TraderConfig  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from v14_common import OOS_SPLIT  # noqa: E402,F401
from v15_common import _max_dd_pct, judge15  # noqa: E402
from v16_common import TFS16, V15A_CF, V15A_FLT, V15A_TRADER, load_year16  # noqa: E402,F401

V16_KEYS = "tf_risk_scale=M20:0.4"
V16A_TRADER = (V15A_TRADER.replace("keep_replaced_tfs=M10|M15|M30|H1", "keep_replaced_tfs=M10|M15|M20|M30|H1")
               .replace("mart_tfs=M10|M15|M30|H1", "mart_tfs=M10|M15|M20|M30|H1") + "," + V16_KEYS)
V16A_FLT = V15A_FLT + "/M20:min_quality=0.99"
V16A_CF = V15A_CF + "/M20:min_quality=0.63"
V16A_TFS = ("M5", "M10", "M15", "M20", "M30", "H1")
EXPECT_V16A = (467, 301.75, -5.82)      # trades, return %, max DD %

# the v16-A scorecard (FINAL_BACKTEST_V16.md / final_v16/v16A_summary.json) used by judge16b
REF16B = {"trades": 467, "net_$": 30174.57, "OOS_net_$": 19661.2, "return_%": 301.75, "max_dd_%": -5.82, "profit_factor": 2.365,
          "win_%": 75.2, "sl_%": 24.4, "worst_day_%eq": -2.64, "OOS_PF": 2.247, "OOS_win_%": 76.1, "OOS_sl_%": 23.9,
          "OOS_max_dd_%": -5.82, "gross_loss_$": -22101.53, "avg_loss_$": -190.53, "months_pos": 13}


def v16a_config() -> TraderConfig:
    return TraderConfig(trade_filter=V16A_FLT, confluence_filter=V16A_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V16A_TRADER).override("timeframes=" + "|".join(V16A_TFS))


def judge16b(res, ref: dict | None = None) -> dict:
    """judge15 metrics (net, OOS, DD, PF, win, sl, worst day, gross loss ...) + the v16b questions."""
    ref = ref or REF16B
    j = judge15(res, ref)
    tr = res.trades
    s = res.summary()
    j["gross_loss_$"] = round(float(j.get("gross_loss_$", 0.0)), 2)     # from judge (v14_common): sum of the trades with net < 0
    j["avg_loss_$"] = round(float(j.get("avg_loss_$", 0.0)), 2)
    j["m20_trades"] = int((tr.tf == "M20").sum()) if len(tr) else 0
    j["counter_trend_trades"] = int(s.get("counter_trend_trades", 0))
    j["fast_fill_trades"] = int(s.get("fast_fill_trades", 0))
    j["trend_skipped"] = int(s.get("trend_skipped", 0))
    j["fast_cancelled"] = int(s.get("fast_cancelled", 0))
    j["saved_$"] = round(j["gross_loss_$"] - ref["gross_loss_$"], 2)          # > 0 = fewer $ lost than the reference
    j["d_net_$"] = round(j["net_$"] - ref["net_$"], 2)
    j["d_sl_pt"] = round(j["sl_%"] - ref["sl_%"], 1)
    j["less_loss"] = bool(j["sl_%"] < ref["sl_%"] and j["max_dd_%"] > ref["max_dd_%"] and j["gross_loss_$"] > ref["gross_loss_$"])
    j["hold_profit"] = bool(j["net_$"] >= 0.97 * ref["net_$"] and j["profit_factor"] >= ref["profit_factor"] - 0.05
                            and j["OOS_net_$"] >= 0.97 * ref["OOS_net_$"])
    j["hold_oos"] = bool(j["OOS_sl_%"] < ref["OOS_sl_%"] and j["OOS_PF"] >= ref["OOS_PF"] - 0.10
                         and j["OOS_max_dd_%"] >= ref["OOS_max_dd_%"] - 0.5)
    j["no_worse_day"] = bool(j["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.25)
    j["score"] = int(j["less_loss"]) + int(j["hold_profit"]) + int(j["hold_oos"]) + int(j["no_worse_day"])
    for k in ("more_trades", "more_profit", "hold_loss"):      # the v15/v16 questions are not asked here
        j.pop(k, None)
    return j


def fmt16b(name: str, j: dict) -> str:
    return (f"{name:<34} n {j['trades']:4d} net {j['net_$']:8.0f} OOS {j['OOS_net_$']:7.0f} DD {j['max_dd_%']:6.2f} PF {j['profit_factor']:5.3f} "
            f"win {j['win_%']:4.1f} sl {j['sl_%']:4.1f} gl {j['gross_loss_$']:8.0f} wd {j['worst_day_%eq']:5.2f} | OOS PF {j['OOS_PF']:4.2f} "
            f"sl {j['OOS_sl_%']:4.1f} | ct {j.get('counter_trend_trades', 0):3d} ff {j.get('fast_fill_trades', 0):3d} "
            f"skip {j.get('trend_skipped', 0):4d}/{j.get('fast_cancelled', 0):3d} | mo+ {j['months_pos']}/{j['months']} score {j['score']} "
            f"[{'L' if j['less_loss'] else '-'}{'P' if j['hold_profit'] else '-'}{'O' if j['hold_oos'] else '-'}{'D' if j['no_worse_day'] else '-'}]")


__all__ = ["v16a_config", "V16A_TRADER", "V16A_FLT", "V16A_CF", "V16A_TFS", "EXPECT_V16A", "REF16B", "judge16b", "fmt16b",
           "load_year16", "OOS_SPLIT", "_max_dd_pct"]
