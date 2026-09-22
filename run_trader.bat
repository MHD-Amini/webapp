@echo off
REM LU-POI TRADER v14 - live MT5 bot.  v14-A (study_results/MARTINGALE_V14.md) = v13-A + ASYMMETRIC MARTINGALE SIZING:
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
  python trader.py --symbol XAUUSD.t --risk 1.0 --min-quality 0.50 --commission 7 --timeframes M5,M10,M15,M30,H1 --trader "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1,regime_metric=adr_ratio,regime_threshold=1.0,regime_short=5,regime_long=20,range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1,range_sl_after_leg=0|0.3|x|x,mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf,mart_tfs=M10|M15|M30|H1,mart_sides=buy,mart_ungated_scale=0.5" --trade-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.57/M15:min_quality=0.60/M30|H1:min_quality=0.57" --confluence-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/M15:min_quality=0.60/M30|H1:min_quality=0.57" --state trader_state.json --log trader.log
) ELSE (
  python trader.py %*
)
pause
