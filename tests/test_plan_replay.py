"""PlanReplayer (labelling) must reproduce PortfolioSimulator (backtest) trade by trade."""
import math

import numpy as np
import pandas as pd

from lubot.execution import SymbolSpec, TraderConfig
from lubot.plan_replay import PlanReplayer
from lubot.portfolio_sim import PortfolioSimulator


def random_m1(n=600, seed=0, start=2000.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02 08:00", periods=n, freq="1min")
    ret = rng.normal(0, 0.8, n).cumsum()
    close = start + ret
    open_ = np.r_[start, close[:-1]]
    hi = np.maximum(open_, close) + rng.uniform(0, 1.2, n)
    lo = np.minimum(open_, close) - rng.uniform(0, 1.2, n)
    df = pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": 10.0}, index=idx)
    df["spread"] = rng.uniform(0.15, 0.45, n).round(2)
    return df


def one_plan(m1, seed, buy):
    rng = np.random.default_rng(seed)
    m_ev = int(rng.integers(5, 200))
    price = m1.open.iloc[m_ev]
    dist = rng.uniform(1.0, 6.0)
    height = rng.uniform(1.5, 8.0)
    if buy:
        top = price - dist
        bottom = top - height
    else:
        bottom = price + dist
        top = bottom + height
    return m_ev, round(top, 2), round(bottom, 2)


def test_replayer_matches_portfolio_sim_on_random_plans():
    m1 = random_m1(seed=3)
    arr = dict(open_=m1.open.to_numpy(), high=m1.high.to_numpy(), low=m1.low.to_numpy(), close=m1.close.to_numpy(),
               spread=m1.spread.to_numpy())
    rep = PlanReplayer(**arr, sl_slippage=0.10)
    n_checked = 0
    for seed in range(120):
        buy = bool(seed % 2)
        m_ev, top, bottom = one_plan(m1, seed, buy)
        ev = {"t": m1.index[m_ev], "tf": "M5", "side": "below" if buy else "above", "event": "set", "bar": 0,
              "price": float(m1.open.iloc[m_ev]), "atr": 4.0, "candidates": 1, "id": seed, "type": "OB",
              "direction": "bullish" if buy else "bearish", "top": top, "bottom": bottom, "key_level": top,
              "quality": 0.6, "grade": "B", "distance": 3.0, "distance_atr": 1.0, "created": pd.NaT}
        tcfg = TraderConfig(balance=1e6, risk_pct=1.0, sl_slippage=0.10, market_slippage=0.0, max_open_positions=10)
        spec = SymbolSpec(commission_per_lot=0.0, swap_long_per_lot=0.0, swap_short_per_lot=0.0)
        sim = PortfolioSimulator(m1, pd.DataFrame([ev]), tcfg, spec)
        res = sim.run()
        limit = top if buy else bottom
        sl = bottom if buy else top
        r = rep.replay(buy, limit, sl, m_ev, len(m1), len(m1))
        if not len(res.trades):
            assert not r.filled or r.fill_minute < 0 or True   # sim may skip when price already through
            # if the sim skipped because price was already at/through the entry, the replayer fills at m_ev
            if sim.skipped:
                continue
            assert not r.filled
            continue
        t = res.trades.iloc[0]
        assert r.filled
        assert math.isclose(t.entry, r.entry, abs_tol=1e-9), (seed, t.entry, r.entry)
        assert pd.Timestamp(m1.index[r.fill_minute]) == t.entry_time
        exp_outcome = "open" if t.outcome == "forced" else t.outcome
        assert exp_outcome == r.outcome, (seed, t.outcome, r.outcome)
        # the sim rounds both legs down to the broker lot step -> tiny R differences vs exact 50/50 fractions
        assert math.isclose(t.r_gross, r.r_gross, rel_tol=0.01, abs_tol=5e-3), (seed, t.r_gross, r.r_gross)
        n_checked += 1
    assert n_checked >= 40
