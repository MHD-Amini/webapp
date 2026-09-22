#!/usr/bin/env python3
"""v8 step 6c - stress tests of the recommended v8 configuration (OOS Mar-Sep 2026). -> study_results/trader_v8_stress.csv"""
import pandas as pd
from backtest_trader import load_selections, spec_override
from lubot import load_mt5_csv
from lubot.execution import SymbolSpec, TraderConfig
from lubot.portfolio_sim import PortfolioSimulator

FLT = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"
BASE = "risk_pct=1.0,exec_mode=split,sl_slippage=0.10,market_slippage=0.05,max_open_positions=4,dedupe_overlap=0.5"
V = {"recommended": ("", "", 0), "spread_x1.5": ("spread_multiplier=1.5", "", 0), "spread_x2": ("spread_multiplier=2.0", "", 0),
     "slippage_x3": ("sl_slippage=0.30,market_slippage=0.15", "", 0), "worst_intrabar": ("intrabar=worst", "", 0),
     "be_delay_2min": ("", "", 2), "netting": ("exec_mode=netting", "", 0), "risk_0.5": ("risk_pct=0.5", "", 0),
     "commission_x2": ("", "commission_per_lot=14", 0), "no_costs": ("sl_slippage=0,market_slippage=0,spread_multiplier=0", "commission_per_lot=0,swap_long_per_lot=0,swap_short_per_lot=0", 0),
     "M5_cost0.06": ("", "", 0, "M5:max_cost_r=0.06;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"),
     "M5_cost0.10": ("", "", 0, "M5:max_cost_r=0.10;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"),
     "M5_no_session_rule": ("", "", 0, "M5:max_cost_r=0.08;min_quality=0.55/M10|M15|M30|H1:min_quality=0.60"),
     "M5_q0.60": ("", "", 0, "M5:max_cost_r=0.08;min_quality=0.60;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60")}
m1 = load_mt5_csv("data/xauusd_m1.csv")["2026-03-01":]
sel = pd.concat([load_selections("study_results/sel_v8_M5.pkl")] + [load_selections(f"study_results/sel_v7_{tf}.pkl") for tf in ("M10", "M15", "M30", "H1")],
                ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
rows = []
for name, v in V.items():
    over, sp, bed = v[0], v[1], v[2]
    flt = v[3] if len(v) > 3 else FLT
    t = TraderConfig().override(BASE + ("," + over if over else "")); t.trade_filter = flt
    s = PortfolioSimulator(m1, sel, t, spec_override(SymbolSpec(), sp), be_delay_bars=bed, start="2026-03-01").run().summary()
    rows.append({"name": name, **{k: s.get(k) for k in ("trades", "win_%", "profit_factor", "avg_R", "total_R", "return_%", "max_dd_%", "sharpe_daily")}})
    print(f"{name:<20} trades {s['trades']:4d} PF {s['profit_factor']:5.2f} R/tr {s['avg_R']:+.3f} ret {s['return_%']:+6.1f}% DD {s['max_dd_%']:6.1f}%", flush=True)
pd.DataFrame(rows).to_csv("study_results/trader_v8_stress.csv", index=False)
