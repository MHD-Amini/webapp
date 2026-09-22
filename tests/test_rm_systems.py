"""v9 risk-management systems: hand-built M1 scenarios for the simulator extensions used by the study
(partial fraction != 50 %, TP2 off, BE trigger without partial, trailing runner, whole-position trail,
3-leg ladder with / without ratchet, time stop, BE offset).  Zone 1995-2000 -> buy limit 2000, SL 1995, 1R = $5."""
import math

from tests.test_portfolio_sim import bars, cfg, run, sel, spec  # noqa: F401


def _one(seq, **kw):
    res, sim = run(bars(seq), [sel("2026-03-02 10:00")], cfg(**kw))
    assert len(res.trades) == 1
    return res.trades.iloc[0], sim


ENTRY = [(2005, 2006, 2004, 2005), (2001.5, 2001.8, 1999.0, 2001)]     # order at 10:00, fill at ask 2000 at 10:01


def test_partial_25pct_at_0p6R_then_tp2_3R():
    # TP1 = 2003 (0.6R), TP2 = 2015 (3R); 0.20 lots -> legs 0.05 / 0.15
    t, sim = _one(ENTRY + [(2001, 2003.2, 2000.5, 2003), (2003, 2015.5, 2002.5, 2015)],
                  partial_r=0.6, partial_frac=0.25, tp2_r=3.0)
    assert t.outcome == "tp2" and math.isclose(t.lots, 0.20)
    # gross = 0.05*100*3 + 0.15*100*15 = 15 + 225 = 240 -> 2.4 R  (= 0.25*0.6 + 0.75*3)
    assert math.isclose(t.gross, 240.0, abs_tol=1e-6) and math.isclose(t.r_net, 2.4, abs_tol=1e-6)


def test_partial_25pct_then_be_gives_0p15R():
    t, _ = _one(ENTRY + [(2001, 2003.2, 2000.5, 2003), (2003, 2003.5, 1999.5, 1999.8)],
                partial_r=0.6, partial_frac=0.25, tp2_r=3.0)
    assert t.outcome == "partial_be" and math.isclose(t.r_net, 0.25 * 0.6, abs_tol=1e-6)


def test_no_be_after_partial_full_stop_costs_0p6R():
    # partial 50 % at 0.4R (2002) then price falls to the original SL 1995 -> -0.5 + 0.2 = -0.3R
    t, _ = _one(ENTRY + [(2001, 2002.5, 2000.5, 2002), (2002, 2002.2, 1994.0, 1994.5)],
                partial_r=0.4, partial_frac=0.5, tp2_r=1.5, be_on_partial=False)
    assert t.outcome == "partial_sl" and math.isclose(t.r_net, 0.5 * 0.4 - 0.5, abs_tol=1e-6)


def test_single_target_no_partial():
    # partial_frac=0 -> one leg, TP 1.5R = 2007.5 ; the 0.4R touch must NOT close anything
    t, _ = _one(ENTRY + [(2001, 2002.5, 2000.5, 2002), (2002, 2008, 2001, 2007)], partial_frac=0, tp2_r=1.5)
    assert t.outcome == "tp2" and not bool(t.partial) and math.isclose(t.r_net, 1.5, abs_tol=1e-6)


def test_be_trigger_without_partial_uses_closed_bar_mfe():
    # BE once a CLOSED bar's MFE >= 1R (2005).  Bar 10:02 high 2005.2 -> armed at the open of 10:03; then price
    # falls to 1999.5 -> stopped at BE 2000 -> 0 R (without the trigger it would be a -1R stop later)
    t, _ = _one(ENTRY + [(2001, 2005.2, 2000.5, 2004), (2004, 2004.5, 1999.5, 1999.8)],
                partial_frac=0, tp2_r=3.0, be_trigger_r=1.0)
    assert t.outcome == "be" and math.isclose(t.r_net, 0.0, abs_tol=1e-6)
    # same path but the trigger is 1.2R (2006) -> not armed -> position survives to the end of data
    t, _ = _one(ENTRY + [(2001, 2005.2, 2000.5, 2004), (2004, 2004.5, 1999.5, 1999.8)],
                partial_frac=0, tp2_r=3.0, be_trigger_r=1.2)
    assert t.outcome == "forced"


