"""v15 - the strings shipped in run_trader.bat parse into a TraderConfig that carries v15-A (confluence memory 240 min + conviction
sizing x1.25 / x0.9) ON TOP of v14-A (martingale) and v13-A (regime ladder), with every other v15 lever OFF."""
import re

from lubot.execution import TraderConfig
from tests.test_bat_v13 import _bat_line


def test_bat_trader_string_is_v15a():
    line = _bat_line()
    t = TraderConfig().override(re.search(r'--trader "([^"]*)"', line).group(1))
    # v15-A
    assert t.confluence_memory_min == 240 and t.confluence_memory_kind == "all"
    assert t.confluent_risk_scale == 1.25 and t.plain_risk_scale == 0.9
    assert t.tier_filter == "" and t.mart_confluent_only is False                      # v15-B tier / gate NOT shipped
    # v14-A still underneath
    assert t.mart_mode == "mult" and t.mart_mult == 1.5 and t.mart_scope == "tf" and t.mart_ungated_scale == 0.5
    # v13-A still underneath
    assert t.regime_metric == "adr_ratio" and t.range_tp_levels == ("0.5", "1.0", "1.5", "2.5")
    # the confluence filter (the bar the memory widens) is unchanged: M10 0.50
    cf = re.search(r'--confluence-filter "([^"]*)"', line).group(1)
    assert "M10:min_quality=0.50" in cf
    header = [l for l in open("run_trader.bat", encoding="utf-8").read().splitlines() if l.startswith("REM")]
    assert any("v15-A" in l for l in header)          # the v15 layer is documented in the bat header (v16/v16b ship on top of it)
