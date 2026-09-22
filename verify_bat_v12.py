#!/usr/bin/env python3
"""Replay the exact run_trader.bat v12-A strings in the simulator: must give 427 tr / +179.51 % / DD -5.28 %.  -> logs/verify_bat_v12.log"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v12_funnel import load_year
from run_v10_study import BASE
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator
TRADER = "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1"
FLT = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.57/M15:min_quality=0.60/M30|H1:min_quality=0.57"
CF = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/M15:min_quality=0.60/M30|H1:min_quality=0.57"
m1, sel = load_year("data/xauusd_m1.csv")
t = TraderConfig(trade_filter=FLT, confluence_filter=CF, max_daily_loss_pct=4.5, max_total_loss_pct=9.0).override(BASE).override(TRADER)
s = PortfolioSimulator(m1, sel, t, SymbolSpec()).run().summary()
study = json.load(open("study_results/v12_levers/X_CF_m10_q0.5+KR_htf_b1+F_m10_q0.57.json"))
line = f"bat replay: {s['trades']} tr / {s['return_%']:+.2f} % / DD {s['max_dd_%']} / PF {s['profit_factor']}  | study: {study['trades']} / {study['return_%']:+.2f} / {study['max_dd_%']} / {study['profit_factor']}"
ok = (s["trades"], s["return_%"], s["max_dd_%"]) == (study["trades"], study["return_%"], study["max_dd_%"])
open("logs/verify_bat_v12.log", "w").write(line + f"\nIDENTICAL: {ok}\n")
print(line, "\nIDENTICAL:", ok)
