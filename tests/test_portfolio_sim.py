"""Hand-built M1 scenarios for the portfolio simulator (fills, partial close, BE, costs)."""
import math

import numpy as np
import pandas as pd

from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

SPREAD = 0.30


def bars(seq, start="2026-03-02 10:00", spread=SPREAD):
    """seq = list of (open, high, low, close) bid bars, one per minute."""
    idx = pd.date_range(start, periods=len(seq), freq="1min")
    df = pd.DataFrame(seq, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 10.0
    df["spread"] = spread
    return df


def sel(t, side="below", direction="bullish", top=2000.0, bottom=1995.0, tf="M15", pid=1, event="set"):
    return {"t": pd.Timestamp(t), "tf": tf, "side": side, "event": event, "bar": 0, "price": 2010.0, "atr": 4.0,
            "candidates": 1, "id": pid, "type": "OB", "direction": direction, "top": top, "bottom": bottom,
            "key_level": top, "quality": 0.6, "grade": "B", "distance": 10.0, "distance_atr": 2.5, "created": pd.NaT}


def cfg(**kw):
    base = dict(balance=10_000.0, risk_pct=1.0, sl_slippage=0.0, market_slippage=0.0)
    base.update(kw)
    return TraderConfig(**base)


def spec(**kw):
    base = dict(commission_per_lot=0.0, swap_long_per_lot=0.0, swap_short_per_lot=0.0)
    base.update(kw)
    return SymbolSpec(**base)


def run(m1, events, tcfg=None, sp=None, **kw):
    sim = PortfolioSimulator(m1, pd.DataFrame(events), tcfg or cfg(), sp or spec(), **kw)
    return sim.run(), sim


# ------------------------------------------------------------------------------------------
def test_buy_limit_fills_on_ask_not_bid():
    # zone 1995-2000 -> buy limit 2000.  Bid low 1999.80 but ask low = 2000.10 > 2000 -> NO fill
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.80, 2001), (2001, 2002, 2000.5, 2001.5)])
    res, sim = run(m1, [sel("2026-03-02 10:00")])
    assert len(res.trades) == 0 and len(sim.pending) == 1
    # bid low 1999.60 -> ask low 1999.90 <= 2000 -> filled at 2000 (ask)
    m1 = bars([(2005, 2006, 2004, 2005), (2004, 2004.5, 1999.60, 2001), (2001, 2002, 2000.5, 2001.5)])
    res, sim = run(m1, [sel("2026-03-02 10:00")])
    t = res.trades                       # end of data -> marked to market as "forced"
    assert len(t) == 1 and t.entry[0] == 2000.0 and t.outcome[0] == "forced"


def test_full_cycle_partial_then_tp2_bull():
    # zone 1995-2000; 1R = 5; TP1 2002 (0.4R), TP2 2007.5 (1.5R), BE = 2000
    m1 = bars([
        (2005, 2006, 2004, 2005),         # 10:00 order placed at open (event stamped 10:00)
        (2001.5, 2001.8, 1999.0, 2001),     # 10:01 fill at ask 2000 (bid low 1999 -> ask 1999.3)
        (2001, 2002.5, 2000.5, 2002),     # 10:02 bid high 2002.5 >= TP1 2002 -> leg1 closed, BE armed
        (2002, 2003, 2000.2, 2002.5),     # 10:03 bid low 2000.2 > BE 2000 -> survives
        (2002.5, 2008, 2002, 2007),       # 10:04 bid high 2008 >= TP2 -> leg2 closed
    ])
    res, sim = run(m1, [sel("2026-03-02 10:00")])
    t = res.trades
    assert len(t) == 1 and t.outcome[0] == "tp2" and bool(t.partial[0])
    # risk 1% of 10k = $100, 1R=$5 -> $500/lot -> 0.20 lots, legs 0.10 / 0.10
    assert math.isclose(t.lots[0], 0.20)
    # gross = 0.10*100*2 + 0.10*100*7.5 = 20 + 75 = 95 -> 0.95R
    assert math.isclose(t.gross[0], 95.0, abs_tol=1e-6)
    assert math.isclose(t.r_net[0], 0.95, abs_tol=1e-6)
    assert math.isclose(sim.balance, 10_095.0, abs_tol=1e-6)