def test_trailing_runner_after_partial():
    # 50 % at 0.4R (2002) -> BE; runner trailed 0.5R ($2.5) below the extreme high of the closed bars, no TP2
    seq = ENTRY + [
        (2001, 2002.5, 2000.5, 2002),     # 10:02 TP1 -> leg1 closed, BE, hwm 2002.5 -> trail 2000.0 (= BE, no change)
        (2002, 2006.0, 2001.5, 2005.5),   # 10:03 hwm 2006 -> trail SL 2003.5 (applied at the open of 10:04)
        (2005.5, 2006.2, 2004.0, 2005),   # 10:04 hwm 2006.2 -> SL 2003.7 for 10:05
        (2005, 2005.2, 2003.0, 2003.2),   # 10:05 low 2003.0 <= 2003.7 -> runner stopped at 2003.7
    ]
    t, _ = _one(seq, partial_r=0.4, partial_frac=0.5, tp2_r=0, trail_r=0.5)
    assert t.outcome == "trail"
    # gross = 0.10*100*2 + 0.10*100*3.7 = 20 + 37 = 57 ; risk money 0.20*100*5 = 100 -> 0.57 R
    assert math.isclose(t.r_net, 0.57, abs_tol=1e-6)


def test_trail_whole_position_from_fill_with_activation():
    # no partial, trail 1R ($5) from the extreme, active only once MFE >= 0.5R
    seq = ENTRY + [
        (2001, 2001.5, 2000.3, 2001),     # 10:02 hwm 2001.5 (0.3R) -> not active
        (2001, 2004.0, 2000.8, 2003.8),   # 10:03 hwm 2004 (0.8R) -> SL 1999 for 10:04 (above 1995)
        (2003.8, 2004.2, 1998.8, 1999.0), # 10:04 low 1998.8 <= 1999 -> stopped at 1999 = -0.2R
    ]
    t, _ = _one(seq, partial_frac=0, tp2_r=0, trail_r=1.0, trail_start_r=0.5, trail_after_partial=False)
    # a trailed stop that exits BELOW the entry is reported as "sl" (only profitable trail exits count as "trail")
    assert t.outcome == "sl" and math.isclose(t.r_net, -0.2, abs_tol=1e-6)
    # a higher run makes the trail lock profit: hwm 2007 -> SL 2002 -> exit +0.4R, reported as "trail"
    seq2 = ENTRY + [(2001, 2007.0, 2000.8, 2006.5), (2006.5, 2006.8, 2001.5, 2001.8)]
    t, _ = _one(seq2, partial_frac=0, tp2_r=0, trail_r=1.0, trail_start_r=0.5, trail_after_partial=False)
    assert t.outcome == "trail" and math.isclose(t.r_net, 0.4, abs_tol=1e-6)


def test_ladder_three_legs_and_ratchet():
    # 34/33/33 at 0.4/1.0/2.0R = 2002 / 2005 / 2010, 0.30 lots -> legs rounded down 0.10 / 0.09, remainder 0.11
    seq = ENTRY + [
        (2001, 2002.5, 2000.5, 2002),     # leg1 at 2002 -> BE
        (2002, 2005.5, 2001.5, 2005),     # leg2 at 2005
        (2005, 2005.5, 2001.8, 2002.0),   # falls to 2001.8: without ratchet BE 2000 survives; with ratchet SL=2002 -> out
        (2002, 2010.5, 2001.9, 2010),     # leg3 at 2010
    ]
    t, _ = _one(seq, tp_levels=("0.4", "1.0", "2.0"), tp_fracs=("0.34", "0.33", "0.33"), risk_pct=1.5)
    assert t.outcome == "tp2" and math.isclose(t.lots, 0.30)
    # 100*(0.10*2 + 0.09*5 + 0.11*10) = 175 ; risk money 0.30*100*5 = 150 -> 1.1667 R
    assert math.isclose(t.r_net, 175 / 150, abs_tol=1e-6)
    t, _ = _one(seq, tp_levels=("0.4", "1.0", "2.0"), tp_fracs=("0.34", "0.33", "0.33"), risk_pct=1.5, ratchet_sl=True)
    assert t.outcome == "trail"                                  # last leg stopped at the ratcheted stop 2002
    assert math.isclose(t.r_net, (0.10 * 2 + 0.09 * 5 + 0.11 * 2) * 100 / 150, abs_tol=1e-6)


def test_time_stop_closes_at_open_after_n_minutes():
    seq = ENTRY + [(2001, 2001.5, 2000.5, 2001.2), (2001.2, 2001.6, 2000.9, 2001.4), (2001.4, 2001.8, 2001.0, 2001.5),
                   (2001.5, 2001.9, 2001.1, 2001.6)]
    # filled 10:01; max_hold 3 min -> closed at the open of 10:04 at bid 2001.4 -> +0.28R (no partial reached)
    t, _ = _one(seq, max_hold_min=3)
    assert t.outcome == "time" and math.isclose(t.r_net, 1.4 / 5, abs_tol=1e-6)


