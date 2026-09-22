"""Unit tests for the v7 execution layer (trade plan, sizing)."""
import math

from lubot.execution import BUY, SELL, SymbolSpec, TradePlan, TraderConfig, expected_outcomes, size_plan


def bull_poi(top=2000.0, bottom=1995.0, atr=4.0):
    return {"id": 7, "tf": "M15", "type": "OB", "direction": "bullish", "top": top, "bottom": bottom,
            "quality": 0.63, "grade": "B", "distance": 8.0, "distance_atr": round(8.0 / atr, 2), "time": "2026-03-02 10:00:00"}


def bear_poi(top=2010.0, bottom=2006.0, atr=4.0):
    return {"id": 8, "tf": "H1", "type": "IMB", "direction": "bearish", "top": top, "bottom": bottom,
            "quality": 0.55, "grade": "B", "distance": 6.0, "distance_atr": round(6.0 / atr, 2)}


def test_bull_plan_entry_top_sl_bottom():
    p = TradePlan.from_poi(bull_poi(), TraderConfig())
    assert p.side == BUY
    assert p.entry == 2000.0 and p.sl == 1995.0           # entry = start (top), SL = end (bottom)
    assert p.risk == 5.0
    assert p.tp1 == 2002.0                                  # +0.4R
    assert p.tp2 == 2007.5                                  # +1.5R
    assert p.be_price == 2000.0
    assert math.isclose(p.r_of(2002.0), 0.4)
    assert math.isclose(p.r_of(1995.0), -1.0)


def test_bear_plan_entry_bottom_sl_top():
    p = TradePlan.from_poi(bear_poi(), TraderConfig())
    assert p.side == SELL
    assert p.entry == 2006.0 and p.sl == 2010.0
    assert p.risk == 4.0
    assert p.tp1 == 2004.4 and p.tp2 == 2000.0
    assert math.isclose(p.r_of(2004.4), 0.4)


def test_sl_buffer_and_offset_options():
    p = TradePlan.from_poi(bull_poi(), TraderConfig(sl_buffer_atr=0.5, be_offset_r=0.1))
    assert p.sl == 1993.0                                   # bottom - 0.5 * ATR(4)
    assert p.risk == 7.0
    assert math.isclose(p.be_price, 2000.7)


def test_degenerate_zone_rejected():
    assert TradePlan.from_poi(bull_poi(top=2000.0, bottom=2000.0), TraderConfig()) is None


def test_sizing_split_mode():
    spec = SymbolSpec()
    p = TradePlan.from_poi(bull_poi(), TraderConfig())      # 1R = $5 -> $500 per lot
    s = size_plan(p, 10_000.0, TraderConfig(risk_pct=1.0), spec)   # risk $100 -> 0.2 lots
    assert s.ok and math.isclose(s.lots_total, 0.20) and math.isclose(s.lots_leg1, 0.10) and math.isclose(s.lots_leg2, 0.10)
    assert math.isclose(s.risk_money, 100.0)
    # rounding down: risk $37 -> 0.074 lots -> 0.07 -> legs 0.03 / 0.04
    s = size_plan(p, 3_700.0, TraderConfig(risk_pct=1.0), spec)
    assert math.isclose(s.lots_total, 0.07) and math.isclose(s.lots_leg1, 0.03) and math.isclose(s.lots_leg2, 0.04)
    assert s.risk_money <= 37.0 + 1e-9
    # too small for two legs -> rejected (never over-risk)
    s = size_plan(p, 700.0, TraderConfig(risk_pct=1.0), spec)     # $7 -> 0.014 -> 0.01 lot
    assert not s.ok


def test_sizing_netting_mode_single_leg_fallback():
    spec = SymbolSpec()
    p = TradePlan.from_poi(bull_poi(), TraderConfig())
    s = size_plan(p, 700.0, TraderConfig(risk_pct=1.0, exec_mode="netting"), spec)
    assert s.ok and math.isclose(s.lots_total, 0.01) and s.lots_leg1 == 0.0 and math.isclose(s.lots_leg2, 0.01)


def test_expected_outcomes_default_spec():
    o = expected_outcomes(TraderConfig())
    assert o["stop_before_partial"] == -1.0
    assert math.isclose(o["partial_then_breakeven"], 0.2)          # 0.5 * 0.4
    assert math.isclose(o["partial_then_tp2"], 0.95)               # 0.5 * 0.4 + 0.5 * 1.5


def test_overrides_parser():
    t = TraderConfig().override("risk_pct=0.5,exec_mode=netting,grades=A|B,min_quality=0.6,max_open_positions=2")
    assert t.risk_pct == 0.5 and t.exec_mode == "netting" and t.grades == ("A", "B")
    assert t.min_quality == 0.6 and t.max_open_positions == 2


def test_overlap():
    a = TradePlan.from_poi(bull_poi(2000, 1995), TraderConfig())
    b = TradePlan.from_poi(bull_poi(1998, 1990), TraderConfig())
    assert math.isclose(a.overlaps(b), 3 / 5)
    c = TradePlan.from_poi(bull_poi(1990, 1980), TraderConfig())
    assert a.overlaps(c) == 0.0
