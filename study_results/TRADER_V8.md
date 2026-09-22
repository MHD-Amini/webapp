# TRADER v8 — making the M5 trades good again (M5 trade filter)

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

| rule set | plans | kept % | R/trade | win % | SL % | R train | R val | +months (of 14) |
|---|---|---|---|---|---|---|---|---|
| cost0.08_q0.55_no_nypm_buys | 277 | 12.00 | 0.09 | 75.80 | 24.20 | 0.08 | 0.11 | 8 |
| cost0.06_q0.55_no_nypm | 348 | 15.10 | 0.09 | 76.40 | 23.60 | 0.09 | 0.09 | 9 |
| cost0.06_q0.55_buys | 245 | 10.70 | 0.08 | 73.90 | 26.10 | 0.11 | 0.05 | 7 |
| cost0.08_q0.6 | 407 | 17.70 | 0.08 | 75.90 | 24.10 | 0.13 | -0.01 | 11 |
| cost0.08_q0.55_no_nypm | 503 | 21.90 | 0.07 | 75.10 | 24.90 | 0.06 | 0.08 | 10 |
| cost0.1_q0.6 | 467 | 20.30 | 0.06 | 74.90 | 25.10 | 0.10 | -0.01 | 9 |
| cost0.06_buys | 286 | 12.40 | 0.06 | 72.40 | 27.60 | 0.12 | -0.01 | 8 |
| cost0.08_q0.55_buys | 365 | 15.90 | 0.06 | 73.40 | 26.60 | 0.07 | 0.04 | 8 |
| cost0.06_q0.6 | 303 | 13.20 | 0.05 | 73.30 | 26.70 | 0.08 | 0.02 | 8 |
| q0.6 | 684 | 29.70 | 0.05 | 74.00 | 25.70 | 0.07 | -0.01 | 8 |
| cost0.06_no_nypm | 443 | 19.30 | 0.05 | 73.60 | 26.40 | 0.05 | 0.04 | 9 |
| cost0.1_q0.55_no_nypm | 597 | 26.00 | 0.04 | 72.90 | 27.10 | 0.03 | 0.05 | 7 |

`cost0.08_q0.55_no_nypm` was chosen: positive in both train and val, > 200 plans, 10/14 positive months, and the loosest
of the stable sets (the tighter `cost0.06` / `buys` variants keep too few trades).  Long-only variants are *not* used:
sells were negative in every period, but restricting a strategy to one side is a regime bet.

## 3. Out-of-sample result (Mar–Sep 2026)

| configuration | trades | win % | PF | R/trade | return % | max DD % | Mar–May % | Jun–Sep % | +months |
|---|---|---|---|---|---|---|---|---|---|
| v7_base | 395 | 71.40 | 0.85 | -0.04 | -16.59 | -25.96 | 3.42 | -18.12 | 2/7 |
| v7_q060 | 98 | 80.60 | 1.27 | 0.06 | 5.13 | -5.25 | 5.55 | 0.03 | 6/7 |
| v7_noM5 | 181 | 73.50 | 1.02 | 0.01 | 1.21 | -5.86 | 4.01 | -0.64 | 2/7 |
| v8_M5only | 98 | 80.60 | 1.49 | 0.10 | 10.11 | -4.18 | 11.61 | -1.55 | 4/7 |
| v8_all | 250 | 75.60 | 1.08 | 0.02 | 5.48 | -8.66 | 10.26 | -4.08 | 4/7 |
| v8_all_q060 | 85 | 81.20 | 1.38 | 0.07 | 6.09 | -2.78 | 3.86 | 2.15 | 6/7 |
| v8_all_others_q060 | 131 | 80.90 | 1.46 | 0.10 | 12.32 | -3.17 | 10.38 | 2.16 | 5/7 |

* `v7_base` = the v7 report (all TFs, no filter).  `v7_q060` = the user's workaround.  `v7_noM5` = drop M5.
* **`v8_M5only`: M5 alone goes from −15.2 % (280 trades, PF 0.82) to +10.1 % (98 trades, PF 1.49, max DD 4.2 %).**
* **`v8_all_others_q060` (recommended): +12.3 %, PF 1.46, 131 trades, max DD 3.2 %, Sharpe 2.35, 5/7 positive months.**
  M5 contributes +9.8 R of the +12.8 R — the 5-minute trades are now the main profit source instead of the main loss.
* Honest reading: the second half (Jun–Sep) is much weaker (+2.2 %) than the first (+10.4 %); July was negative for every
  configuration.  Six months / 131 trades is a short sample; the M5 edge after costs is ~0.10 R per trade.

OOS grid of single rules on M5 alone (`study_results/filter_study_oos.csv`, top 8 by total R) — the cost cap alone is not
enough (+3 % at 0.05, ≈0 at 0.08), the quality threshold alone gives +6–7 %, the combination gives +10–15 %:

| rule set | trades | win % | PF | R/trade | return % | max DD % |
|---|---|---|---|---|---|---|
| cost0.08_q0.55_buys | 85 | 84.70 | 2.10 | 0.18 | 15.62 | -3.14 |
| cost0.06_q0.55_buys | 69 | 85.50 | 2.36 | 0.21 | 14.77 | -2.18 |
| buys | 161 | 77.60 | 1.36 | 0.09 | 13.90 | -5.55 |
| cost0.1_q0.55_buys | 97 | 83.50 | 1.78 | 0.14 | 13.77 | -3.45 |
| cost0.08_q0.55 | 121 | 80.20 | 1.46 | 0.10 | 12.13 | -5.02 |
| cost0.08_q0.55_no_nypm_buys | 69 | 84.10 | 2.01 | 0.17 | 11.73 | -2.18 |
| cost0.1_buys | 137 | 79.60 | 1.39 | 0.08 | 11.48 | -3.65 |
| cost0.06_q0.55 | 100 | 80.00 | 1.50 | 0.11 | 10.76 | -4.74 |

## 4. Stress tests of the recommended configuration (OOS)

| variant | trades | win % | PF | R/trade | return % | max DD % |
|---|---|---|---|---|---|---|
| recommended | 131 | 80.90 | 1.46 | 0.10 | 12.32 | -3.17 |
| spread_x1.5 | 113 | 78.80 | 1.39 | 0.09 | 9.77 | -3.83 |
| spread_x2 | 84 | 79.80 | 1.41 | 0.09 | 6.91 | -3.16 |
| slippage_x3 | 131 | 80.90 | 1.39 | 0.09 | 10.65 | -3.72 |
| worst_intrabar | 131 | 80.90 | 1.49 | 0.10 | 13.25 | -2.85 |
| be_delay_2min | 131 | 80.90 | 1.48 | 0.10 | 12.96 | -3.02 |
| netting | 132 | 80.30 | 1.46 | 0.10 | 12.54 | -3.21 |
| risk_0.5 | 126 | 81.00 | 1.53 | 0.10 | 6.21 | -1.39 |
| commission_x2 | 122 | 80.30 | 1.42 | 0.09 | 10.88 | -3.96 |
| no_costs | 160 | 78.80 | 1.37 | 0.08 | 13.34 | -4.44 |
| M5_cost0.06 | 117 | 80.30 | 1.42 | 0.10 | 10.42 | -4.21 |
| M5_cost0.10 | 144 | 79.20 | 1.27 | 0.06 | 8.57 | -5.11 |
| M5_no_session_rule | 151 | 80.10 | 1.40 | 0.09 | 12.96 | -3.85 |
| M5_q0.60 | 85 | 81.20 | 1.38 | 0.07 | 6.09 | -2.78 |

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
