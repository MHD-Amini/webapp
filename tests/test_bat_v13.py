"""v13 - the strings shipped in run_trader.bat parse into a TraderConfig that carries the v13-A regime management."""
import re

from lubot.execution import TraderConfig, ladder


def _bat_line():
    bat = open("run_trader.bat", encoding="utf-8").read()
    return next(l for l in bat.splitlines() if l.strip().startswith("python trader.py --symbol"))


def test_bat_trader_string_is_v13a():
    line = _bat_line()
    trader = re.search(r'--trader "([^"]*)"', line).group(1)
    t = TraderConfig().override(trader)
    assert t.regime_metric == "adr_ratio" and t.regime_threshold == 1.0 and (t.regime_short, t.regime_long) == (5, 20)
    assert ladder(t) == ((0.6, 1.2, 2.4, 4.8), (0.25, 0.25, 0.25, 0.25))
    assert ladder(t, range_regime=True) == ((0.5, 1.0, 1.5, 2.5), (0.25, 0.25, 0.25, 0.25))
    assert t.range_sl_after_leg == ("0", "0.3", "x", "x") and t.range_risk_scale == 1.0 and t.range_tfs == ()
    # v12-A part unchanged
    assert t.dedupe_cross_tf is False and t.keep_replaced_bars == 1
    assert {"M10", "M15", "M30", "H1"} <= set(t.keep_replaced_tfs)   # v16 adds M20 to the set
    assert t.ladder_fallback == "merge"
    flt = re.search(r'--trade-filter "([^"]*)"', line).group(1)
    cf = re.search(r'--confluence-filter "([^"]*)"', line).group(1)
    assert "M10:min_quality=0.57" in flt and "M10:min_quality=0.50" in cf and "M5:max_cost_r=0.08" in flt
