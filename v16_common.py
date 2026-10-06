#!/usr/bin/env python3
"""v16 shared helpers: the v15-A trader exactly as shipped in run_trader.bat (strings frozen here AND cross-checked against the
bat by tests/test_v16_levers.py), the v15-A reference numbers (FINAL_BACKTEST_V15.md) and the v16 judge.

    from v16_common import v15a_config, V15A_TRADER, EXPECT_V15A, REF16, judge16, fmt16, load_year16
"""
from __future__ import annotations

import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.data import load_mt5_csv  # noqa: E402
from lubot.execution import TraderConfig  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from v14_common import OOS_SPLIT  # noqa: E402,F401
from v15_common import V14A_CF, V14A_FLT, V14A_TRADER, _max_dd_pct, judge15  # noqa: E402

V15_KEYS = "confluence_memory_min=240,confluent_risk_scale=1.25,plain_risk_scale=0.9"
V15A_TRADER = V14A_TRADER + "," + V15_KEYS
V15A_FLT = V14A_FLT
V15A_CF = V14A_CF
EXPECT_V15A = (448, 297.45, -5.82)      # trades, return %, max DD %

# the v15-A scorecard (FINAL_BACKTEST_V15.md) used by judge16
REF16 = {"trades": 448, "net_$": 29745.0, "OOS_net_$": 19264.0, "return_%": 297.45, "max_dd_%": -5.82, "profit_factor": 2.375,
         "win_%": 74.8, "sl_%": 24.8, "worst_day_%eq": -2.42, "OOS_PF": 2.259, "OOS_win_%": 76.3, "OOS_sl_%": 23.7}

TFS16 = ("M5", "M10", "M15", "M20", "M30", "H1")     # concat order = run_v12_funnel.load_year (stable sort -> event order)


def v15a_config() -> TraderConfig:
    return TraderConfig(trade_filter=V15A_FLT, confluence_filter=V15A_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V15A_TRADER)


def judge16(res, ref: dict | None = None) -> dict:
    """judge15 against the v15-A reference (more trades > 448, more profit > 29 745 $ AND OOS > 19 264 $, loss bands vs v15-A)."""
    j = judge15(res, ref or REF16)
    tr = res.trades
    if len(tr):
        j["rank2_trades"] = int((tr["rank"] > 1).sum()) if "rank" in tr else 0
        j["m20_trades"] = int((tr.tf == "M20").sum())
    return j


def fmt16(name: str, j: dict) -> str:
    return (f"{name:<36} n {j['trades']:4d} net {j['net_$']:8.0f} OOSnet {j['OOS_net_$']:7.0f} DD {j['max_dd_%']:6.2f} PF {j['profit_factor']:5.3f} "
            f"win {j['win_%']:4.1f} sl {j['sl_%']:4.1f} wd {j['worst_day_%eq']:5.2f} | OOS PF {j['OOS_PF']:4.2f} win {j['OOS_win_%']:4.1f} "
            f"sl {j['OOS_sl_%']:4.1f} | r2 {j.get('rank2_trades', 0):3d} m20 {j.get('m20_trades', 0):3d} | mo+ {j['months_pos']}/{j['months']} "
            f"score {j['score']} [{'T' if j['more_trades'] else '-'}{'P' if j['more_profit'] else '-'}{'L' if j['hold_loss'] else '-'}"
            f"{'O' if j['hold_oos'] else '-'}]")


def load_year16(csv: str = "data/xauusd_m1.csv", start: str = "2025-09-01", stream: str = "v16", tfs=TFS16, max_rank: int = 1):
    """M1 year + the recorded selection streams.  ``stream='v10'`` = the v15 streams (rank 1 only); ``'v16'`` = the re-recorded
    top-K streams (study_results/sel_v16_<TF>.pkl) cut at ``max_rank``.  Missing TF files are skipped (M20 has no v10 stream).
    Loading goes through backtest_trader.load_selections per TF + the same concat / stable sort as run_v12_funnel.load_year, so the
    event order (and therefore the simulator result) of the v10 streams is byte-identical to every study before v16."""
    from backtest_trader import load_selections
    m1 = load_mt5_csv(csv)[start:]
    parts = []
    for tf in tfs:
        if not glob.glob(f"study_results/sel_{stream}_{tf}.pkl"):
            continue
        d = load_selections(f"study_results/sel_{stream}_{tf}.pkl")
        if "rank" in d:
            d = d[d["rank"] <= max_rank]
        parts.append(d)
    if not parts:
        raise SystemExit(f"no sel_{stream}_*.pkl streams in study_results/")
    sel = pd.concat(parts, ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    print(f"selections[{stream}]: {len(sel)} events, TFs {sorted(sel.tf.unique())}, {sel.t.min()} -> {sel.t.max()}", flush=True)
    return m1, sel


__all__ = ["v15a_config", "V15A_TRADER", "V15A_FLT", "V15A_CF", "EXPECT_V15A", "REF16", "TFS16", "judge16", "fmt16", "load_year16",
           "OOS_SPLIT", "_max_dd_pct"]
