"""End-to-end test of trader.py against the fake MT5 terminal: plan -> two limit legs -> fill ->
TP1 closes leg A -> bot moves leg B to break-even -> restart re-adopts state."""
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_mt5 import FakeMT5  # noqa: E402
from lubot import StrategyConfig  # noqa: E402
from lubot.execution import TradePlan, TraderConfig  # noqa: E402
from lubot.mt5_broker import MT5Broker  # noqa: E402
import trader as trader_mod  # noqa: E402


def make_m1(n=3000, start="2026-03-02 00:00", p0=2000.0, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="1min")
    close = p0 + np.cumsum(rng.normal(0, 0.5, n))
    open_ = np.r_[p0, close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 0.4, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.4, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 10.0}, index=idx)


def make_trader(tmp_path, fake, dry=False, history_bars=2000, **tkw):
    log = logging.getLogger("test_trader")
    log.setLevel(logging.INFO)
    broker = MT5Broker("XAUUSD.t", mt5=fake)
    cfg = StrategyConfig(timeframes=("M15",))
    tkw.setdefault("risk_pct", 1.0)
    tcfg = TraderConfig(**tkw)
    state = trader_mod.State(str(tmp_path / "state.json"))
    tr = trader_mod.Trader(broker, cfg, tcfg, state, log, dry_run=dry, history_bars=history_bars)
    return tr, broker, state


def selection(top=1990.0, bottom=1985.0, pid=5):
    return {"M15": {"tf": "M15", "time": "2026-03-02 10:00:00", "price": 2000.0, "range_bias": "none", "price_zone": "n/a",
                    "above": None, "candidates_above": 0, "candidates_below": 1,
                    "below": {"id": pid, "tf": "M15", "type": "OB", "direction": "bullish", "top": top, "bottom": bottom,
                              "mid": (top + bottom) / 2, "key_level": top, "quality": 0.62, "grade": "B", "distance": 10.0,
                              "distance_atr": 2.5, "time": "2026-03-02 09:00:00", "liquidity_between": [], "orderflow_count": 2}}}


def test_full_life_cycle_split_mode(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake)
    assert tr.mode == "split"
    tr.on_selection(selection())
    # two legs placed: A (tp1) and B (tp2), both at limit 1990 with SL 1985
    assert len(fake.orders) == 2
    legs = sorted(fake.orders.values(), key=lambda o: o.tp)
    assert all(o.price_open == 1990.0 and o.sl == 1985.0 for o in legs)
    assert math.isclose(legs[0].tp, 1992.0) and math.isclose(legs[1].tp, 1997.5)      # 0.4R and 1.5R of 1R=5
    # risk 1% of 10k = 100$ / (5 $ * 100) = 0.2 lots -> 0.1 + 0.1
    assert math.isclose(sum(o.volume_current for o in legs), 0.20)
    plan = state.plans["M15#5"]
    assert plan["order_tickets"] and not plan["position_tickets"]
    # price drops to the zone -> both legs fill (ask 1989.8 <= 1990)
    fake.set_price(1989.5)
    tr.manage()
    plan = state.plans["M15#5"]
    assert len(plan["position_tickets"]) == 2 and not plan["order_tickets"]
    # rally through TP1 -> leg A closed by the server; bot must move leg B to BE
    fake.set_price(1992.3)
    tr.manage()
    plan = state.plans["M15#5"]
    assert plan["partial_done"] and len(plan["position_tickets"]) == 1
    leg_b = fake.positions[plan["position_tickets"][0]]
    assert math.isclose(leg_b.sl, 1990.0)                      # break-even
    assert math.isclose(leg_b.tp, 1997.5)
    assert fake.history[0]["reason"] == "tp" and math.isclose(fake.history[0]["pnl"], 0.1 * 100 * 2.0)
    # restart: new Trader with the same state file re-adopts the open leg
    tr2, _, state2 = make_trader(tmp_path, fake)
    tr2.adopt()
    assert "M15#5" in state2.plans and state2.plans["M15#5"]["position_tickets"] == [leg_b.ticket]
    # back to BE -> leg B stopped at entry -> plan finished, POI not re-traded
    fake.set_price(1989.9)
    tr2.manage()
    assert "M15#5" not in state2.plans
    assert math.isclose(fake.balance, 10_020.0, abs_tol=1e-6)     # +$20 from leg A, 0 from leg B
    tr2.on_selection(selection())
    assert not fake.orders                                       # one trade per POI


