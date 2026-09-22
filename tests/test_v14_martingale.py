"""v14 - bounded martingale: sequence sizing (lubot/martingale.py) + zone-averaging grid (deep leg) in the simulator."""
import pandas as pd

from lubot.execution import SymbolSpec, TradePlan, TraderConfig, apply_mart_ladder, grid_deep_plan, size_plan
from lubot.martingale import Martingale
from lubot.portfolio_sim import PortfolioSimulator

from tests.test_portfolio_sim import bars, cfg, sel, spec  # noqa: F401

SPREAD = 0.3


def _plan(t=None, **kw):
    d = dict(sel("2026-03-02 10:00"))
    d.update(kw)
    return TradePlan.from_poi(d, t or TraderConfig(), SymbolSpec())


# ---------------------------------------------------------------------------- A. sequence sizing state machine
def test_mult_steps_and_caps():
    t = TraderConfig(mart_mode="mult", mart_mult=2.0, mart_max_steps=3, mart_max_risk_pct=5.0, risk_pct=1.0)
    m = Martingale(t)
    p = _plan()
    assert m.scale(p, 10_000) == (1.0, 0)
    m.on_close("M15", -100.0, -1.0)
    assert m.scale(p, 10_000) == (2.0, 1)
    m.on_close("M15", -100.0, -1.0)
    assert m.scale(p, 10_000) == (4.0, 2)
    m.on_close("M15", -100.0, -1.0)
    m.on_close("M15", -100.0, -1.0)                      # 4th loss: k capped at 3 -> 8x, but risk cap 5 % / 1 % = 5x
    assert m.scale(p, 10_000) == (5.0, 3)
    m.on_close("M15", +50.0, 0.5)                        # a win resets
    assert m.scale(p, 10_000) == (1.0, 0)
    # break-even exits are neutral: neither step nor reset
    m.on_close("M15", -100.0, -1.0)
    m.on_close("M15", -3.0, -0.03)                       # tiny loss (costs only) = BE -> neutral
    assert m.scale(p, 10_000) == (2.0, 1)
    m.on_close("M15", 0.0, 0.0)
    assert m.scale(p, 10_000) == (2.0, 1)


def test_add_fib_anti_and_shrink():
    p = _plan()
    add = Martingale(TraderConfig(mart_mode="add", mart_mult=1.5, mart_max_steps=5, mart_max_risk_pct=0))
    fib = Martingale(TraderConfig(mart_mode="fib", mart_max_steps=5, mart_max_risk_pct=0))
    shrink = Martingale(TraderConfig(mart_mode="mult", mart_mult=0.5, mart_max_steps=5))
    for k in range(1, 4):
        for m in (add, fib, shrink):
            m.on_close("M5", -50.0, -1.0)
        assert add.scale(p, 1e4) == (1.0 + 0.5 * k, k)
        assert fib.scale(p, 1e4) == ((1.0, 2.0, 3.0)[k - 1], k)
        assert shrink.scale(p, 1e4) == (0.5 ** k, k)
    anti = Martingale(TraderConfig(mart_mode="anti", mart_mult=1.5, mart_max_steps=2, mart_max_risk_pct=0))
    anti.on_close("M5", +50.0, 0.5)
    assert anti.scale(p, 1e4) == (1.5, 1)
    anti.on_close("M5", +50.0, 0.5)
    anti.on_close("M5", +50.0, 0.5)
    assert anti.scale(p, 1e4) == (1.5 ** 2, 2)           # capped at 2 steps
    anti.on_close("M5", -50.0, -1.0)
    assert anti.scale(p, 1e4) == (1.0, 0)


def test_deficit_mode_recovers_the_money_and_gives_up():
    t = TraderConfig(mart_mode="deficit", mart_deficit_r=1.0, mart_max_steps=2, mart_max_risk_pct=0, risk_pct=1.0)
    m = Martingale(t)
    p = _plan()
    m.on_close("M15", -100.0, -1.0)                      # deficit 100 $ ; base risk 1 % of 10 000 = 100 $ -> 2x
    assert m.scale(p, 10_000) == (2.0, 1)
    m.on_close("M15", +60.0, 0.3, step_used=1)           # partial recovery: deficit 40 -> 1.4x
    assert m.scale(p, 10_000) == (1.4, 1)
    m.on_close("M15", -20.0, -0.1, step_used=1)          # a costs-only loss (not a "loss" for k) still adds to the deficit -> 60
    # 2 recovery trades closed -> give up (max_steps) -> reset
    assert m.scale(p, 10_000) == (1.0, 0)
    m.on_close("M15", -100.0, -1.0)
    m.on_close("M15", +200.0, 2.0, step_used=1)          # fully recovered -> reset
    assert m.scale(p, 10_000) == (1.0, 0)