def test_be_offset_locks_ticks():
    # 50 % at 0.4R then BE at +0.2R (2001): leg2 out at 2001 -> 0.2 + 0.1 = 0.3R
    t, _ = _one(ENTRY + [(2001, 2002.5, 2000.5, 2002), (2002, 2002.2, 2000.5, 2000.8)], be_offset_r=0.2)
    assert t.outcome == "partial_be" and math.isclose(t.r_net, 0.3, abs_tol=1e-6)


def test_defaults_unchanged_v8_spec():
    # default TraderConfig == user spec: 50 % @ 0.4R -> BE, TP2 1.5R  (guards the v8 baseline)
    c = cfg()
    assert (c.partial_r, c.partial_frac, c.tp2_r, c.be_on_partial, c.be_trigger_r, c.trail_r, c.max_hold_min,
            c.tp_levels, c.ratchet_sl, c.be_offset_r) == (0.4, 0.5, 1.5, True, 0.0, 0.0, 0, (), False, 0.0)


# ----------------------------------------------------------------------------- v10 account protection
def _two_losers(day2=False):
    """Two bullish zones far apart; both fill and both get stopped (each -1R = -1 % at risk_pct 1 -> -2.x % with slippage)."""
    from tests.test_portfolio_sim import bars, sel
    seq = [(2005, 2006, 2004, 2005), (2001.5, 2001.8, 1999.0, 2001), (2001, 2001.5, 1994.0, 1994.5),  # zone A filled + stopped
           (1994.5, 1995, 1993, 1994), (1990.5, 1991, 1989.0, 1990), (1990, 1990.5, 1984.0, 1984.5)]  # zone B filled + stopped
    m1 = bars(seq)
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:03", pid=2, top=1990.0, bottom=1985.0)]
    return m1, ev


def test_daily_loss_limit_flattens_and_blocks_new_orders():
    from tests.test_portfolio_sim import bars, run, sel, cfg
    # risk 3 % per trade: first stop = -3 %; daily limit 2.5 % -> hit at the close of the stop minute -> zone B never placed
    m1, ev = _two_losers()
    res, sim = run(m1, ev, cfg(risk_pct=3.0, max_daily_loss_pct=2.5))
    t = res.trades
    assert len(t) == 1 and t.outcome[0] == "sl"
    assert sim.daily_halt_day is not None and len(sim.daily_halts) == 1
    assert any(why == "daily loss limit" for _, why in sim.skipped)
    assert not sim.halted
    # without the rule both zones trade
    res2, _ = run(m1, ev, cfg(risk_pct=3.0))
    assert len(res2.trades) == 2


def test_daily_limit_closes_open_position_at_market_and_resets_next_day():
    from tests.test_portfolio_sim import bars, run, sel, cfg
    # a single long that bleeds: floating loss crosses the daily limit before the SL -> closed at market as daily_halt
    seq = [(2005, 2006, 2004, 2005), (2001.5, 2001.8, 1999.0, 2001), (2001, 2001.2, 1996.5, 1996.6),  # -3.4 of 5 R = -68 % of risk
           (1996.6, 1997, 1996, 1996.5)]
    # next server day: a new zone is allowed again
    seq += [(1996.5, 1997, 1996, 1996.5)] * 2
    m1 = bars(seq, start="2026-03-02 23:57")
    ev = [sel("2026-03-02 23:57", pid=1), sel("2026-03-03 00:01", pid=3, top=1990.0, bottom=1985.0)]
    res, sim = run(m1, ev, cfg(risk_pct=4.0, max_daily_loss_pct=2.5))       # -68 % x 4 % = -2.7 % > 2.5 %
    t = res.trades
    assert t.outcome[0] == "daily_halt" and t.r_net[0] < 0 and t.r_net[0] > -1.0
    assert sim.daily_halt_day is None                      # reset at the day change
    assert "M15#3" in sim.pending or any(k == "M15#3" for k in sim.traded_pois) or len(sim.pending) == 1


def test_total_loss_limit_halts_for_good():
    from tests.test_portfolio_sim import bars, run, sel, cfg
    m1, ev = _two_losers()
    res, sim = run(m1, ev, cfg(risk_pct=3.0, max_total_loss_pct=2.5))
    assert len(res.trades) == 1 and sim.halted and sim.halt_time is not None
    assert res.summary()["halted"] is True
    assert any(why == "halted (total loss limit)" for _, why in sim.skipped) or len(sim.pending) == 0


def test_loss_limits_off_by_default():
    c = cfg()
    assert c.max_daily_loss_pct == 0.0 and c.max_total_loss_pct == 0.0