def test_mirror_cancel_when_poi_disappears(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake)
    tr.on_selection(selection(pid=1))
    assert len(fake.orders) == 2
    empty = selection(pid=1)
    empty["M15"]["below"] = None
    tr.on_selection(empty)
    assert not fake.orders and "M15#1" not in state.plans
    # a different POI -> new orders; the old one cancelled
    tr.on_selection(selection(pid=2, top=1980.0, bottom=1975.0))
    assert len(fake.orders) == 2 and "M15#2" in state.plans


def test_skip_when_price_already_through_entry(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=1988.0)         # inside the zone
    tr, broker, state = make_trader(tmp_path, fake)
    tr.on_selection(selection())
    assert not fake.orders


def test_dry_run_sends_nothing(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, dry=True)
    tr.on_selection(selection())
    assert not fake.orders and not fake.sent
    assert "M15#5" in state.plans


def test_netting_partial_close_at_market(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0, hedging=False)
    tr, broker, state = make_trader(tmp_path, fake)
    assert tr.mode == "netting"
    tr.on_selection(selection())
    assert len(fake.orders) == 1 and math.isclose(list(fake.orders.values())[0].tp, 1997.5)
    fake.set_price(1989.5)
    tr.manage()
    fake.set_price(1992.3)                 # TP1 touched -> bot closes half at market, SL -> BE
    tr.manage()
    pl = state.plans["M15#5"]
    pos = fake.positions[pl["position_tickets"][0]]
    assert pl["partial_done"] and math.isclose(pos.volume, 0.10) and math.isclose(pos.sl, 1990.0)
    assert fake.history[0]["reason"] == "market" and math.isclose(fake.history[0]["vol"], 0.10)


def test_scan_runs_on_fake_history(tmp_path):
    m1 = make_m1(n=6000)
    fake = FakeMT5(m1, bid=float(m1.close.iloc[-1]))
    tr, broker, state = make_trader(tmp_path, fake)
    tr.refresh_history()
    res = tr.scan()
    assert "M15" in res and "above" in res["M15"] and "below" in res["M15"]


def test_v8_trade_filter_gates_live_orders(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    # zone 1985-1990 = $5 -> cost_r = (spread ~0.3 + 0.07) / 5 = 0.074; a 0.05 cap rejects, 0.10 accepts
    tr, broker, state = make_trader(tmp_path, fake, trade_filter="M15:max_cost_r=0.05")
    tr.on_selection(selection())
    assert not fake.orders and "M15#5" not in state.plans
    (tmp_path / "b").mkdir(); (tmp_path / "c").mkdir()
    tr2, _, state2 = make_trader(_sub(tmp_path, "b"), fake, trade_filter="M15:max_cost_r=0.10;min_quality=0.55")
    tr2.on_selection(selection())
    assert len(fake.orders) == 2 and "M15#5" in state2.plans
    # a rule on another timeframe leaves M15 untouched; quality gate rejects a 0.62 zone at 0.65
    fake.orders.clear()
    tr3, _, state3 = make_trader(_sub(tmp_path, "c"), fake, trade_filter="M5:max_cost_r=0.01/M15:min_quality=0.65")
    tr3.on_selection(selection(pid=9))
    assert not fake.orders and "M15#9" not in state3.plans


def test_v9_recommended_management_live_split(tmp_path):
    """v9 recommendation: close 25 % at +0.6R, SL -> BE, TP2 = 2.5R.  Two limit legs 25 % / 75 %, server-side TPs,
    BE move after leg A closes - exactly the same mechanics as the current spec, only the numbers change."""
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, partial_r=0.6, partial_frac=0.25, tp2_r=2.5, risk_pct=2.0)
    tr.on_selection(selection())
    legs = sorted(fake.orders.values(), key=lambda o: o.tp)
    assert len(legs) == 2 and all(o.price_open == 1990.0 and o.sl == 1985.0 for o in legs)
    assert math.isclose(legs[0].tp, 1993.0) and math.isclose(legs[1].tp, 2002.5)      # 0.6R and 2.5R of 1R=5
    # risk 2 % of 10k = $200 / ($5 * 100) = 0.40 lots -> 0.10 (25 %) + 0.30 (75 %)
    assert math.isclose(legs[0].volume_current, 0.10) and math.isclose(legs[1].volume_current, 0.30)
    fake.set_price(1989.5); tr.manage()                        # fill
    fake.set_price(1993.3); tr.manage()                        # TP1 -> leg A closed by the server, leg B -> BE
    plan = state.plans["M15#5"]
    assert plan["partial_done"] and len(plan["position_tickets"]) == 1
    leg_b = fake.positions[plan["position_tickets"][0]]
    assert math.isclose(leg_b.sl, 1990.0) and math.isclose(leg_b.tp, 2002.5)
    fake.set_price(2002.8); tr.manage()                        # TP2
    assert "M15#5" not in state.plans
    # +$30 (0.10 x 100 x 3.0) + $375 (0.30 x 100 x 12.5) = $405 = 2.025 R of the $200 risk
    assert math.isclose(fake.balance, 10_405.0, abs_tol=1e-6)


