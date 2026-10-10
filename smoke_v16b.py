#!/usr/bin/env python3
"""v16b smoke / parity: v16-A (run_trader.bat strings frozen in v16b_common) on the v16 streams must reproduce FINAL_BACKTEST_V16
byte-for-byte after the v16b simulator changes (467 / +301.75 / -5.82 / PF 2.365); then a first look at the levers.
    python3 smoke_v16b.py [--variants "name=override;name=override"]   -> study_results/v16b_smoke.jsonl (append)
"""
from __future__ import annotations
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator
from v16b_common import EXPECT_V16A, fmt16b, judge16b, load_year16, v16a_config

ap = argparse.ArgumentParser()
ap.add_argument("--variants", default="parity=")
a = ap.parse_args()
m1, sel = load_year16(stream="v16", max_rank=3)
for item in a.variants.split(";"):
    name, _, ov = item.partition("=")
    t0 = time.time()
    res = PortfolioSimulator(m1, sel, v16a_config().override(ov), SymbolSpec()).run()
    j = judge16b(res); j["secs"] = round(time.time() - t0, 1); j["name"] = name; j["override"] = ov
    print(fmt16b(name, j), f"{j['secs']}s", flush=True)
    if name == "parity":
        got = (j["trades"], j["return_%"], j["max_dd_%"])
        print("PARITY", "IDENTICAL" if got == EXPECT_V16A else f"MISMATCH {got} != {EXPECT_V16A}", flush=True)
    with open("study_results/v16b_smoke.jsonl", "a") as f:
        f.write(json.dumps(j, default=str) + "\n")
