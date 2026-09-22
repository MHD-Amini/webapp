"""v13 - regime-adaptive management (lubot/regime.py + TraderConfig.regime_* / range_*)."""
import math

import numpy as np
import pandas as pd

from lubot.execution import SymbolSpec, TradePlan, TraderConfig, ladder
from lubot.portfolio_sim import PortfolioSimulator
from lubot.regime import daily_bars, latest_metric, metric_series, minute_metric, regime_of

from tests.test_portfolio_sim import bars, cfg, sel, spec  # noqa: F401


def _m1_days(ranges, start="2026-03-02", minutes=60):
    """One synthetic server day per entry of ``ranges``: flat bars whose high-low = the range (close = open = 2000)."""
    frames = []
    for i, r in enumerate(ranges):
        idx = pd.date_range(pd.Timestamp(start) + pd.Timedelta(days=i), periods=minutes, freq="1min")
        df = pd.DataFrame({"open": 2000.0, "high": 2000.0 + r / 2, "low": 2000.0 - r / 2, "close": 2000.0}, index=idx)
        df["volume"] = 1.0
        df["spread"] = 0.3
        frames.append(df)
    return pd.concat(frames)


def test_metric_uses_only_closed_days():
    # 20 days of range 10, then 5 days of range 5: adr_ratio (5/20) of the day AFTER the last one = 5 / mean(10x15,5x5)
    m1 = _m1_days([10.0] * 20 + [5.0] * 5)
    d = daily_bars(m1)
    s = metric_series(d, "adr_ratio", 5, 20)
    assert math.isnan(s.iloc[0]) and math.isnan(s.iloc[19]) and abs(s.iloc[20] - 1.0) < 1e-9   # 20 closed days needed
    # day index 24 (the last one) sees days 4..23 as its long window: 16 x 10 + 4 x 5 = 180 -> mean 9; short = 4 x 5 + 1 x 10 = 30 -> 6
    assert abs(s.iloc[24] - (6.0 / 9.0)) < 1e-9
    # per-minute metric = value of the server day, identical for every bar of that day
    mm = minute_metric(m1, "adr_ratio", 5, 20)
    last_day = mm[-60:]
    assert np.allclose(last_day, s.iloc[24])
    # live helper on a frame whose last row is the (unfinished) current day -> same value as the series for that day
    assert abs(latest_metric(d, "adr_ratio", 5, 20) - s.iloc[24]) < 1e-12
    assert regime_of(0.85, 0.9) == "range" and regime_of(0.95, 0.9) == "trend" and regime_of(float("nan"), 0.9) == "trend"


def test_er_metric():
    # closes 2000 -> +1 every day for 30 days: perfectly efficient -> er = 1
    idx = pd.date_range("2026-03-02", periods=30, freq="1D")
    d = pd.DataFrame({"open": 2000.0, "high": 2001.0, "low": 1999.0, "close": 2000.0 + np.arange(30)}, index=idx)
    s = metric_series(d, "er", 5, 20)
    assert abs(s.iloc[-1] - 1.0) < 1e-9
    # alternating +1 / -1 -> net move 0 or 1 over 5 days -> er small
    d2 = d.copy()
    d2["close"] = 2000.0 + np.where(np.arange(30) % 2 == 0, 1.0, 0.0)
    s2 = metric_series(d2, "er", 5, 20)
    assert s2.iloc[-1] <= 0.21


def test_ladder_switches_only_in_range_regime():
    t = TraderConfig(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"),
                     range_tp_levels=("0.5", "1.0"), range_tp_fracs=("1", "1"), range_sl_after_leg=("0", "x"), range_risk_scale=0.5)
    assert ladder(t) == ((0.6, 1.2, 2.4, 4.8), (0.25, 0.25, 0.25, 0.25))
    assert ladder(t, range_regime=True) == ((0.5, 1.0), (0.5, 0.5))
    d = dict(sel("2026-03-02 10:00"))
    p_trend = TradePlan.from_poi(d, t, SymbolSpec(), regime="trend")
    p_range = TradePlan.from_poi(d, t, SymbolSpec(), regime="range")
    p_off = TradePlan.from_poi(d, t, SymbolSpec())
    assert p_trend.tps == (2003.0, 2006.0, 2012.0, 2024.0) and p_trend.regime == "trend" and p_trend.sl_after_leg == () and p_trend.risk_scale == 1.0
    assert p_range.tps == (2002.5, 2005.0) and p_range.regime == "range" and p_range.sl_after_leg == ("0", "x") and p_range.risk_scale == 0.5
    assert p_off.tps == p_trend.tps and p_off.regime == ""
    # range_tfs restricts the alternative management to the listed timeframes
    t.range_tfs = ("M5",)
    p_m15 = TradePlan.from_poi(d, t, SymbolSpec(), regime="range")
    assert p_m15.tps == p_trend.tps and p_m15.regime == "trend" and p_m15.risk_scale == 1.0


