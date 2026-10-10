"""v16b - loss-reduction levers: daily trend gate (trend_sma / trend_sides / trend_mode), impulsive-arrival guard
(min_fill_age_min / fast_fill_mode) and regime x side sizing (regime_side_scale).  Defaults must be byte-identical to v16
(parity on the full year is checked by smoke_v16b.py: v16-A = 467 / +301.75 / -5.82)."""
import numpy as np
import pandas as pd

from lubot.execution import TraderConfig
from lubot.regime import counter_trend, daily_bars, latest_trend, minute_trend, trend_series
from tests.test_portfolio_sim import bars, cfg, run, sel, spec  # noqa: F401

# a minute index that spans several server days so the daily trend exists: 4 flat days, then the test day
def _days_then(seq, start_day="2026-03-02", closes=(2000, 2010, 2020, 2030), spread=0.3):
    frames = []
    for i, c in enumerate(closes):
        d = pd.Timestamp(start_day) + pd.Timedelta(days=i)
        frames.append(bars([(c, c + 1, c - 1, c)] * 3, start=d + pd.Timedelta(hours=10), spread=spread))
    frames.append(bars(seq, start=pd.Timestamp(start_day) + pd.Timedelta(days=len(closes), hours=10), spread=spread))
    return pd.concat(frames)


def test_v16b_defaults_are_off_and_override_parses():
    c = TraderConfig()
    assert (c.trend_sma, c.trend_sides, c.trend_mode, c.trend_risk_scale, c.trend_tfs, c.trend_regime) == (0, ("sell",), "skip", 0.5, (), "")
    assert (c.min_fill_age_min, c.fast_fill_mode, c.fast_fill_scale, c.fast_fill_tfs, c.fast_fill_regime, c.regime_side_scale) == \
        (0, "cancel", 0.5, (), "", "")
    c.override("trend_sma=20,trend_sides=sell|buy,trend_mode=scale,trend_risk_scale=0.6,trend_tfs=M5|M10,trend_regime=range,"
               "min_fill_age_min=5,fast_fill_mode=scale,fast_fill_scale=0.4,fast_fill_tfs=M5,fast_fill_regime=trend,"
               "regime_side_scale=range:sell:0.5|trend:buy:1.2")
    assert (c.trend_sma, c.trend_sides, c.trend_mode, c.trend_risk_scale, c.trend_tfs, c.trend_regime) == \
        (20, ("sell", "buy"), "scale", 0.6, ("M5", "M10"), "range")
    assert (c.min_fill_age_min, c.fast_fill_mode, c.fast_fill_scale, c.fast_fill_tfs, c.fast_fill_regime) == (5, "scale", 0.4, ("M5",), "trend")
    assert c.regime_side_scale == "range:sell:0.5|trend:buy:1.2"


def test_trend_series_uses_closed_days_only():
    m1 = _days_then([(2030, 2031, 2029, 2030)] * 3, closes=(2000, 2010, 2020, 2030))
    d = daily_bars(m1)
    s = trend_series(d, 3)
    # day 3 (close 2030 > SMA3 of 2010/2020/2030=2020) -> +1 valid on day 4 (shift)
    assert s.iloc[-1] == 1.0 and np.isnan(s.iloc[0]) and np.isnan(s.iloc[1]) and np.isnan(s.iloc[2])
    mt = minute_trend(m1, 3)
    assert np.isnan(mt[0]) and mt[-1] == 1.0
    # live helper: the last (unfinished) day is excluded -> same answer as the series' last value
    assert latest_trend(d, 3) == 1.0
    # a falling market: last closed day below its SMA -> -1
    m1d = _days_then([(2000, 2001, 1999, 2000)] * 3, closes=(2030, 2020, 2010, 2000))
    assert latest_trend(daily_bars(m1d), 3) == -1.0
    assert counter_trend("sell", 1.0) and not counter_trend("buy", 1.0) and counter_trend("buy", -1.0) and not counter_trend("sell", float("nan"))


def test_trend_gate_skips_counter_trend_sells_only():
    # up-trend (closes rising); a SELL zone above price and a BUY zone below price are shown on the test day
    m1 = _days_then([(2030, 2031, 2029, 2030)] * 4, closes=(2000, 2010, 2020, 2030))
    t0 = m1.index[-4]
    ev = [sel(t0, pid=1, top=2025.0, bottom=2020.0),                                        # buy below
          sel(t0, pid=2, side="above", direction="bearish", top=2040.0, bottom=2035.0)]     # sell above
    res, sim = run(m1, ev, cfg())
    assert set(sim.pending) == {"M15#1", "M15#2"}
    res, sim = run(m1, ev, cfg(trend_sma=3))
    assert set(sim.pending) == {"M15#1"} and ("M15#2", "counter-trend") in sim.skipped and sim.trend_skipped == 1
    # both sides gated: in an up-trend the buy is WITH the trend -> still placed
    res, sim = run(m1, ev, cfg(trend_sma=3, trend_sides=("sell", "buy")))
    assert set(sim.pending) == {"M15#1"}
    # scale mode: the sell is placed at trend_risk_scale
    res, sim = run(m1, ev, cfg(trend_sma=3, trend_mode="scale", trend_risk_scale=0.4))
    assert set(sim.pending) == {"M15#1", "M15#2"}
    assert sim.pending["M15#2"].plan.counter_trend and sim.pending["M15#2"].plan.risk_scale == 0.4 and sim.trend_scaled == 1
    assert not sim.pending["M15#1"].plan.counter_trend and sim.pending["M15#1"].plan.risk_scale == 1.0
    # tf scope: gate only M5 -> the M15 sell passes
    res, sim = run(m1, ev, cfg(trend_sma=3, trend_tfs=("M5",)))
    assert set(sim.pending) == {"M15#1", "M15#2"}
    # down-trend: the sell passes, a buy gated on both sides is skipped
    m1d = _days_then([(2000, 2001, 1999, 2000)] * 4, closes=(2030, 2020, 2010, 2000))
    t0 = m1d.index[-4]
    ev = [sel(t0, pid=1, top=1995.0, bottom=1990.0), sel(t0, pid=2, side="above", direction="bearish", top=2010.0, bottom=2005.0)]
    res, sim = run(m1d, ev, cfg(trend_sma=3, trend_sides=("sell", "buy")))
    assert set(sim.pending) == {"M15#2"} and ("M15#1", "counter-trend") in sim.skipped