# ----------------------------------------------------------------------------- v10 multi-TP extensions
LADDER4 = dict(tp_levels=("0.5", "1.0", "1.5", "2.5"), tp_fracs=("0.25", "0.25", "0.25", "0.25"), risk_pct=2.0)
# 1R = $5 -> targets 2002.5 / 2005 / 2007.5 / 2012.5 ; 2 % of 10k = $200 / ($5*100) = 0.40 lots -> 0.10 per leg


def test_sl_after_leg_schedule_lock_profit_after_third_leg():
    # stop schedule: leg1 -> leave, leg2 -> BE, leg3 -> +1.0R (2005) ; price then falls to 2004 -> runner out at 2005
    seq = ENTRY + [
        (2001, 2002.6, 2000.5, 2002.4),   # leg1 2002.5 ; stop stays 1995
        (2002.4, 2002.8, 1999.0, 1999.5), # dips below entry: NO BE yet -> survives (would be stopped with be_on_partial)
        (1999.5, 2005.2, 1999.2, 2005),   # leg2 2005 -> BE ; (leg3 2007.5 not reached)
        (2005, 2007.6, 2004.8, 2007.4),   # leg3 2007.5 -> stop of leg4 -> +1R = 2005
        (2007.4, 2007.5, 2004.0, 2004.2), # low 2004 <= 2005 -> leg4 stopped at 2005 (+1R)
    ]
    t, _ = _one(seq, sl_after_leg=("x", "0", "1.0"), **LADDER4)
    assert t.outcome == "trail" and math.isclose(t.lots, 0.40)
    # 100*(0.10*2.5 + 0.10*5 + 0.10*7.5 + 0.10*5) = 200 ; risk 0.40*100*5 = 200 -> 1.0 R
    assert math.isclose(t.r_net, 1.0, abs_tol=1e-6)
    # same path with the classic BE after leg 1 -> the 10:03 dip stops the other three legs at BE: 0.25*0.5 = 0.125 R
    t, _ = _one(seq, **LADDER4)
    assert t.outcome == "partial_be" and math.isclose(t.r_net, 0.125, abs_tol=1e-6)


def test_sl_after_leg_first_entry_zero_equals_classic_be():
    seq = ENTRY + [(2001, 2002.6, 2000.5, 2002.4), (2002.4, 2002.8, 1999.0, 1999.5)]
    t1, _ = _one(seq, sl_after_leg=("0", "x", "x"), **LADDER4)
    t2, _ = _one(seq, **LADDER4)
    assert t1.outcome == t2.outcome == "partial_be" and math.isclose(t1.r_net, t2.r_net)


def test_trail_after_leg_activates_trailing_only_after_k_legs():
    # 3 legs 0.4/1.0/runner(0), trail 0.5R ($2.5) active only after the 2nd leg closed
    seq = ENTRY + [
        (2001, 2002.5, 2000.5, 2002),     # leg1 2002 -> BE ; hwm 2002.5 ; trailing NOT active (1 leg closed)
        (2002, 2004.0, 2001.5, 2003.8),   # hwm 2004 -> trail would be 2001.5 - but inactive ; low 2001.5 ok vs BE 2000
        (2003.8, 2005.2, 2003.5, 2005),   # leg2 2005 -> trailing active from the next bar ; hwm 2005.2 -> SL 2002.7
        (2005, 2005.1, 2002.5, 2002.6),   # low 2002.5 <= 2002.7 -> runner stopped at 2002.7
    ]
    t, _ = _one(seq, tp_levels=("0.4", "1.0", "0"), tp_fracs=("0.34", "0.33", "0.33"), trail_r=0.5, trail_after_leg=2, risk_pct=1.5)
    assert t.outcome == "trail"
    # legs 0.10 / 0.09 / 0.11 : 100*(0.10*2 + 0.09*5 + 0.11*2.7) = 94.7 ; risk 150 -> 0.63133 R
    assert math.isclose(t.r_net, 94.7 / 150, abs_tol=1e-6)
    # with trail_after_leg=1 the 10:03 bar's hwm 2004 sets SL 2001.5 for 10:04 whose low 2001.5 stops the rest at 2001.5
    seq_b = ENTRY + seq[2:4] + [(2003.8, 2003.9, 2001.4, 2001.6)]
    t, _ = _one(seq_b, tp_levels=("0.4", "1.0", "0"), tp_fracs=("0.34", "0.33", "0.33"), trail_r=0.5, trail_after_leg=1, risk_pct=1.5)
    assert t.outcome == "trail" and math.isclose(t.r_net, (0.10 * 2 + 0.20 * 1.5) * 100 / 150, abs_tol=1e-6)


