"""v16 - live bot (fake MT5): ranked candidates (rank-2 zones) placed with their own bar / scale, kept while shown on any rank slot,
cancelled when they leave the ranked list; scanner.scan(top_k) returns the ranked lists."""
import math

import pandas as pd

from lubot.config import StrategyConfig
from lubot.engine import MultiTimeframeScanner
from tests.fake_mt5 import FakeMT5
from tests.test_trader_live import make_m1, make_trader, selection

LADDER = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)


def ranked_selection(r1=(1990.0, 1985.0, 1), r2=(1980.0, 1975.0, 2), q2=0.62):
    s = selection(top=r1[0], bottom=r1[1], pid=r1[2])
    m15 = s["M15"]
    d1 = dict(m15["below"], rank=1)
    ranked = [d1]
    if r2 is not None:
        d2 = dict(d1, id=r2[2], top=r2[0], bottom=r2[1], mid=(r2[0] + r2[1]) / 2, key_level=r2[0], quality=q2, rank=2)
        ranked.append(d2)
    m15["below_ranked"] = ranked
    m15["above_ranked"] = []
    m15["candidates_below"] = len(ranked)
    return s


def test_live_rank2_zone_placed_scaled_and_cancelled_when_gone(tmp_path):
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, broker, state = make_trader(tmp_path, fake, max_rank=2, rank2_risk_scale=0.5, **LADDER)
    tr.on_selection(ranked_selection())
    assert set(state.plans) == {"M15#1", "M15#2"}
    p1, p2 = state.plans["M15#1"], state.plans["M15#2"]
    assert p1["rank"] == 1 and p1["risk_scale"] == 1.0 and math.isclose(p1["lots_total"], 0.20)      # 1 % / 5 $
    assert p2["rank"] == 2 and p2["risk_scale"] == 0.5 and math.isclose(p2["lots_total"], 0.10)      # 0.5 % / 5 $
    assert len(broker.orders(tr.magic)) == 4                                                           # 2 legs each
    # rank 2 leaves the ranked list -> its order is cancelled, rank 1 untouched
    tr.on_selection(ranked_selection(r2=None))
    assert set(state.plans) == {"M15#1"} and len(broker.orders(tr.magic)) == 2
    # promotion: #2 comes back as rank 1 (replacing #1) -> #2 placed again, #1 kept 1 bar (keep_replaced) or cancelled
    tr.on_selection(ranked_selection(r1=(1980.0, 1975.0, 2), r2=(1990.0, 1985.0, 1)))
    assert set(state.plans) == {"M15#1", "M15#2"}
    assert state.plans["M15#2"]["rank"] == 1 and state.plans["M15#1"]["rank"] == 1          # #1 keeps its original plan (rank 1)


def test_live_rank2_gates(tmp_path):
    # max_rank 1 (default): the ranked list is ignored
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr, _, state = make_trader(tmp_path, fake, **LADDER)
    tr.on_selection(ranked_selection())
    assert set(state.plans) == {"M15#1"}
    # own bar: q 0.62 < 0.70 -> rank 2 rejected
    (tmp_path / "b").mkdir()
    tr2, _, state2 = make_trader(tmp_path / "b", FakeMT5(make_m1(), bid=2000.0), max_rank=2, rank2_filter="M15:min_quality=0.70", **LADDER)
    tr2.on_selection(ranked_selection())
    assert set(state2.plans) == {"M15#1"}
    # tf scope
    (tmp_path / "c").mkdir()
    tr3, _, state3 = make_trader(tmp_path / "c", FakeMT5(make_m1(), bid=2000.0), max_rank=2, rank2_tfs=("M10",), **LADDER)
    tr3.on_selection(ranked_selection())
    assert set(state3.plans) == {"M15#1"}
    # overlap with the rank-1 zone of the same TF -> deduped
    (tmp_path / "d").mkdir()
    tr4, _, state4 = make_trader(tmp_path / "d", FakeMT5(make_m1(), bid=2000.0), max_rank=2, **LADDER)
    tr4.on_selection(ranked_selection(r2=(1989.0, 1984.0, 2)))
    assert set(state4.plans) == {"M15#1"}


def test_scanner_scan_top_k_returns_ranked_lists():
    m1 = make_m1()
    cfg = StrategyConfig(timeframes=("M15",), selection_mode="closest")
    sc = MultiTimeframeScanner(m1[["open", "high", "low", "close", "volume"]], cfg)
    out = sc.scan(top_k=3)["M15"]
    assert "above_ranked" in out and "below_ranked" in out
    for side in ("above", "below"):
        lst = out[side + "_ranked"]
        assert len(lst) <= 3 and len(lst) == min(3, out["candidates_" + side])
        if lst:
            assert lst[0]["id"] == out[side]["id"] and [c["rank"] for c in lst] == list(range(1, len(lst) + 1))
    # top_k 1 -> the classic dict (no ranked lists)
    sc2 = MultiTimeframeScanner(m1[["open", "high", "low", "close", "volume"]], cfg)
    assert "above_ranked" not in sc2.scan()["M15"]


def test_live_tf_risk_scale(tmp_path):
    tr, _, state = make_trader(tmp_path, FakeMT5(make_m1(), bid=2000.0), tf_risk_scale="M15:0.5", **LADDER)
    tr.on_selection(selection())
    assert state.plans["M15#5"]["risk_scale"] == 0.5 and math.isclose(state.plans["M15#5"]["lots_total"], 0.10)
