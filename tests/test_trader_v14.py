"""v14 - live bot (fake MT5): martingale sizing from the persisted closed-plan list, restart-safety, zone-grid deep leg."""
import math

from tests.fake_mt5 import FakeMT5
from tests.test_trader_live import make_m1, make_trader, selection

LADDER = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0)


def test_live_martingale_steps_after_a_stop_and_survives_a_restart(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, mart_mode="mult", mart_mult=2.0, mart_max_risk_pct=0, **LADDER)
    assert tr.mart.on and tr.mart.snapshot() == {}
    tr.on_selection(selection(pid=1))                         # zone 1985-1990, 1R = 5 -> 0.2 lots (2 legs of 0.1)
    assert math.isclose(sum(o.volume_current for o in fake.orders.values()), 0.20)
    fake.set_price(1989.5)
    tr.manage()
    fake.set_price(1984.5)                                    # stopped at 1985 -> -100 $
    tr.manage()
    assert "M15#1" not in state.plans and len(state.closed) == 1
    tf, net, r_net, step = state.closed[0]
    assert tf == "M15" and math.isclose(net, -100.0) and math.isclose(r_net, -1.0) and step == 0
    assert tr.mart.snapshot()["all"]["k"] == 1
    # the next plan is sized x2 (equity 9 900 -> 2 % = 198 $ / 500 = 0.396 -> 0.39 lots)
    fake.set_price(2000.0)
    tr.on_selection(selection(pid=2, top=1980.0, bottom=1975.0))
    pl = state.plans["M15#2"]
    assert pl["mart_step"] == 1 and pl["mart_scale"] == 2.0 and math.isclose(pl["lots_total"], 0.39)
    # RESTART: a new Trader on the same state file rebuilds the same streak (k = 1) from the closed list
    tr2, _, state2 = make_trader(tmp_path, fake, mart_mode="mult", mart_mult=2.0, mart_max_risk_pct=0, **LADDER)
    assert tr2.mart.snapshot() == tr.mart.snapshot() and state2.closed == state.closed
    tr2.adopt()
    # the recovery trade wins (fill 1980, TP 1985) -> streak reset, the following plan is back to base size
    fake.set_price(1979.5)
    tr2.manage()
    fake.set_price(1985.5)
    tr2.manage()
    assert "M15#2" not in state2.plans and len(state2.closed) == 2 and state2.closed[1][3] == 1 and state2.closed[1][1] > 0
    assert tr2.mart.snapshot()["all"]["k"] == 0
    assert "mart" in tr2.status_line()


def test_live_ungated_step_down_and_gate(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, mart_mode="mult", mart_mult=1.5, mart_tfs=("M5",), mart_ungated_scale=0.5,
                                    mart_max_risk_pct=0, **LADDER)
    tr.on_selection(selection(pid=1))
    fake.set_price(1989.5); tr.manage()
    fake.set_price(1984.5); tr.manage()                       # loss -> k = 1
    fake.set_price(2000.0)
    tr.on_selection(selection(pid=2, top=1980.0, bottom=1975.0))   # M15 fails the M5 gate -> stepped DOWN x0.5
    pl = state.plans["M15#2"]
    assert pl["mart_step"] == -1 and pl["mart_scale"] == 0.5 and math.isclose(pl["lots_total"], 0.09)   # 0.5 % of 9 900 / 500


def test_live_zone_grid_deep_leg(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, grid_add_r=0.5, grid_base_frac=0.5, grid_add_frac=0.5,
                                    grid_cancel_on_partial=False, **LADDER)
    tr.on_selection(selection(pid=1))                         # edge 1990 (0.5 % -> 0.1 lots), deep 1987.5 (risk 2.5 -> 0.2 lots)
    assert "M15#1" in state.plans and "M15#1+g" in state.plans
    edge, deep = state.plans["M15#1"], state.plans["M15#1+g"]
    assert deep["grid_leg"] and deep["grid_parent"] == "M15#1" and math.isclose(deep["entry"], 1987.5) and deep["sl"] == 1985.0
    assert math.isclose(edge["lots_total"], 0.10) and math.isclose(deep["lots_total"], 0.20)
    assert len(fake.orders) == 4                              # 2 legs each
    # the deep leg does not block a second plan on the pending / open-position counts
    assert tr._accept(tr_plan(tr, pid=3, top=1970.0, bottom=1965.0)) is None
    # edge fills, price dips to the deep entry -> deep fills too; both run to the edge's target 1995 (same exit prices)
    fake.set_price(1989.5); tr.manage()
    fake.set_price(1987.0); tr.manage()
    assert state.plans["M15#1"]["position_tickets"] and state.plans["M15#1+g"]["position_tickets"]
    fake.set_price(1995.5); tr.manage()
    assert "M15#1" not in state.plans and "M15#1+g" not in state.plans
    # edge +50 $ (0.1 x 5 x 100), deep 0.2 x 7.5 x 100 = +150 $
    assert math.isclose(fake.balance, 10_200.0, abs_tol=1e-6)


def test_live_deep_order_cancelled_when_edge_disappears(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, grid_add_r=0.5, **LADDER)
    tr.on_selection(selection(pid=1))
    assert len(fake.orders) == 4
    empty = selection(pid=1)
    empty["M15"]["below"] = None
    tr.on_selection(empty)                                    # mirror cancel of the edge -> the deep order goes with it
    assert not fake.orders and "M15#1" not in state.plans and "M15#1+g" not in state.plans


def tr_plan(tr, **kw):
    from lubot.execution import TradePlan
    d = dict(selection(**kw)["M15"]["below"])
    d["tf"] = "M15"
    return TradePlan.from_poi(d, tr.t, tr.spec)