def test_tp_unit_atr_targets_in_atr_of_the_pOI_timeframe():
    # sel() carries atr 4.0 ; tp_unit=atr with levels 0.5|1.0 ATR -> targets 2002 / 2004 (instead of R = $5 multiples)
    seq = ENTRY + [(2001, 2002.2, 2000.5, 2002), (2002, 2004.3, 2001.5, 2004)]
    t, _ = _one(seq, tp_unit="atr", partial_r=0.5, partial_frac=0.5, tp2_r=1.0)
    assert t.outcome == "tp2" and math.isclose(t.tp1, 2002.0) and math.isclose(t.tp2, 2004.0)
    # gross 0.10*100*2 + 0.10*100*4 = 60 ; risk 0.20*100*5 = 100 -> 0.6 R ; the SL / R definition is unchanged
    assert math.isclose(t.r_net, 0.6, abs_tol=1e-6)


def test_ladder_fallback_merge_keeps_total_volume():
    from lubot.execution import SymbolSpec, TradePlan, TraderConfig, merge_small_legs, size_plan
    assert merge_small_legs([0.01, 0.005, 0.01, 0.005], 0.01) == [0.01, 0.0, 0.015, 0.0] or \
        sum(merge_small_legs([0.01, 0.005, 0.01, 0.005], 0.01)) == 0.03
    d = sel("2026-03-02 10:00")
    # 1 % of 10k = $100 / ($5*100) = 0.20 lots -> 5 legs of 0.04: fine ; 0.05 lots (risk 0.25 %) -> 5 legs of 0.01: fine ;
    # 0.03 lots (risk 0.15 %) -> 5 x 0.006 -> reject, or merge into 0.01 / 0.01 / 0.01
    tc = TraderConfig(risk_pct=0.15, tp_levels=("0.4", "0.8", "1.2", "1.6", "2.0"), tp_fracs=("0.2",) * 5)
    plan = TradePlan.from_poi(d, tc)
    sz = size_plan(plan, 10_000.0, tc, SymbolSpec())
    assert not sz.ok
    tc.ladder_fallback = "merge"
    sz = size_plan(plan, 10_000.0, tc, SymbolSpec())
    assert sz.ok and math.isclose(sz.lots_total, 0.03) and all(l == 0 or l >= 0.01 for l in sz.lots_legs) \
        and math.isclose(sum(sz.lots_legs), 0.03)
    # merged legs are never sent: only the non-empty legs open as positions and the plan still closes normally
    seq = ENTRY + [(2001, 2002.2, 2000.5, 2002), (2002, 2004.2, 2001.5, 2004), (2004, 2006.2, 2003.5, 2006),
                   (2006, 2008.2, 2005.5, 2008), (2008, 2010.2, 2007.5, 2010)]
    res, sim = run(bars(seq), [d], cfg(risk_pct=0.15, tp_levels=("0.4", "0.8", "1.2", "1.6", "2.0"), tp_fracs=("0.2",) * 5,
                                       ladder_fallback="merge"))
    assert len(res.trades) == 1 and res.trades.iloc[0].outcome == "tp2"
    legs = [x.split("@")[0] for x in res.trades.iloc[0].legs.split(";")]
    assert 2 <= len(legs) < 5 and all(float(l) >= 0.01 for l in legs) and math.isclose(sum(map(float, legs)), 0.03)


def test_five_leg_ladder_full_run_and_ratchet():
    lv, fr = ("0.4", "0.8", "1.2", "1.6", "2.0"), ("0.2",) * 5     # 2002/2004/2006/2008/2010 ; 0.20 lots -> 0.04 each
    seq = ENTRY + [(2001, 2002.2, 2000.5, 2002), (2002, 2004.2, 2001.5, 2004), (2004, 2006.2, 2003.5, 2006),
                   (2006, 2008.2, 2005.5, 2008), (2008, 2010.2, 2007.5, 2010)]
    t, _ = _one(seq, tp_levels=lv, tp_fracs=fr)
    assert t.outcome == "tp2" and math.isclose(t.r_net, 0.2 * (0.4 + 0.8 + 1.2 + 1.6 + 2.0), abs_tol=1e-6)
    # ratchet: after leg 3 (2006) the stop is at leg-2 target 2004; a dip to 2003.9 stops legs 4+5 there
    seq_r = seq[:5] + [(2006, 2006.5, 2003.9, 2004.5)]
    t, _ = _one(seq_r, tp_levels=lv, tp_fracs=fr, ratchet_sl=True)
    assert t.outcome == "trail" and math.isclose(t.r_net, 0.2 * (0.4 + 0.8 + 1.2) + 0.4 * 0.8, abs_tol=1e-6)


