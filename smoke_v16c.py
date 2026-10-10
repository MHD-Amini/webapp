#!/usr/bin/env python3
"""v16c parity smoke: the v16b-A trader through the simulator WITH the v16c code present (all v16c levers at their defaults) must
reproduce the v16b final numbers exactly (446 trades / +338.31 % / -5.55 % max DD).  Optionally one override for a quick look.

    python3 smoke_v16c.py                      # parity only
    python3 smoke_v16c.py "dd_throttle_pct=3.5,dd_throttle_scale=0.5"
"""
import sys
import time

from backtest_trader import spec_override
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator
from v16c_common import EXPECT_V16B, fmt16c, judge16c, load_year16, v16b_config

m1, sel = load_year16("data/xauusd_m1.csv", stream="v16", max_rank=3)
t0 = time.time()
res = PortfolioSimulator(m1, sel, v16b_config(), spec_override(SymbolSpec(), "")).run()
j = judge16c(res)
got = (j["trades"], j["return_%"], j["max_dd_%"])
print(fmt16c("ref(v16b-A)", j), f"({time.time() - t0:.0f}s)")
print("PARITY", "IDENTICAL" if got == EXPECT_V16B else f"MISMATCH {got} != {EXPECT_V16B}", flush=True)
for over in sys.argv[1:]:
    t0 = time.time()
    res = PortfolioSimulator(m1, sel, v16b_config().override(over), spec_override(SymbolSpec(), "")).run()
    j = judge16c(res)
    s = res.summary()
    print(fmt16c(over[:34], j), f"({time.time() - t0:.0f}s) dd_scaled {s['dd_scaled']} dd_skipped {s['dd_skipped']} "
          f"dd_days {s['dd_days']} day_soft {s['day_soft_scaled']}/{s['day_soft_skipped']} open_risk {s['open_risk_scaled']}/"
          f"{s['open_risk_skipped']} streak {s['streak_scaled']}")
if got != EXPECT_V16B:
    sys.exit(1)
