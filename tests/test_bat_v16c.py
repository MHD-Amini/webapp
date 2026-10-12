"""v16c - the strings shipped in run_trader.bat parse into the TraderConfig of the v16c-A study variant named in the bat header
(REM v16c study: study_results/v16c_levers/<name>.json) ON TOP of v16b-A / v16-A / v15-A / v14-A / v13-A, with every other v16c lever
(open-risk cap, streak throttle) OFF.  No CSV needed: the bat config is compared field by field with the config the study used, and the
live bot (fake MT5) is driven with the shipped strings.
"""
import dataclasses
import json
import math
import re

from lubot.execution import TraderConfig
from tests.test_bat_v16 import _bat_config
from v16c_common import V16B_CF, V16B_FLT, v16b_config

V16C_KEYS_SHIPPED = {"dd_throttle_pct", "dd_throttle_scale", "dd_throttle_tfs"}       # v16c-A = the htf drawdown throttle


def _study_config():
    """The exact overrides string of the shipped study json (as the grid replayed it) applied to v16b-A."""
    bat = open("run_trader.bat", encoding="utf-8").read()
    path = re.search(r"REM v16c study: (\S+)", bat).group(1)
    study = json.load(open(path))
    return v16b_config().override(study["overrides"]), study


def test_bat_header_is_v16c_and_names_the_study():
    bat = open("run_trader.bat", encoding="utf-8").read().splitlines()
    assert "v16c" in bat[1] and "LESS_DD_V16C" in bat[1]
    assert any(l.startswith("REM v16c study: study_results/v16c_levers/") for l in bat)
    assert any(l.startswith("REM Previous layer (v16b-A") for l in bat)         # the v16b header is kept as history
    assert any(l.startswith("REM v16b study: ") for l in bat)                    # test_bat_v16b still finds the v16b study
    assert any(l.startswith("REM v16 study: ") for l in bat)


def test_bat_trader_string_is_v16c_a():
    t, tfs = _bat_config()
    # v16c-A = the drawdown throttle on the higher timeframes, equity basis, step (no ramp)
    assert t.dd_throttle_pct == 3.5 and t.dd_throttle_scale == 0.5 and t.dd_throttle_ramp == 0 and t.dd_basis == "equity"
    assert t.dd_throttle_tfs == ("M15", "M20", "M30", "H1")
    # the other v16c levers are OFF
    assert t.day_soft_loss_pct == 0 and t.max_open_risk_pct == 0 and t.streak_n == 0
    assert t.max_daily_loss_pct == 4.5 and t.max_total_loss_pct == 9.0
    # v16b-A / v16-A / v15-A / v14-A / v13-A still underneath, unchanged
    assert t.min_fill_age_min == 2 and t.fast_fill_mode == "cancel" and t.regime_side_scale == "range:sell:0.5"
    assert tfs == ("M5", "M10", "M15", "M20", "M30", "H1")
    assert t.trade_filter == V16B_FLT and t.confluence_filter == V16B_CF
    assert t.tf_risk_scale == "M20:0.4" and t.max_rank == 1
    assert t.confluence_memory_min == 240 and t.confluent_risk_scale == 1.25 and t.plain_risk_scale == 0.9
    assert t.mart_mode == "mult" and t.mart_mult == 1.5 and t.mart_scope == "tf" and t.mart_sides == ("buy",)
    assert t.regime_metric == "adr_ratio" and t.regime_threshold == 1.0 and t.range_tp_levels == ("0.5", "1.0", "1.5", "2.5")


def test_bat_config_equals_shipped_study_config():
    """Every TraderConfig field of the bat == the field of the study variant named in the bat header, except `timeframes`,
    which the live bot takes from --timeframes (the study passes it inside v16b_config)."""
    t, tfs = _bat_config()
    s, study = _study_config()
    assert study["name"] == "DDT3.5_x0.5_htf" and study["trades"] == 445 and study["score"] == 4 and study["less_dd"]
    diffs = {f.name: (getattr(t, f.name), getattr(s, f.name)) for f in dataclasses.fields(TraderConfig)
             if getattr(t, f.name) != getattr(s, f.name)}
    assert set(diffs) <= {"timeframes"}, diffs
    assert tuple(s.timeframes) == tfs


def test_bat_minus_v16c_keys_is_v16b_a():
    """Dropping the v16c keys from the bat string gives the v16b-A config byte for byte (the reference of FINAL_BACKTEST_V16C)."""
    from backtest_v16c_final import strip_v16c
    from tests.test_bat_v13 import _bat_line
    from run_v10_study import BASE
    line = _bat_line()
    trader = re.search(r'--trader "([^"]*)"', line).group(1)
    dropped = {kv.partition("=")[0] for kv in trader.split(",")} - {kv.partition("=")[0] for kv in strip_v16c(trader).split(",")}
    assert dropped == V16C_KEYS_SHIPPED
    t = TraderConfig(risk_pct=1.0, trade_filter=V16B_FLT, confluence_filter=V16B_CF, max_daily_loss_pct=4.5,
                     max_total_loss_pct=9.0).override(BASE).override(strip_v16c(trader))
    ref = v16b_config()
    diffs = {f.name for f in dataclasses.fields(TraderConfig) if getattr(t, f.name) != getattr(ref, f.name)}
    assert diffs <= {"timeframes"}, diffs


# ----------------------------------------------------------------------------------------------------------- live bot (fake MT5)
def test_live_shipped_strings_throttle_m15_in_drawdown_only(tmp_path):
    """The shipped v16c-A keys through trader.py against the fake terminal: an M15 plan placed while equity is 4 % below the
    persisted peak is sized at HALF risk; at the peak (or only 3 % below) it is full size; the peak survives a restart."""
    from tests.fake_mt5 import FakeMT5
    from tests.test_trader_live import make_m1, make_trader, selection
    t, _ = _bat_config()
    base = dict(dd_throttle_pct=t.dd_throttle_pct, dd_throttle_scale=t.dd_throttle_scale, dd_throttle_tfs=t.dd_throttle_tfs,
                dd_basis=t.dd_basis, tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0,
                dedupe_cross_tf=False)
    fake = FakeMT5(make_m1(), bid=2000.0, balance=10_000.0)
    tr, _, state = make_trader(tmp_path, fake, **base)
    tr.on_selection(selection(top=1993.0, bottom=1988.0, pid=5))
    p5 = state.plans["M15#5"]
    assert p5["risk_scale"] == 1.0 and math.isclose(p5["lots_total"], 0.20) and state.risk["peak_equity"] == 10_000.0
    fake.balance = 9_700.0                                               # -3.0 %: below the 3.5 threshold -> full size
    tr.on_selection(selection(top=1985.0, bottom=1980.0, pid=6))
    assert state.plans["M15#6"]["risk_scale"] == 1.0
    fake.balance = 9_600.0                                               # -4.0 % -> x0.5
    tr.on_selection(selection(top=1977.0, bottom=1972.0, pid=7))
    p7 = state.plans["M15#7"]
    assert p7["risk_scale"] == 0.5 and p7["dd_scale"] == 0.5 and math.isclose(p7["dd_pct_at"], 4.0)
    assert math.isclose(p7["lots_total"], 0.09)                          # 0.5 % of 9 600 = 48 $ / 5 $ -> 0.09 lots
    # restart: the peak is read back from trader_state.json
    tr2, _, state2 = make_trader(tmp_path, fake, **base)
    assert state2.risk["peak_equity"] == 10_000.0
