"""v16b - live bot (fake MT5): the three loss-reduction levers through trader.py, same rules as PortfolioSimulator.
  * daily trend gate: a counter-trend SELL (last CLOSED day close > SMA N) is skipped (trend_mode=skip) or sized x trend_risk_scale
    (scale); buys untouched; tf / regime scope honoured.
  * fast-fill guard: a position that opened < min_fill_age_min after the order was placed (server tick clock) is closed at market
    (cancel) or reduced to x fast_fill_scale (scale); an order that filled later is left alone; decided once per plan.
  * regime x side scale: a plan placed in a 'range' regime on the listed side is sized x s.
"""
import math

import numpy as np
import pandas as pd

from tests.fake_mt5 import FakeMT5
from tests.test_trader_live import make_m1, make_trader, selection

LADDER = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)


def trending_m1(up: bool = True, n_days: int = 8, p0: float = 2000.0, bars_per_day: int = 600):
    """M1 history over n_days closed server days with a clear daily trend (+6 $/day or -6 $/day), then the test day."""
    rng = np.random.default_rng(3)
    frames = []
    for i in range(n_days + 1):
        day = pd.Timestamp("2026-03-02") + pd.Timedelta(days=i)
        idx = pd.date_range(day + pd.Timedelta(hours=1), periods=bars_per_day, freq="1min")
        base = p0 + (6.0 if up else -6.0) * i
        close = base + np.cumsum(rng.normal(0, 0.05, len(idx)))
        open_ = np.r_[base, close[:-1]]
        high = np.maximum(open_, close) + 0.2
        low = np.minimum(open_, close) - 0.2
        frames.append(pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 10.0}, index=idx))
    return pd.concat(frames)


def sell_selection(top=2070.0, bottom=2065.0, pid=9):
    s = selection(top=top, bottom=bottom, pid=pid)
    m15 = s["M15"]
    d = dict(m15["below"], direction="bearish", top=top, bottom=bottom, mid=(top + bottom) / 2, key_level=bottom)
    m15["below"], m15["above"] = None, d
    m15["candidates_above"], m15["candidates_below"] = 1, 0
    return s


def test_live_trend_gate_skips_counter_trend_sell_only(tmp_path):
    m1 = trending_m1(up=True)                       # daily closes rising -> last closed day close > SMA5 -> trend UP
    px = float(m1.close.iloc[-1])
    fake = FakeMT5(m1, bid=px)
    tr, _, state = make_trader(tmp_path, fake, history_bars=6000, trend_sma=5, **LADDER)
    tr.refresh_history()
    assert tr.current_trend() == 1.0
    # a SELL zone above price is counter-trend -> skipped
    tr.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    assert "M15#9" not in state.plans and not fake.orders
    # a BUY zone below price is with the trend -> placed
    tr.on_selection(selection(top=px - 7, bottom=px - 12, pid=5))
    assert "M15#5" in state.plans and len(fake.orders) == 2
    # the same sell on a DOWN trend history is placed
    m1d = trending_m1(up=False)
    pxd = float(m1d.close.iloc[-1])
    (tmp_path / "b").mkdir()
    fake2 = FakeMT5(m1d, bid=pxd)
    tr2, _, state2 = make_trader(tmp_path / "b", fake2, history_bars=6000, trend_sma=5, **LADDER)
    tr2.refresh_history()
    assert tr2.current_trend() == -1.0
    tr2.on_selection(sell_selection(top=pxd + 12, bottom=pxd + 7, pid=9))
    assert "M15#9" in state2.plans


def test_live_trend_gate_scale_and_scopes(tmp_path):
    m1 = trending_m1(up=True)
    px = float(m1.close.iloc[-1])
    # scale mode: the counter-trend sell is placed at x0.5 (1 % x 0.5 / 5 $ = 0.10 lots)
    tr, _, state = make_trader(tmp_path, FakeMT5(m1, bid=px), history_bars=6000, trend_sma=5, trend_mode="scale", trend_risk_scale=0.5, **LADDER)
    tr.refresh_history()
    tr.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    p = state.plans["M15#9"]
    assert p["counter_trend"] and p["risk_scale"] == 0.5 and math.isclose(p["lots_total"], 0.10)
    # tf scope: gate only M5 -> the M15 sell is not gated
    (tmp_path / "b").mkdir()
    tr2, _, state2 = make_trader(tmp_path / "b", FakeMT5(m1, bid=px), history_bars=6000, trend_sma=5, trend_tfs=("M5",), **LADDER)
    tr2.refresh_history()
    tr2.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    assert "M15#9" in state2.plans and not state2.plans["M15#9"]["counter_trend"] and state2.plans["M15#9"]["risk_scale"] == 1.0
    # regime scope: gate only plans placed in a 'range' regime; regime lever off -> plan.regime '' -> not gated
    (tmp_path / "c").mkdir()
    tr3, _, state3 = make_trader(tmp_path / "c", FakeMT5(m1, bid=px), history_bars=6000, trend_sma=5, trend_regime="range", **LADDER)
    tr3.refresh_history()
    tr3.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    assert "M15#9" in state3.plans
    # lever off (default): nothing gated, no trend computed
    (tmp_path / "d").mkdir()
    tr4, _, state4 = make_trader(tmp_path / "d", FakeMT5(m1, bid=px), history_bars=6000, **LADDER)
    tr4.refresh_history()
    assert math.isnan(tr4.current_trend())
    tr4.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    assert "M15#9" in state4.plans


