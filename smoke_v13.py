#!/usr/bin/env python3
"""v13 step 2 smoke: parity (defaults == v12-A exactly) + first look at the regime-adaptive ladder.  -> logs/smoke_v13.log"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v13_diag import v12a_config, load_year, EXPECT
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator

m1, sel = load_year("data/xauusd_m1.csv")
def run(over, label):
    t0 = time.time()
    t = v12a_config().override(over)
    res = PortfolioSimulator(m1, sel, t, SymbolSpec()).run()
    s = res.summary(); tr = res.trades
    tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
    mo = tr.groupby("month").r_net.sum().round(1).to_dict()
    oos = tr[tr.close_time >= "2026-03-01"]
    oos_pf = oos[oos.net > 0].net.sum() / abs(oos[oos.net < 0].net.sum())
    line = (f"{label:<46} n {s['trades']:4d} ret {s['return_%']:+7.2f}% DD {s['max_dd_%']:6.2f} PF {s['profit_factor']:5.3f} win {s['win_%']:4.1f} "
            f"sl {s['sl_%']:4.1f} OOS_PF {oos_pf:4.2f} OOS_R {oos.r_net.sum():+6.1f} range_tr {s.get('range_trades',0):3d} | Apr26 {mo.get('2026-04',0):+5.1f} Sep25 {mo.get('2025-09',0):+5.1f} "
            f"worst_mo {min(mo.values()):+5.1f} months_pos {sum(v>0 for v in mo.values())}/{len(mo)} [{time.time()-t0:.0f}s]")
    print(line, flush=True)
    return s, mo

s, mo = run("", "v12-A (defaults, parity)")
got = (s["trades"], s["return_%"], s["max_dd_%"])
print("PARITY IDENTICAL:", got == EXPECT, got, EXPECT, flush=True)
assert got == EXPECT
for over, label in [
    ("regime_metric=adr_ratio,regime_threshold=0.9,range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1", "adr<0.9 -> tight 0.5/1/1.5/2.5"),
    ("regime_metric=adr_ratio,regime_threshold=0.9,range_tp_levels=0.6|1.2|1.8|3.0,range_tp_fracs=1|1|1|1", "adr<0.9 -> mid 0.6/1.2/1.8/3.0"),
    ("regime_metric=adr_ratio,regime_threshold=0.9,range_tp_levels=0.6|1.2|2.4|4.8,range_tp_fracs=1|1|1|1,range_sl_after_leg=0|0.3|1.0|x", "adr<0.9 -> G + lock 0/0.3/1.0"),
    ("regime_metric=er,regime_threshold=0.3,range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1", "er5<0.3 -> tight"),
    ("regime_metric=adr_ratio,regime_threshold=0.9,range_risk_scale=0.5", "adr<0.9 -> half risk"),
    ("regime_metric=adr_ratio,regime_threshold=0.9,range_risk_scale=0", "adr<0.9 -> no trading"),
]:
    run(over, label)