def test_v9_recommended_management_too_small_account_is_rejected(tmp_path):
    """With 1 % of $10k the 25 % leg would be 0.05 lots -> fine; with 0.4 % it would be 0.01/0.03 -> fine;
    0.2 % -> 0.04 lots total cannot be split into 0.01 + 0.03? it can; 0.1 % -> 0.02 lots -> leg A 0.005 < min -> rejected."""
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, partial_r=0.6, partial_frac=0.25, tp2_r=2.5, risk_pct=0.1)
    tr.on_selection(selection())
    assert not fake.orders and "M15#5" not in state.plans


# ----------------------------------------------------------------------------- v10 account protection (live bot)
def test_v10_daily_loss_limit_flattens_blocks_and_resets_next_day(tmp_path):
    """risk 8 % -> 1.6 lots; a 1.4 $ adverse move = -224 $ = -2.2 % > 1.5 %: bot closes everything, blocks new plans
    for the rest of the server day, keeps the block across a restart, resets on the next server day."""
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, risk_pct=8.0, max_daily_loss_pct=1.5, max_total_loss_pct=9.0)
    assert tr.check_risk_limits() is True and state.risk["start_balance"] == 10_000.0 and state.risk["day"] is not None
    tr.on_selection(selection())
    assert len(fake.orders) == 2
    fake.set_price(1989.5); tr.manage()
    assert state.plans["M15#5"]["position_tickets"]
    fake.set_price(1989.7)
    assert tr.check_risk_limits() is True                     # small floating loss: allowed
    fake.set_price(1988.6)                                    # -1.4 $ x 1.6 lots x 100 = -224 $ = -2.2 % > 1.5 %
    assert tr.check_risk_limits() is False
    assert not fake.positions and not fake.orders and "M15#5" not in state.plans
    assert state.risk["daily_halt_day"] == state.risk["day"] and len(state.risk["daily_halts"]) == 1
    assert fake.balance < 10_000 * (1 - 0.015)
    tr.on_selection(selection(top=1980.0, bottom=1975.0, pid=7))
    assert not fake.orders                                    # blocked for today
    tr2, _, state2 = make_trader(tmp_path, fake, risk_pct=8.0, max_daily_loss_pct=1.5, max_total_loss_pct=9.0)
    assert state2.risk["daily_halt_day"] is not None and tr2.check_risk_limits() is False   # restart keeps the block
    fake.set_price(1988.6, advance_seconds=86_400)            # next server day
    assert tr2.check_risk_limits() is True and state2.risk["daily_halt_day"] is None
    tr2.on_selection(selection(top=1980.0, bottom=1975.0, pid=8))
    assert len(fake.orders) == 2


def test_v10_total_loss_limit_halts_for_good_and_survives_restart(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, risk_pct=8.0, max_daily_loss_pct=0.0, max_total_loss_pct=2.0)
    tr.check_risk_limits()
    tr.on_selection(selection())
    fake.set_price(1989.5); tr.manage()
    assert state.plans["M15#5"]["position_tickets"]
    fake.set_price(1988.6)                                    # -2.2 % > 2 %
    assert tr.check_risk_limits() is False and state.risk["halted"] is True and state.risk["halt_time"]
    assert not fake.positions and not fake.orders
    tr.on_selection(selection(top=1980.0, bottom=1975.0, pid=9))
    assert not fake.orders
    fake.set_price(1988.6, advance_seconds=86_400)
    tr2, _, state2 = make_trader(tmp_path, fake, risk_pct=8.0, max_total_loss_pct=2.0)
    assert state2.risk["halted"] is True and tr2.check_risk_limits() is False
    tr2.on_selection(selection(top=1980.0, bottom=1975.0, pid=10))
    assert not fake.orders


