"""v15 - live bot (fake MT5): conviction sizing, tiered admission, confluence memory persisted across a restart."""
import math

from tests.fake_mt5 import FakeMT5
from tests.test_trader_live import make_m1, make_trader, selection

LADDER = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)


def two_tf(top=1990.0, bottom=1985.0, pid5=7, q5=0.62, with_m15=True, pid15=1):
    """M15 zone shown (optional) + an M5 zone on the same level (overlap 80 %)."""
    s = selection(top=top, bottom=bottom, pid=pid15)
    m5 = {"tf": "M5", "time": "2026-03-02 10:00:00", "price": 2000.0, "range_bias": "none", "price_zone": "n/a", "above": None,
          "candidates_above": 0, "candidates_below": 1,
          "below": {"id": pid5, "tf": "M5", "type": "OB", "direction": "bullish", "top": top - 0.5, "bottom": bottom + 0.5,
                    "mid": (top + bottom) / 2, "key_level": top - 0.5, "quality": q5, "grade": "B", "distance": 10.0,
                    "distance_atr": 2.5, "time": "2026-03-02 09:55:00", "liquidity_between": [], "orderflow_count": 2}}
    return {"M15": s["M15"], "M5": m5} if with_m15 else {"M5": m5}


def test_live_conviction_sizing_and_tier(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    # (confluence is only judged when a confluence_filter is set - same rule as the simulator)
    tr, broker, state = make_trader(tmp_path, fake, confluent_risk_scale=1.5, plain_risk_scale=0.5, confluence_filter="M5:min_quality=0.50",
                                    **LADDER)
    tr.on_selection(two_tf())
    p15, p5 = state.plans["M15#1"], state.plans["M5#7"]
    # M15 placed first = plain (x0.5): 0.5 % of 10 000 / 5 $ = 0.10 lots; M5 overlaps it = confluent (x1.5): 1.5 % / 4 $ = 0.375 -> 0.37
    assert not p15["confluent"] and p5["confluent"]
    assert p15["risk_scale"] == 0.5 and p5["risk_scale"] == 1.5
    assert math.isclose(p15["lots_total"], 0.10) and math.isclose(p5["lots_total"], 0.37)
    # tier: an M5 zone with q 0.52 fails the normal bar (0.55) but passes the tier bar (0.50) -> admitted at x0.4
    fake2 = FakeMT5(make_m1(), bid=2000.0)
    (tmp_path / "b").mkdir()
    tr2, _, state2 = make_trader(tmp_path / "b", fake2, trade_filter="M5:min_quality=0.55", tier_filter="M5:min_quality=0.50",
                                 tier_risk_scale=0.4, **LADDER)
    tr2.on_selection(two_tf(with_m15=False, q5=0.52))
    p = state2.plans["M5#7"]
    assert p["tier"] and p["risk_scale"] == 0.4 and math.isclose(p["lots_total"], 0.10)       # 0.4 % / 4 $ = 0.10
    # q 0.48 fails both bars -> nothing placed
    tr2.on_selection(two_tf(with_m15=False, q5=0.48, pid5=8))
    assert "M5#8" not in state2.plans


def test_live_confluence_memory_survives_cancel_and_restart(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    kw = dict(trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50", confluence_memory_min=30, **LADDER)
    tr, broker, state = make_trader(tmp_path, fake, **kw)
    tr.on_selection(selection(pid=1))                          # M15 order placed
    assert "M15#1" in state.plans
    # the M15 slot is cleared -> the order is cancelled -> remembered
    tr.on_selection({"M15": {**selection(pid=1)["M15"], "below": None}})
    assert "M15#1" not in state.plans and len(state.memory) == 1 and state.memory[0][0] == "M15" and state.memory[0][5] is False
    # an M5 zone on the same level with q 0.52: nothing active on another TF, but the memory (< 30 min) makes it confluent
    tr.on_selection(two_tf(with_m15=False, q5=0.52))
    assert "M5#7" in state.plans and state.plans["M5#7"]["confluent"]
    # RESTART: the memory is persisted in the state file
    tr2, _, state2 = make_trader(tmp_path, fake, **kw)
    assert state2.memory == state.memory
    # without the memory lever the same M5 zone is rejected
    fake3 = FakeMT5(make_m1(), bid=2000.0)
    (tmp_path / "c").mkdir()
    tr3, _, state3 = make_trader(tmp_path / "c", fake3, trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50", **LADDER)
    tr3.on_selection(selection(pid=1))
    tr3.on_selection({"M15": {**selection(pid=1)["M15"], "below": None}})
    tr3.on_selection(two_tf(with_m15=False, q5=0.52))
    assert "M5#7" not in state3.plans and state3.memory == []
