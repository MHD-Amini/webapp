@echo off
REM LU-POI TRADER v16b - live MT5 bot.  v16b-A (study_results/LESS_LOSS_V16B.md) = v16-A + TWO LOSS-REDUCTION LEVERS (fewer stop-outs, fewer $ lost,
REM   MORE profit): the v16b diagnosis of the 114 stop-outs of v16-A found two loss slices computable before the fill:
REM   (1) min_fill_age_min=2 = IMPULSIVE-ARRIVAL GUARD: a pending order that fills < 2 min after it was placed (price was already running into
REM       the zone when the scanner showed it: 39 %% stop rate, -2 k$/year) is NOT traded.  The simulator cancels the order before the fill; a
REM       broker fills a limit order itself, so the live bot closes a position it sees opened < 2 min after placement AT MARKET (cost = one
REM       spread; ~15 cases a year) - fast_fill_mode=cancel.  Decided once per plan, logged 'FAST FILL'.
REM   (2) regime_side_scale=range:sell:0.5 = SELLS placed while the daily regime is 'range' (adr_ratio < 1.0, the v13 regime already live) are
REM       sized at HALF risk (range-regime sells: 75 tr, 36 %% stop, -1.8 k$/year; 43 %% stop on the OOS half).  Buys and trend-regime sells untouched.
REM   Full year Sep25-Sep26 (FINAL_BACKTEST_V16B.md): 446 trades (-21), net +33 831 $ (+12.1 %% vs +30 175), max DD 5.55 %% (5.82), PF 3.00 (2.37),
REM   win 75.8 %%, stop-outs 23.8 %% (24.4), gross $ lost -16 921 (-22 102 = -23 %%), worst day -2.34 %% (-2.64), OOS net +23 958 $ (+19 661),
REM   OOS PF 3.12 (2.25), OOS stop-outs 21.1 %% (23.9), 13/13 months positive.  Stress x6: profit held 6/6, OOS held 6/6, less loss 5/6.
REM   v16b-B (most $ saved: gross loss -15 081 = -32 %%, PF 3.09, 400 tr, +31 446 $, but worst day -2.89): add trend_sma=20,trend_sides=sell,
REM     trend_regime=range (skip counter-trend sells in a range), min_fill_age_min=3,fast_fill_tfs=M5|M10, regime_side_scale=range:sell:0.25.
REM   v16b-C (most $ earned: 445 tr, +35 754 $, DD 5.78, gl -19 488, wd -2.33): min_fill_age_min=2 + trend_sma=10,trend_sides=sell,trend_mode=scale,
REM     trend_risk_scale=0.5,trend_tfs=M15|M20|M30|H1 (counter-trend sells on M15+ at half size) and drop regime_side_scale.
REM   Single lever (F2 alone: 447 tr, +33 089 $, gl -20 036, DD 5.57): drop regime_side_scale.   v16-A: drop min_fill_age_min and regime_side_scale.
REM v16b study: study_results/v16b_levers/C_F2+RS_0.5.json
REM Previous layer (v16-A, study_results/MORE_TRADES_V16.md) = v15-A + NEW TRADE SOURCE: the M20 TIMEFRAME, CONFLUENT ONLY:
REM   --timeframes adds M20 (derived from M1 like every other timeframe; same quality model, tf_minutes is a model feature).  Its PLAIN bar is
REM   unreachable (--trade-filter M20:min_quality=0.99) and its CONFLUENCE bar is 0.63 (--confluence-filter M20:min_quality=0.63): an M20 zone
REM   is traded ONLY when a plan of ANOTHER timeframe on the same level is active or remembered (v15 memory 240 min) AND its quality >= 0.63;
REM   tf_risk_scale=M20:0.4 sizes every M20 plan at 40 %% of the normal risk (the worst-day band is what binds); M20 joins keep_replaced_tfs
REM   and mart_tfs like the other higher timeframes.  Rank-2 scanner zones (the other v16 idea) are NOT shipped: they lose at every bar.
REM   Full year Sep25-Sep26: 467 trades (+19), net +30 175 $ (vs +29 745), max DD 5.82 %% (=), PF 2.365, win 75.2 %%, stop-outs 24.4 %%,
REM   worst day -2.64 %%, OOS net +19 661 $ (vs +19 264), OOS PF 2.25, 13/13 months; 21 M20 trades, 86 %% win, +1 052 $.
REM   Stress x6 (spread x2, commission x2, slip x3, worst intrabar, risk 0.5, risk 2): more trades AND more $ than v15-A in 6/6, OOS 6/6.
REM   v16-B (most $, worst day / OOS PF 0.02-0.15 pt outside the band): M20 confluence bar 0.60, tf_risk_scale=M20:0.6 and add
REM     max_rank=2,rank2_filter=M5|M10|M15|M20|M30|H1:min_quality=0.99 (keep-demoted orders) -> 509 tr, +36 670 $, DD 5.60, wd -2.94.
REM   v16-C (loss profile untouched on the OOS half): tf_risk_scale=M20:0.3 (465 tr, +29 974 $, wd -2.45).
REM   v15-A: drop M20 from --timeframes / both filters / keep_replaced_tfs / mart_tfs and drop tf_risk_scale.
REM v16 study: study_results/v16_levers/M20SC_0.63_x0.4.json
REM Previous layer (v15-A, study_results/MORE_TRADES_V15.md) = v14-A + CONFLUENCE MEMORY + CONVICTION SIZING:
REM   confluence_memory_min=240: a zone also counts as CONFLUENT (judged by --confluence-filter, M10 quality 0.50) when a plan of ANOTHER
REM   timeframe on the same level was active (order or position, same side) within the last 240 minutes, not only right now -> more trades.
REM   confluent_risk_scale=1.25 / plain_risk_scale=0.9: confluent plans (win 82 %%, stop 18 %%) are sized x1.25, plain plans x0.9.
REM   Full year Sep25-Sep26: 448 trades (+18), +297 %% (net +29 745 $ vs +22 753), max DD 5.82 %%, PF 2.38, win 74.8 %%, stop-outs 24.8 %%,
REM   worst day -2.42 %%, OOS net +19 264 $ (vs +14 524), OOS PF 2.26, 13/13 months positive.  The memory is persisted in trader_state.json.
REM   v15-B (most trades): add tier_filter=M10:min_quality=0.55,tier_risk_scale=0.5 (477 tr, +32 637 $, DD 6.08).
REM   v15-C (loss profile untouched): confluence_memory_min=960 alone, drop the two *_risk_scale keys (459 tr, +24 619 $).
REM   v14-A: drop confluence_memory_min / confluent_risk_scale / plain_risk_scale.
REM Previous layer (v14-A, study_results/MARTINGALE_V14.md) = v13-A + ASYMMETRIC MARTINGALE SIZING:
REM   one loss streak PER TIMEFRAME (mart_scope=tf): a LOSING plan (r_net <= -0.2 R; break-even exits are neutral) re-sizes the NEXT plans of
REM   the SAME timeframe until a win of that timeframe resets its streak: M10/M15/M30/H1 BUY plans (the slices whose post-loss edge is positive)
REM   are stepped UP x1.5 per consecutive loss (max 3 steps, max 3 %% of equity); every other plan of a timeframe in a streak (all M5 plans,
REM   sells) is stepped DOWN to HALF size (mart_ungated_scale=0.5).
REM   Full year Sep25-Sep26: 430 trades, +227.5 %%, max DD 5.84 %%, PF 2.25, OOS PF 2.15, $ lost -18 220 (v13-A -18 711), 13/13 months positive.
REM   The streak state is rebuilt from the closed-plan list in trader_state.json on every start (a restart cannot lose or double a streak).
REM   v14-B (the loss cutter, -12.7 %% $ lost, DD 4.78): mart_mode=fib,mart_scope=all instead of mult/tf.   v14-C (fewest rules, pure step-down):
REM   mart_mode=mult,mart_mult=1.0,mart_tfs=M10|M15|M30|H1,mart_ungated_scale=0.5.   v13-A: drop every mart_* key.
REM Previous layer (v13-A):  v13-A (study_results/WEAK_MONTHS_V13.md) = v12-A + REGIME-ADAPTIVE MANAGEMENT:
REM   regime_metric=adr_ratio: mean daily range of the last 5 CLOSED server days / last 20 days.  < 1.0 (volatility contracting = "range")
REM   -> plans placed in a range use the TIGHT ladder 25%% each at +0.5R / +1.0R / +1.5R / +2.5R with SL -> break-even after leg 1 and
REM   SL -> +0.3R after leg 2 (range_sl_after_leg=0|0.3|x|x); otherwise ("trend") the v10 G ladder +0.6R / +1.2R / +2.4R / +4.8R, BE after leg 1.
REM   Full year Sep25-Sep26: 430 trades, +188.7 %%, max DD 5.45 %%, PF 2.01, win 75 %%, worst day -2.28 %%, 13/13 months positive
REM   (v12-A: 427 / +179.5 %% / 5.28 %% / 1.87 / 72.6 %% / -2.65 %% / 12 of 13 months, Apr 2026 -$132 -> now +$343).
REM Everything else = v12-A: replaced pending orders kept 1 bar (M10/M15/M30/H1), confluence zones judged by --confluence-filter (M10
REM quality 0.50) and traded on both timeframes (dedupe_cross_tf=false), plain M10 quality 0.57, M30/H1 0.57, v8 M5 filter; account
REM protection: daily loss 4.5%% -> flat until next server day, total loss 9%% -> HALT (--max-daily-loss / --max-total-loss, 0 = off).
REM Hedging account required for the ladder (netting -> two-leg fallback).
REM Windows: open + log in your MT5 terminal FIRST, then double-click this file.   First run: pip install -r requirements.txt && pip install MetaTrader5
REM v13-C (fewest new rules): drop range_sl_after_leg=0|0.3|x|x.   v12-A (no regime switch): drop every regime_*/range_* key.
cd /d "%~dp0"
IF "%1"=="" (
  python trader.py --symbol XAUUSD.t --risk 1.0 --min-quality 0.50 --commission 7 --timeframes M5,M10,M15,M20,M30,H1 --trader "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M20|M30|H1,regime_metric=adr_ratio,regime_threshold=1.0,regime_short=5,regime_long=20,range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1,range_sl_after_leg=0|0.3|x|x,mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf,mart_tfs=M10|M15|M20|M30|H1,mart_sides=buy,mart_ungated_scale=0.5,confluence_memory_min=240,confluent_risk_scale=1.25,plain_risk_scale=0.9,tf_risk_scale=M20:0.4,min_fill_age_min=2,regime_side_scale=range:sell:0.5" --trade-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.57/M15:min_quality=0.60/M30|H1:min_quality=0.57/M20:min_quality=0.99" --confluence-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/M15:min_quality=0.60/M30|H1:min_quality=0.57/M20:min_quality=0.63" --state trader_state.json --log trader.log
) ELSE (
  python trader.py %*
)
pause
