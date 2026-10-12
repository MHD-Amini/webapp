"""v16c - live bot (fake MT5): the drawdown throttle and the day soft cap through trader.py, same rules as PortfolioSimulator.
  * dd throttle: the account's peak (equity or balance) is persisted in trader_state.json (risk.peak_equity) and updated every loop;
    a NEW plan placed while the account is more than dd_throttle_pct % below the peak is sized x dd_throttle_scale (0 = skipped),
    the tf scope is honoured, the ramp is linear, a restart keeps the peak (so a restart inside a drawdown keeps throttling).
  * day soft cap: once equity is day_soft_loss_pct % below the day-start equity, new plans are x day_soft_scale; nothing is flattened.
  * defaults: nothing changes (risk_scale 1.0, 0.20 lots for a 1 % / 5 $ plan on 10 000 $).
"""
import math

from tests.fake_mt5 import FakeMT5
from tests.test_trader_live import make_m1, make_trader, selection

LADDER = dict(tp_levels=("1.0", "1.0"), tp_fracs=("1", "1"), sl_slippage=0.0, market_slippage=0.0, dedupe_cross_tf=False)


def _plan(tr, state, pid, px):
    """one BUY zone per pid, far enough apart not to overlap the previous (still shown) plan."""
    off = 7 + 8 * (pid - 5)
    tr.on_selection(selection(top=px - off, bottom=px - off - 5, pid=pid))
    return state.plans.get(f"M15#{pid}")


def test_live_dd_throttle_scales_new_plans_and_persists_peak(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0, balance=10_000.0)
    tr, _, state = make_trader(tmp_path, fake, dd_throttle_pct=3.5, dd_throttle_scale=0.5, **LADDER)
    # at the peak: full size
    p = _plan(tr, state, 5, 2000.0)
    assert p["risk_scale"] == 1.0 and math.isclose(p["lots_total"], 0.20) and p["dd_pct_at"] == 0.0
    assert state.risk["peak_equity"] == 10_000.0
    # the account loses 4 % (balance 9 600, no open positions -> equity 9 600): 4 % below the peak -> x0.5 on a 9 600 base
    fake.balance = 9_600.0
    p = _plan(tr, state, 6, 2000.0)
    assert p["risk_scale"] == 0.5 and p["dd_scale"] == 0.5 and math.isclose(p["dd_pct_at"], 4.0)
    assert math.isclose(p["lots_total"], 0.09)          # 1 % x 0.5 of 9 600 = 48 $ / 5 $ = 0.096 -> 0.09 (floored to the step)
    assert state.risk["peak_equity"] == 10_000.0 and state.risk["dd_scaled"] == 1
    # only 3 % below the peak (threshold 3.5 is a strict >): untouched
    fake.balance = 9_700.0
    p = _plan(tr, state, 7, 2000.0)
    assert p["risk_scale"] == 1.0 and math.isclose(p["dd_pct_at"], 3.0)
    # a new peak resets the drawdown and is persisted
    fake.balance = 10_500.0
    tr.check_risk_limits()
    assert state.risk["peak_equity"] == 10_500.0
    # restart from the state file inside a drawdown: the peak survives, the throttle still fires
    fake.balance = 10_000.0                               # 4.76 % below 10 500
    tr2, _, state2 = make_trader(tmp_path, fake, dd_throttle_pct=3.5, dd_throttle_scale=0.5, **LADDER)
    assert state2.risk["peak_equity"] == 10_500.0
    p = _plan(tr2, state2, 8, 2000.0)
    assert p["risk_scale"] == 0.5 and math.isclose(p["dd_pct_at"], 4.762, abs_tol=1e-3)