def test_gates_and_scope_and_replay():
    t = TraderConfig(mart_mode="mult", mart_mult=2.0, mart_tfs=("M15",), mart_sides=("buy",), mart_min_quality=0.6,
                     mart_regime="", mart_scope="tf", mart_max_risk_pct=0)
    m = Martingale(t)
    m.on_close("M15", -100, -1.0)
    m.on_close("M5", -100, -1.0)
    m.on_close("M5", -100, -1.0)
    ok = _plan(t)                                        # M15 buy q 0.6
    assert m.scale(ok, 1e4) == (2.0, 1)                  # per-TF streak: M15 has 1 loss (not 3)
    assert m.scale(_plan(t, tf="M5"), 1e4) == (1.0, 0)   # tf gate
    assert m.scale(_plan(t, direction="bearish", side="above"), 1e4) == (1.0, 0)   # side gate
    assert m.scale(_plan(t, quality=0.55), 1e4) == (1.0, 0)                        # quality gate
    t.mart_regime = "trend"
    p_range = TradePlan.from_poi(dict(sel("2026-03-02 10:00")), t, SymbolSpec(), regime="range")
    p_trend = TradePlan.from_poi(dict(sel("2026-03-02 10:00")), t, SymbolSpec(), regime="trend")
    assert m.scale(p_range, 1e4) == (1.0, 0) and m.scale(p_trend, 1e4) == (2.0, 1)
    # live bot: replay from the closed list gives the same state
    m2 = Martingale.replay(t, [("M15", -100, -1.0, 0), ("M5", -100, -1.0, 0), ("M5", -100, -1.0, 0)])
    assert m2.snapshot() == m.snapshot()


def test_mart_scale_feeds_sizing_and_recovery_ladder():
    t = TraderConfig(risk_pct=1.0, tp_levels=("0.6", "1.2", "2.4", "4.8"), tp_fracs=("1", "1", "1", "1"),
                     mart_mode="mult", mart_tp_levels=("0.5", "1.0"), mart_tp_fracs=("1", "1"), mart_sl_after_leg=("0", "x"))
    p = _plan(t)
    s0 = size_plan(p, 10_000, t, SymbolSpec())
    p.mart_scale, p.mart_step = 2.0, 1
    s1 = size_plan(p, 10_000, t, SymbolSpec())
    assert abs(s1.risk_money - 2 * s0.risk_money) < 1.0 and s1.lots_total == 0.4 and s0.lots_total == 0.2
    apply_mart_ladder(p, t, SymbolSpec())
    assert p.tps == (2002.5, 2005.0) and p.tp1 == 2002.5 and p.tp2 == 2005.0 and p.sl_after_leg == ("0", "x") and p.fracs == (0.5, 0.5)
    q = _plan(t)                                          # step 0 -> the normal ladder stays
    apply_mart_ladder(q, t, SymbolSpec())
    assert q.tps == (2003.0, 2006.0, 2012.0, 2024.0)


