"""v16b - the strings shipped in run_trader.bat parse into the TraderConfig of the v16b-A study variant (C_F2+RS_0.5: impulsive-arrival
guard min_fill_age_min=2 + range-regime sells at half size) ON TOP of v16-A / v15-A / v14-A / v13-A, with every other v16b lever (daily
trend gate, fast-fill scaling, BE trigger, tighter day cap) OFF.  No CSV needed: the bat config is compared field by field with the config
the study used, and the live bot (fake MT5) is driven with the shipped strings.
"""
import dataclasses
import json
import math
import re

import pandas as pd

from lubot.execution import TraderConfig
from tests.test_bat_v16 import _bat_config
from v16b_common import V16A_CF, V16A_FLT, v16a_config

V16B_KEYS = {"min_fill_age_min", "regime_side_scale"}


def _study_config():
    """The exact overrides string of the shipped study json (as the grid replayed it) applied to v16-A."""
    bat = open("run_trader.bat", encoding="utf-8").read()
    path = re.search(r"REM v16b study: (\S+)", bat).group(1)
    study = json.load(open(path))
    return v16a_config().override(study["overrides"]), study


def test_bat_header_is_v16b_and_names_the_study():
    bat = open("run_trader.bat", encoding="utf-8").read().splitlines()
    assert "v16b" in bat[1] and "LESS_LOSS_V16B" in bat[1]
    assert any(l.startswith("REM v16b study: study_results/v16b_levers/C_F2+RS_0.5.json") for l in bat)
    assert any(l.startswith("REM Previous layer (v16-A") for l in bat)          # the v16 header is kept as history
    assert any(l.startswith("REM v16 study: ") for l in bat)                     # test_bat_v16 still finds the v16 study


def test_bat_trader_string_is_v16b_a():
    t, tfs = _bat_config()
    # v16b-A = the two levers
    assert t.min_fill_age_min == 2 and t.fast_fill_mode == "cancel"
    assert t.fast_fill_tfs == () and t.fast_fill_regime == ""                    # unscoped (F2, not F3_m510 / F3_rng)
    assert t.regime_side_scale == "range:sell:0.5"
    # the other v16b levers are OFF
    assert t.trend_sma == 0 and t.trend_mode == "skip" and t.trend_tfs == () and t.trend_regime == ""
    assert t.be_trigger_r in (0, 0.0, None) or not t.be_trigger_r
    assert t.max_daily_loss_pct == 4.5 and t.max_total_loss_pct == 9.0
    # v16-A / v15-A / v14-A / v13-A still underneath, unchanged
    assert tfs == ("M5", "M10", "M15", "M20", "M30", "H1")
    assert t.trade_filter == V16A_FLT and t.confluence_filter == V16A_CF
    assert t.tf_risk_scale == "M20:0.4" and t.max_rank == 1
    assert t.confluence_memory_min == 240 and t.confluent_risk_scale == 1.25 and t.plain_risk_scale == 0.9
    assert t.mart_mode == "mult" and t.mart_mult == 1.5 and t.mart_scope == "tf" and t.mart_sides == ("buy",)
    assert t.regime_metric == "adr_ratio" and t.regime_threshold == 1.0 and t.range_tp_levels == ("0.5", "1.0", "1.5", "2.5")


def test_bat_config_equals_shipped_study_config():
    """Every TraderConfig field of the bat == the field of the study variant named in the bat header (C_F2+RS_0.5),
    except `timeframes`, which the live bot takes from --timeframes (the study passes it inside v16a_config)."""
    t, tfs = _bat_config()
    s, study = _study_config()
    assert study["name"] == "C_F2+RS_0.5" and study["trades"] == 446 and study["score"] == 4
    diffs = {f.name: (getattr(t, f.name), getattr(s, f.name)) for f in dataclasses.fields(TraderConfig)
             if getattr(t, f.name) != getattr(s, f.name)}
    assert set(diffs) <= {"timeframes"}, diffs
    assert tuple(s.timeframes) == tfs


