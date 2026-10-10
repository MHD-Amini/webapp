"""v16c - drawdown-reduction levers: DD throttle (dd_throttle_pct / dd_throttle_scale / dd_throttle_ramp / dd_basis), day soft cap
(day_soft_loss_pct / day_soft_scale), open-risk cap (max_open_risk_pct / open_risk_mode) and the loss-streak throttle (streak_n).
Defaults must be byte-identical to v16b (parity on the full year is checked by run_v16c_levers.py: v16b-A = 446 / +338.31 / -5.55)."""
import pandas as pd

from lubot.execution import TraderConfig
from tests.test_portfolio_sim import bars, cfg, run, sel, spec  # noqa: F401


def test_v16c_defaults_are_off_and_override_parses():
    c = TraderConfig()
    assert (c.dd_throttle_pct, c.dd_throttle_scale, c.dd_throttle_ramp, c.dd_basis, c.dd_throttle_tfs) == (0.0, 0.5, 0.0, "equity", ())
    assert (c.day_soft_loss_pct, c.day_soft_scale) == (0.0, 0.5)
    assert (c.max_open_risk_pct, c.open_risk_mode, c.open_risk_pending) == (0.0, "fit", False)
    assert (c.streak_n, c.streak_scale, c.streak_days) == (0, 0.5, 5.0)
    c.override("dd_throttle_pct=3.5,dd_throttle_scale=0.6,dd_throttle_ramp=2,dd_basis=balance,dd_throttle_tfs=M5|M10,"
               "day_soft_loss_pct=1.0,day_soft_scale=0,max_open_risk_pct=3,open_risk_mode=skip,open_risk_pending=true,"
               "streak_n=2,streak_scale=0.4,streak_days=3")
    assert (c.dd_throttle_pct, c.dd_throttle_scale, c.dd_throttle_ramp, c.dd_basis, c.dd_throttle_tfs) == (3.5, 0.6, 2.0, "balance", ("M5", "M10"))
    assert (c.day_soft_loss_pct, c.day_soft_scale) == (1.0, 0.0)
    assert (c.max_open_risk_pct, c.open_risk_mode, c.open_risk_pending) == (3.0, "skip", True)
    assert (c.streak_n, c.streak_scale, c.streak_days) == (2, 0.4, 3.0)


# a losing buy (fills at 2000, stopped at 1995) followed by a second zone shown while the account is in drawdown
def _loss_then_new(spread=0.3):
    seq = [(2005, 2006, 2004, 2005),            # 10:00 order placed (zone 1995-2000, buy limit 2000, SL 1995)
           (2004, 2004.5, 1999.0, 2000.5),      # 10:01 fill at 2000 (ask low 1999.3)
           (2000.5, 2001, 1994.0, 1996),        # 10:02 stop at 1995 -> -1 % of equity (bid low 1994 -> stop 1995 hit)
           (1996, 1997, 1995.5, 1996.5),        # 10:03 second zone shown here (1985-1990), account 1 % below its peak
           (1996.5, 1997, 1996, 1996.5)]
    return bars(seq, spread=spread)


def _two(m1):
    return [sel(m1.index[0], pid=1, top=2000.0, bottom=1995.0), sel(m1.index[3], pid=2, top=1990.0, bottom=1985.0)]


def test_dd_throttle_scales_new_plans_only_below_threshold():
    m1 = _loss_then_new()
    res, sim = run(m1, _two(m1), cfg())
    assert len(res.trades) == 1 and res.trades.iloc[0].outcome == "sl"
    assert "M15#2" in sim.pending
    base_lots = sim.pending["M15#2"].lots_leg1 + sim.pending["M15#2"].lots_leg2
    assert sim.dd_scaled == 0 and sim.pending["M15#2"].plan.dd_scale == 1.0 and sim.pending["M15#2"].plan.dd_pct_at > 0.9
    # threshold above the drawdown -> untouched
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=2.0, dd_throttle_scale=0.5))
    assert sim.pending["M15#2"].lots_leg1 + sim.pending["M15#2"].lots_leg2 == base_lots and sim.dd_scaled == 0
    # threshold below the drawdown (~1 %) -> x0.5
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=0.5, dd_throttle_scale=0.5))
    p = sim.pending["M15#2"]
    assert sim.dd_scaled == 1 and p.plan.dd_scale == 0.5
    assert abs((p.lots_leg1 + p.lots_leg2) - 0.5 * base_lots) <= 0.011
    # scale 0 -> skipped
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=0.5, dd_throttle_scale=0.0))
    assert "M15#2" not in sim.pending and sim.dd_skipped == 1 and any(k == "M15#2" and r.startswith("dd throttle") for k, r in sim.skipped)
    # tf scope: another timeframe listed -> not throttled
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=0.5, dd_throttle_scale=0.5, dd_throttle_tfs=("M5",)))
    assert sim.dd_scaled == 0 and sim.pending["M15#2"].plan.dd_scale == 1.0
    # balance basis works the same here (the loss is realised)
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=0.5, dd_throttle_scale=0.5, dd_basis="balance"))
    assert sim.dd_scaled == 1
    assert res.summary()["dd_scaled"] == 1 and res.summary()["dd_scaled_trades"] == 0      # the second plan never filled


def test_dd_throttle_ramp_is_linear():
    sim_cfg = cfg(dd_throttle_pct=2.0, dd_throttle_scale=0.5, dd_throttle_ramp=2.0)
    m1 = _loss_then_new()
    res, sim = run(m1, _two(m1), sim_cfg)
    assert sim.dd_throttle_scale(1.0) == 1.0 and sim.dd_throttle_scale(2.0) == 1.0
    assert abs(sim.dd_throttle_scale(3.0) - 0.75) < 1e-9 and abs(sim.dd_throttle_scale(4.0) - 0.5) < 1e-9
    assert abs(sim.dd_throttle_scale(6.0) - 0.5) < 1e-9
    sim.tcfg.dd_throttle_ramp = 0.0
    assert sim.dd_throttle_scale(2.1) == 0.5