# ---------------------------------------------------------------------------- B. zone-averaging grid
def test_grid_deep_plan_geometry():
    t = TraderConfig(grid_add_r=0.4, grid_base_frac=0.5, grid_add_frac=0.5, tp_levels=("0.6", "1.2"), tp_fracs=("1", "1"))
    edge = _plan(t)                                       # buy 2000, sl 1995, 1R = 5, tps 2003 / 2006
    deep = grid_deep_plan(edge, t, SymbolSpec())
    assert deep.entry == 1998.0 and deep.sl == 1995.0 and deep.risk == 3.0 and deep.grid_leg and deep.grid_parent == "M15#1"
    assert deep.key == "M15#1+g" and deep.tps == edge.tps and deep.tp1 == 2003.0     # same exit PRICES
    assert abs(deep.risk_scale - 1.0) < 1e-9                                         # add/base = 1 -> same $ budget as the edge
    # own ladder: the same R multiples measured from the deep entry with the deep risk (3) -> 1999.8 / 2001.6
    t.grid_deep_ladder = "own"
    deep2 = grid_deep_plan(edge, t, SymbolSpec())
    assert deep2.tps == (1999.8, 2001.6)
    # sell side mirror
    e2 = _plan(t, direction="bearish", side="above")     # sell 1995, sl 2000
    d2 = grid_deep_plan(e2, TraderConfig(grid_add_r=0.5), SymbolSpec())
    assert d2.entry == 1997.5 and d2.sl == 2000.0 and d2.risk == 2.5


def _grid_cfg(**kw):
    base = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), grid_add_r=0.5, grid_base_frac=0.5, grid_add_frac=0.5, grid_cancel_on_partial=False)
    base.update(kw)
    return cfg(**base)


def test_grid_stopped_plan_loses_the_budget_split_and_deep_fills_deeper():
    # zone 1995-2000, 1R = 5; edge 0.5 % budget at 2000 (lots 0.1), deep 0.5 % budget at 1997.5 (risk 2.5 -> lots 0.2); both stopped at 1995
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1997.0, 1997.5), (1997.5, 1997.6, 1994.5, 1994.8)])
    res, sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(), spec()), None
    r = res.run()
    t = r.trades.sort_values("entry_time")
    assert len(t) == 2 and list(t.grid_leg) == [False, True]
    edge, deep = t.iloc[0], t.iloc[1]
    assert edge.entry == 2000.0 and edge.lots == 0.1 and deep.entry == 1997.5 and deep.lots == 0.2
    assert abs(edge.net + 50.0) < 1e-6 and abs(deep.net + 50.0) < 1e-6          # each leg loses its half of the 1 % budget
    assert res.grid_placed == 1 and res.grid_filled == 1
    # base 0.5 + add 0.3 < 1: a fully stopped plan loses 0.8 % instead of 1 %
    r2 = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(grid_add_frac=0.3), spec()).run()
    assert abs(r2.trades.net.sum() + 80.0) < 1e-6


def test_grid_deep_not_filled_shallow_winner_and_deep_cancelled_with_edge():
    # price dips to 1998.5 (0.3 R deep) then runs to the 1R target 2005: the deep order at 1997.5 never fills and is cancelled
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1998.5, 1999), (1999, 2005.5, 1998.9, 2005.2)])
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(), spec())
    r = sim.run()
    t = r.trades
    assert len(t) == 1 and not t.grid_leg[0] and t.outcome[0] == "tp2" and abs(t.net[0] - 50.0) < 1e-6
    assert sim.grid_placed == 1 and sim.grid_filled == 0
    assert any(c.plan.grid_leg and c.reason_cancel == "edge closed" for c in sim.cancelled)


def test_grid_deep_fills_then_both_win_at_the_same_price():
    # dip to 1997.0 (deep fills at 1997.5), then to the 1R target 2005: edge +50 $, deep 0.2 lots x 7.5 = +150 $
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1997.0, 1997.5), (1997.5, 2005.5, 1997.4, 2005.2)])
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(), spec())
    t = sim.run().trades.sort_values("entry_time")
    assert len(t) == 2 and abs(t.iloc[0].net - 50.0) < 1e-6 and abs(t.iloc[1].net - 150.0) < 1e-6
    assert t.iloc[1].outcome == "tp2" and t.iloc[1].grid_parent == "M15#1"


def test_grid_deep_does_not_take_a_slot_and_is_cancelled_on_partial():
    # max_open_positions=1: the deep leg must still be allowed to fill (it belongs to the edge plan)
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1997.0, 1997.5), (1997.5, 2005.5, 1997.4, 2005.2)])
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(max_open_positions=1), spec())
    assert len(sim.run().trades) == 2
    # two-leg ladder: the edge takes its first partial at 2002 BEFORE the deep order fills -> deep order withdrawn
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2002.5, 2000.5, 2002.2), (2002.2, 2002.3, 1997.0, 1998),
               (1998, 2000.2, 1997.5, 2000.1)])
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]),
                             _grid_cfg(tp_levels=("0.4", "1.5"), tp_fracs=("1", "1"), be_offset_r=0.0, grid_cancel_on_partial=True), spec())
    r = sim.run()
    assert sim.grid_filled == 0 and any(c.reason_cancel == "edge took a partial" for c in sim.cancelled)
    assert len(r.trades) == 1 and not r.trades.grid_leg[0]