def test_partial_then_breakeven_bull():
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),     # fill 2000
        (2001, 2002.5, 2000.5, 2002),     # TP1 -> BE
        (2002, 2002.2, 1999.5, 1999.8),   # bid low 1999.5 <= BE 2000 -> leg2 out at 2000
    ])
    res, sim = run(m1, [sel("2026-03-02 10:00")])
    t = res.trades
    assert t.outcome[0] == "partial_be"
    assert math.isclose(t.r_net[0], 0.2, abs_tol=1e-6)     # 0.5 * 0.4R + 0.5 * 0
    assert math.isclose(sim.balance, 10_020.0, abs_tol=1e-6)


def test_stop_before_partial_with_slippage_and_commission():
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),     # fill 2000
        (2001, 2001.5, 1994.0, 1994.5),   # bid low 1994 <= SL 1995 -> both legs stopped
    ])
    tc = cfg(sl_slippage=0.10)
    res, sim = run(m1, [sel("2026-03-02 10:00")], tc, spec(commission_per_lot=7.0))
    t = res.trades
    assert t.outcome[0] == "sl" and not bool(t.partial[0])
    # loss: 0.20 lots * 100 * (5 + 0.10 slippage) = 102 ; commission 0.2 * 7 = 1.4
    assert math.isclose(t.gross[0], -102.0, abs_tol=1e-6)
    assert math.isclose(t.commission[0], 1.4, abs_tol=1e-6)
    assert math.isclose(t.net[0], -103.4, abs_tol=1e-6)
    assert t.r_net[0] < -1.0


def test_sell_side_uses_ask_for_stop_and_tp():
    # bearish zone 2010-2014 -> sell limit 2010 (bid), SL 2014 on ASK, 1R=4, TP1 2008.4, TP2 2004
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2006, 2010.5, 2005.5, 2009.5),   # bid high 2010.5 >= 2010 -> fill 2010
        (2009, 2013.75, 2007.9, 2008.5),  # bearish bar: O->H first; ask high = 2014.05 >= SL 2014 -> stopped
    ])
    ev = [sel("2026-03-02 10:00", side="above", direction="bearish", top=2014.0, bottom=2010.0)]
    res, sim = run(m1, ev)
    t = res.trades
    assert len(t) == 1 and t.side[0] == "sell" and t.outcome[0] == "sl"
    # same bars with zero spread: ask high 2013.75 < 2014 -> no stop; then low 2007.9 <= TP1 2008.4 -> partial
    m1z = bars([(2005, 2006, 2004, 2005), (2006, 2010.5, 2005.5, 2009.5), (2009, 2013.75, 2007.9, 2008.5)], spread=0.0)
    res, sim = run(m1z, ev)
    assert res.trades.partial[0] and res.trades.outcome[0] == "forced"


def test_intrabar_order_bear_bar_sl_first_for_long():
    # after fill, one bearish minute contains both TP1 and SL: path O->H->L->C -> TP1 (high) first, then BE stop
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),         # fill 2000
        (2001.5, 2002.5, 1994.0, 1994.5),     # bearish bar: O->H(2002.5 hits TP1)->L(1994 hits BE 2000)->C
    ])
    res, _ = run(m1, [sel("2026-03-02 10:00")])
    assert res.trades.outcome[0] == "partial_be"
    # "worst" mode: SL always first when both are inside the bar
    res, _ = run(m1, [sel("2026-03-02 10:00")], cfg(intrabar="worst"))
    assert res.trades.outcome[0] == "sl"
    # bullish bar with both levels: O->L->H->C -> SL first
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),
        (2001.5, 2003.0, 1994.0, 2002.8),     # bullish: O->L(SL)->H
    ])
    res, _ = run(m1, [sel("2026-03-02 10:00")])
    assert res.trades.outcome[0] == "sl"


def test_mirror_policy_cancels_when_selection_changes():
    m1 = bars([(2005, 2006, 2004, 2005)] * 5)
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:02", pid=2, top=1990.0, bottom=1985.0)]
    res, sim = run(m1, ev)
    assert set(sim.pending) == {"M15#2"} and len(sim.cancelled) == 1 and sim.cancelled[0].reason_cancel == "replaced"
    ev = [sel("2026-03-02 10:00", pid=1), sel("2026-03-02 10:02", pid=-1, event="clear")]
    res, sim = run(m1, ev)
    assert not sim.pending and sim.cancelled[0].reason_cancel == "no longer shown"


def test_one_trade_per_poi_and_overlap_dedupe():
    m1 = bars([(2005, 2006, 2004, 2005)] * 4)
    ev = [sel("2026-03-02 10:00", pid=1, tf="M15"), sel("2026-03-02 10:01", pid=9, tf="M5", top=1999.0, bottom=1996.0)]
    res, sim = run(m1, ev)
    assert len(sim.pending) == 1 and sim.skipped[0][1] == "overlaps pending"


