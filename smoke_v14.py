#!/usr/bin/env python3
"""v14 step 2 smoke: parity (defaults == v13-A exactly) + first look at every martingale family on the real year.
Resumable: every variant's judge dict is appended to study_results/v14_smoke.jsonl; variants already there are skipped.
    nohup python3 smoke_v14.py > logs/smoke_v14.log 2>&1 &
"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v14_common import CSV, EXPECT_V13A, fmt_judge, judge, load_year, v13a_config
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator

OUT = Path("study_results/v14_smoke.jsonl")
OUT.parent.mkdir(exist_ok=True)
done = {}
if OUT.exists():
    for line in OUT.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            done[d["label"]] = d

VARIANTS = [
    ("", "v13-A (defaults, parity)"),
    ("mart_mode=mult,mart_mult=2.0,mart_max_steps=3,mart_max_risk_pct=4", "A mult x2 cap3 <=4%"),
    ("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3", "A mult x1.5 cap3 <=3%"),
    ("mart_mode=fib,mart_max_steps=3,mart_max_risk_pct=3", "A fib cap3 <=3%"),
    ("mart_mode=add,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3", "A dAlembert +0.5 cap3"),
    ("mart_mode=deficit,mart_deficit_r=1.0,mart_max_steps=3,mart_max_risk_pct=3", "A deficit /1R cap3 <=3%"),
    ("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_tfs=M10|M15|M30|H1,mart_sides=buy", "A x1.5 gated (no M5, buys)"),
    ("mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_tp_levels=0.5|1.0|1.5|2.5,mart_tp_fracs=1|1|1|1,mart_sl_after_leg=0|0.3|x|x", "A x1.5 + tight recovery ladder"),
    ("mart_mode=mult,mart_mult=0.5,mart_max_steps=3", "B shrink x0.5 after losses"),
    ("mart_mode=anti,mart_mult=1.3,mart_max_steps=3,mart_max_risk_pct=3", "B anti x1.3 after wins"),
    ("grid_add_r=0.4,grid_base_frac=0.5,grid_add_frac=0.5", "C grid 0.4R 50/50"),
    ("grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5", "C grid 0.5R 50/50"),
    ("grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.3", "C grid 0.5R 50/30 (0.8 budget)"),
    ("grid_add_r=0.3,grid_base_frac=0.6,grid_add_frac=0.4", "C grid 0.3R 60/40"),
    ("grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5,grid_cancel_on_partial=false", "C grid 0.5R keep after partial"),
    ("grid_add_r=0.5,grid_base_frac=0.5,grid_add_frac=0.5,grid_deep_ladder=own", "C grid 0.5R own ladder"),
]

m1, sel = load_year(CSV)
for over, label in VARIANTS:
    if label in done:
        print(fmt_judge(label, done[label]) + " [cached]", flush=True)
        continue
    t0 = time.time()
    t = v13a_config().override(over)
    res = PortfolioSimulator(m1, sel, t, SymbolSpec()).run()
    j = judge(res)
    j["label"], j["over"] = label, over
    if over == "":
        s = res.summary()
        got = (s["trades"], s["return_%"], s["max_dd_%"])
        print("PARITY IDENTICAL:", got == EXPECT_V13A, got, EXPECT_V13A, flush=True)
        assert got == EXPECT_V13A
    print(fmt_judge(label, j) + f" [{time.time() - t0:.0f}s]", flush=True)
    with OUT.open("a") as f:
        f.write(json.dumps(j, default=str) + "\n")
