"""v16 - the strings shipped in run_trader.bat parse into the TraderConfig of the v16-A study variant (M20SC_0.63_x0.4: M20
timeframe traded only when confluent at quality >= 0.63, sized x0.4) ON TOP of v15-A / v14-A / v13-A, with every other v16 lever
(rank-2 zones, keep-demoted) OFF.  No CSV needed: the bat config is compared field by field with the config the study used."""
import dataclasses
import json
import re

from lubot.config import TIMEFRAME_MINUTES
from lubot.execution import TraderConfig
from run_v10_study import BASE
from tests.test_bat_v13 import _bat_line
from v16_common import V15A_CF, V15A_FLT, v15a_config


def _bat_config():
    line = _bat_line()
    trader = re.search(r'--trader "([^"]*)"', line).group(1)
    flt = re.search(r'--trade-filter "([^"]*)"', line).group(1)
    cf = re.search(r'--confluence-filter "([^"]*)"', line).group(1)
    tfs = tuple(re.search(r"--timeframes (\S+)", line).group(1).split(","))
    t = TraderConfig(risk_pct=1.0, trade_filter=flt, confluence_filter=cf, max_daily_loss_pct=4.5,
                     max_total_loss_pct=9.0).override(BASE).override(trader)
    return t, tfs


def _study_config():
    """The exact overrides string of the shipped study json (as the grid replayed it) applied to v15-A."""
    bat = open("run_trader.bat", encoding="utf-8").read()
    path = re.search(r"REM v16 study: (\S+)", bat).group(1)
    study = json.load(open(path))
    return v15a_config().override(study["overrides"]), study


def test_bat_timeframes_include_m20():
    _, tfs = _bat_config()
    assert tfs == ("M5", "M10", "M15", "M20", "M30", "H1")
    assert all(tf in TIMEFRAME_MINUTES for tf in tfs) and TIMEFRAME_MINUTES["M20"] == 20


def test_bat_trader_string_is_v16a():
    t, _ = _bat_config()
    # v16-A: M20 confluent-only (plain bar unreachable, confluence bar 0.63), sized x0.4, in the TF-scoped keys
    assert t.trade_filter == V15A_FLT + "/M20:min_quality=0.99"
    assert t.confluence_filter == V15A_CF + "/M20:min_quality=0.63"
    assert t.tf_risk_scale == "M20:0.4"
    assert t.keep_replaced_tfs == ("M10", "M15", "M20", "M30", "H1")
    assert t.mart_tfs == ("M10", "M15", "M20", "M30", "H1")
    # the other v16 levers are OFF (rank-2 zones lose; keep-demoted = v16-B only)
    assert t.max_rank == 1 and t.rank2_filter == "" and t.rank2_risk_scale == 1.0 and t.rank2_tfs == ()
    assert t.rank2_confluent_only is False
    # v15-A / v14-A / v13-A still underneath
    assert t.confluence_memory_min == 240 and t.confluent_risk_scale == 1.25 and t.plain_risk_scale == 0.9
    assert t.mart_mode == "mult" and t.mart_mult == 1.5 and t.mart_scope == "tf" and t.mart_ungated_scale == 0.5
    assert t.regime_metric == "adr_ratio" and t.range_tp_levels == ("0.5", "1.0", "1.5", "2.5")
    assert "v16" in open("run_trader.bat", encoding="utf-8").read().splitlines()[1]


def test_bat_config_equals_shipped_study_config():
    """Every TraderConfig field of the bat == the field of the study variant named in the bat header (M20SC_0.63_x0.4),
    except `timeframes`, which the live bot takes from --timeframes (the study passes it inside the overrides)."""
    t, tfs = _bat_config()
    s, study = _study_config()
    assert study["name"] == "M20SC_0.63_x0.4" and study["trades"] == 467
    diffs = {f.name: (getattr(t, f.name), getattr(s, f.name)) for f in dataclasses.fields(TraderConfig)
             if getattr(t, f.name) != getattr(s, f.name)}
    assert set(diffs) <= {"timeframes"}, diffs
    assert tuple(s.timeframes) == tfs