def test_live_fast_fill_guard_closes_an_impulsive_fill(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, min_fill_age_min=5, **LADDER)
    tr.on_selection(selection())                     # buy limit 1990 placed at tick time T
    pl = state.plans["M15#5"]
    assert pl["placed_tick"] == fake.now and len(fake.orders) == 2
    # price runs into the zone 2 min later -> both legs fill -> the bot closes them at market, plan finished, POI consumed
    fake.set_price(1989.5, advance_seconds=120)
    tr.manage()
    assert "M15#5" not in state.plans
    assert not fake.positions and not fake.orders
    assert len(fake.history) == 2 and all(h["reason"] == "market" for h in fake.history)
    assert "M15#5" in state.traded                   # one trade per POI: the simulator counts the cancelled fast fill as traded too? no:
    # (the simulator cancels BEFORE the fill -> the POI is NOT marked traded there; live the fill happened, so the POI IS consumed -
    #  the conservative choice: never re-enter an impulsive zone twice in one show)


def test_live_fast_fill_guard_leaves_a_patient_fill_and_honours_scope(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, _, state = make_trader(tmp_path, fake, min_fill_age_min=5, **LADDER)
    tr.on_selection(selection())
    fake.set_price(1989.5, advance_seconds=600)      # 10 min later -> a normal fill
    tr.manage()
    pl = state.plans["M15#5"]
    assert len(pl["position_tickets"]) == 2 and pl["fast_fill_checked"] and not pl.get("fast_fill")
    # scale mode: 2-min fill -> each leg reduced to half (0.10 -> 0.05)
    (tmp_path / "b").mkdir()
    fake2 = FakeMT5(make_m1(), bid=2000.0)
    tr2, _, state2 = make_trader(tmp_path / "b", fake2, min_fill_age_min=5, fast_fill_mode="scale", fast_fill_scale=0.5, **LADDER)
    tr2.on_selection(selection())
    fake2.set_price(1989.5, advance_seconds=120)
    tr2.manage()
    pl2 = state2.plans["M15#5"]
    assert pl2["fast_fill"] and len(pl2["position_tickets"]) == 2
    assert all(math.isclose(fake2.positions[t].volume, 0.05) for t in pl2["position_tickets"])
    # tf scope: guard only M5 -> the M15 fast fill is left alone
    (tmp_path / "c").mkdir()
    fake3 = FakeMT5(make_m1(), bid=2000.0)
    tr3, _, state3 = make_trader(tmp_path / "c", fake3, min_fill_age_min=5, fast_fill_tfs=("M5",), **LADDER)
    tr3.on_selection(selection())
    fake3.set_price(1989.5, advance_seconds=60)
    tr3.manage()
    assert len(state3.plans["M15#5"]["position_tickets"]) == 2 and not state3.plans["M15#5"].get("fast_fill")
    # lever off: no placed_tick needed, nothing checked
    (tmp_path / "d").mkdir()
    fake4 = FakeMT5(make_m1(), bid=2000.0)
    tr4, _, state4 = make_trader(tmp_path / "d", fake4, **LADDER)
    tr4.on_selection(selection())
    fake4.set_price(1989.5, advance_seconds=60)
    tr4.manage()
    assert len(state4.plans["M15#5"]["position_tickets"]) == 2 and "fast_fill_checked" not in state4.plans["M15#5"]


def test_live_regime_side_scale(tmp_path):
    # adr_ratio with a huge threshold -> every plan is placed in a 'range' regime
    m1 = trending_m1(up=False, n_days=24, bars_per_day=200)         # adr_ratio needs 20 closed days
    px = float(m1.close.iloc[-1])
    kw = dict(regime_metric="adr_ratio", regime_threshold=100.0, regime_side_scale="range:sell:0.25", **LADDER)
    tr, _, state = make_trader(tmp_path, FakeMT5(m1, bid=px), history_bars=6000, **kw)
    tr.refresh_history()
    both = sell_selection(top=px + 12, bottom=px + 7, pid=9)
    both["M15"]["below"] = selection(top=px - 7, bottom=px - 12, pid=5)["M15"]["below"]
    both["M15"]["candidates_below"] = 1
    tr.on_selection(both)
    ps, pb = state.plans["M15#9"], state.plans["M15#5"]
    assert ps["regime"] == "range" and pb["regime"] == "range"
    assert ps["risk_scale"] == 0.25 and math.isclose(ps["lots_total"], 0.05)       # 0.25 % / 5 $ = 0.05 lots
    assert pb["risk_scale"] == 1.0 and math.isclose(pb["lots_total"], 0.20)