def test_v10_limits_off_do_nothing(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, _, state = make_trader(tmp_path, fake, risk_pct=8.0)
    assert tr.check_risk_limits() is True and state.risk["start_balance"] is None


# ----------------------------------------------------------------------------- v10 multi-TP ladder (live bot)
def test_v10_four_leg_ladder_live_with_stop_schedule(tmp_path):
    """4 legs 25 % each at 0.5/1.0/1.5/2.5R (1R = $5 -> 1992.5 / 1995 / 1997.5 / 2002.5), stop schedule x|0|1.0:
    nothing after leg 1, BE after leg 2, +1R lock (1995) after leg 3.  Same rules as the simulator."""
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, tp_levels=("0.5", "1.0", "1.5", "2.5"), tp_fracs=("0.25",) * 4,
                                    sl_after_leg=("x", "0", "1.0"), risk_pct=2.0, ladder_fallback="merge")
    tr.on_selection(selection())
    legs = sorted(fake.orders.values(), key=lambda o: o.tp)
    assert len(legs) == 4 and all(o.price_open == 1990.0 and o.sl == 1985.0 for o in legs)
    assert [round(o.tp, 2) for o in legs] == [1992.5, 1995.0, 1997.5, 2002.5]
    assert all(math.isclose(o.volume_current, 0.10) for o in legs)          # 0.40 lots / 4
    pl = state.plans["M15#5"]
    assert len(pl["ladder"]) == 4 and pl["leg_a_ticket"] is None
    fake.set_price(1989.5); tr.manage()                                       # all four legs filled
    assert len(pl["position_tickets"]) == 4
    fake.set_price(1992.7); tr.manage()                                       # leg 1 TP -> stop stays 1985 ("x")
    assert pl["n_closed"] == 1 and all(math.isclose(p.sl, 1985.0) for p in fake.positions.values())
    fake.set_price(1988.0); tr.manage()                                       # dip below entry survives (no BE yet)
    assert len(fake.positions) == 3
    fake.set_price(1995.2); tr.manage()                                       # leg 2 TP -> BE 1990 on legs 3+4
    assert pl["n_closed"] == 2 and all(math.isclose(p.sl, 1990.0) for p in fake.positions.values())
    fake.set_price(1997.7); tr.manage()                                       # leg 3 TP -> SL 1995 (+1R) on leg 4
    assert pl["n_closed"] == 3 and len(fake.positions) == 1
    assert math.isclose(list(fake.positions.values())[0].sl, 1995.0)
    fake.set_price(1994.8); tr.manage()                                       # leg 4 stopped at 1995
    assert "M15#5" not in state.plans
    # pnl: 0.10*100*(2.5 + 5 + 7.5 + 5) = $200 = 1.0 R of the $200 risk
    assert math.isclose(fake.balance, 10_200.0, abs_tol=1e-6)


def test_v10_ladder_classic_be_and_ratchet_live(tmp_path):
    """3 legs 0.6/1.5/2.5R (1993/1997.5/2002.5) classic BE after leg 1, ratchet after leg 2 -> stop at 1993."""
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, tp_levels=("0.6", "1.5", "2.5"), tp_fracs=("0.25", "0.25", "0.5"),
                                    ratchet_sl=True, risk_pct=2.0)
    tr.on_selection(selection())
    assert len(fake.orders) == 3
    vols = sorted(o.volume_current for o in fake.orders.values())
    assert [round(v, 2) for v in vols] == [0.10, 0.10, 0.20]
    fake.set_price(1989.5); tr.manage()
    fake.set_price(1993.2); tr.manage()                                       # leg 1 -> BE 1990
    assert all(math.isclose(p.sl, 1990.0) for p in fake.positions.values()) and len(fake.positions) == 2
    fake.set_price(1997.7); tr.manage()                                       # leg 2 -> ratchet: SL -> previous target 1993
    assert len(fake.positions) == 1 and math.isclose(list(fake.positions.values())[0].sl, 1993.0)
    fake.set_price(1992.9); tr.manage()
    assert "M15#5" not in state.plans
    # 0.10*100*3 + 0.10*100*7.5 + 0.20*100*3 = 30 + 75 + 60 = $165
    assert math.isclose(fake.balance, 10_165.0, abs_tol=1e-6)


