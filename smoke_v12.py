#!/usr/bin/env python3
"""v12 step 2 smoke: parity of the defaults + one run per new lever on the full year.  Output -> logs/smoke_v12.log"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v12_funnel import load_year, ref_config  # noqa: E402
from lubot.execution import SymbolSpec  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402

os.makedirs("logs", exist_ok=True)
m1, sel = load_year("data/xauusd_m1.csv")
ref = json.load(open("study_results/v12_funnel_ref.json"))
out = open("logs/smoke_v12.log", "a")


def go(name, **kw):
    t0 = time.time()
    c = ref_config()
    for k, v in kw.items():
        setattr(c, k, v)
    res = PortfolioSimulator(m1, sel, c, SymbolSpec()).run()
    s = res.summary()
    tr = res.trades
    oos = tr[tr.close_time >= "2026-03-01"]
    pf = oos[oos.net > 0].net.sum() / abs(oos[oos.net < 0].net.sum())
    line = (f"{name:<28} n {s['trades']:4d} ret {s['return_%']:+7.1f}% DD {s['max_dd_%']:6.2f}% PF {s['profit_factor']:5.2f} "
            f"win {s['win_%']:4.1f} sl {s['sl_%']:4.1f} OOS {oos.r_net.sum():+6.1f}R/{pf:4.2f} re {s['reentries_placed']}/"
            f"{s['reentry_trades']} conf {s['confluent_trades']} {time.time() - t0:.0f}s")
    print(line, flush=True)
    out.write(line + "\n")
    out.flush()
    return s


s = go("ref")
ok = (s["trades"], s["return_%"], s["max_dd_%"]) == (ref["trades"], ref["return_%"], ref["max_dd_%"])
out.write(f"PARITY {'OK' if ok else 'BROKEN'}\n")
print("PARITY", "OK" if ok else "BROKEN")
go("keep_replaced_bars=3", keep_replaced_bars=3)
go("reentry_bars=6", reentry_bars=6)
go("conf HTF q0.52", confluence_filter="M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/"
                                        "M10|M15|M30|H1:min_quality=0.52")