def test_day_soft_cap_scales_or_skips_without_flattening():
    m1 = _loss_then_new()
    res, sim = run(m1, _two(m1), cfg(day_soft_loss_pct=0.5, day_soft_scale=0.5))
    assert sim.day_soft_scaled == 1 and sim.pending["M15#2"].plan.dd_scale == 0.5 and len(res.trades) == 1
    res, sim = run(m1, _two(m1), cfg(day_soft_loss_pct=0.5, day_soft_scale=0.0))
    assert sim.day_soft_skipped == 1 and "M15#2" not in sim.pending and ("M15#2", "day soft cap") in sim.skipped
    res, sim = run(m1, _two(m1), cfg(day_soft_loss_pct=2.0, day_soft_scale=0.5))
    assert sim.day_soft_scaled == 0


def test_streak_throttle_counts_consecutive_losses():
    m1 = _loss_then_new()
    res, sim = run(m1, _two(m1), cfg(streak_n=1, streak_scale=0.5))
    assert sim.streak_scaled == 1 and sim.pending["M15#2"].plan.dd_scale == 0.5 and len(sim.streak_losses) == 1
    res, sim = run(m1, _two(m1), cfg(streak_n=2, streak_scale=0.5))
    assert sim.streak_scaled == 0


def test_open_risk_cap_fits_or_skips_the_second_plan():
    # first buy fills at 2000 (SL 1995 = 1 % eq = 100 $ -> 0.2 lots), second zone shown while it is open -> open risk 1 % eq;
    # the end-of-data flatten closes everything, so the sizing decision is read from the plans (dd_scale) and the counters.
    # (TP1 of a 5 $ zone is at +2 R x 0.4 = 2002 -> the bars stay below 2001.5 so the position stays open with both legs)
    seq = [(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.0, 2000.5), (2000.5, 2001, 1999.5, 2000.5), (2000.5, 2001, 2000, 2000.5)]
    m1 = bars(seq, spread=0.3)
    ev = [sel(m1.index[0], pid=1, top=2000.0, bottom=1995.0), sel(m1.index[2], pid=2, top=1990.0, bottom=1985.0)]

    def second(sim):
        return [p for p in sim.cancelled if p.plan.poi_id == 2]

    res, sim = run(m1, ev, cfg(), )
    assert len(res.trades) == 1 and res.trades.iloc[0].outcome == "forced" and len(second(sim)) == 1
    p2 = second(sim)[0]
    full = p2.lots_leg1 + p2.lots_leg2
    assert full == 0.2 and p2.plan.dd_scale == 1.0 and sim.open_risk_scaled == 0
    # cap 1.5 % -> only 0.5 % left for the second plan -> fitted to half (0.1 lots)
    res, sim = run(m1, ev, cfg(max_open_risk_pct=1.5))
    p2 = second(sim)[0]
    assert sim.open_risk_scaled == 1 and abs(p2.plan.dd_scale - 0.5) < 0.01 and abs(p2.lots_leg1 + p2.lots_leg2 - 0.1) < 1e-9
    # skip mode
    res, sim = run(m1, ev, cfg(max_open_risk_pct=1.5, open_risk_mode="skip"))
    assert sim.open_risk_skipped == 1 and not second(sim) and any(k == "M15#2" and r.startswith("open risk cap") for k, r in sim.skipped)
    # fit mode with no budget left at all -> skipped as well
    res, sim = run(m1, ev, cfg(max_open_risk_pct=1.0))
    assert sim.open_risk_skipped == 1 and not second(sim)
    # cap large enough -> untouched
    res, sim = run(m1, ev, cfg(max_open_risk_pct=5.0))
    assert sim.open_risk_scaled == 0 and second(sim)[0].plan.dd_scale == 1.0
    # the open-risk helper: legs at break-even count as zero risk; pending orders can be counted too
    sim2 = run(m1[:3], ev[:1], cfg())[1]
    assert not sim2.positions           # flattened at the end of data
    from lubot.portfolio_sim import Leg, Position
    from lubot.execution import TradePlan
    plan = TradePlan(side="buy", entry=2000.0, sl=1995.0, tp1=2002.0, tp2=2007.5, be_price=2000.0, risk=5.0, zone_top=2000.0,
                     zone_bottom=1995.0, tf="M15", poi_id=9)
    pos = Position(plan=plan, lots=0.2, legs=[Leg(0.1, 2002.0, 1995.0), Leg(0.1, 2007.5, 1995.0)], entry_time=m1.index[1],
                   entry_price=2000.0, risk_money=100.0)
    sim2.positions["M15#9"] = pos
    assert abs(sim2.open_risk_usd(2000.5) - 100.0) < 1e-6
    pos.legs[0].sl = 2000.0
    assert abs(sim2.open_risk_usd(2000.5) - 50.0) < 1e-6
    pos.legs[1].sl = 2001.0            # stop above the entry = locked profit -> 0 risk
    assert sim2.open_risk_usd(2000.5) == 0.0
    assert sim2.open_risk_usd(2000.5, include_pending=True) == 0.0


def test_peak_tracking_and_dd_days():
    m1 = _loss_then_new()
    res, sim = run(m1, _two(m1), cfg(dd_throttle_pct=0.5))
    assert sim.peak_equity >= 10_000.0 and sim.dd_minutes >= 1 and res.summary()["dd_days"] >= 0.0
    assert "dd_scale" in res.trades.columns and "dd_pct_at" in res.trades.columns
