#!/usr/bin/env python3
"""v15 shared helpers: the v14-A trader exactly as shipped in run_trader.bat (strings frozen here AND cross-checked against the
bat by tests/test_v15_levers.py), the reference numbers, and the v15 judge (more trades / more profit / loss percentage held).

    from v15_common import v14a_config, V14A_TRADER, EXPECT_V14A, judge15
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import TraderConfig  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from run_v13_diag import V12A_CF, V12A_FLT  # noqa: E402
from v14_common import OOS_SPLIT, V13A_TRADER, judge  # noqa: E402,F401

V14A_MART = ("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf,mart_tfs=M10|M15|M30|H1,"
             "mart_sides=buy,mart_ungated_scale=0.5")
V14A_TRADER = V13A_TRADER + "," + V14A_MART
V14A_FLT = V12A_FLT
V14A_CF = V12A_CF
EXPECT_V14A = (430, 227.53, -5.84)      # trades, return %, max DD %

# the reference scorecard (FINAL_BACKTEST_V14.md) used by the judge
REF = {"trades": 430, "net_$": 22753.0, "OOS_net_$": 14524.0, "return_%": 227.53, "max_dd_%": -5.84, "profit_factor": 2.249,
       "win_%": 74.7, "sl_%": 24.9, "worst_day_%eq": -1.99, "OOS_PF": 2.154, "OOS_win_%": None, "OOS_sl_%": None}


def v14a_config() -> TraderConfig:
    return TraderConfig(trade_filter=V14A_FLT, confluence_filter=V14A_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V14A_TRADER)


def judge15(res, ref: dict | None = None) -> dict:
    """v14 judge + the v15 questions: more trades?  more profit (full year AND OOS)?  loss percentage held (full year AND OOS)?"""
    out = judge(res)
    tr = res.trades
    ref = ref or REF
    if not len(tr):
        return out
    oos = tr[tr.close_time >= OOS_SPLIT]
    out["net_$"] = round(float(tr.net.sum()), 2)
    out["OOS_trades"] = int(len(oos))
    out["OOS_win_%"] = round(100 * float((oos.net > 0).mean()), 1) if len(oos) else float("nan")
    out["OOS_sl_%"] = round(100 * float((oos.outcome == "sl").mean()), 1) if len(oos) else float("nan")
    out["OOS_max_dd_%"] = _max_dd_pct(res.equity.equity[OOS_SPLIT:]) if len(oos) else float("nan")
    out["more_trades"] = bool(out["trades"] > ref["trades"])
    out["more_profit"] = bool(out["net_$"] > ref["net_$"] and out["OOS_net_$"] > ref["OOS_net_$"])
    # "loss percentage maintained": stop-out rate <= ref + 2 pt, win rate >= ref - 3 pt, max DD <= ref + 0.5 pt,
    # worst day >= ref - 0.5 pt, PF >= ref - 0.10
    out["hold_loss"] = bool(out["sl_%"] <= ref["sl_%"] + 2.0 and out["win_%"] >= ref["win_%"] - 3.0
                            and out["max_dd_%"] >= ref["max_dd_%"] - 0.5 and out["worst_day_%eq"] >= ref["worst_day_%eq"] - 0.5
                            and out["profit_factor"] >= ref["profit_factor"] - 0.10)
    ref_oos_sl = ref.get("OOS_sl_%") or 25.4
    ref_oos_win = ref.get("OOS_win_%") or 74.6
    out["hold_oos"] = bool(out["OOS_sl_%"] <= ref_oos_sl + 2.0 and out["OOS_win_%"] >= ref_oos_win - 3.0
                           and out["OOS_PF"] >= ref["OOS_PF"] - 0.10 and out["max_dd_%"] >= ref["max_dd_%"] - 0.5)
    out["score"] = int(out["more_trades"]) + int(out["more_profit"]) + int(out["hold_loss"]) + int(out["hold_oos"])
    return out


def _max_dd_pct(eq: pd.Series) -> float:
    if not len(eq):
        return float("nan")
    dd = eq / eq.cummax() - 1.0
    return round(float(dd.min() * 100), 2)


def fmt15(name: str, j: dict) -> str:
    return (f"{name:<34} n {j['trades']:4d} net {j['net_$']:8.0f} OOSnet {j['OOS_net_$']:7.0f} DD {j['max_dd_%']:6.2f} PF {j['profit_factor']:5.3f} "
            f"win {j['win_%']:4.1f} sl {j['sl_%']:4.1f} wd {j['worst_day_%eq']:5.2f} | OOS PF {j['OOS_PF']:4.2f} win {j['OOS_win_%']:4.1f} "
            f"sl {j['OOS_sl_%']:4.1f} | mo+ {j['months_pos']}/{j['months']} score {j['score']} "
            f"[{'T' if j['more_trades'] else '-'}{'P' if j['more_profit'] else '-'}{'L' if j['hold_loss'] else '-'}{'O' if j['hold_oos'] else '-'}]")