def test_v10_defaults_do_not_change_v9_behaviour():
    c = cfg()
    assert (c.sl_after_leg, c.trail_after_leg, c.tp_unit, c.ladder_fallback) == ((), 0, "r", "reject")
    t_a, _ = _one(ENTRY + [(2001, 2003.2, 2000.5, 2003), (2003, 2015.5, 2002.5, 2015)], partial_r=0.6, partial_frac=0.25, tp2_r=3.0)
    assert math.isclose(t_a.r_net, 2.4, abs_tol=1e-6)


# ------------------------------------------------------------------------------------------ v11 "more trades" levers
def _two_tf_overlap_events():
    # same level shown on M15 (10:00) and M5 (10:01): zones 1995-2000 and 1996-1999 (overlap 100 % of the smaller)
    return [sel("2026-03-02 10:00", pid=1, tf="M15"), sel("2026-03-02 10:01", pid=9, tf="M5", top=1999.0, bottom=1996.0)]


def test_v11_defaults_keep_cross_tf_dedupe():
    res, sim = run(bars([(2005, 2006, 2004, 2005)] * 4), _two_tf_overlap_events(), cfg())
    assert len(sim.pending) == 1 and sim.skipped[0][1] == "overlaps pending"


def test_v11_dedupe_same_tf_only_allows_confluence_on_another_tf():
    res, sim = run(bars([(2005, 2006, 2004, 2005)] * 4), _two_tf_overlap_events(), cfg(dedupe_cross_tf=False))
    assert set(sim.pending) == {"M15#1", "M5#9"} and not sim.skipped
    # the same-timeframe overlap is still refused (persist policy so the first order is not simply replaced)
    ev = [sel("2026-03-02 10:00", pid=1, tf="M15"), sel("2026-03-02 10:01", pid=2, tf="M15", top=1999.0, bottom=1996.0)]
    res, sim = run(bars([(2005, 2006, 2004, 2005)] * 4), ev, cfg(dedupe_cross_tf=False, order_policy="persist"))
    assert set(sim.pending) == {"M15#1"} and sim.skipped[0][1] == "overlaps pending"


def test_v11_overlap_mode_allow_and_share():
    res, sim = run(bars([(2005, 2006, 2004, 2005)] * 4), _two_tf_overlap_events(), cfg(overlap_mode="allow"))
    assert set(sim.pending) == {"M15#1", "M5#9"}
    a, b = sim.pending["M15#1"], sim.pending["M5#9"]
    # full risk on both: 1 % of 10k = $100; M15 1R = $5 -> 0.20 lots; M5 1R = $3 -> 0.33 lots
    assert math.isclose(a.lots_leg1 + a.lots_leg2, 0.20) and math.isclose(b.lots_leg1 + b.lots_leg2, 0.33)
    res, sim = run(bars([(2005, 2006, 2004, 2005)] * 4), _two_tf_overlap_events(), cfg(overlap_mode="share", overlap_risk_frac=0.5))
    a, b = sim.pending["M15#1"], sim.pending["M5#9"]
    assert math.isclose(a.lots_leg1 + a.lots_leg2, 0.20)                 # first plan: full risk
    assert math.isclose(b.lots_leg1 + b.lots_leg2, 0.16)                 # second (overlapping): 0.5 % -> $50 / $3 = 0.166 -> 0.16
    assert b.plan.risk_scale == 0.5


def test_v11_cancel_grace_keeps_order_when_reshown_and_cancels_when_not():
    flat = [(2005, 2006, 2004, 2005)] * 8
    # shown 10:00, cleared 10:02, shown again 10:03 (inside a 3-minute grace) -> order survives
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:02", pid=-1, event="clear"), sel("2026-03-02 10:03", pid=1)]
    res, sim = run(bars(flat), ev, cfg(cancel_grace_min=3))
    assert set(sim.pending) == {"M15#1"} and not sim.cancelled and sim.pending["M15#1"].grace_until == -1
    # cleared 10:02 and never re-shown -> cancelled at 10:05 with the grace tag
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:02", pid=-1, event="clear")]
    res, sim = run(bars(flat), ev, cfg(cancel_grace_min=3))
    assert not sim.pending and sim.cancelled[0].reason_cancel == "no longer shown (grace)"
    # a fill inside the grace period is a normal trade
    seq = [(2005, 2006, 2004, 2005), (2005, 2006, 2004, 2005), (2005, 2006, 2004, 2005), (2004, 2004.5, 1999.0, 2001),
           (2001, 2002, 2000.5, 2001.5)]
    res, sim = run(bars(seq), ev, cfg(cancel_grace_min=3))
    assert len(res.trades) == 1 and not sim.cancelled
    # default (0) = immediate cancel, as in v10
    res, sim = run(bars(flat), ev, cfg())
    assert sim.cancelled[0].reason_cancel == "no longer shown"


