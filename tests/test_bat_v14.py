"""v14 - the strings shipped in run_trader.bat parse into a TraderConfig that carries the v14-A asymmetric martingale ON TOP of v13-A."""
import re

from lubot.execution import TraderConfig
from lubot.martingale import Martingale
from tests.test_bat_v13 import _bat_line
from tests.test_v14_martingale import _plan


def test_bat_trader_string_is_v14a():
    line = _bat_line()
    t = TraderConfig().override(re.search(r'--trader "([^"]*)"', line).group(1))
    assert t.mart_mode == "mult" and t.mart_mult == 1.5 and t.mart_max_steps == 3 and t.mart_max_risk_pct == 3.0
    assert t.mart_scope == "tf" and t.mart_tfs == ("M10", "M15", "M30", "H1") and t.mart_sides == ("buy",) and t.mart_ungated_scale == 0.5
    assert t.grid_add_r == 0.0 and t.mart_tp_levels == () and t.mart_loss_r == 0.2          # no grid, no recovery ladder, default loss rule
    # behaviour (per-TF streaks): after one M15 loss an M15 buy is x1.5, an M15 sell is x0.5, other timeframes are untouched;
    # after an M5 loss every M5 plan is x0.5 (M5 never steps up)
    m = Martingale(t)
    m.on_close("M15", -100.0, -1.0)
    assert m.scale(_plan(t), 1e4) == (1.5, 1)
    assert m.scale(_plan(t, direction="bearish", side="above"), 1e4) == (0.5, -1)
    assert m.scale(_plan(t, tf="M5"), 1e4) == (1.0, 0) and m.scale(_plan(t, tf="M10"), 1e4) == (1.0, 0)
    m.on_close("M5", -100.0, -1.0)
    assert m.scale(_plan(t, tf="M5"), 1e4) == (0.5, -1)
    m.on_close("M15", -100.0, -1.0); m.on_close("M15", -100.0, -1.0); m.on_close("M15", -100.0, -1.0)
    assert m.scale(_plan(t), 1e4) == (3.0, 3)                                                  # 1.5^3 = 3.375 capped by 3 % / 1 %