def test_defaults_are_byte_identical_and_range_management_applies_in_sim():
    # 25 synthetic days (20 x range 10 then 5 x range 2 -> adr_ratio < 0.9 on the last day), then a trade day
    m1 = _m1_days([10.0] * 20 + [2.0] * 5)
    # trade day: zone 1995-2000, fill at 2000, run to 2005 (1R) then back to the entry
    day = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.60, 2001), (2001, 2005.2, 2000.5, 2005), (2005, 2005, 2000.0, 2000.2),
                (2000.2, 2000.5, 1999.9, 2000.1)], start=str(m1.index[-1].normalize() + pd.Timedelta(days=1, hours=10)))
    m1 = pd.concat([m1, day])
    ev = [sel(day.index[0])]
    base = cfg(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"), ladder_fallback="merge")
    ref, _ = PortfolioSimulator(m1, pd.DataFrame(ev), base, spec()).run(), None
    # lever ON but the regime is 'trend' (threshold below the metric) -> identical trades
    on_trend = cfg(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"), ladder_fallback="merge",
                   regime_metric="adr_ratio", regime_threshold=0.1, range_tp_levels=("0.5", "1.0"), range_tp_fracs=("1", "1"))
    r2 = PortfolioSimulator(m1, pd.DataFrame(ev), on_trend, spec()).run()
    assert r2.trades.net.tolist() == ref.trades.net.tolist() and r2.trades.regime.tolist() == ["trend"]
    # regime 'range' (threshold 0.9 > metric ~0.3) -> the 2-leg range ladder: 0.5R leg at 2002.5 and 1.0R leg at 2005 both hit
    on_range = cfg(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"), ladder_fallback="merge",
                   regime_metric="adr_ratio", regime_threshold=0.9, range_tp_levels=("0.5", "1.0"), range_tp_fracs=("1", "1"))
    r3 = PortfolioSimulator(m1, pd.DataFrame(ev), on_range, spec()).run()
    t3 = r3.trades
    assert len(t3) == 1 and t3.regime[0] == "range" and t3.outcome[0] == "tp2"
    assert abs(t3.r_gross[0] - 0.75) < 0.02                       # 0.5 x 0.5R + 0.5 x 1.0R
    assert r3.summary()["range_trades"] == 1 and r3.summary()["range_plans"] == 1
    # the reference (G ladder) closes leg 1 at 0.6R and the rest returns to BE -> 0.15R
    assert ref.trades.outcome[0] == "partial_be" and abs(ref.trades.r_gross[0] - 0.15) < 0.02
    # range_risk_scale=0 -> no order in the range regime
    off = cfg(regime_metric="adr_ratio", regime_threshold=0.9, range_risk_scale=0.0)
    r4 = PortfolioSimulator(m1, pd.DataFrame(ev), off, spec()).run()
    assert len(r4.trades) == 0 and any(w == "range regime (no trading)" for _, w in r4.sim.skipped)
    # range_risk_scale=0.5 -> half the lots
    half = cfg(regime_metric="adr_ratio", regime_threshold=0.9, range_risk_scale=0.5)
    r5 = PortfolioSimulator(m1, pd.DataFrame(ev), half, spec()).run()
    assert abs(r5.trades.lots[0] - ref.trades.lots[0] / 2) <= 0.011


def test_range_sl_after_leg_locks_profit():
    # range regime, G ladder kept but stop -> +0.3R after leg 2: price hits 1.2R then falls back to the entry -> exit at +0.3R
    m1 = _m1_days([10.0] * 20 + [2.0] * 5)
    day = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.60, 2001), (2001, 2006.2, 2000.5, 2006), (2006, 2006, 2000.0, 2000.2)],
               start=str(m1.index[-1].normalize() + pd.Timedelta(days=1, hours=10)))
    m1 = pd.concat([m1, day])
    ev = [sel(day.index[0])]
    t = cfg(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"), ladder_fallback="merge",
            regime_metric="adr_ratio", regime_threshold=0.9, range_tp_levels=("0.6", "1.2", "2.4", "4.8"),
            range_tp_fracs=("1", "1", "1", "1"), range_sl_after_leg=("0", "0.3", "x", "x"))
    r = PortfolioSimulator(m1, pd.DataFrame(ev), t, spec()).run()
    tr = r.trades
    # legs: 0.25 x 0.6 + 0.25 x 1.2 + 0.5 x 0.3 = 0.6R
    assert len(tr) == 1 and abs(tr.r_gross[0] - 0.60) < 0.03 and tr.outcome[0] == "trail"
    # same bars without the range schedule (lever off): rest goes back to BE -> 0.45R
    t0 = cfg(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"), ladder_fallback="merge")
    r0 = PortfolioSimulator(m1, pd.DataFrame(ev), t0, spec()).run()
    assert abs(r0.trades.r_gross[0] - 0.45) < 0.03
