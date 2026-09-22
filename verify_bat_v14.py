#!/usr/bin/env python3
"""Replay the exact run_trader.bat v14-A strings in the simulator: must equal study_results/v14_levers/TF_1.5_c3_htfbuy_dn0.5.json
(430 tr / +227.53 % / DD -5.84 % / PF 2.249).  The strings are READ FROM run_trader.bat itself.  -> logs/verify_bat_v14.log"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v12_funnel import load_year
from run_v10_study import BASE
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

STUDY = "study_results/v14_levers/TF_1.5_c3_htfbuy_dn0.5.json"
bat = open("run_trader.bat", encoding="utf-8").read()
line = next(l for l in bat.splitlines() if l.strip().startswith("python trader.py --symbol"))
def arg(name):
    return re.search(name + r' "([^"]*)"', line).group(1)
TRADER, FLT, CF = arg("--trader"), arg("--trade-filter"), arg("--confluence-filter")
risk = float(re.search(r"--risk ([0-9.]+)", line).group(1))
print("bat --trader:", TRADER)
m1, sel = load_year("data/xauusd_m1.csv")
t = TraderConfig(risk_pct=risk, trade_filter=FLT, confluence_filter=CF, max_daily_loss_pct=4.5, max_total_loss_pct=9.0).override(BASE).override(TRADER)
s = PortfolioSimulator(m1, sel, t, SymbolSpec()).run().summary()
study = json.load(open(STUDY))
out = (f"bat replay: {s['trades']} tr / {s['return_%']:+.2f} % / DD {s['max_dd_%']} / PF {s['profit_factor']} / stepped up {s.get('mart_trades')} down {s.get('mart_down_trades')}"
       f"  | study v14-A: {study['trades']} / {study['return_%']:+.2f} / {study['max_dd_%']} / {study['profit_factor']} / {study['up_n']} {study['dn_n']}")
ok = (s["trades"], s["return_%"], s["max_dd_%"], s["profit_factor"]) == (study["trades"], study["return_%"], study["max_dd_%"], study["profit_factor"])
os.makedirs("logs", exist_ok=True)
open("logs/verify_bat_v14.log", "w").write(out + f"\nIDENTICAL: {ok}\n")
print(out, "\nIDENTICAL:", ok)
sys.exit(0 if ok else 1)
