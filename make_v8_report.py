#!/usr/bin/env python3
"""v8 step 6 - write study_results/TRADER_V8.md from the saved study CSVs (re-runnable)."""
import pandas as pd

c = pd.read_csv("study_results/trader_v8_compare.csv")
st = pd.read_csv("study_results/trader_v8_stress.csv")
oos = pd.read_csv("study_results/filter_study_oos.csv")
ins = pd.read_csv("study_results/filter_grid_insample_labels.csv")


def tbl(df, cols, names=None):
    names = names or cols
    out = "| " + " | ".join(names) + " |\n|" + "---|" * len(cols) + "\n"
    for _, r in df.iterrows():
        cells = []
        for col in cols:
            v = r[col]
            cells.append(f"{v:.2f}" if isinstance(v, float) and col not in ("trades", "n") else str(v))
        out += "| " + " | ".join(cells) + " |\n"
    return out


c2 = c[["name", "trades", "win_%", "profit_factor", "avg_R", "return_%", "max_dd_%", "H1_return_%", "H2_return_%", "months_pos"]].copy()
c2["months_pos"] = c2.months_pos.astype(int).astype(str) + "/7"
ins2 = ins[["name", "n", "keep_%", "avg_r", "win_%", "sl_%", "train_avg_r", "val_avg_r", "months_pos"]].head(12).copy()
oos2 = oos.sort_values("total_R", ascending=False)[["name", "trades", "win_%", "profit_factor", "avg_R", "return_%", "max_dd_%"]]