def test_grid_gates_regime_and_tf():
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1997.0, 1997.5), (1997.5, 2005.5, 1997.4, 2005.2)])
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(grid_tfs=("M5",)), spec())
    assert len(sim.run().trades) == 1 and sim.grid_placed == 0
    sim = PortfolioSimulator(m1, pd.DataFrame([sel("2026-03-02 10:00")]), _grid_cfg(grid_regime="range"), spec())
    assert len(sim.run().trades) == 1 and sim.grid_placed == 0          # regime lever off -> plan.regime "" != "range"


def test_martingale_in_sim_steps_after_a_loss_and_resets_after_a_win():
    # trade 1 (10:00, zone 1995-2000) stopped; trade 2 (poi 2, zone 1985-1990) placed after the stop -> 2x size; then a win resets
    seq = [(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.6, 2001), (2001, 2001, 1994.5, 1994.8),        # trade 1 fills, stopped
           (1994.8, 1995, 1994.6, 1994.9),                                                              # 10:03 event for poi 2
           (1994.9, 1995, 1989.6, 1990.5), (1990.5, 1995.6, 1990.4, 1995.2),                             # trade 2 fills 1990, tp 1R = 1995
           (1995.2, 1995.5, 1995.0, 1995.3),                                                            # 10:06 event for poi 3
           (1995.3, 1995.4, 1979.6, 1980.5), (1980.5, 1985.6, 1980.4, 1985.2)]                           # trade 3 fills 1980, tp 1985
    m1 = bars(seq)
    ev = [sel("2026-03-02 10:00"), sel("2026-03-02 10:03", top=1990.0, bottom=1985.0, pid=2), sel("2026-03-02 10:06", top=1980.0, bottom=1975.0, pid=3)]
    t = cfg(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), mart_mode="mult", mart_mult=2.0, mart_max_risk_pct=0, max_open_positions=4)
    r = PortfolioSimulator(m1, pd.DataFrame(ev), t, spec()).run()
    tr = r.trades.sort_values("entry_time").reset_index(drop=True)
    assert list(tr.mart_step) == [0, 1, 0] and list(tr.mart_scale) == [1.0, 2.0, 1.0]
    # 1 % of 10 000 / (5 x 100) = 0.2 lots; after the -100 $ loss equity 9 900 -> 2 % = 198 $ / 500 = 0.396 -> 0.39 (rounded down)
    assert tr.lots[0] == 0.2 and abs(tr.lots[1] - 0.39) < 1e-9 and abs(tr.risk_money[1] - 195.0) < 1e-6
    assert tr.net[0] < 0 and tr.net[1] > 0 and tr.net[2] > 0
    assert r.summary()["mart_trades"] == 1 and r.summary()["mart_max_scale"] == 2.0


def test_asymmetric_ungated_scale_steps_down_where_the_gate_fails():
    t = TraderConfig(mart_mode="mult", mart_mult=1.5, mart_tfs=("M15",), mart_ungated_scale=0.5, mart_max_risk_pct=0)
    m = Martingale(t)
    ok, m5 = _plan(t), _plan(t, tf="M5")
    assert m.scale(ok, 1e4) == (1.0, 0) and m.scale(m5, 1e4) == (1.0, 0)     # no streak -> nobody is touched
    m.on_close("M15", -100, -1.0)
    assert m.scale(ok, 1e4) == (1.5, 1) and m.scale(m5, 1e4) == (0.5, -1)    # up where gated in, down where gated out
    m.on_close("M5", +30, 0.3, step_used=-1)                                  # a stepped-down win resets the streak too
    assert m.scale(m5, 1e4) == (1.0, 0)
    t.mart_ungated_scale = 1.0
    m.on_close("M15", -100, -1.0)
    assert m.scale(m5, 1e4) == (1.0, 0)                                       # classic gate: untouched