def test_price_already_through_entry_is_skipped():
    m1 = bars([(1998, 1999, 1997, 1998)] * 3)     # price is already inside the zone at the event
    res, sim = run(m1, [sel("2026-03-02 10:00")])
    assert not sim.pending and sim.skipped[0][1] == "price already at/through entry"


def test_sizing_uses_equity_and_rounds_down():
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),
        (2001, 2001.5, 1994.0, 1994.5),
    ])
    tc = cfg(balance=1234.0)     # 1% = 12.34 -> 0.024 lots -> 0.02 -> legs 0.01/0.01
    res, sim = run(m1, [sel("2026-03-02 10:00")], tc)
    assert math.isclose(res.trades.lots[0], 0.02)
    assert math.isclose(res.trades.risk_money[0], 10.0)


def test_netting_mode_partial_at_market():
    m1 = bars([
        (2005, 2006, 2004, 2005),
        (2001.5, 2001.8, 1999.0, 2001),
        (2001, 2002.5, 2000.5, 2002),     # TP1 touched -> bot closes half at market with slippage
        (2002, 2002.2, 1999.5, 1999.8),   # BE stop
    ])
    tc = cfg(exec_mode="netting", market_slippage=0.05)
    res, sim = run(m1, [sel("2026-03-02 10:00")], tc)
    t = res.trades
    assert t.outcome[0] == "partial_be"
    # half 0.10 lots closed at 2002 - 0.05 = 1.95 * 100 * 0.1 = 19.5 ; rest at BE 2000 -> 0
    assert math.isclose(t.gross[0], 19.5, abs_tol=1e-6)


def test_swap_charged_at_rollover():
    seq = [(2005, 2006, 2004, 2005), (2001.5, 2001.8, 1999.0, 2001)] + [(2001, 2001.5, 2000.5, 2001)] * 3
    m1 = bars(seq, start="2026-03-02 23:57")      # Monday -> Tuesday rollover, position held overnight
    res, sim = run(m1, [sel("2026-03-02 23:57")], sp=spec(swap_long_per_lot=-50.0))
    t = res.trades
    assert len(t) == 1 and math.isclose(t.swap[0], -50.0 * 0.20, abs_tol=1e-6)


# ------------------------------------------------------------------------------------------ v8
def test_v8_trade_filter_in_simulator():
    from lubot.trade_filter import TradeFilter
    m1 = bars([(2005, 2006, 2004, 2005), (2001.5, 2001.8, 1999.0, 2001), (2001, 2002.5, 2000.5, 2002),
               (2002, 2003, 2000.2, 2002.5), (2002.5, 2008, 2002, 2007)])
    # zone 1995-2000 ($5): cost_r = (0.30 + 0.0) / 5 = 0.06 (commission 0 in the test spec)
    res, sim = run(m1, [sel("2026-03-02 10:00")], cfg(trade_filter="M15:max_cost_r=0.05"))
    assert len(res.trades) == 0 and sim.skipped == [("M15#1", "trade filter")] and len(sim.filtered) == 1
    res, sim = run(m1, [sel("2026-03-02 10:00")], cfg(trade_filter="M15:max_cost_r=0.07"))
    assert len(res.trades) == 1 and res.trades.outcome[0] == "tp2"
    # session gate: 10:00 server = 03:00 NY = london
    res, sim = run(m1, [sel("2026-03-02 10:00")], cfg(trade_filter="M15:sessions=ny|nypm"))
    assert len(res.trades) == 0 and res.filter_reasons().index[0] == "M15: session"
    res, sim = run(m1, [sel("2026-03-02 10:00")], cfg(trade_filter="M15:sessions=london;sides=buy;kinds=OB;min_zone_atr=1.0"))
    assert len(res.trades) == 1
    # rules for other timeframes do not touch M15
    res, sim = run(m1, [sel("2026-03-02 10:00")], cfg(trade_filter="M5:max_cost_r=0.001"))
    assert len(res.trades) == 1
    # override parser round-trip through TraderConfig.override
    t = TraderConfig().override("risk_pct=0.5,trade_filter=M5:max_cost_r=0.08;min_quality=0.55/M10:max_cost_r=0.1")
    f = TradeFilter.parse(t.trade_filter)
    assert f.rules["M5"].max_cost_r == 0.08 and f.rules["M5"].min_quality == 0.55 and f.rules["M10"].max_cost_r == 0.1