md = f"""# TRADER v8 — making the M5 trades good again (M5 trade filter)

Out-of-sample **2026-03-02 → 2026-09-04**, $10 000, 1 % risk per trade, split legs, real costs (spread per minute — imputed
where the export has none —, $7/lot commission, $0.10 stop slippage, swaps).  Quality model trained before 2026-03-01
(`models/quality_model_trainonly.json`).  All numbers from `lubot/portfolio_sim.py` (M1 precision).

## 1. Why the M5 trades lost money (v7)

* The M5 zone is small (median $6.3 for the bot's picks, $1.5 for all candidates) so **spread + commission = 0.07 R per trade**
  on the picks, 0.23 R on the average candidate (`models/plan_labels_M5.pkl`: every training candidate replayed as a v7 plan).
  The v7 edge (+0.013 R gross) is smaller than that cost.
* The quality model predicts P(bounce ≥ 1 ATR) — not the outcome of *this plan* (limit at the near edge, SL = far edge,
  half at +0.4R, TP2 +1.5R).  In-sample bot-like M5 plans: quality 0.50–0.55 → −0.15 R, 0.55–0.60 → −0.10 R, ≥ 0.60 → +0.05 R.
* NY-afternoon selections (13:00–17:00 NY, "nypm") were the worst session in-sample (−0.19 R, n=631).
* A second ML model (LightGBM on plan outcome, 260 features, `train_trade_filter.py`) ranks *all* candidates well
  (OOS AUC 0.72) but that is only the zone-size effect; on the bot's own picks it has **no skill** (val/test AUC 0.50).
  It is kept as an optional gate (`model_path=` in the filter string) but is OFF.

## 2. The v8 filter (`lubot/trade_filter.py`)

Per-timeframe, interpretable gates evaluated with the live spread, same code in the backtest and in `trader.py`:

```
--trader "trade_filter=M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"
```

* `max_cost_r=0.08` — (spread + commission per oz) / 1R ≤ 8 % → drops thin zones (in-sample: kept 38 % of M5 picks)
* `min_quality=0.55` on M5 (the quality model's own score)
* `sessions=…` — no new M5 orders from selections made 13:00–17:00 New York
* other timeframes: `min_quality=0.60` (the user's v7 finding, confirmed)

**Rule choice was made in-sample only** (Jan 2025 – Feb 2026, `insample_filter_grid.py` on the plan labels; train < Dec 2025,
val Dec 2025 – Feb 2026), then verified OOS with the portfolio simulator.  Top of the in-sample grid (bot-like M5 plans):

{tbl(ins2, ["name", "n", "keep_%", "avg_r", "win_%", "sl_%", "train_avg_r", "val_avg_r", "months_pos"],
     ["rule set", "plans", "kept %", "R/trade", "win %", "SL %", "R train", "R val", "+months (of 14)"])}
`cost0.08_q0.55_no_nypm` was chosen: positive in both train and val, > 200 plans, 10/14 positive months, and the loosest
of the stable sets (the tighter `cost0.06` / `buys` variants keep too few trades).  Long-only variants are *not* used:
sells were negative in every period, but restricting a strategy to one side is a regime bet.

## 3. Out-of-sample result (Mar–Sep 2026)

{tbl(c2, ["name", "trades", "win_%", "profit_factor", "avg_R", "return_%", "max_dd_%", "H1_return_%", "H2_return_%", "months_pos"],
     ["configuration", "trades", "win %", "PF", "R/trade", "return %", "max DD %", "Mar–May %", "Jun–Sep %", "+months"])}
* `v7_base` = the v7 report (all TFs, no filter).  `v7_q060` = the user's workaround.  `v7_noM5` = drop M5.
* **`v8_M5only`: M5 alone goes from −15.2 % (280 trades, PF 0.82) to +10.1 % (98 trades, PF 1.49, max DD 4.2 %).**
* **`v8_all_others_q060` (recommended): +12.3 %, PF 1.46, 131 trades, max DD 3.2 %, Sharpe 2.35, 5/7 positive months.**
  M5 contributes +9.8 R of the +12.8 R — the 5-minute trades are now the main profit source instead of the main loss.
* Honest reading: the second half (Jun–Sep) is much weaker (+2.2 %) than the first (+10.4 %); July was negative for every
  configuration.  Six months / 131 trades is a short sample; the M5 edge after costs is ~0.10 R per trade.

OOS grid of single rules on M5 alone (`study_results/filter_study_oos.csv`, top 8 by total R) — the cost cap alone is not
enough (+3 % at 0.05, ≈0 at 0.08), the quality threshold alone gives +6–7 %, the combination gives +10–15 %:

{tbl(oos2.head(8), ["name", "trades", "win_%", "profit_factor", "avg_R", "return_%", "max_dd_%"],
     ["rule set", "trades", "win %", "PF", "R/trade", "return %", "max DD %"])}
## 4. Stress tests of the recommended configuration (OOS)

{tbl(st, ["name", "trades", "win_%", "profit_factor", "avg_R", "return_%", "max_dd_%"],
     ["variant", "trades", "win %", "PF", "R/trade", "return %", "max DD %"])}
The result survives 2× spread (+6.9 %), 3× slippage (+10.7 %), worst-case intrabar path (+13.2 %), a 2-minute BE delay,
netting accounts, double commission.  Cost caps 0.06–0.10 and dropping the session rule all stay positive (+8.6 … +13 %).

## 5. Files

* `lubot/trade_filter.py` — the filter; `TraderConfig.trade_filter`; gates in `lubot/portfolio_sim.py` and `trader.py`
* `lubot/plan_replay.py`, `label_plan_outcomes.py` — plan-outcome labels (`models/plan_labels_<TF>.pkl`), parity-tested
* `experiments_m5_filter.py`, `insample_filter_grid.py` — in-sample diagnostics and rule selection
* `train_trade_filter.py` — optional ML gate (`models/trade_filter_M5_trainonly.json`), not used by default
* `record_selections.py --with-features`, `run_v8_record.sh` — chunked, resumable M5 stream with features (`study_results/sel_v8_M5.pkl`)
* `run_filter_study.py`, `run_v8_compare.py`, `run_v8_stress.py`, `make_v8_report.py` — the studies above; results
  `study_results/trader_v8_*`, chart `study_results/charts/trader_v8_equity.png`
"""
open("study_results/TRADER_V8.md", "w").write(md)
print("written study_results/TRADER_V8.md", len(md), "chars")
