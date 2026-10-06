#!/usr/bin/env python3
"""v16 smoke / parity: v15-A on the v15 streams (sel_v10_*, rank 1) must reproduce FINAL_BACKTEST_V15 byte-for-byte after the v16
simulator changes; then the first look at the v16 levers on the sel_v16 streams (when recorded).
    python3 smoke_v16.py [--stream v10|v16] [--variants name=override;name=override]   -> study_results/v16_smoke.jsonl (append)
"""
from __future__ import annotations
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator
from v16_common import EXPECT_V15A, fmt16, judge16, load_year16, v15a_config

ap = argparse.ArgumentParser()
ap.add_argument("--stream", default="v10")
ap.add_argument("--max-rank", type=int, default=1)
ap.add_argument("--variants", default="parity=")
a = ap.parse_args()
m1, sel = load_year16(stream=a.stream, max_rank=a.max_rank)
for item in a.variants.split(";"):
    name, _, ov = item.partition("=")
    t0 = time.time()
    res = PortfolioSimulator(m1, sel, v15a_config().override(ov), SymbolSpec()).run()
    j = judge16(res); j["secs"] = round(time.time() - t0, 1); j["name"] = name; j["stream"] = a.stream; j["override"] = ov
    print(fmt16(name, j), f"{j['secs']}s", flush=True)
    if name == "parity":
        got = (j["trades"], j["return_%"], j["max_dd_%"])
        print("PARITY", "IDENTICAL" if got == EXPECT_V15A else f"MISMATCH {got} != {EXPECT_V15A}", flush=True)
    with open("study_results/v16_smoke.jsonl", "a") as f:
        f.write(json.dumps(j, default=str) + "\n")