# ----------------------------------------------------------------------------------------------------------- live bot (fake MT5)
def _m20_slot(top=1990.0, bottom=1985.0, pid=20, q=0.65):
    """An M20 selection on the same level as the M15 zone of tests.test_trader_live.selection (confluent) - or alone (plain)."""
    return {"tf": "M20", "time": "2026-03-02 10:00:00", "price": 2000.0, "range_bias": "none", "price_zone": "n/a",
            "above": None, "candidates_above": 0, "candidates_below": 1,
            "below": {"id": pid, "tf": "M20", "type": "OB", "direction": "bullish", "top": top - 0.5, "bottom": bottom + 0.5,
                      "mid": (top + bottom) / 2, "key_level": top - 0.5, "quality": q, "grade": "B", "distance": 10.0,
                      "distance_atr": 2.5, "time": "2026-03-02 09:40:00", "liquidity_between": [], "orderflow_count": 2}}


def test_live_m20_confluent_only_at_063_sized_x04(tmp_path):
    """The shipped v16-A gates, through trader.py against the fake terminal: an M20 zone is placed ONLY when confluent AND q >= 0.63,
    at 40 % of the (confluent x1.25) size; plain M20 zones never trade."""
    import math
    from tests.fake_mt5 import FakeMT5
    from tests.test_trader_live import make_m1, make_trader, selection
    t, _ = _bat_config()
    kw = dict(trade_filter=t.trade_filter, confluence_filter=t.confluence_filter, tf_risk_scale=t.tf_risk_scale,
              confluent_risk_scale=t.confluent_risk_scale, plain_risk_scale=t.plain_risk_scale,
              tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)
    # 1) plain M20 zone (nothing else on the level): the 0.99 bar rejects it
    tr, _, state = make_trader(tmp_path, FakeMT5(make_m1(), bid=2000.0), **kw)
    tr.on_selection({"M20": _m20_slot(q=0.80)})
    assert "M20#20" not in state.plans
    # 2) confluent (an M15 plan on the same level is active) but q 0.60 < 0.63 -> rejected
    (tmp_path / "b").mkdir()
    tr2, _, state2 = make_trader(tmp_path / "b", FakeMT5(make_m1(), bid=2000.0), **kw)
    tr2.on_selection({"M15": selection(pid=1)["M15"], "M20": _m20_slot(q=0.60)})
    assert "M15#1" in state2.plans and "M20#20" not in state2.plans
    # 3) confluent and q 0.65 -> placed, confluent, risk_scale = 1.25 (confluent) x 0.4 (M20) = 0.5
    (tmp_path / "c").mkdir()
    tr3, broker3, state3 = make_trader(tmp_path / "c", FakeMT5(make_m1(), bid=2000.0), **kw)
    tr3.on_selection({"M15": selection(pid=1)["M15"], "M20": _m20_slot(q=0.65)})
    p15, p20 = state3.plans["M15#1"], state3.plans["M20#20"]
    assert not p15["confluent"] and p15["risk_scale"] == 0.9                      # placed first = plain x0.9
    assert p20["confluent"] and math.isclose(p20["risk_scale"], 0.5)
    # M15: 0.9 % of 10 000 / 5 $ risk = 0.18 lots; M20: 0.5 % / 4 $ (zone 1989.5-1985.5) = 0.125 -> 0.12 (broker step 0.01)
    assert math.isclose(p15["lots_total"], 0.18) and math.isclose(p20["lots_total"], 0.12)
    assert len(broker3.orders(tr3.magic)) == 4


def test_live_scanner_builds_m20_from_m1():
    """The live scanner derives the M20 timeframe from M1 like every other one (the bat's --timeframes carries M20)."""
    from lubot.config import StrategyConfig
    from lubot.engine import MultiTimeframeScanner
    from tests.test_trader_live import make_m1
    m1 = make_m1(n=6000)
    cfg = StrategyConfig(timeframes=("M15", "M20", "M30"), selection_mode="closest")
    out = MultiTimeframeScanner(m1[["open", "high", "low", "close", "volume"]], cfg).scan(top_k=1)
    assert set(out) == {"M15", "M20", "M30"}
    assert out["M20"]["tf"] == "M20"
    for side in ("above", "below"):
        z = out["M20"].get(side)
        if z:
            assert z["tf"] == "M20"