def test_live_dd_throttle_tf_scope_ramp_and_skip(tmp_path):
    m1 = make_m1()
    # scope = higher TFs only: an M15 plan is throttled, an M5 plan is not (the test trader runs M15 - check the scope test directly)
    fake = FakeMT5(m1, bid=2000.0, balance=10_000.0)
    tr, _, state = make_trader(tmp_path, fake, dd_throttle_pct=3.5, dd_throttle_scale=0.5,
                               dd_throttle_tfs=("M15", "M20", "M30", "H1"), **LADDER)
    _plan(tr, state, 5, 2000.0)
    fake.balance = 9_600.0
    p = _plan(tr, state, 6, 2000.0)
    assert p["risk_scale"] == 0.5
    (tmp_path / "m5").mkdir()
    tr5, _, state5 = make_trader(tmp_path / "m5", FakeMT5(m1, bid=2000.0, balance=10_000.0), dd_throttle_pct=3.5,
                                 dd_throttle_scale=0.5, dd_throttle_tfs=("M5", "M10"), **LADDER)
    _plan(tr5, state5, 5, 2000.0)
    tr5.b.mt5.balance = 9_600.0
    p = _plan(tr5, state5, 6, 2000.0)
    assert p["risk_scale"] == 1.0 and math.isclose(p["dd_pct_at"], 4.0)   # M15 is outside the M5|M10 scope
    # ramp: x1 at 3.0 %, x0.5 at 5.0 %, linear between -> 4.0 % = x0.75
    (tmp_path / "r").mkdir()
    trr, _, stater = make_trader(tmp_path / "r", FakeMT5(m1, bid=2000.0, balance=10_000.0), dd_throttle_pct=3.0,
                                 dd_throttle_scale=0.5, dd_throttle_ramp=2.0, **LADDER)
    _plan(trr, stater, 5, 2000.0)
    trr.b.mt5.balance = 9_600.0
    p = _plan(trr, stater, 6, 2000.0)
    assert math.isclose(p["risk_scale"], 0.75)
    assert math.isclose(trr.dd_throttle_scale(6.0), 0.5) and trr.dd_throttle_scale(3.0) == 1.0
    # scale 0 = no new plans in drawdown
    (tmp_path / "z").mkdir()
    trz, _, statez = make_trader(tmp_path / "z", FakeMT5(m1, bid=2000.0, balance=10_000.0), dd_throttle_pct=3.5,
                                 dd_throttle_scale=0.0, **LADDER)
    _plan(trz, statez, 5, 2000.0)
    trz.b.mt5.balance = 9_600.0
    assert _plan(trz, statez, 6, 2000.0) is None and statez.risk["dd_skipped"] == 1 and "M15#6" not in statez.plans


def test_live_day_soft_cap_scales_without_flatten(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0, balance=10_000.0)
    tr, _, state = make_trader(tmp_path, fake, day_soft_loss_pct=1.5, day_soft_scale=0.5, **LADDER)
    p = _plan(tr, state, 5, 2000.0)
    assert p["risk_scale"] == 1.0 and state.risk["day_start_equity"] == 10_000.0
    fake.balance = 9_800.0                                # -2 % on the day (same server day) -> x0.5, the open orders stay
    p = _plan(tr, state, 6, 2000.0)
    assert p["risk_scale"] == 0.5 and p["dd_scale"] == 0.5 and state.risk["day_soft_scaled"] == 1
    assert fake.balance == 9_800.0 and not fake.positions and "M15#6" in state.plans   # nothing flattened, plan placed
    fake.balance = 9_900.0                                # only -1 % -> full size
    p = _plan(tr, state, 7, 2000.0)
    assert p["risk_scale"] == 1.0


def test_live_v16c_defaults_unchanged(tmp_path):
    m1 = make_m1()
    fake = FakeMT5(m1, bid=2000.0, balance=10_000.0)
    tr, _, state = make_trader(tmp_path, fake, **LADDER)
    _plan(tr, state, 5, 2000.0)
    fake.balance = 9_000.0                                # 10 % down, levers off -> plain 1 % of 9 000
    p = _plan(tr, state, 6, 2000.0)
    assert p["risk_scale"] == 1.0 and p["dd_scale"] == 1.0 and math.isclose(p["lots_total"], 0.18)
    assert state.risk["peak_equity"] is None