def _two_tf_selection(top=1990.0, bottom=1985.0):
    """The same level shown on M15 (id 5) and on M5 (id 77, zone inside the M15 zone)."""
    r = selection(top, bottom, pid=5)
    m5 = dict(r["M15"])
    m5 = {**m5, "tf": "M5", "below": {**r["M15"]["below"], "id": 77, "tf": "M5", "top": top - 1.0, "bottom": bottom + 1.0}}
    r["M5"] = m5
    return r


def test_v11_default_dedupe_refuses_the_same_level_on_a_second_timeframe(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake)
    tr.on_selection(_two_tf_selection())
    assert set(state.plans) == {"M15#5"} and len(fake.orders) == 2


def test_v11_dedupe_cross_tf_off_trades_the_confluence_level_on_both_timeframes(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, dedupe_cross_tf=False)
    tr.on_selection(_two_tf_selection())
    assert set(state.plans) == {"M15#5", "M5#77"} and len(fake.orders) == 4
    # the same-timeframe overlap is still refused: a second M15 zone inside the first one
    r = selection(1989.0, 1986.0, pid=6)
    tr.on_selection({**_two_tf_selection(), "M15": r["M15"]})
    assert "M15#6" not in state.plans


# ------------------------------------------------------------------------------------------ v12 levers in the live bot
def _sub(tmp_path, name):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    return d


def test_v12_confluence_filter_live(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    two = _two_tf_selection()
    two["M5"]["below"]["quality"] = 0.52
    # normal filter: M5 needs quality 0.55 -> M5#77 refused even though the level is active on M15
    tr, broker, state = make_trader(tmp_path, fake, dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55")
    tr.on_selection(two)
    assert set(state.plans) == {"M15#5"}
    # confluence filter M5 quality 0.50 -> traded because M15#5 is active on the same level
    fake2 = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(_sub(tmp_path, "b"), fake2, dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55",
                                    confluence_filter="M5:min_quality=0.50")
    tr.on_selection(two)
    assert set(state.plans) == {"M15#5", "M5#77"} and state.plans["M5#77"]["confluent"] is True
    # the M5 zone alone (no M15 plan) is still refused by the normal filter
    fake3 = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(_sub(tmp_path, "c"), fake3, dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55",
                                    confluence_filter="M5:min_quality=0.50")
    tr.on_selection({"M5": two["M5"]})
    assert not state.plans


def test_v12_keep_replaced_live(tmp_path, monkeypatch):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, keep_replaced_bars=2, keep_replaced_tfs=("M15",))
    tr.on_selection(selection(pid=1))
    assert set(state.plans) == {"M15#1"} and len(fake.orders) == 2
    # POI 1 replaced by POI 2 on the same slot -> #1 kept (2 M15 bars = 30 min), #2 placed
    tr.on_selection(selection(pid=2, top=1980.0, bottom=1975.0))
    assert set(state.plans) == {"M15#1", "M15#2"} and len(fake.orders) == 4 and state.plans["M15#1"]["keep_until"]
    # shown again inside the window -> kept for good (#2 now the replaced one)
    tr.on_selection(selection(pid=1))
    assert "keep_until" not in state.plans["M15#1"] and state.plans["M15#2"]["keep_until"]
    # window over -> #2 cancelled
    t0 = trader_mod.time.time
    monkeypatch.setattr(trader_mod.time, "time", lambda: t0() + 31 * 60)
    tr.on_selection(selection(pid=1))
    assert set(state.plans) == {"M15#1"} and len(fake.orders) == 2
    # a cleared slot cancels at once, even a kept order
    tr.on_selection(selection(pid=3, top=1970.0, bottom=1965.0))
    assert state.plans["M15#1"]["keep_until"]
    empty = selection(pid=1)
    empty["M15"]["below"] = None
    tr.on_selection(empty)
    assert not state.plans and not fake.orders
    # TF not in keep_replaced_tfs -> v11 behaviour (cancel at once)
    fake2 = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(_sub(tmp_path, "b"), fake2, keep_replaced_bars=2, keep_replaced_tfs=("M10",))
    tr.on_selection(selection(pid=1))
    tr.on_selection(selection(pid=2, top=1980.0, bottom=1975.0))
    assert set(state.plans) == {"M15#2"}


# ------------------------------------------------------------------ v13: regime-adaptive management in the live bot
def _m1_regime(range_days, n_days=26, start="2026-02-01 00:00"):
    """Synthetic history: n_days server days of 1440 flat bars whose high-low = the day's range (2000 +- r/2), the last
    closed days taking ``range_days``, then 10 bars of the current (unfinished) day."""
    frames = []
    ranges = [10.0] * (n_days - len(range_days)) + list(range_days)
    for i, r in enumerate(ranges):
        idx = pd.date_range(pd.Timestamp(start) + pd.Timedelta(days=i), periods=1440, freq="1min")
        frames.append(pd.DataFrame({"open": 2000.0, "high": 2000.0 + r / 2, "low": 2000.0 - r / 2, "close": 2000.0, "volume": 10.0}, index=idx))
    idx = pd.date_range(pd.Timestamp(start) + pd.Timedelta(days=n_days), periods=10, freq="1min")
    frames.append(pd.DataFrame({"open": 2000.0, "high": 2000.2, "low": 1999.8, "close": 2000.0, "volume": 10.0}, index=idx))
    return pd.concat(frames)


V13 = dict(tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1",) * 4, ladder_fallback="merge", risk_pct=2.0,
           regime_metric="adr_ratio", regime_threshold=1.0, range_tp_levels=("0.5", "1.0", "1.5", "2.5"), range_tp_fracs=("1",) * 4,
           range_sl_after_leg=("0", "0.3", "x", "x"))


def test_v13_regime_range_uses_tight_ladder_and_lock_live(tmp_path):
    """Last 5 closed days have range 3 vs 10 before -> ADR5/ADR20 < 1 -> 'range': ladder 0.5/1.0/1.5/2.5R, stop schedule
    BE after leg 1, +0.3R after leg 2.  Same rules as the simulator (tests/test_v13_regime.py)."""
    m1 = _m1_regime([3.0] * 5)
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, history_bars=60_000, **V13)
    tr.refresh_history()
    assert tr.current_regime() == "range" and tr.regime_value < 1.0
    tr.on_selection(selection())
    legs = sorted(fake.orders.values(), key=lambda o: o.tp)
    assert [round(o.tp, 2) for o in legs] == [1992.5, 1995.0, 1997.5, 2002.5]     # tight ladder, 1R = 5
    pl = state.plans["M15#5"]
    assert pl["regime"] == "range" and list(pl["sl_after_leg"]) == ["0", "0.3", "x", "x"]
    fake.set_price(1989.5); tr.manage()
    assert len(pl["position_tickets"]) == 4
    fake.set_price(1992.7); tr.manage()                                       # leg 1 -> BE
    assert pl["n_closed"] == 1 and all(math.isclose(p.sl, 1990.0) for p in fake.positions.values())
    fake.set_price(1995.2); tr.manage()                                       # leg 2 -> +0.3R = 1991.5
    assert pl["n_closed"] == 2 and all(math.isclose(p.sl, 1991.5) for p in fake.positions.values())
    fake.set_price(1991.3); tr.manage()                                       # rest stopped at +0.3R
    assert "M15#5" not in state.plans
    # 0.10 lots x 100 x (2.5 + 5 + 1.5 + 1.5) = $105
    assert math.isclose(fake.balance, 10_105.0, abs_tol=1e-6)