# ------------------------------------------------------------------------------------------ v12 "more trades round 2" levers
def test_v12_defaults_are_v11_behaviour():
    c = cfg()
    assert (c.confluence_filter, c.keep_replaced_bars, c.reentry_bars, c.reentry_max) == ("", 0, 0, 1)
    assert c.reentry_outcomes == ("partial_be", "be")


def test_v12_confluence_filter_replaces_the_quality_gate_only_when_another_tf_is_active():
    # M15 shown (q 0.6) then M5 on the same level with q 0.52: the normal filter (M5 min_quality 0.55) rejects it ...
    ev = [sel("2026-03-02 10:00", pid=1, tf="M15"), sel("2026-03-02 10:01", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    ev[1]["quality"] = 0.52
    flat = bars([(2005, 2006, 2004, 2005)] * 4)
    res, sim = run(flat, ev, cfg(dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55"))
    assert set(sim.pending) == {"M15#1"} and sim.filtered == [("M5#9", "M5: quality")]
    # ... the confluence filter (M5 min_quality 0.50) accepts it because M15#1 is active on the same level
    res, sim = run(flat, ev, cfg(dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50"))
    assert set(sim.pending) == {"M15#1", "M5#9"} and sim.pending["M5#9"].plan.confluent
    # without an active plan on another TF the normal filter applies (M5 alone -> rejected)
    res, sim = run(flat, ev[1:], cfg(dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50"))
    assert not sim.pending and sim.filtered == [("M5#9", "M5: quality")]
    # an active plan of the SAME timeframe is not confluence (and is deduped anyway)
    ev2 = [sel("2026-03-02 10:00", pid=1, tf="M5"), sel("2026-03-02 10:01", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    ev2[1]["quality"] = 0.52
    res, sim = run(flat, ev2, cfg(dedupe_cross_tf=False, trade_filter="M5:min_quality=0.55", confluence_filter="M5:min_quality=0.50",
                                  order_policy="persist"))
    assert set(sim.pending) == {"M5#1"}


def test_v12_keep_replaced_keeps_the_order_for_n_bars_but_clear_still_cancels():
    flat = [(2005, 2006, 2004, 2005)] * 40
    # POI 1 replaced by POI 2 (same slot) at 10:02: default -> cancelled at once
    ev = [sel("2026-03-02 10:00", pid=1, tf="M5"), sel("2026-03-02 10:02", pid=2, tf="M5", top=1994.0, bottom=1990.0)]
    res, sim = run(bars(flat), ev, cfg(order_policy="mirror"))
    assert set(sim.pending) == {"M5#2"} and sim.cancelled[0].reason_cancel == "replaced"
    # keep_replaced_bars=2 (M5 -> 10 minutes): both orders live until 10:12, then #1 is cancelled with the tag
    res, sim = run(bars(flat), ev, cfg(keep_replaced_bars=2))
    assert set(sim.pending) == {"M5#2"} and sim.cancelled[0].reason_cancel == "replaced (grace)"
    assert sim.cancelled[0].grace_until == 2 + 10
    # re-shown before the deadline -> kept for good
    ev3 = ev + [sel("2026-03-02 10:05", pid=1, tf="M5")]
    res, sim = run(bars(flat), ev3, cfg(keep_replaced_bars=2))
    # (#2 is now the replaced one -> it gets its own grace window and dies at 10:15)
    assert set(sim.pending) == {"M5#1"} and sim.cancelled[0].plan.key == "M5#2" and sim.cancelled[0].reason_cancel == "replaced (grace)"
    assert sim.pending["M5#1"].grace_until == -1
    # a CLEAR of the slot cancels immediately even with keep_replaced_bars
    ev4 = ev + [sel("2026-03-02 10:03", pid=-1, tf="M5", event="clear")]
    res, sim = run(bars(flat), ev4, cfg(keep_replaced_bars=2))
    assert not sim.pending and {c.reason_cancel for c in sim.cancelled} == {"no longer shown"}
    # a fill of the kept order inside the window is a normal trade
    seq = [(2005, 2006, 2004, 2005)] * 4 + [(2004, 2004.5, 1999.0, 2001), (2001, 2002, 2000.5, 2001.5)]
    res, sim = run(bars(seq), ev, cfg(keep_replaced_bars=2))
    assert len(res.trades) == 1 and res.trades.iloc[0].key == "M5#1"


def test_v12_reentry_after_break_even_exit():
    # partial at 0.4R (2002) -> BE -> stopped at 2000 = partial_be; the plan is re-armed for reentry_bars x TF (M15 -> 15 min)
    seq = ENTRY + [(2001, 2002.5, 2000.5, 2002),     # 10:02 TP1 -> BE
                   (2002, 2002.2, 1999.5, 1999.8),   # 10:03 BE stop -> partial_be ; re-entry placed (price through entry -> unarmed)
                   (1999.8, 2000.2, 1999.6, 2000.1),  # 10:04 opens below -> still not armed
                   (2000.5, 2001.0, 2000.4, 2000.8),  # 10:05 ask open 2000.8 > 2000 -> armed
                   (2000.8, 2001.0, 1999.5, 2000.5),  # 10:06 ask low 1999.8 <= 2000 -> fill #2
                   (2000.5, 2002.6, 2000.4, 2002.4),  # 10:07 TP1 again
                   (2002.4, 2007.8, 2002.0, 2007.5)]  # 10:08 TP2 (1.5R = 2007.5)
    res, sim = run(bars(seq), [sel("2026-03-02 10:00")], cfg(reentry_bars=1))
    t = res.trades
    assert list(t.key) == ["M15#1", "M15#1~1"] and list(t.outcome) == ["partial_be", "tp2"] and list(t.reentry) == [0, 1]
    assert sim.reentries_placed == 1 and res.summary()["reentry_trades"] == 1
    # only one re-entry per POI by default: a second BE exit does not re-arm again
    seq2 = seq[:7] + [(2000.5, 2002.6, 2000.4, 2002.4), (2002.4, 2002.5, 1999.5, 1999.8), (1999.8, 2001, 1999.7, 2000.9),
                      (2001, 2001.2, 1999.5, 2000)]
    res, sim = run(bars(seq2), [sel("2026-03-02 10:00")], cfg(reentry_bars=1))
    assert list(res.trades.outcome) == ["partial_be", "partial_be"] and sim.reentries_placed == 1 and not sim.pending
    # the re-armed order expires after reentry_bars x TF minutes if not filled
    seq3 = ENTRY + [(2001, 2002.5, 2000.5, 2002), (2002, 2002.2, 1999.5, 1999.8)] + [(2003, 2004, 2002.5, 2003.5)] * 20
    res, sim = run(bars(seq3), [sel("2026-03-02 10:00")], cfg(reentry_bars=1))
    assert not sim.pending and sim.cancelled[0].plan.key == "M15#1~1" and sim.cancelled[0].reason_cancel == "expired"
    # a full stop (sl) does not re-arm
    seq4 = ENTRY + [(2001, 2001.5, 1994.5, 1994.8)]
    res, sim = run(bars(seq4), [sel("2026-03-02 10:00")], cfg(reentry_bars=1))
    assert list(res.trades.outcome) == ["sl"] and sim.reentries_placed == 0
    # default off
    res, sim = run(bars(seq), [sel("2026-03-02 10:00")], cfg())
    assert len(res.trades) == 1 and sim.reentries_placed == 0


def test_v12_tf_restrictions_of_reentry_and_keep_replaced():
    seq = ENTRY + [(2001, 2002.5, 2000.5, 2002), (2002, 2002.2, 1999.5, 1999.8), (2000.5, 2001.0, 2000.4, 2000.8),
                   (2000.8, 2001.0, 1999.5, 2000.5)]
    # plan is M15: re-entry only for M10|M30 -> nothing re-armed; for M15|M10 -> re-armed
    res, sim = run(bars(seq), [sel("2026-03-02 10:00")], cfg(reentry_bars=1, reentry_tfs=("M10", "M30")))
    assert sim.reentries_placed == 0 and len(res.trades) == 1
    res, sim = run(bars(seq), [sel("2026-03-02 10:00")], cfg(reentry_bars=1, reentry_tfs=("M15", "M10")))
    assert sim.reentries_placed == 1 and len(res.trades) == 2
    flat = [(2005, 2006, 2004, 2005)] * 40
    ev = [sel("2026-03-02 10:00", pid=1, tf="M5"), sel("2026-03-02 10:02", pid=2, tf="M5", top=1994.0, bottom=1990.0)]
    res, sim = run(bars(flat), ev, cfg(keep_replaced_bars=2, keep_replaced_tfs=("M10",)))
    assert sim.cancelled[0].reason_cancel == "replaced"          # M5 not in the list -> v11 behaviour
    res, sim = run(bars(flat), ev, cfg(keep_replaced_bars=2, keep_replaced_tfs=("M5",)))
    assert sim.cancelled[0].reason_cancel == "replaced (grace)"