def test_trend_gate_no_history_means_no_gate():
    # a single day of bars: the trend is NaN -> nothing is gated
    m1 = bars([(2005, 2006, 2004, 2005)] * 6)
    ev = [sel("2026-03-02 10:00", pid=2, side="above", direction="bearish", top=2015.0, bottom=2010.0)]
    res, sim = run(m1, ev, cfg(trend_sma=3))
    assert set(sim.pending) == {"M15#2"} and sim.trend_skipped == 0


def test_fast_fill_guard_cancels_or_scales():
    # buy limit 2000 (zone 1995-2000) placed at 10:00; price reaches it at 10:02 (2 min later)
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 2002, 2003), (2003, 2003.5, 1999.5, 2001),
               (2001, 2002, 2000.5, 2001.5), (2001.5, 2003, 2001, 2002.5)])
    ev = [sel("2026-03-02 10:00", pid=1)]
    res, sim = run(m1, ev, cfg())
    assert len(res.trades) == 1 and res.trades.entry[0] == 2000.0
    # guard 5 min: the fill 2 min after placement is refused and the order cancelled
    res, sim = run(m1, ev, cfg(min_fill_age_min=5))
    assert len(res.trades) == 0 and not sim.pending and sim.fast_cancelled == 1
    assert any(p.reason_cancel == "fast fill" for p in sim.cancelled)
    # guard 2 min: minute 2 is NOT < 2 -> filled normally
    res, sim = run(m1, ev, cfg(min_fill_age_min=2))
    assert len(res.trades) == 1 and sim.fast_cancelled == 0 and not res.trades.fast_fill[0]
    # scale mode: filled at half size
    res_full, _ = run(m1, ev, cfg())
    res, sim = run(m1, ev, cfg(min_fill_age_min=5, fast_fill_mode="scale", fast_fill_scale=0.5))
    assert len(res.trades) == 1 and sim.fast_scaled == 1 and res.trades.fast_fill[0]
    assert abs(res.trades.lots[0] - 0.5 * res_full.trades.lots[0]) <= 0.011
    # tf scope: guard only M5 -> the M15 order fills normally
    res, sim = run(m1, ev, cfg(min_fill_age_min=5, fast_fill_tfs=("M5",)))
    assert len(res.trades) == 1 and sim.fast_cancelled == 0


def test_fast_fill_guard_lets_a_patient_fill_through():
    # price takes 8 minutes to reach the limit -> no guard effect at 5 min
    seq = [(2005, 2006, 2004, 2005)] * 8 + [(2003, 2003.5, 1999.5, 2001), (2001, 2002, 2000.5, 2001.5)]
    res, sim = run(bars(seq), [sel("2026-03-02 10:00", pid=1)], cfg(min_fill_age_min=5))
    assert len(res.trades) == 1 and sim.fast_cancelled == 0


def test_regime_side_scale():
    # regime lever on with adr_ratio; the test frame has no 20-day history -> regime "trend" for every plan
    m1 = bars([(2005, 2006, 2004, 2005)] * 6)
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:00", pid=2, side="above", direction="bearish", top=2015.0, bottom=2010.0)]
    c = cfg(regime_metric="adr_ratio", regime_threshold=1.0, regime_side_scale="trend:sell:0.5|range:sell:0.25")
    res, sim = run(m1, ev, c)
    assert sim.pending["M15#1"].plan.regime == "trend" and sim.pending["M15#1"].plan.risk_scale == 1.0
    assert sim.pending["M15#2"].plan.regime == "trend" and sim.pending["M15#2"].plan.risk_scale == 0.5
    # without the regime lever the map is inert
    res, sim = run(m1, ev, cfg(regime_side_scale="trend:sell:0.5"))
    assert sim.pending["M15#2"].plan.risk_scale == 1.0


def test_summary_carries_v16b_counters():
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 2002, 2003), (2003, 2003.5, 1999.5, 2001), (2001, 2002, 2000.5, 2001.5)])
    res, sim = run(m1, [sel("2026-03-02 10:00", pid=1)], cfg(min_fill_age_min=5))
    s = res.summary()
    assert s["fast_cancelled"] == 1 and s["fast_scaled"] == 0 and s["trend_skipped"] == 0 and s["fast_fill_trades"] == 0
