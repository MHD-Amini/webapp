#!/usr/bin/env python3
"""v14 shared helpers: the v13-A trader exactly as shipped in run_trader.bat, the year loader, the judge.

    from v14_common import v13a_config, load_year, judge, EXPECT_V13A
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from run_v10_study import BASE  # noqa: E402
from run_v12_funnel import load_year  # noqa: E402,F401
from run_v13_diag import V12A_CF, V12A_FLT  # noqa: E402

# --- v13-A exactly as shipped in run_trader.bat (verified by verify_bat_v13.py)
V13A_TRADER = ("tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,"
               "keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1,regime_metric=adr_ratio,regime_threshold=1.0,"
               "regime_short=5,regime_long=20,range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1,range_sl_after_leg=0|0.3|x|x")
EXPECT_V13A = (430, 188.65, -5.45)      # trades, return %, max DD %
OOS_SPLIT = "2026-03-01"
CSV = "data/xauusd_m1.csv"


def v13a_config() -> TraderConfig:
    return TraderConfig(trade_filter=V12A_FLT, confluence_filter=V12A_CF, max_daily_loss_pct=4.5,
                        max_total_loss_pct=9.0).override(BASE).override(V13A_TRADER)


def daily_pnl(tr: pd.DataFrame) -> pd.Series:
    return tr.set_index("close_time").net.resample("1D").sum()


def judge(res, start_balance: float = 10_000.0) -> dict:
    """The v14 scorecard of a simulator result: return / DD / PF and the LOSS side (what the martingale must reduce)."""
    s = res.summary()
    tr = res.trades
    out = {k: s.get(k) for k in ("trades", "return_%", "max_dd_%", "max_dd_$", "profit_factor", "win_%", "sl_%", "total_R",
                                 "avg_R", "sharpe_daily", "end_balance", "daily_halts", "halted", "stopped_out")}
    if not len(tr):
        return out
    losses = tr[tr.net < 0]
    wins = tr[tr.net > 0]
    d = daily_pnl(tr)
    d = d[d != 0]
    eq = res.equity.equity
    tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
    mo = tr.groupby("month").net.sum()
    mo_r = tr.groupby("month").r_net.sum()
    oos = tr[tr.close_time >= OOS_SPLIT]
    is_ = tr[tr.close_time < OOS_SPLIT]
    pf = lambda x: (x[x.net > 0].net.sum() / abs(x[x.net < 0].net.sum())) if (x.net < 0).any() else float("inf")
    # loss-side metrics
    out.update({
        "gross_loss_$": round(losses.net.sum(), 2),
        "gross_win_$": round(wins.net.sum(), 2),
        "avg_loss_$": round(losses.net.mean(), 2) if len(losses) else 0.0,
        "avg_loss_R": round(losses.r_net.mean(), 3) if len(losses) else 0.0,
        "worst_trade_$": round(tr.net.min(), 2),
        "worst_trade_%eq": round(100 * tr.net.min() / start_balance, 2),
        "worst_day_$": round(d.min(), 2) if len(d) else 0.0,
        "worst_day_%": round(100 * d.min() / start_balance, 2) if len(d) else 0.0,
        "neg_days": int((d < 0).sum()),
        "neg_days_%": round(100 * (d < 0).mean(), 1) if len(d) else 0.0,
        "max_dd_R": s.get("max_dd_R"),
        "ulcer": round(float(np.sqrt(((eq / eq.cummax() - 1) ** 2).mean()) * 100), 3),
        "max_risk_$": round(tr.risk_money.max(), 2),
        "max_risk_%start": round(100 * tr.risk_money.max() / start_balance, 2),
        "avg_risk_$": round(tr.risk_money.mean(), 2),
        "months_pos": int((mo > 0).sum()), "months": int(len(mo)),
        "worst_month_$": round(mo.min(), 2), "worst_month_R": round(mo_r.min(), 2),
        "apr26_R": round(mo_r.get("2026-04", 0.0), 2), "sep25_R": round(mo_r.get("2025-09", 0.0), 2),
        "IS_R": round(is_.r_net.sum(), 2), "IS_PF": round(pf(is_), 3),
        "OOS_R": round(oos.r_net.sum(), 2), "OOS_PF": round(pf(oos), 3), "OOS_net_$": round(oos.net.sum(), 2),
        "max_consec_losses": int(_max_run(tr.net < 0)),
        "mart_trades": int((tr.mart_step > 0).sum()) if "mart_step" in tr else 0,
        "mart_down_trades": int((tr.mart_step < 0).sum()) if "mart_step" in tr else 0,
        "grid_leg_trades": int(tr.grid_leg.sum()) if "grid_leg" in tr else 0,
        "return_over_dd": round(s["return_%"] / abs(s["max_dd_%"]), 2) if s.get("max_dd_%") else float("nan"),
        "loss_per_return": round(abs(losses.net.sum()) / max(tr.net.sum(), 1.0), 3),
    })
    # worst day / max risk RELATIVE to the equity at the time (the start-balance versions above overstate late-year values)
    eq_d = eq.resample("1D").first().ffill()
    rel = (d / eq_d.reindex(d.index).ffill() * 100).dropna()
    out["worst_day_%eq"] = round(float(rel.min()), 2) if len(rel) else 0.0
    eq_at = eq.reindex(tr.entry_time, method="ffill").to_numpy()
    out["max_risk_%eq"] = round(float((tr.risk_money.to_numpy() / eq_at * 100).max()), 2)
    out["worst_trade_%eq"] = round(float((tr.net.to_numpy() / eq_at * 100).min()), 2)
    return out


def _max_run(mask: pd.Series) -> int:
    best = cur = 0
    for v in mask.to_numpy():
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def fmt_judge(name: str, j: dict) -> str:
    return (f"{name:<40} n {j['trades']:4d} ret {j['return_%']:+7.2f}% DD {j['max_dd_%']:6.2f} PF {j['profit_factor']:5.3f} "
            f"win {j['win_%']:4.1f} | loss$ {j['gross_loss_$']:9.0f} avgL$ {j['avg_loss_$']:7.1f} worstT {j['worst_trade_%eq']:5.2f}% "
            f"worstD {j['worst_day_%eq']:5.2f}% negD {j['neg_days']:3d} ulcer {j['ulcer']:5.3f} maxRisk {j['max_risk_%eq']:5.2f}% "
            f"| OOS_PF {j['OOS_PF']:4.2f} mo+ {j['months_pos']}/{j['months']} r/dd {j['return_over_dd']:5.1f} up {j['mart_trades']:3d} dn {j['mart_down_trades']:3d} deep {j['grid_leg_trades']:3d}")
