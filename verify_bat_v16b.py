#!/usr/bin/env python3
"""Replay the exact run_trader.bat v16b-A strings in the simulator on the v16 streams (top-3 incl. M20): must equal the study json named
in the bat header (REM v16b study: <name>) or given with --study.  The strings are READ FROM run_trader.bat itself.  -> logs/verify_bat_v16b.log
    python3 verify_bat_v16b.py [--study study_results/v16b_levers/<name>.json]
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_v10_study import BASE
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator
from v16b_common import load_year16

ap = argparse.ArgumentParser()
ap.add_argument("--study", default="")
a = ap.parse_args()
bat = open("run_trader.bat", encoding="utf-8").read()
line = next(l for l in bat.splitlines() if l.strip().startswith("python trader.py --symbol"))
def arg(name):
    return re.search(name + r' "([^"]*)"', line).group(1)
TRADER, FLT, CF = arg("--trader"), arg("--trade-filter"), arg("--confluence-filter")
risk = float(re.search(r"--risk ([0-9.]+)", line).group(1))
tfs = re.search(r"--timeframes (\S+)", line).group(1)
m = re.search(r"REM v16b study: (\S+)", bat)
study_path = a.study or (m.group(1) if m else "")
print("bat --trader:", TRADER)
print("bat --timeframes:", tfs)
m1, sel = load_year16("data/xauusd_m1.csv", stream="v16", max_rank=3)
t = TraderConfig(risk_pct=risk, trade_filter=FLT, confluence_filter=CF, max_daily_loss_pct=4.5, max_total_loss_pct=9.0).override(BASE).override(TRADER)
if not t.timeframes:
    t.timeframes = tuple(tfs.split(","))
res = PortfolioSimulator(m1, sel, t, SymbolSpec()).run()
s = res.summary()
net = round(float(res.trades.net.sum()), 2)
gl = round(float(res.trades.net[res.trades.net < 0].sum()), 2)
out = (f"bat replay: {s['trades']} tr / net {net:+.2f} $ / {s['return_%']:+.2f} % / DD {s['max_dd_%']} / PF {s['profit_factor']} / "
       f"sl {s.get('sl_%')} / gross loss {gl:.2f} / fast cancelled {s.get('fast_cancelled')} / M20 {int((res.trades.tf == 'M20').sum())}")
ok = None
if study_path and os.path.exists(study_path):
    study = json.load(open(study_path))
    out += f"  | study {os.path.basename(study_path)}: {study['trades']} / {study['net_$']:+.2f} / {study['return_%']:+.2f} / {study['max_dd_%']} / {study['profit_factor']}"
    ok = (s["trades"], s["return_%"], s["max_dd_%"], s["profit_factor"]) == (study["trades"], study["return_%"], study["max_dd_%"], study["profit_factor"])
os.makedirs("logs", exist_ok=True)
open("logs/verify_bat_v16b.log", "w").write(out + f"\nIDENTICAL: {ok}\n")
print(out, "\nIDENTICAL:", ok)
sys.exit(0 if ok else 1)