def test_v13_regime_trend_keeps_the_normal_ladder_live(tmp_path):
    """Steady ranges -> ADR ratio 1.0 (not < 1.0) -> 'trend': the normal G ladder, classic BE after leg 1."""
    m1 = _m1_regime([10.0] * 5)
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, history_bars=60_000, **V13)
    tr.refresh_history()
    assert tr.current_regime() == "trend"
    tr.on_selection(selection())
    legs = sorted(fake.orders.values(), key=lambda o: o.tp)
    assert [round(o.tp, 2) for o in legs] == [1993.0, 1996.0, 2002.0, 2014.0]      # G ladder
    pl = state.plans["M15#5"]
    assert pl["regime"] == "trend" and not pl["sl_after_leg"]
    fake.set_price(1989.5); tr.manage()
    fake.set_price(1993.2); tr.manage()                                        # leg 1 -> classic BE
    assert pl["n_closed"] == 1 and all(math.isclose(p.sl, 1990.0) for p in fake.positions.values())


def test_v13_range_risk_scale_zero_blocks_orders_live(tmp_path):
    m1 = _m1_regime([3.0] * 5)
    fake = FakeMT5(m1, bid=2000.0)
    kw = dict(V13); kw["range_risk_scale"] = 0.0
    tr, broker, state = make_trader(tmp_path, fake, history_bars=60_000, **kw)
    tr.refresh_history()
    tr.on_selection(selection())
    assert not fake.orders and not state.plans
