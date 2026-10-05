#!/usr/bin/env python3
"""v15 step 2 SMOKE: parity (defaults == v14-A exactly) + one run per new lever family on the full year.
    python3 smoke_v15.py  -> study_results/v15_smoke.jsonl, logs/smoke_v15.log"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec
from lubot.portfolio_sim import PortfolioSimulator
from v14_common import CSV, load_year
from v15_common import EXPECT_V14A, fmt15, judge15, v14a_config

TIER_M10 = "M10:min_quality=0.50"                                              # M10 0.50-0.57 at reduced risk
TIER_ALL = "M5:max_cost_r=0.12;min_quality=0.53;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/M15:min_quality=0.55/M30|H1:min_quality=0.52"
VARIANTS = {
    "ref": "",
    "CS_1.5_1.0": "confluent_risk_scale=1.5",
    "CS_1.5_0.75": "confluent_risk_scale=1.5,plain_risk_scale=0.75",
    "CS_2.0_0.75": "confluent_risk_scale=2.0,plain_risk_scale=0.75",
    "CM_60": "confluence_memory_min=60",
    "CM_240": "confluence_memory_min=240",
    "CM_240_open": "confluence_memory_min=240,confluence_memory_kind=open",
    "TIER_m10_0.5": f"tier_filter={TIER_M10},tier_risk_scale=0.5",
    "TIER_all_0.5": f"tier_filter={TIER_ALL},tier_risk_scale=0.5",
    "MG_conf": "mart_confluent_only=true",
    "CMB_cs1.5_cm240": "confluent_risk_scale=1.5,plain_risk_scale=0.75,confluence_memory_min=240",
}


def main():
    os.makedirs("logs", exist_ok=True)
    m1, sel = load_year(CSV)
    out = open("study_results/v15_smoke.jsonl", "a")
    for name, over in VARIANTS.items():
        t0 = time.time()
        # tier_filter contains ',' inside? no: TF blocks use '/' and ';' -> safe for override()
        tcfg = v14a_config().override(over)
        res = PortfolioSimulator(m1, sel, tcfg, SymbolSpec()).run()
        j = judge15(res)
        j["name"], j["overrides"], j["secs"] = name, over, round(time.time() - t0, 1)
        s = res.summary()
        j["tier_trades"], j["confluent_trades"] = s.get("tier_trades"), s.get("confluent_trades")
        line = fmt15(name, j) + f" conf {s.get('confluent_trades')} tier {s.get('tier_trades')}"
        if name == "ref":
            got = (int(s["trades"]), round(s["return_%"], 2), round(s["max_dd_%"], 2))
            line += f"  PARITY {'IDENTICAL' if got == EXPECT_V14A else 'MISMATCH ' + str(got)}"
        print(line, flush=True)
        out.write(json.dumps(j, default=str) + "\n"); out.flush()


if __name__ == "__main__":
    main()