def test_bat_minus_v16b_keys_is_v16a():
    """Dropping the two v16b keys from the bat string gives the v16-A config byte for byte (the reference of FINAL_BACKTEST_V16B)."""
    from backtest_v16b_final import strip_v16b
    from tests.test_bat_v13 import _bat_line
    from run_v10_study import BASE
    line = _bat_line()
    trader = re.search(r'--trader "([^"]*)"', line).group(1)
    dropped = {kv.partition("=")[0] for kv in trader.split(",")} - {kv.partition("=")[0] for kv in strip_v16b(trader).split(",")}
    assert dropped == V16B_KEYS
    t = TraderConfig(risk_pct=1.0, trade_filter=V16A_FLT, confluence_filter=V16A_CF, max_daily_loss_pct=4.5,
                     max_total_loss_pct=9.0).override(BASE).override(strip_v16b(trader))
    ref = v16a_config()
    diffs = {f.name for f in dataclasses.fields(TraderConfig) if getattr(t, f.name) != getattr(ref, f.name)}
    assert diffs <= {"timeframes"}, diffs


# ----------------------------------------------------------------------------------------------------------- live bot (fake MT5)
def test_live_shipped_strings_fast_fill_and_range_sell_half(tmp_path):
    """The shipped v16b-A keys through trader.py against the fake terminal: (1) in a 'range' regime a SELL is placed at HALF risk
    (0.5 % / 5 $ = 0.10 lots) while a BUY stays at 1 % (0.20 lots); (2) a position that opened < 2 min after its order was placed
    is closed at market (FAST FILL) and the plan is finished; a fill 3 min after placement is kept."""
    from tests.fake_mt5 import FakeMT5
    from tests.test_trader_live import make_m1, make_trader, selection
    from tests.test_trader_v16b import sell_selection, trending_m1
    t, _ = _bat_config()
    base = dict(min_fill_age_min=t.min_fill_age_min, fast_fill_mode=t.fast_fill_mode, regime_side_scale=t.regime_side_scale,
                tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)
    # --- (1) regime x side sizing: adr_ratio with a huge threshold -> every plan is placed in a 'range' regime
    m1 = trending_m1(up=False, n_days=24, bars_per_day=200)
    px = float(m1.close.iloc[-1])
    tr, _, state = make_trader(tmp_path, FakeMT5(m1, bid=px), history_bars=6000, regime_metric=t.regime_metric,
                               regime_threshold=100.0, regime_short=t.regime_short, regime_long=t.regime_long, **base)
    tr.refresh_history()
    both = sell_selection(top=px + 12, bottom=px + 7, pid=9)
    both["M15"]["below"] = selection(top=px - 7, bottom=px - 12, pid=5)["M15"]["below"]
    both["M15"]["candidates_below"] = 1
    tr.on_selection(both)
    ps, pb = state.plans["M15#9"], state.plans["M15#5"]
    assert ps["regime"] == "range" and ps["side"] == "sell" and ps["risk_scale"] == 0.5 and math.isclose(ps["lots_total"], 0.10)
    assert pb["regime"] == "range" and pb["side"] == "buy" and pb["risk_scale"] == 1.0 and math.isclose(pb["lots_total"], 0.20)
    # the same sell in a 'trend' regime (threshold 0 -> never range) is full size
    (tmp_path / "t").mkdir()
    tr2, _, state2 = make_trader(tmp_path / "t", FakeMT5(m1, bid=px), history_bars=6000, regime_metric=t.regime_metric,
                                 regime_threshold=0.0, regime_short=t.regime_short, regime_long=t.regime_long, **base)
    tr2.refresh_history()
    tr2.on_selection(sell_selection(top=px + 12, bottom=px + 7, pid=9))
    assert state2.plans["M15#9"]["regime"] == "trend" and state2.plans["M15#9"]["risk_scale"] == 1.0
    # --- (2) fast-fill guard at the shipped N = 2 min: a 1-min fill is closed at market, a 3-min fill is kept
    (tmp_path / "f").mkdir()
    fake = FakeMT5(make_m1(), bid=2000.0)
    tr3, _, state3 = make_trader(tmp_path / "f", fake, **base)
    tr3.on_selection(selection())
    assert "M15#5" in state3.plans and len(fake.orders) == 2
    fake.set_price(1989.5, advance_seconds=60)
    tr3.manage()
    assert "M15#5" not in state3.plans and not fake.positions and not fake.orders
    assert len(fake.history) == 2 and all(h["reason"] == "market" for h in fake.history)
    (tmp_path / "g").mkdir()
    fake2 = FakeMT5(make_m1(), bid=2000.0)
    tr4, _, state4 = make_trader(tmp_path / "g", fake2, **base)
    tr4.on_selection(selection())
    fake2.set_price(1989.5, advance_seconds=180)
    tr4.manage()
    pl = state4.plans["M15#5"]
    assert len(pl["position_tickets"]) == 2 and pl["fast_fill_checked"] and not pl.get("fast_fill")
