# LU-POI TRADER — Liquidity University POI trading bot for XAUUSD.t (MT5)   *(v16b)*

**v7 turns the POI scanner into a trading bot.**  For every POI the scanner shows (M5 / M10 / M15 / M30 / H1) the
bot places a **limit order at the start of the zone** with the **stop at the end of the zone**, closes **50 % at
+0.4R and moves the stop to break-even**, and lets the rest run to **TP2 = +1.5R**.  It attaches to the MT5
terminal that is already open and logged in on your Windows PC — **no login option, no credentials in the bot**.

| what | command |
|---|---|
| **Live trading** (Windows, MT5 open) | `run_trader.bat`  or  `python trader.py --symbol XAUUSD.t --risk 1.0 --min-quality 0.50 --commission 7 --timeframes M5,M10,M15,M20,M30,H1 --trader "tp_levels=0.6\|1.2\|2.4\|4.8,tp_fracs=1\|1\|1\|1,ladder_fallback=merge,dedupe_cross_tf=false,keep_replaced_bars=1,keep_replaced_tfs=M10\|M15\|M20\|M30\|H1,regime_metric=adr_ratio,regime_threshold=1.0,regime_short=5,regime_long=20,range_tp_levels=0.5\|1.0\|1.5\|2.5,range_tp_fracs=1\|1\|1\|1,range_sl_after_leg=0\|0.3\|x\|x,mart_mode=mult,mart_mult=1.5,mart_max_steps=3,mart_max_risk_pct=3,mart_scope=tf,mart_tfs=M10\|M15\|M20\|M30\|H1,mart_sides=buy,mart_ungated_scale=0.5,confluence_memory_min=240,confluent_risk_scale=1.25,plain_risk_scale=0.9,tf_risk_scale=M20:0.4,min_fill_age_min=2,regime_side_scale=range:sell:0.5" --trade-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia\|london\|preny\|ny\|lclose/M10:min_quality=0.57/M15:min_quality=0.60/M30\|H1:min_quality=0.57/M20:min_quality=0.99" --confluence-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia\|london\|preny\|ny\|lclose/M10:min_quality=0.50/M15:min_quality=0.60/M30\|H1:min_quality=0.57/M20:min_quality=0.63" --state trader_state.json --log trader.log` |
| **FINAL BACKTEST of v16b-A on the CSV** (strings read from `run_trader.bat`, v16-A alongside) | `python backtest_v16b_final.py --csv data/xauusd_m1.csv --study "study_results/v16b_levers/C_F2+RS_0.5.json"` (or `bash run_v16b_final.sh`) → **`study_results/FINAL_BACKTEST_V16B.md`** + `final_v16b/*` + `charts/final_v16b_equity.png` |
| **v16b loss-reduction study** (diagnosis of the stop-outs, 96 variants, stress ×6, walk-forward) | `python run_v16b_diag.py; bash run_v16b_all.sh; bash run_v16b_stress.sh "<finalists>"; python judge_v16b_stress.py; python walkforward_v16b.py; bash run_v16b_final.sh; python make_v16b_report.py; python verify_bat_v16b.py` (resumable, autosave) → **`study_results/LESS_LOSS_V16B.md`** |
| **FINAL BACKTEST of v16-A on the CSV** (strings read from `run_trader.bat`, v15-A alongside) | `python backtest_v16_final.py --csv data/xauusd_m1.csv --study study_results/v16_levers/M20SC_0.63_x0.4.json` → **`study_results/FINAL_BACKTEST_V16.md`** + `final_v16/*` + `charts/final_v16_equity.png` |
| **v16 new-trade-sources study** (top-3 recorder incl. M20, 171 variants, stress ×6, walk-forward) | `bash run_v16_record.sh; bash run_v16_all.sh; bash run_v16_stress.sh; python walkforward_v16.py; python backtest_v16_final.py; python make_v16_report.py; python verify_bat_v16.py` (resumable, autosave) → **`study_results/MORE_TRADES_V16.md`** |
| **FINAL BACKTEST of v15-A on the CSV** (strings read from `run_trader.bat`, v14-A alongside) | `python backtest_v15_final.py --csv data/xauusd_m1.csv` → **`study_results/FINAL_BACKTEST_V15.md`** + `final_v15/*` + `charts/final_v15_equity.png` |
| **v15 more-trades / more-profit study** (diagnosis, 209 variants, stress ×6, walk-forward) | `python run_v15_diag.py; bash run_v15_all.sh; python run_v15_levers.py --stress ...; python walkforward_v15.py; python backtest_v15_final.py; python make_v15_report.py; python verify_bat_v15.py` (resumable, autosave) → **`study_results/MORE_TRADES_V15.md`** |
| **FINAL BACKTEST of v14-A on the CSV** (strings read from `run_trader.bat`, v13-A alongside) | `python backtest_v14_final.py --csv data/xauusd_m1.csv` → **`study_results/FINAL_BACKTEST_V14.md`** + `final_v14/*` + `charts/final_v14_equity.png` |
| **v14 martingale study** (diagnosis, 140 variants, stress ×6, shuffle/bootstrap, walk-forward) | `python run_v14_diag.py; python run_v14_levers.py; python run_v14_levers.py --stress ...; python shuffle_v14.py; python walkforward_v14.py; python make_v14_report.py; python verify_bat_v14.py` (resumable) → **`study_results/MARTINGALE_V14.md`** |
| **v13 weak-months study** (diagnosis, 177 variants, stress, walk-forward, neighbourhood) | `python run_v13_diag.py; bash run_v13_all.sh; bash run_v13_stage4.sh; bash run_v13_neigh.sh; python walkforward_v13.py; python make_v13_report.py; python verify_bat_v13.py` (resumable) → **`study_results/WEAK_MONTHS_V13.md`** |
| **v12 more-trades study, round 2** (funnel, 212 variants, stress, walk-forward) | `python run_v12_funnel.py; bash run_v12_all.sh; bash run_v12_stage4.sh; python rank_v12.py; python make_v12_report.py` (resumable) → **`study_results/MORE_TRADES_V12.md`** |
| **v11 more-trades study** (funnel, 159 variants, stress) | `python run_v11_funnel.py; bash run_v11_all.sh; python run_v11_combos.py --stress ...; python make_v11_report.py` (resumable) → **`study_results/MORE_TRADES_STUDY.md`** |
| **v10 multi-TP study + full-year backtest** (887 exit systems, Sep 2025 → Sep 2026) | `bash run_v10_record.sh; bash run_v10_all.sh` (resumable) → **`study_results/MULTI_TP_STUDY.md`** |
| **v9 risk-management study** (580 exit systems, OOS + in-sample + stress) | `bash run_v9_all.sh` (resumable) → **`study_results/RISK_MGMT_STUDY.md`** |
| Dry run (prints the orders it would send) | `run_trader_dryrun.bat`  or  `python trader.py --dry-run --once` |
| **Realistic portfolio backtest** | `python backtest_trader.py --csv data.csv --sel "study_results/sel_v*_*.pkl" --trader "trade_filter=..."` (after `bash run_v7_record.sh` / `bash run_v8_record.sh`) |
| **v8 M5-filter study** (in-sample choice, OOS check, stress) | `python insample_filter_grid.py; python run_v8_compare.py --filter ...; python run_v8_stress.py; python make_v8_report.py` → `study_results/TRADER_V8.md` |
| Full sensitivity study + report | `python run_trader_study.py --csv data.csv` → `study_results/TRADER_BACKTEST.md` |
| POI scanner only (v6) | `python bot.py scan --csv data.csv` / `python bot.py live` |

→ **Results: section 0j (v16b LESS LOSS: fast-fill guard + range sells at half size + FINAL BACKTEST), 0i (v16 new trade sources: M20 confluent-only + FINAL BACKTEST), 0h (v15 confluence memory + conviction sizing), 0g (v14 asymmetric martingale + FINAL BACKTEST), 0f (v13 weak months / regime-adaptive management), 0e (v12 more trades round 2), 0d (v11 more trades), 0c (v10 multi-TP + full year + loss rules), 0b (v9 management), 0a/0 below, `study_results/MULTI_TP_STUDY.md` (v10), `study_results/RISK_MGMT_STUDY.md` (v9), `TRADER_V8.md` (v8), `TRADER_BACKTEST.md` (v7).**

---

## 0j. v16b — REDUCE THE LOSS PERCENTAGE while MAINTAINING THE PROFITABILITY PERCENTAGE; FINAL BACKTEST

**Spec.**  Find a way for the v16 bot (`run_trader.bat` = v16-A) to reduce the loss percentage while maintaining the profitability percentage; save after every
step (recoverable).  "Loss percentage" was read as the stop-out rate AND the max drawdown AND the $ lost - all three must fall; "profitability" as the net $,
the profit factor and the OOS net - held within 3 % / 0.05 PF.  Judge: `v16b_common.judge16b` (less_loss / hold_profit / hold_oos / no_worse_day, score 0-4).

**Diagnosis** (`run_v16b_diag.py` → `study_results/v16b_diag/DIAG.md`, 37 tables on the 114 stop-outs of v16-A).  The losses sit in three slices, all visible
BEFORE the fill: (1) **sells** stop out 32.7 % vs buys 20.1 % and earn 3.9 k$ of the 30.2 k$; (2) **counter-trend sells** (daily close above SMA10/20): 93-100
trades, 35-39 % stop, ~0 $; **range-regime sells** (the v13 adr_ratio regime): 75 trades, 36 % stop, -1.8 k$ (43 % stop OOS); (3) **impulsive arrivals** -
orders FILLED within 5 min of placement (price already running into the zone when the scanner showed it): 61 trades, 39 % stop, -2.0 k$; range-regime fast
fills 50 % stop, -3.1 k$.  Not levers: quality band, session, kind, timeframe, concurrency, martingale step-down, day clusters.

**Levers** (`TraderConfig`, simulator + `trader.py`, defaults byte-identical: parity 467 / +301.75 / -5.82 exact): `trend_sma` / `trend_sides` / `trend_mode` /
`trend_risk_scale` / `trend_tfs` / `trend_regime` (daily trend gate), `min_fill_age_min` / `fast_fill_mode` / `fast_fill_scale` / `fast_fill_tfs` / `fast_fill_regime`
(impulsive-arrival guard), `regime_side_scale` (regime x side sizing); `be_trigger_r` and `max_daily_loss_pct` re-tested.  Grid: 96 full-year runs (66 singles +
30 combos, `run_v16b_levers.py`, resumable, autosaved to GitHub every 4 min - survived three sandbox resets and two dead chat sessions).  **Ten variants score 4/4**,
three families: the fast-fill guard (F2: -0.9 pt stop, +10 % net, DD 5.57), the SCOPED trend gate on sells (range-only or M15+ at half size) and the range-sell
size as the best combiner.  OUT: a break-even trigger before TP1 (stop rate 16-21 % but -23..-60 % net - the winners' retrace takes them out), tighter day-loss
caps (DD and worst day get WORSE: the flatten locks the loss in), the trend gate on both sides, the unscoped trend skip (-8..-25 % net), scaling fast fills.

**Result — `run_trader.bat` ships v16b-A = v16-A + `min_fill_age_min=2` + `regime_side_scale=range:sell:0.5`.**  (1) a pending order that would fill < 2 min
after placement is cancelled - live, since a broker fills a limit order itself, the bot closes a position it sees opened < 2 min after placement at market
(cost: one spread; 22 cases a year); (2) a SELL placed while the daily regime is "range" is sized at half risk.  FINAL BACKTEST on the CSV
(`backtest_v16b_final.py`, 359 813 M1 bars 2025-09-01 → 2026-09-04, $10 000, 1 % base risk, real costs; the reference = the bat strings minus the two keys):

| | v16-A reference | **v16b-A (shipped)** |
|---|---|---|
| trades | 467 | **446** (-21) |
| **stop-outs %** | 24.4 | **23.8** (-0.6 pt) |
| **gross $ lost** | -22,102 | **-16,921** (-23.4 %) |
| avg loss $ | -191 | **-157** |
| **max drawdown %** | -5.82 | **-5.55** |
| worst day % of equity | -2.64 | **-2.34** |
| net profit $ / return % | +30,175 / +301.75 | **+33,831 / +338.31** (+12.1 %) |
| profit factor | 2.365 | **2.999** |
| win % | 75.2 | **75.8** |
| OOS (Mar-Sep 26) net $ / PF / stop % | +19,661 / 2.25 / 23.9 | **+23,958 / 3.12 / 21.1** |
| months positive | 13/13 | 13/13 |

Every loss metric improves AND every profit metric improves (score 4/4): the removed / shrunk trades were net losers and the freed slots and better equity path
go to the remaining plans.  Stress ×6 (spread ×2, commission ×2, slip ×3, worst intrabar, risk 0.5 / 2 %, each judged against the v16-A row of the same
scenario): profit held 6/6, OOS held 6/6, less loss 5/6 (slip ×3 DD 5.98 vs 5.82), worst day in band 5/6 (risk 0.5: -2.16 vs -1.90, 0.01 pt beyond).  Walk-forward
(split 2026-03-01): the OOS half passes every band; the IS half holds the profit but the loss slices earn a little there (they are an OOS-heavy phenomenon),
IS→OOS Spearman of the $-lost deltas over 95 variants 0.77.  Alternatives documented in the bat: **v16b-B** (most $ saved: + range counter-trend sells skipped
SMA20, F3 on M5|M10, range sells x0.25 → 400 tr, +31 446 $, $ lost -15 081 = -32 %, PF 3.09, but worst day -2.89), **v16b-C** (most $ earned: F2 + counter-trend
sells on M15+ at half size → 445 tr, +35 754 $, $ lost -19 488), **F2 alone** (447 tr, +33 089 $, $ lost -20 036).  `verify_bat_v16b.py` replays the bat strings:
IDENTICAL to the study json.  Live bot: `trader.py` carries the three levers (`tests/test_trader_v16b.py`, `tests/test_bat_v16b.py`: range sell 0.10 lots next to a
0.20-lot buy, a 1-min fill closed at market, a 3-min fill kept).  175 tests pass.

**Honest reading.**  v16b removes exactly the two loss slices the data points at and nothing else; the gain is real on the whole year and on the OOS half but it
is one year of one instrument, and the levers were chosen on the full year (then stress-tested and walk-forward checked).  Live, the fast-fill guard costs one
spread per guarded fill instead of nothing.  Judge it on the demo account on the same metrics (stop %, $ lost, DD, worst day, PF) before trusting the size.
Details: **`study_results/LESS_LOSS_V16B.md`**, `FINAL_BACKTEST_V16B.md`, `v16b_diag/DIAG.md`, `charts/v16b_*.png`, `charts/final_v16b_equity.png`.

---

## 0i. v16 — new trade sources: the M20 timeframe (confluent only) + ranked zones; FINAL BACKTEST

**Spec.**  Make the v15 bot take more trades and make more profit while maintaining the loss percentage; save after every step (recoverable).

**Why new sources.**  v11 / v12 / v15 had exhausted admission relaxation (quality bars, cost bars, sessions, tiers, re-entry, re-arm, front offset).  The
recorded streams carried ONE zone per side per timeframe - the scanner's slot winner - although 24 % of the set events had >= 2 qualified candidates.  v16
re-recorded the whole year with the **top-3 qualified candidates per slot** (`record_selections_v16.py` → `sel_v16_<TF>.pkl`, `rank` column, rank-1 rows
identical to the v10 streams) and added a **6th timeframe, M20** (derived from M1 like the others; same quality model, `tf_minutes` is a feature → interpolation).

**Levers** (`TraderConfig`, defaults byte-identical to v15, simulator and live bot share the code): `max_rank`, `rank2_filter`, `rank2_risk_scale`, `rank2_tfs`,
`rank2_confluent_only` (ranked zones), `tf_risk_scale=M20:0.4` (per-timeframe size), M20 in `--timeframes` / both filters / `keep_replaced_tfs` / `mart_tfs`.
Grid: 171 full-year runs (`run_v16_levers.py`, resumable, autosaved to GitHub every 4 min — survived nine sandbox resets and one dead chat session).

**What the data says.**  (A) **Rank-2 zones LOSE** at every quality bar (fills win 48-62 %, stop 40-58 %, -0.2..-2.8 k$); rank 3 is worse.  The scanner's
ranking is right.  The only positive part of `max_rank=2` is *keep-demoted* (an order is no longer cancelled when its POI slips to rank 2: +28 trades, +2.9 k$,
but OOS PF 2.13 < band).  (B) **Plain M20 zones lose** (37 % win); **confluent M20 zones** (a plan of another timeframe active or remembered on the level) win
79-90 % and add +2.9..+4.7 k$ at full size - but every M20 leg is one more position on the days when 2-3 confluent plans are stopped within one minute, so
the **worst day** (-3.4..-3.5 % vs the -2.92 band) is what binds.  `tf_risk_scale` brings it back: at x0.4 the worst day is inside the band with the DD unchanged.

**Result — `run_trader.bat` ships v16-A = v15-A + M20 (plain bar 0.99 = never alone, confluence bar 0.63, `tf_risk_scale=M20:0.4`).**  FINAL BACKTEST on
the CSV (`backtest_v16_final.py`, 359 813 M1 bars 2025-09-01 → 2026-09-04, $10 000, 1 % base risk, real costs):

| | v15-A reference | **v16-A (shipped)** |
|---|---|---|
| trades | 448 | **467** (+19; 21 M20 trades, 86 % win, +1 052 $) |
| net profit $ | +29,745 | **+30,175** (+1.4 %) |
| return % | +297.45 | **+301.75** |
| max drawdown % | -5.82 | **-5.82** |
| profit factor | 2.375 | 2.365 |
| win % / stop-outs % | 74.8 / 24.8 | **75.2 / 24.4** |
| worst day % of equity | -2.42 | -2.64 |
| OOS (Mar-Sep 26) net $ / PF / win / stop | +19,264 / 2.26 / 76.3 / 23.7 | **+19,661 / 2.25 / 76.1 / 23.9** |
| months positive | 13/13 | 13/13 |

Stress ×6 (spread ×2, commission ×2, slip ×3, worst intrabar, risk 0.5 / 2 %): more trades AND more $ than v15-A in 6/6, OOS net above with the OOS PF in band
in 6/6, loss bands held in 5/6 (miss: max DD at 0.5 % base risk).  Walk-forward: the extra trades carry over (Spearman +0.95), the extra $ moderately (+0.52);
the OOS half misses only the worst day in R (-3.04 vs -2.10 R: the 2026-04-08 cluster gets the M20 leg as a third stop, -49 $ at x0.4).
Alternatives documented in the bat: **v16-B** (most $: M20 bar 0.60, `tf_risk_scale=M20:0.6`, + keep-demoted `max_rank=2,rank2_filter=...:min_quality=0.99`:
509 trades, +36 670 $, DD 5.60, worst day -2.94, OOS PF 2.19 - the loss bands 0.02-0.15 pt outside) and **v16-C** (`tf_risk_scale=M20:0.3`: 465 trades,
+29 974 $, OOS loss profile untouched).  `verify_bat_v16.py` replays the bat strings: IDENTICAL to the study json.  Live bot: `trader.py` scans M20, gates
M20 by the confluence bar, scales by `tf_risk_scale`; fake-MT5 tests in `tests/test_bat_v16.py`.

**Honest reading.**  v16 is a small, robust gain (+1-4 % at the sizes that keep the worst day inside the band), not a big one: the slot winner IS the best
zone, and a 6th timeframe only adds *confirmation* of the five, which the v15 confluence sizing already prices.  Everything that earns more (bigger M20
size, keep-demoted) adds one more leg to the same clustered stop-outs.  The next real gain needs a better **entry model**, not more sources or admission rules.
Details: **`study_results/MORE_TRADES_V16.md`**, `FINAL_BACKTEST_V16.md`, `charts/v16_*.png`, `charts/final_v16_equity.png`.  157 tests pass.

---

## 0h. v15 — more trades AND more profit at the same loss percentage (confluence memory + conviction sizing) + FINAL BACKTEST

**Spec.**  Make the v14 bot take more trades and make more profit while maintaining the loss percentage; save after every step (recoverable).

**Diagnosis** (`run_v15_diag.py` → `study_results/v15_diag/`).  The trade filter rejects 2 462 unique POIs a year; replaying them shows that **admission
relaxation is exhausted**: only M10 quality 0.50-0.57 carries a thin edge (+0.10 R), every other rejected band loses 0.1-0.4 R per fill.  Re-arming a zone
after a stop (106/107 stops have price through the entry) and entering in front of the zone (-0.04..+0.09 R) are dead.  The one strong, OOS-stable signal
in the traded population: **CONFLUENT plans** (zone overlapping an active plan of another timeframe) win 81.7 % / stop 17.6 % / +0.47 R vs 70.8 % / 28.9 %
/ +0.18 R for the rest (IS 79.5 / OOS 84.0 % win).

**Levers** (`TraderConfig`, defaults byte-identical to v14, simulator and live bot share the code): `confluence_memory_min=N` (a plan of another TF that
left the books within N minutes still counts as confluence → more zones judged by the looser confluence bar; the live bot persists the memory in
`trader_state.json`), `confluent_risk_scale` / `plain_risk_scale` (conviction sizing), `tier_filter` + `tier_risk_scale` (second bar at reduced size),
`mart_confluent_only`.  Grid: 209 full-year runs (`run_v15_levers.py`, resumable, autosaved to GitHub every 4 min — survived three sandbox resets).

**Result — `run_trader.bat` ships v15-A = v14-A + `confluence_memory_min=240,confluent_risk_scale=1.25,plain_risk_scale=0.9`.**  FINAL BACKTEST on the
CSV (`backtest_v15_final.py`, 359 813 M1 bars 2025-09-01 → 2026-09-04, $10 000, 1 % base risk, real costs):

| | v14-A reference | **v15-A (shipped)** |
|---|---|---|
| trades | 430 | **448** (+18) |
| net profit $ | +22,753 | **+29,745** (+31 %) |
| return % | +227.53 | **+297.45** |
| max drawdown % | -5.84 | **-5.82** |
| profit factor | 2.249 | **2.375** |
| win % / stop-outs % | 74.7 / 24.9 | **74.8 / 24.8** |
| worst day % of equity | -1.99 | -2.42 |
| max risk on one plan % eq | 2.24 | 2.81 |
| OOS (Mar-Sep 26) net $ / PF / win / stop | +14,524 / 2.15 / 76.3 / 23.7 | **+19,264 / 2.26 / 76.3 / 23.7** |
| months positive | 13/13 | 13/13 |

Stop-out rate, win rate and max DD unchanged to the decimal; the price is a worst day of -2.42 % (was -1.99) and a larger
max single-plan risk (martingale step × conviction).  Stress ×6: ahead of v14-A on net $ and OOS PF in 6/6 scenarios, DD within +0.5 pt in 5/6 (not at 2 % base
risk); weak point = spread ×2 worst day -4.55 %.  Walk-forward: Spearman IS→OOS of the extra trades +0.90, extra $ +0.84 (population properties).
Alternatives documented in the bat: **v15-B** (+ `tier_filter=M10:min_quality=0.55,tier_risk_scale=0.5`: 477 trades, +32 637 $, DD 6.08) and **v15-C**
(`confluence_memory_min=960` alone: 459 trades, +24 619 $, loss profile byte-for-byte).  `verify_bat_v15.py` replays the bat strings: IDENTICAL to the study json.
Details: **`study_results/MORE_TRADES_V15.md`**, `FINAL_BACKTEST_V15.md`, `charts/v15_*.png`, `charts/final_v15_equity.png`.  140 tests pass.

## 0g. v14 — a martingale that REDUCES the losses (the asymmetric, edge-aware martingale) + FINAL BACKTEST

**Spec.**  Create a Martingale strategy for the v13-A trader that reduces the losses of the trades; be creative; save after every step.

**Diagnosis** (`run_v14_diag.py` → `study_results/v14_diag/`).  A classic martingale cannot reduce losses on this bot.  The 430 trades of the year
contain 106 losers in 76 runs, **max run 3** (never 4) — fewer and shorter than independence predicts — so a step 4+ never fires; and **the trade
after a loss is WEAKER, not stronger**: win 76.5 % / +0.31 R after 0 losses, 68.4 % / +0.13 R after 1, 75 % / +0.09 R after 2.  Per slice the
post-loss edge is NEGATIVE on M5 (−0.02 R, n 43) and on sells (−0.06 R, n 40) and positive on M10/M15/M30/H1 buys (+0.29 R, n 66).  Every
step-up scheme on the same sequence (×2, ×1.5, ×1.25, d'Alembert, Fibonacci, deficit recovery) INCREASES the dollars lost and buys return with
drawdown.  84 % of the losses close with no other position open → the realistic lever is the SIZE OF THE NEXT ORDER.

**Lever** (`lubot/martingale.py` — a `Martingale` state machine; `TraderConfig` keys `mart_mode / mart_mult / mart_max_steps / mart_max_risk_pct /
mart_scope / mart_tfs / mart_sides / mart_min_quality / mart_regime / mart_ungated_scale / mart_loss_r / mart_tp_levels…`, plus a zone-grid family
`grid_add_r / grid_base_frac / grid_add_frac / grid_deep_ladder`; defaults byte-identical, parity 430 / +188.65 / −5.45 exact; 18 new tests).  The
creative part is **asymmetry**: after a loss the next plan is stepped **UP only where the post-loss edge is positive** (HTF buys) and **DOWN to
half size everywhere else** (M5 plans, sells).  A win resets the streak, break-even exits are neutral (`mart_loss_r=0.2`), max risk per plan is
capped at 3 % of equity.  140 full-year variants (`run_v14_levers.py`), stress ×6 on 6 finalists + reference (42 runs), shuffle / block-bootstrap
n = 1000 (`shuffle_v14.py`), walk-forward on the IS/OOS halves (`walkforward_v14.py`).  `run_trader.bat` ships **v14-A**; `verify_bat_v14.py`
replays its exact strings to 430 / +227.53 % / DD −5.84 % / PF 2.249 = the study json.  The live bot rebuilds the streak state from the
`closed` list of `trader_state.json` on every start (realised P&L read from the MT5 deal history), so a restart cannot lose or double a streak.
**131 tests pass.**

**Result** (full year Sep 2025 → Sep 2026, $10 000, 1 % base risk, real costs; OOS = Mar–Sep 2026):

| variant | trades | return | max DD | PF | win | $ lost | avg loss | worst day | max risk | ret/DD | OOS PF | months > 0 | up / down |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v13-A reference (flat 1 %) | 430 | +188.7 % | 5.45 % | 2.008 | 75.3 % | −18 711 | −177 | −2.04 % | 1.02 % | 34.6 | 1.91 | 13 / 13 | 0 / 0 |
| **v14-A** (shipped): per-TF streak, ×1.5 up on HTF buys, ×0.5 down elsewhere | **430** | **+227.5 %** | 5.84 % | **2.249** | 74.7 % | −18 220 (−2.6 %) | −167 | **−1.99 %** | 2.24 % | **39.0** | **2.15** | **13 / 13** | 38 / 71 |
| v14-B (loss cutter): Fibonacci up on HTF buys, ×0.5 down, account streak | 430 | +175.3 % | **4.78 %** | 2.074 | 74.0 % | **−16 327 (−12.7 %)** | **−146** | −1.97 % | 2.96 % | 36.7 | 1.94 | 13 / 13 | 55 / 77 |
| v14-C (fewest rules): pure step-DOWN ×0.5 of M5 / sells, no step-up | 430 | +179.4 % | 4.79 % | 2.078 | 74.9 % | −16 643 (−11.1 %) | −154 | −1.98 % | **1.00 %** | 37.5 | 1.98 | 13 / 13 | 84 / 45 |
| zone grid (option): deep leg 0.5 R into the zone, 60/40 budget, own ladder | 632 | +152.0 % | 4.07 % | 2.038 | 72.5 % | −14 648 (−22 %) | −84 | −1.94 % | 0.60 % | 37.4 | 1.87 | 13 / 13 | 202 deep |
| classic martingale ×2 (cap 3, 3 %) — rejected | 428 | +305 % | 10.40 % | 2.011 | 75.5 % | −30 190 (+61 %) | −288 | −5.19 % | 3.05 % | 29.4 | 1.99 | 13 / 13 | 123 / 0 |

* **The step-DOWN is what cuts the losses, the gated step-UP pays the return back.**  v14-A's 71 half-size trades (M5 / sells after a loss of their
  TF) won 62 % and lost −2 062 $ in total; its 38 stepped-up HTF buys won **92 %** (+7 078 $, −905 $ lost); the 7 trades at step 2 (×2.25) won 7 / 7.
* **Every ungated step-up lost more money than the reference** (−19…−35 k$), deficit recovery drove DD to 13.5 %, the anti-martingale lost
  −35 k$ with 11/13 months, shrinking everywhere cut the return by 40–65 pt.  Among the 140 variants only 5 pass all five criteria (less $ lost,
  loss band held, better return/DD, return held, OOS PF held) — all five are asymmetric.
* **Stress** (return / DD / $ lost / OOS PF), v14-A vs reference: spread ×2 +122 % / 6.2 / −12 259 / 1.68 (ref +88 / 7.1 / −12 097 / 1.51);
  commission ×2 +198 / 6.0 / −16 902 / 2.01 (ref +162 / 5.1 / −16 867 / 1.86); slippage ×3 +210 / 5.6 / −18 056 / 2.06 (ref +176 / 5.3 / −18 535 /
  1.86); worst intrabar +231 / 5.9 / −18 089 / 2.21 (ref +192 / 5.2); risk 0.5 % +88 / 3.9 / 2.02; risk 2 % +798 / 9.9 / 1.96 — ahead of the
  reference on return and OOS PF in 6 of 6 scenarios.  v14-B / v14-C lose less money than the reference in all 6.
* **Shuffle / block bootstrap (n = 1000)**: v14-A loses less than flat sizing in 88 % of shuffled orders / 94 % of block bootstraps, out-returns
  it in 63 % / 93 %; the HISTORICAL order ranks 0.97 on return/DD among shuffles (the DD advantage is partly order luck) but 0.62 among block
  bootstraps (normal).  v14-C loses less in 100 % / 100 %.  → the loss reduction and the return gain are robust to the trade order; the drawdown
  gain is not guaranteed.
* **Walk-forward** (IS Sep25–Feb26 → OOS Mar–Sep26): the $-lost side of a sizing rule carries over almost perfectly (Spearman **+0.98**), the DD
  **+0.88**, the PF only **+0.31**.  Of the 70 variants a user would have picked on the first half, 50 still lose less than the reference on the
  second half.  v14-A: IS PF 2.46 → OOS PF 2.15, $ lost −11 % IS, +1.6 % OOS in dollars (−1.9 % relative to the OOS-start equity — it compounds faster).
* **Honest**: the gates (HTF buys up, M5 / sells down) are read from the same year they are judged on; the loss reduction of v14-A is modest
  (−2.6 % $ lost, avg loss −5 %) — it is the best RISK-ADJUSTED variant, v14-B / v14-C are the LOSS CUTTERS (−11…−13 % $ lost, DD 4.8 %) at a
  5–13 pt return cost.  The martingale changes SIZE only; entries, stops and targets are v13-A; the v10 account rules stay in force.
* **FINAL BACKTEST on the user's CSV** (`backtest_v14_final.py`, strings read from `run_trader.bat`, 359 813 M1 bars 2025-09-01 → 2026-09-04):
  **430 trades, +227.53 % ($10 000 → $32 753), max DD 5.84 %, PF 2.249, win 74.7 %, 13/13 months positive, worst day −1.99 % of equity, OOS PF 2.15,
  0 daily halts** — identical to the study json.  Report with month-by-month, by-TF, streak-step and worst-trade tables: **`study_results/FINAL_BACKTEST_V14.md`**.
* Details, all 140 variants, diagnosis tables, charts: **`study_results/MARTINGALE_V14.md`** (+ `charts/v14_*.png`, `charts/final_v14_equity.png`).

---

## 0f. v13 — the weak months (Apr 2026 negative, Sep 2025 weak) and the regime-adaptive management

**Spec.**  The v12-A trader showed one NEGATIVE month (Apr 2026, −$132) and one WEAK month (Sep 2025, +$332).  Find the problem and a way to
make a good profit out of those months WITHOUT breaking the other 11 (same loss band as v12, judged on the full year + the OOS half); save after
every step (recoverable).

**Diagnosis** (`run_v13_diag.py` → `study_results/v13_diag/`).  **April 2026 is a MANAGEMENT problem, not a selection problem**: 38 trades
(a normal number), no bad slice that is not strongly positive over the year, the filtered POIs replayed ALL negative — but the 4-leg ladder
0.6/1.2/2.4/4.8 R reached 1.2 R in only 26 % of the trades (year 40–56 %), 4.8 R in 5 % (year 9–18 %), partials fell back to break-even and
the stop-rate rose to 34 %; the month was a post-crash range (month range 8 %, chop 20.8, 4 EMA20 flips).  A flat 1 R exit on the same fills
would have made +12 R.  **September 2025 is opportunity starvation**: the lowest volatility of the year (avg daily range $54 = 1.56 % at
$3 500 gold), M5 zones of $2.3 (year $4–7) → 160 of 180 M5 POIs rejected by the cost gate; the rejects replayed +0.7 R GROSS over 130 fills
(zero edge before commission) → the gate was right, nothing in the same stream can be added.  Also a partial month (13 trading days with a trade).

**Lever** (`lubot/regime.py`, TraderConfig `regime_*` / `range_*`, defaults byte-identical, parity exact, 5 + 3 + 1 tests).  A regime metric
from CLOSED daily bars only: `adr_ratio` = mean daily range of the last 5 server days / last 20 days; `< 1.0` = volatility contracting =
**range**.  Plans PLACED in a range use the **tight ladder 0.5 / 1.0 / 1.5 / 2.5 R (25 % each)** and the **stop schedule 0 | 0.3 | x | x**
(BE after leg 1, +0.3 R after leg 2); everything else keeps the v10 G ladder.  177 full-year variants (`run_v13_levers.py`: metric × threshold
× ladder × lock × TF subset, the alternative ladder for EVERY plan, locks for every plan, risk scaling), stress × 6, walk-forward, a
22-setting neighbourhood.  The live bot computes the same metric every minute (`Trader.current_regime`, shown in the status line) and
carries the range stop schedule in each plan's state.  `run_trader.bat` ships v13-A; `verify_bat_v13.py` replays its exact strings to
430 / +188.65 % / DD −5.45 % / PF 2.008 = the study json.  **113 tests pass.**

**Result** (full year Sep 2025 → Sep 2026, $10 000, 1 % risk, real costs; OOS = Mar–Sep 2026):

| variant | trades | return | max DD | PF | win | worst day | OOS PF | Apr 2026 | Sep 2025 | months > 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v12-A reference | 427 | +179.5 % | 5.28 % | 1.87 | 72.6 % | −2.65 % | 1.78 | −0.72 R (−$132) | +3.35 R | 12 / 13 |
| **v13-A**: ADR5/20 < 1.0 → tight ladder + lock +0.3 R | **430** | **+188.7 %** | **5.45 %** | **2.01** | **75.3 %** | **−2.28 %** | **1.91** | **+1.75 R (+$343)** | +3.35 R | **13 / 13** |
| v13-C: same, no lock (fewest new rules) | 430 | +184.7 % | 5.26 % | 2.00 | 75.3 % | −2.28 % | 1.90 | +0.99 R | +3.35 R | 13 / 13 |
| v13-B: ADR3/20 < 0.9 → tight ladder (lowest DD) | 430 | +185.8 % | 4.38 % | 1.98 | 74.7 % | −2.58 % | 1.93 | +1.15 R | +3.35 R | 13 / 13 |
| tight ladder for EVERY plan (LAD_tight, rejected) | 432 | +130 % | 5.59 % | 1.86 | 77.1 % | −2.04 % | 1.72 | +1.52 R | +4.34 R | 12 / 13 |

* 220 of the 430 trades are range-managed (33 in April, 38 in July, 0 in Sep 2025); on those SAME fills the tight ladder makes +41.0 R vs
  +37.4 R for the reference management, stop-rate 24.5 % vs 29.5 %, positive in both halves; the trend trades are untouched.  The other
  11 months are net unchanged (±0.0 R in total, single months −2.8…+4.6 R).
* **The switch is needed**: the tight ladder for every plan gives +130 % (the far legs earn the year in trending months); locks or reduced
  risk for every plan do not turn April positive; not trading in a range costs half the return.
* **Stress** (return / DD / OOS PF / April R), v13-A vs reference: spread ×2 +88 % / 7.1 / 1.51 / −0.8 (ref +80 / 6.6 / 1.48 / −0.8),
  commission ×2 +162 / 5.1 / 1.86 / +2.9 (ref +145 / 5.7 / 1.71 / +0.6), slippage ×3 +176 / 5.3 / 1.86 / +1.3 (ref +167 / 5.4 / 1.72 / −1.2),
  worst intrabar +192 / 5.2 / 1.96 / +2.3, risk 0.5 % +74 / 2.6, risk 2 % +672 / 10.1 / 1.84 — ahead of the reference on return and OOS PF in
  6 of 6 scenarios.  At double spread every variant loses ~110 M5 trades to the cost gate and April is negative for all of them.
* **Walk-forward**: Spearman(IS R, OOS R) over the 177 variants = **+0.23** (p 0.002), (IS PF, OOS PF) = +0.36 — positive this time
  (management levers generalise; the v11/v12 selection levers gave −0.29).  v13-A ranks 37/177 in-sample and 34/177 out-of-sample.
* **Neighbourhood** (threshold 0.8–1.1, ADR windows 3–10 / 10–40 days, locks, ladders, fractions — 22 settings): April positive in
  **22 / 22**, 13/13 months in 22 / 22, both loss bands held in 20 / 22, PF 1.87–2.03 → a smooth plateau, not a lucky cell.
* **Honest**: Sep 2025 is NOT improved (by design — no gross edge in the rejected trades; the only variants that lift it do so through the
  in-sample half and lose OOS).  One deep range month in the data; the lever is judged on 220 trades and will be tested for real in the next range.
* Details, all variants, tables and charts: **`study_results/WEAK_MONTHS_V13.md`** (+ `charts/v13_*.png`).

---

## 0e. v12 — more trades at the same loss profile, round 2

**Spec.**  Starting from v11-B (348 trades / year, +148 %, max DD 5.2 %, PF 1.91, win 72 %, worst day −2.3 %, OOS PF 1.73) make the bot
trade MORE again while keeping the loss percentage; save after every step (recoverable).

**What was run.**  Funnel of the 3 882 POIs shown in the full year under v11-B (348 = 9 % traded; 69 % die in the filter, 22 % are
cancelled before the fill — **323 of them because the scanner *replaced* the zone by another one on the same slot, and 165 of those were
shown again later**; 324 quality-rejected zones overlapped a level another timeframe actually traded).  Three new simulator levers
(defaults byte-identical to v11, parity exact, 6 unit tests): `keep_replaced_bars` / `keep_replaced_tfs` (keep a *replaced* order N bars of
its TF; a *cleared* slot still cancels), `confluence_filter` (a different filter string for zones already active on another TF),
`reentry_bars` / `reentry_tfs` / `reentry_max` (re-arm a zone after a break-even exit).  212 full-year runs (61 singles + 150 combos,
`run_v12_levers.py`, resumable), stress × 6 and a walk-forward check of the finalists (`run_v12_stress.py`), report `make_v12_report.py`.
Both winning levers are ported to `trader.py` (fake-MT5 tests); `run_trader.bat` ships v12-A and its exact strings replayed in the
simulator give 427 / +179.51 % / DD −5.28 % (`verify_bat_v12.py`).  **104 tests pass.**

**Result** (full year Sep 2025 → Sep 2026, $10 000, 1 % risk, real costs; OOS = Mar–Sep 2026):

| variant | trades | return | max DD | PF | win | stop-rate | worst day | OOS PF | loss band held |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v11-B reference | 348 | +148 % | 5.22 % | 1.91 | 71.6 % | 27.9 % | −2.29 % | 1.73 | — |
| **v12-C**: + `keep_replaced_bars=1` (M10/M15/M30/H1) | 371 (+7 %) | +166 % | 5.83 % | 1.99 | 73.0 % | 26.4 % | −2.50 % | 1.84 | yes (DD +0.6) |
| **v12-A**: v12-C + confluence filter M10 0.50 + M10 0.57 | **427 (+23 %)** | **+180 %** | **5.28 %** | **1.87** | **72.6 %** | **26.9 %** | **−2.65 %** | **1.78** | **yes, both halves** |
| v12-B: v12-A + confluence M15 0.50 | 468 (+34 %) | +192 % | 5.36 % | 1.80 | 71.6 % | 28.0 % | −3.25 % | 1.72 | no (PF, worst day) |
| re-entry M10/M15 1 bar (rejected) | 400 | +157 % | 5.50 % | 1.83 | 70.5 % | 29.0 % | −3.99 % | 1.82 | no; DD 10.6 % at spread ×2 |

* **Keep replaced orders** is the robust, *mechanical* lever (independent of the entry model): +23 trades, better than the reference on
  every loss metric except a 0.6-pt deeper DD; positive on both halves and in every stress scenario.  On M5 it loses (−11 R / 36 trades)
  → higher timeframes only.  Keeping longer than 1 bar dilutes.
* **Confluence filter**: M10 zones that are already active on another timeframe pass at quality 0.50 (+21 trades, OOS-neutral); the M15
  relaxation is slightly negative OOS and only in v12-B.  Dropping the HTF bar completely for confluence zones → DD 7.3 %.
* **Re-entry after a break-even exit** adds 50–210 trades that are break-even as a group, worst day −4 %, and every combination with
  the other levers blows the drawdown (7.8–10.6 %) → rejected.  M5 relaxations, grace/persist orders: rejected again.
* **Stress** (return / DD / OOS PF): v12-A spread ×2 +80 % / 6.6 % / 1.48 (ref +58 % / 9.3 % / 1.29), commission ×2 +145 % / 5.7 % / 1.71,
  slippage ×3 +167 % / 5.4 % / 1.72, worst intrabar +176 % / 5.3 % / 1.76, risk 0.5 % +72 % / 3.1 %, risk 2 % +658 % / 10.2 %.
* **Walk-forward**: Spearman(IS R, OOS R) over the 212 variants = −0.29 — the in-sample half would pick heavy M15 confluence
  relaxations that rank 60th–190th out-of-sample.  The finalists were chosen on the OOS half (selection bias acknowledged); the
  keep-replaced core does not depend on the entry model and holds everywhere.
* Details, funnel, all 212 variants, extra-trade breakdown: **`study_results/MORE_TRADES_V12.md`** (+ `charts/v12_*.png`).

---

## 0d. v11 — more trades at the same loss profile

**Spec.**  Make the bot trade MORE while keeping the loss percentage (drawdown / stop-rate / worst day) of v10; save after every step.

**What was run.**  Funnel of the 3 882 POIs the scanner showed in the full year (only 251 = 6.5 % became trades: 66 % die in the v8
filter, 18 % are cancelled before the fill by the mirror policy, **9 % are refused because another timeframe already had an order on
the same level**), then 159 variants on the full-year streams: 53 existing levers (quality / cost / session gates per TF, order
policy, dedupe, entry offset, max open), 3 new simulator levers (`dedupe_cross_tf`, `overlap_mode=allow|share`, `cancel_grace_min`;
defaults byte-identical to v10) and 90 combinations, all judged on the out-of-sample half (Mar–Sep 2026), stress × 6 of the finalists.

**Result: trade the confluence zones.**  v10's overlap de-duplication refused a zone whenever another timeframe had an order on the
same level — those are the best trades of the year (M15 +31 trades at 81 % win, +0.67 R each).

| full year Sep 2025 → Sep 2026, $10k, 1 % risk, real costs | v10 reference | **v11-A** `dedupe_cross_tf=false` | **v11-B** + M30/H1 quality 0.57 |
|---|---|---|---|
| trades | 251 | 331 (+32 %) | **348 (+39 %)** |
| return · max drawdown | +80.7 % · 5.5 % | +136 % · 5.7 % | **+148 % · 5.2 %** |
| PF · win-rate · positive months | 1.75 · 69 % · 11/13 | 1.89 · 72 % · 11/13 | **1.91 · 72 % · 12/13** |
| out-of-sample (Mar–Sep 26) R · PF | +26.7 · 1.64 | +35.2 · 1.65 | **+42.0 · 1.73** |
| worst day · stop-rate | −1.9 % · 30 % | −2.8 % · 28 % | −2.3 % · 28 % |
| stress: spread ×2 / commission ×2 / slippage ×3 (return) | +33 / +64 / +74 % | +52 / +112 / +128 % | +58 / +124 / +136 % |

**Rejected** (more trades *and* more losses): persisting / grace-period orders (+76…361 trades, DD 11–16 %, OOS PF 1.0–1.25), entering
in front of the zone (DD 7–12 %), M5 quality < 0.55 (DD 7–11 %), M10 quality < 0.60 (in-sample +50 R but OOS collapses to +15 R — a
pure in-sample artefact), sharing the risk of the second confluence plan (same trades, lower PF).  `max_open_positions` and
`one_trade_per_poi` are never binding.  Price of v11: worst day −1.9 → −2.3 %, up to 4 correlated positions at once, DD 9.3 % (vs 6.8 %)
if the spread doubles.  Live bot: `--trader ...,dedupe_cross_tf=false` (ported to `trader.py`, tests), filter in `run_trader.bat`.
**Full report: `study_results/MORE_TRADES_STUDY.md`.**  Scripts: `run_v11_funnel.py`, `run_v11_levers.py`, `run_v11_combos.py`,
`make_v11_report.py`, `run_v11_all.sh`.

---

## 0c. v10 — more than two take-profits?  Loss limits.  Full-year backtest.

**Spec.** (1) Test whether 3+ take-profit legs raise profitability; be creative.  (2) Bot rules: max **4.5 % loss per day**
(flat until the next server day), max **9 % loss overall** (bot stops for good).  (3) **Full-year** backtest.  (4) Save after every step.

**What was run.** 887 exit systems (3/4/5-leg ladders × fraction splits × stop schedules, runner ladders, ATR-unit ladders,
geometric ladders, two-leg references) on the v8 entries — OOS portfolio Mar–Sep 2026 **and** in-sample replay of 1 270 plans
Jan 2025–Feb 2026 (Spearman 0.52 between the two rankings) — then new full-year selection streams **Sep 2025 → Sep 2026** for
all 5 timeframes and a 112-run full-year portfolio backtest (7 systems × loss rules on/off × 7 stress scenarios).

**Result: a 4-leg geometric ladder — 25 % at +0.6R / +1.2R / +2.4R / +4.8R, stop to break-even after the first leg.**
`--trader tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge`

| full year Sep 2025 → Sep 2026, $10k, 1 % risk, real costs | current spec | v9 (25 % @ 0.6R → 2.5R) | **v10 G ladder** |
|---|---|---|---|
| return · max drawdown | +28.6 % · 4.4 % | +60.5 % · 6.8 % | **+80.7 % · 5.5 %** |
| PF · win-rate · Sharpe · positive months | 1.49 · 79 % · 2.39 · 10/13 | 1.63 · 70 % · 2.86 · 10/13 | **1.75** · 69 % · **3.28** · **11/13** |
| Sep25–Feb26 (entry model in-sample) · Mar–Sep26 (OOS) | $1 351 · $1 505 | $2 865 · $3 189 | **$3 966 · $4 107** |
| OOS grid Mar–Sep26 return · DD · in-sample R/plan · IS DD (R) | +12.3 % · 3.2 % · +0.165 · −20.1 | +29.4 % · 4.3 % · **+0.308** · −20.9 | +31.5 % · 4.1 % · +0.301 · **−17.8** |

More legs is **not** automatically better: the median 3/4/5-leg system is worse than the median two-leg system (OOS +19–20 %
vs +25 %).  What works is first leg ≥ 0.6R, last leg ≥ 3R (4–5R catches the big gold runs), break-even after the first leg
(waiting for leg 2 adds R but +9 R in-sample drawdown and a 46–55 % win-rate), 15–30 % on the first leg.  Ratchets, +0.5R locks,
trailed runners and ATR-unit targets do not beat fixed ladders.  59 of 826 multi-leg systems beat v9 on both IS and OOS
return, none with a lower drawdown on both — except the G ladder, which ties v9 in-sample and beats it OOS and over the year on
return *and* drawdown.  Higher-return alternatives (5-leg 0.5/1/2/3/5R be2: +89 % year; two-leg 1R/4R: +69 %) come with 58 %
win-rates and 7–8 % drawdowns.

**Loss rules** (`TraderConfig.max_daily_loss_pct=4.5`, `max_total_loss_pct=9.0`; `trader.py --max-daily-loss / --max-total-loss`,
0 = off; simulator + live bot, persisted state, 7 tests): at 1 % risk they **never trigger** in the whole year on any system
(worst day −2.5 %, worst intraday dip −2.6 %, deepest drawdown −8.1 %) — free insurance; at 3 % risk they fire 4–12 times a year.

**Live bot:** `trader.py` now places one limit leg per target (N legs, server-side TPs) and applies the stop schedule when a
target leg closes (`_manage_ladder`; `sl_after_leg`, classic BE, ratchet) — `tests/test_trader_live.py` 4-leg / 3-leg scenarios.
Needs a hedging account (netting falls back to the two-leg bot-side partial).  **Full report: `study_results/MULTI_TP_STUDY.md`.**
Scripts: `run_v10_record.sh`, `run_v10_study.py`, `run_v10_year.py`, `make_v10_report.py`, `run_v10_all.sh`.

---

## 0b. v9 — the risk-management study (which exit system is the most profitable?)

The v7/v8 management was *"close 50 % at +0.4R → stop to break-even → TP2 +1.5R"*.  v9 held the v8 entries fixed and ran
**580 management systems** — two-leg partials (level × fraction × TP2 × BE on/off), single targets ± BE trigger, trailed
runners, whole-position trails, 3-leg ladders ± ratchet, time stops, BE offsets — through the realistic portfolio simulator
**out-of-sample (Mar–Sep 2026)** and replayed **all 580 in-sample (Jan 2025–Feb 2026, 1 270 plans)**, then stress-tested the
finalists.  Spearman correlation of the two rankings: 0.61 (n = 580) — the ranking is real.

**Result: close 25 % at +0.6R → stop to break-even → TP2 = +2.5R** (`--trader partial_r=0.6,partial_frac=0.25,tp2_r=2.5`).

| | current spec (50 % @ 0.4R, TP2 1.5R) | **v9 recommended** |
|---|---|---|
| in-sample R / plan (1 270 plans) · PF · win · max DD (R) | +0.165 · 1.88 · 81 % · −20.1 | **+0.308** · **2.29** · 76 % · −20.9 |
| OOS return · max DD · PF · Sharpe · positive months | +12.3 % · 3.2 % · 1.46 · 2.35 · 5/7 | **+29.4 %** · 4.3 % · 1.68 · 3.26 · 6/7 |
| paired in-sample improvement | | +0.143 R/plan, t = 7.1, better in 13 of 14 months |

Why: the 0.4R partial is too early (70–77 % of fills also reach +0.6R) and 1.5R too close (half of the trades that reach
0.6R reach 2.5R).  0.6R is the knee: beyond it drawdown grows fast; smaller partials (25 %) beat larger ones at every level;
2.5R is the in-sample optimum, 3R the OOS optimum (twin: `tp2_r=3.0`, OOS +34.6 %, IS +0.279).  Break-even stays (without
it the win-rate drops to 35 % and drawdown +50 %).  Trails, ladders, ratchets, time stops and BE offsets do not beat the
plain two-leg system on both periods.  Higher-return systems exist (single 3R + BE after 1R +39 %, 2R trail +57 % OOS) but
with 24–34 % win-rates, 1.5–3× the drawdown and a negative second OOS half.  Same order flow as today (two limit legs
25 % / 75 %, server-side TPs, BE move after leg A), so the live bot needs no code change — only the numbers.
**Full report: `study_results/RISK_MGMT_STUDY.md`.**  Scripts: `run_rm_study.py`, `rm_insample.py`, `rm_stress.py`, `make_rm_report.py`, `run_v9_all.sh`.

---

## 0a. v8 — the M5 trade filter (what changed since v7)

v7 lost −14 % because the **M5 trades** (68 % of all trades) lost −0.05 R each: the M5 zone is a few dollars, so spread +
commission eat ~0.07 R per trade, and the scanner's P(bounce ≥ 1 ATR) is not the probability that *this plan* (limit at the
near edge, SL at the far edge, half at +0.4R, TP2 +1.5R) works.  v8 adds `lubot/trade_filter.py` — per-timeframe,
interpretable gates checked with the live spread, the same code in the backtest and in `trader.py`:

```
trade_filter = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"
```
* `max_cost_r` — (spread + commission/oz) / 1R must be ≤ 8 % → no thin zones
* `min_quality` — M5 needs the quality model's score ≥ 0.55; the other timeframes ≥ 0.60
* `sessions` — no new M5 orders from selections made 13:00–17:00 New York (the "nypm" session, worst in-sample)
* also available: `min_zone_atr`, `max_zone_atr`, `hours`, `sides`, `kinds`, and an optional ML gate `model_path`/`model_min`

The rules were chosen **in-sample only** (every M5 candidate of 2025-01 → 2026-02 replayed as a v7 plan on M1 bars,
`label_plan_outcomes.py`; train < Dec 2025, validation Dec 2025 – Feb 2026), then verified out-of-sample with the portfolio
simulator.  A second ML model trained on plan outcomes had *no* skill on the bot's own picks (AUC 0.50) and is OFF.

**Out-of-sample 2026-03-02 → 2026-09-04, $10 000, 1 % risk, real costs** (`study_results/TRADER_V8.md`):

| configuration | trades | win % | PF | R/trade | return | max DD | Mar–May | Jun–Sep |
|---|---|---|---|---|---|---|---|---|
| v7 base (all TFs, no filter) | 395 | 71.4 | 0.85 | −0.044 | **−16.6 %** | −26.0 % | +3.4 % | −18.1 % |
| v7 `min_quality=0.60` | 98 | 80.6 | 1.27 | +0.057 | +5.1 % | −5.3 % | +5.6 % | 0.0 % |
| v7 without M5 | 181 | 73.5 | 1.02 | +0.008 | +1.2 % | −5.9 % | +4.0 % | −0.6 % |
| **v8 M5 only (filtered)** | 98 | 80.6 | 1.49 | +0.104 | **+10.1 %** | −4.2 % | +11.6 % | −1.6 % |
| **v8 all TFs (recommended, default)** | 131 | 80.9 | **1.46** | +0.098 | **+12.3 %** | **−3.2 %** | +10.4 % | +2.2 % |

The M5 trades went from the main loss (−15 R) to the main profit source (+9.8 R of +12.8 R).  Stress tests of the
recommended configuration: 2× spread +6.9 %, 3× slippage +10.7 %, worst-case intrabar path +13.2 %, 2-min BE delay
+13.0 %, netting +12.5 %, commission ×2 +10.9 %, risk 0.5 % +6.2 % / DD 1.4 %.  Honest caveats: 131 trades in six months,
the second half is much weaker than the first (July negative for every configuration), sells are still negative — the M5
edge after costs is ~0.10 R per trade, not more.  Start with `--dry-run`, then 0.5 % risk.

`--trade-filter ""` restores the v7 behaviour; `python backtest_trader.py ... --trader "trade_filter=M5:max_cost_r=0.06"`
tests other rules on the recorded streams (`study_results/sel_v8_M5.pkl` carries the feature vectors, so `model_path` rules
work in the backtest too).

---

## 0. The trader (v7)

### 0.1 Trade plan (`lubot/execution.py`)
* bullish POI (below price) → **BUY LIMIT at the top of the zone**, **SL at the bottom**;
  bearish POI (above price) → **SELL LIMIT at the bottom**, **SL at the top**.  `1R = zone height` (no buffer; `sl_buffer_atr` exists but is 0).
* **TP1 = +0.4R → close 50 %**, stop of the remainder → **break-even** (entry).  **TP2 = +1.5R.**
* Gross outcomes per trade: **−1R** (stopped before the partial), **+0.20R** (partial then BE), **+0.95R** (partial then TP2).
* Size: `risk_pct` (default **1 %**) of current equity between entry and SL, rounded **down** to the broker volume step.
  Hedging account → two half legs (leg A: TP1, leg B: TP2, both SL = zone end, all **server-side**).  Netting account →
  one order with TP2; the bot closes half at market when +0.4R is touched.  Too small for two 0.01 legs → the trade is skipped, never over-risked.

### 0.2 Live bot (`trader.py`, `lubot/mt5_broker.py`)
```
pip install -r requirements.txt && pip install MetaTrader5      # once, Windows
# open MT5, log in to your account, add XAUUSD.t to Market Watch, then:
python trader.py --symbol XAUUSD.t --risk 1.0 --min-quality 0.50 --timeframes M5,M10,M15,M30,H1
python trader.py --dry-run --once                 # scan + print the orders, send nothing
python trader.py --min-quality 0.60 --timeframes M10,M15,M30,H1 --trader max_open_positions=2   # stricter
```
Every minute after the M1 bar closes it: reloads history from the terminal → runs the v6 scanner on closed bars →
places limit orders for newly shown POIs → cancels pending orders of POIs no longer shown (**mirror policy** — the
backtest shows that persisting stale orders loses money) → detects fills → when leg A has been closed at TP1 moves
leg B's stop to break-even → persists everything to `trader_state.json` (crash-safe; on restart the bot re-adopts its
own orders/positions by magic number and comment).  Stops and targets live on the server, so a PC crash only delays
the break-even move.  One trade per POI; zones overlapping ≥ 50 % with an active plan are not traded twice; max 4 open
plans; margin check before every order.  Logs go to `trader.log`.

`--trader key=value,...` exposes every `TraderConfig` field (`partial_r`, `partial_frac`, `tp2_r`, `be_offset_r`,
`sl_buffer_atr`, `max_open_positions`, `grades=A|B`, `sides=buy`, `size_on=balance`, ...); `--set` passes scanner overrides.

### 0.3 Realistic backtest (`record_selections.py` → `lubot/portfolio_sim.py` → `backtest_trader.py`)
1. `bash run_v7_record.sh` walks the scanner bar by bar (model trained before 2026‑03‑01, out‑of‑sample from there)
   and records **every change of the displayed POIs** with the bar‑close timestamp — exactly the live bot's inputs.  Resumable per timeframe.
2. `PortfolioSimulator` replays that stream on the **M1 bars**: limit fills on the ask (buys) / bid (sells); stops and
   targets on the correct side; MT5‑tester intrabar path (O→L→H→C bullish, O→H→L→C bearish; `intrabar=worst` = stop
   first); TP1 leg = server‑side TP (no slippage), stop‑outs = market with `sl_slippage` $0.10; **$7/lot commission**,
   **swaps** (‑$50/+$15 per lot per night, 3× Wednesday); spread per minute (real from 2026‑04‑06, before that the same
   weekday/NY‑hour spread of the bars that have one); margin / stop‑out; equity‑based sizing; the same order policy,
   dedupe and position limits as the live bot.
3. `run_trader_study.py` runs 35 variants (costs ×, slippage ×3, worst intrabar, BE latency, netting, persistent orders,
   risk, position limits, quality thresholds, per‑timeframe, sides, alternative managements) and writes the report.

### 0.4 Backtest results — out-of-sample 2026-03-02 → 2026-09-04 (model trained before March), $10 000, 1 % risk

Full report with 35 variants: **`study_results/TRADER_BACKTEST.md`** (charts in `study_results/charts/trader_*.png`).

| configuration (`--trader ...`) | trades | win % | partial hit | TP2 | full SL | PF | return | max DD |
|---|---|---|---|---|---|---|---|---|
| **user spec, default scanner** (`min_quality 0.50`, all 5 TFs) | 395 | 71.9 | 72 % | 17 % | 28 % | **0.87** | **−14.3 %** | −24.7 % |
| same, **zero costs** (pure price path) | 424 | 73.6 | 74 % | 18 % | 26 % | 1.04 | +4.5 % | −16.4 % |
| `min_quality=0.55` | 212 | 75.5 | 76 % | 16 % | 24 % | 1.02 | +1.2 % | −9.6 % |
| **`min_quality=0.60`** | 96 | 80.2 | 80 % | 14 % | 20 % | **1.21** | **+4.0 %** | −5.3 % |
| `min_quality=0.60,timeframes=M10\|M15\|M30\|H1` | 50 | 80.0 | 80 % | 22 % | 20 % | 1.57 | +5.5 % | −3.5 % |
| `timeframes=M10` | 112 | 75.9 | 76 % | 21 % | 24 % | 1.23 | +6.1 % | −4.3 % |
| `timeframes=M30` | 39 | 79.5 | 80 % | 18 % | 21 % | 1.48 | +3.4 % | −2.1 % |
| `sides=buy` | 224 | 75.4 | 75 % | 20 % | 25 % | 1.21 | +11.8 % | −5.3 % |
| `sides=sell` | 170 | 67.1 | 68 % | 13 % | 32 % | 0.58 | −23.0 % | −25.7 % |
| `order_policy=persist` (keep stale orders) | 1025 | 66.8 | 67 % | 20 % | 33 % | 0.81 | −53.0 % | −58.2 % |
| management: no partial, TP 1.5R only | 395 | 17.5 | – | 17 % | 83 % | 0.77 | −26.5 % | −32.6 % |
| management: 50 % @ 0.5R, TP2 1R | 395 | 68.6 | 69 % | 32 % | 31 % | 1.00 | +0.6 % | −12.1 % |
| management: 50 % @ 0.4R, TP2 2R | 395 | 71.9 | 72 % | 14 % | 28 % | 0.91 | −10.2 % | −23.4 % |

**Honest reading.** With the user's management the outcome mix is stable and matches the POI studies: ~72 % of fills
reach +0.4R, 17 % run to +1.5R, 28 % are stopped for −1R.  That mix is worth **+0.013 R per trade before costs** and
**−0.037 R after** spread ($0.28 ≈ 0.04 R on a $7 zone), $7/lot commission and $0.10 stop slippage — at the default
scanner threshold **the edge is smaller than the costs** and the half-year ends at −14 % (July alone −13 R).  The
partial-close management is nevertheless the *best* of the managements tested (a plain 1.5R target loses −26 %), and
the mirror order policy is essential (persisting stale orders −53 %).  What makes it positive is **trading fewer, better
zones**: `min_quality 0.60` (≈ 0.7 trades/day) gives PF 1.21 / +4 % / DD 5 %; M10 + M30 zones and buys are the
profitable parts, M5 (68 % of all trades) and sells lose.  Six months is a short sample — treat every subset as an
indication, not a promise; the model was trained on a bullish gold year, the likely reason sells under-perform.

**Recommended live settings (v8)** — `run_trader.bat` already applies the v8 filter (section 0a); for a cautious start:
```
python trader.py --symbol XAUUSD.t --risk 0.5 --commission 7 --trader max_open_positions=2
```
(v7 alternative without M5: `--trade-filter "" --min-quality 0.60 --timeframes M10,M15,M30,H1`)
Run with `--dry-run` for a few days first and compare the printed plans with `trader.log`.


---

## 1. Strategy → code mapping

Every concept of the PDF is implemented incrementally on **closed bars only**
(no look-ahead). A swing at bar `i-1` is only known when bar `i` closes, an OB is
only known once the displacement candle closes, etc.

| PDF lesson | Implementation (`lubot/`) |
|---|---|
| **3 Candle Formation** – candle #2 highest/lowest of 3 | `structure.py` → `SH` / `SL` liquidity |
| **Liquidity** – buy stops above unbroken swing highs, sell stops below swing lows | `Liquidity(side=BSL/SSL)`, `swept_at` = stop hunt |
| **Equal Highs / Lows** (incl. *relative* equal; a stop-hunted level is *not* EQH) | `_tag_equal()` with ATR tolerance |
| **Previous Day / Week High & Low** | `PDH PDL PWH PWL` |
| **Asia Session** 17:00–00:00 NY | `ASIA_H ASIA_L` (server→NY tz conversion) |
| **QM / Trading Range** – stop hunt + BOS → Strong High/Low, Weak High/Low | `TradingRange`, `bias`, **Premium / Discount** (`zone_of`) |
| **Orderblock** – last opposite candle(s) before the move, *MUST take out liquidity*, body zone | `poi.py::_detect_orderblocks` (consecutive same-colour candles merged; `swept` lists the liquidity taken) |
| **Breaker Block** – OB that was not respected, used from the other side | `_violate()` creates a `BB` with flipped direction |
| **Imbalance Fill** – 3-candle gap, candle #1 is the POI, filled at its high/low | `_detect_imbalance` (`key_level` = fill level) |
| **Hidden Base** – LTF (M1) OB hidden inside the HTF impulse | `_hidden_base()` looks inside the M1 data of the impulse |
| **Unmitigated Wick** – open of the wick and its 50 % | `_detect_wicks` (`key_level` = 50 %) |
| **Key Level** = opening of the POI (refinement) | `POI.key_level` |
| **Mitigation / Order Flow** – POI, push away, return, reverse | `unmitigated → tapped → respected / violated`; **order-flow support** = respected same-direction POIs in the lookback |
| **POI rule set** 1-4 | per-TF scan · liquidity must rest *between* price and the POI (feeding into it) · unmitigated only · closest above / below |

### Selection pipeline (per timeframe, on every closed bar)
1. all *alive* (unmitigated, not aged out) POIs of types `OB BB IMB HB UW`
2. bullish POIs must be **below** price, bearish **above**
3. **Rule 2** – active liquidity (SL/EQL/PDL/… for bullish, SH/EQH/PDH/… for bearish) must rest between price and the POI
4. **Order flow** – ≥ `min_orderflow_support` (default **1**) POIs of the same direction that were already *mitigated and respected* within `orderflow_lookback_bars`
5. sort by distance → **closest above** & **closest below**; a missing side stays `None` (wait)

## 1b. Quality mode (default) — pick the POI most likely to bounce  (v6)

`selection_mode="quality"` (default) replaces the literal "closest POI" rule with a **bounce-probability
ranking**. The model has grown in five steps — v2 structure, v3 context, v4 price action, v5 classic indicators,
**v6 level memory + honest learning** — and every step is documented in `study_results/QUALITY_V*.md`.

1. Every POI carries **creation features** (`POI.features`): zone geometry, displacement, swept liquidity, base and
   impulse price action, the indicator state when the base was built (`cr_*`) **and (v6) the level memory of the
   area at creation (`cl_*`)** — had this price area already reversed price, how often was it visited / sliced.
2. While the POI is alive the detector tracks its **life-cycle** (distance travelled away, near-misses, retrace).
3. At scoring time the engine adds **context features**: distance, liquidity between / behind / beyond, order flow,
   confluence, QM range position, BOS momentum, day / week ranges, round numbers, tested areas, crowding, volatility
   regime, session, timeframe, HTF confluence, approach price action, 61 selection-time indicators + 11 parent-TF
   indicators, **and (v6, `lubot/levels.py`) 28 level-memory features**: rolling 3000-bar volume / time-at-price
   profile (LVN / HVN score, POC distance, value-area position, thin area behind the zone), **reaction memory**
   (swing reversals that formed in the zone area in the zone direction vs against it, reversals per visit, share of
   visits that sliced through, bars since the last visit), how the area evolved since the base was built, and the
   parent timeframe's memory of the same area. All signed values are oriented to the zone direction.
4. **The v6 model** (`models/quality_model.json`, 258 columns) is a **POI-weighted ensemble**: a bagged LightGBM
   (5 × 270 rounds, 15 leaves, depth 4) and a bagged sklearn GBM (5 × 400 trees, depth 3), probabilities averaged;
   both stored as plain JSON trees and evaluated with numpy only (no LightGBM / sklearn at runtime). Every POI has
   one vote in training (rows are weighted 1 / re-records of that POI — 70 % of the training rows were re-records
   of a still-alive zone, which had stretched the v2–v5 probabilities). `why` lists the top drivers; `bot.py`
   prints an **`indicators:`** and a **`level memory:`** line per POI.
5. Candidates below `min_quality` (0.50) or farther than 8 ATR are dropped; the rest are ranked by
   `quality − 0.02 × distance_atr` and the best above / below are returned with a **grade** (A ≥ 0.65,
   B ≥ 0.55, C ≥ 0.50). If nothing qualifies on a side → `none - waiting`.

Candidate-level out-of-sample (Mar → Sep 2026, models trained before March; best-ranked POI per slot):

| selection | slots kept | bounce ≥1 ATR | median bounce | ≥2 ATR |
|---|---|---|---|---|
| closest (PDF rule 4) | 100 % | 43.7 % | 0.8 ATR | – |
| quality v5, P ≥ 0.50 / 0.60 / 0.65 | 36 / 13 / 6 % | 65.0 / 71.2 / 77.7 % | 1.64 / 2.19 / 2.47 | 44 / 53 / 62 % |
| **quality v6, P ≥ 0.50** | 37 % | 64.6 % | 1.60 ATR | 43.2 % |
| quality v6, P ≥ 0.55 | 24 % | 69.8 % | 1.89 ATR | 47.6 % |
| quality v6, P ≥ 0.60 | 13 % | **73.0 %** | 2.08 ATR | 51.6 % |
| quality v6, P ≥ 0.65 | 5.5 % | **76.3 %** | 2.40 ATR | 55.1 % |

OOS AUC 0.652 (v5) → **0.657** (v6), POI-weighted 0.660; calibrated (predicted .62 → actual .72, .67 → .78).
The measurable gain comes from *how the model learns* (POI weights: +0.7 weighted AUC and +10–15 points hit-rate
of the chosen candidate at strict thresholds on validation; LightGBM + GBM ensemble). The **level memory** is the
strongest new single signal of the project (`lv_rev_per_visit`: bounce 31 → 52 % across quintiles) but is largely
already carried by the structural features, so it adds +1–2 points only at the top of the ranking.

Whole bot re-run out-of-sample Mar→Sep 2026 (models trained before March, `run_v6_parts.sh` + `summarize_v6.py`):

| mode | POIs/day | reached | bounce ≥1 ATR | P≥0.60 (n) | P≥0.65 (n) | R/trade, mid entry / SL 0.5 ATR / TP 0.4R |
|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 43 | 88.5 % | 40.2 % | – | – | +0.095 (PF 1.51) |
| quality v4 | 14.0 | 82.4 % | 57.5 % | 67.3 % (375) | 70.1 % (165) | +0.107 (PF 1.58) |
| quality v5 | 13.0 | 81.6 % | 57.2 % | 65.7 % (349) | 71.9 % (161) | +0.098 (PF 1.51) |
| **quality v6** | 14.3 | 81.3 % | 57.3 % | **68.0 % (408)** | 69.2 % (163) | +0.097 (PF 1.50) |

End-to-end, v6 = v5 = v4 at the default threshold (the PDF rule set dominates; the ranking re-orders zones that
are all reasonable). v6 returns **17 % more zones at `min_quality 0.60`** (≈ 3 / day) with a higher reach rate
(82.8 vs 80.2 %) and hit-rate (68.0 vs 65.7 %), and has the best calibration of the series (0.62 → 0.68,
0.73 → 0.73). Full write-up: `study_results/QUALITY_V6.md` (v5: `QUALITY_V5.md`).

```bash
python bot.py scan --csv data.csv                                     # quality v6 (default)
python bot.py --set min_quality=0.60 scan --csv data.csv              # ~3 zones/day at ~68 %
python bot.py --set quality_model_path=models/v5/quality_model.json scan --csv data.csv   # v5 model
python bot.py --set quality_model_path=models/v4/quality_model.json scan --csv data.csv   # v4 model
python bot.py --set use_levels=false,quality_model_path=models/v5/quality_model.json scan --csv data.csv  # v5 without level-memory cost
python bot.py --set selection_mode=closest scan --csv data.csv        # original PDF rule 4
# retrain (training sets ~40 min serial on 2 cores / 1 GB; model ~10 min):
bash build_all_train_v6.sh data.csv                                   # resumable, commits each TF -> models/v6/train_*.pkl
python experiments_v6.py && python ablation_v6.py                     # learner study / feature ablation (resumable)
python train_v6.py --pattern "models/v6/train_*.pkl" --split 2026-03-01 --final
bash run_v6_parts.sh data.csv && python summarize_v6.py               # bot-level OOS comparison (resumable)
```
Example:
```
  BELOW: IMB bullish zone 4374.05 - 4424.13  (mid 4399.09, key 4374.05)  dist 58.85 (3.97 ATR)  P(bounce>=1ATR)=74% [A]  OF near 16/recent 16  HTF-confluence  liq-behind 1  liq->[SL@4472.03, SL@4477.96]
         below drivers: zone_vs_bar_range +0.50, zone_atr +0.43, edge_to_key_atr +0.17, cr_atr_pctile +0.10, lv_rev_per_visit +0.08
         below indicators: RSI 58  |  ADX 32 trend-with  |  zone beyond BB  |  ST aligned  |  HTF RSI 63  |  relvol 0.9  |  ATR pct 39%
         below level memory: reversals here 6 with / 2 against  |  rev/visit 0.11  |  sliced 41% of visits  |  last visit 37 bars ago  |  mid-volume (x0.9)  |  inside value area  |  HTF reversals 2
```

### Recovery / checkpoints
Every step of the v5 and v6 work was committed and pushed (`save.sh`), long jobs are resumable (they skip finished
outputs) and `PROGRESS.md` logs which step to continue from. After a sandbox reset: `bash restore.sh` (relinks the
CSV, reinstalls scikit-learn / lightgbm, repoints `save.sh` at the current backup repo, runs the tests and prints
the next step). Full snapshots (code + models + training sets) are linked in `PROGRESS.md`.

### Spread handling
The MT5 export only carries `<SPREAD>` from Apr 2026 on (median $0.28); older bars have 0. `load_mt5_csv`
fills those bars with the **typical spread of the same weekday / NY hour** measured on the bars that do have
one (`lubot/data.py::impute_spread`, flag column `spread_imputed`), so every cost figure pays a realistic
spread. `rescore_imputed_spread.py` re-prices older cached results the same way.

---

## 2. Install

```bash
pip install -r requirements.txt          # pandas numpy matplotlib pytest (scikit-learn + lightgbm only for training)
pip install MetaTrader5                  # only for live mode (Windows)
python -m pytest tests -q                # 32 unit tests on hand-built candles
```

## 3. Usage

### Backtest on the uploaded CSV
```bash
python bot.py --plots backtest --csv "XAUUSD.t_M1_202605261607_2026090323581111.csv"
```
Output → `backtest_results/stats.csv`, `trades.csv`, `selections.json`, `charts/*.png`.

### Point-in-time scan (what the bot would have shown at that moment)
```bash
python bot.py --plots scan --csv data.csv --at "2026-08-20 13:00" --json scan.json
python bot.py --timeframes M15,H1 scan --csv data.csv
```

### Live MT5
```bash
python bot.py live --symbol XAUUSD.t                       # terminal already logged in
python bot.py live --symbol XAUUSD.t --login 123 --password *** --server Broker-Server
python bot.py live --once --json latest.json --plots       # single scan + charts
```
The live loop reloads the M1 history each minute (bars are re-aggregated to
M5/M10/M15/M30/H1 so all timeframes stay aligned), ignores the still-forming HTF
bar, prints only when a selection changes and can dump JSON for other tools.

### Config overrides
```bash
python bot.py --set min_orderflow_support=2,require_premium_discount=true,poi_types=OB|BB|UW scan --csv data.csv
```
All thresholds are in **ATR multiples** so the same settings work on every timeframe
(see `lubot/config.py`). Notable keys: `ob_zone=body|full`, `ob_require_liquidity_sweep`,
`respect_move_atr`, `orderflow_lookback_bars`, `max_poi_age_bars`, `max_distance_atr`,
`server_utc_offset_hours` (auto-detected in live mode).

### Example output
```
=== M15 | 2026-08-20 12:45:00 | price 4482.98 | range bearish (discount) | candidates above 1 / below 4
  ABOVE: HB  bearish zone 4497.14 - 4497.48  (mid 4497.31, key 4497.14)  dist 14.16 (2.24 ATR)  OF x61  liq->[SH@4494.25]
  BELOW: HB  bullish zone 4472.57 - 4474.04  (mid 4473.31, key 4474.04)  dist  8.94 (1.42 ATR)  OF x66  liq->[SL@4477.96]
```
`OF xN` = number of respected same-direction POIs supporting the candidate,
`liq->[…]` = liquidity resting between price and the POI (the market's *reason* to go there).

---

## 4. Backtest results (CSV: 2026-05-26 → 2026-09-03, 99 281 M1 bars)

Walk-forward: every closed bar → selection; each newly selected POI is then scored
with the *following* bars only. Entry = zone edge, SL = other edge + 0.1 ATR.

| TF | selected | reached % | reaction ≥1 ATR % | hit 1R % | hit 2R % | hit 3R % | avg MFE (ATR) |
|---|---|---|---|---|---|---|---|
| ALL | 3007 | 87.0 | 64.1 | 86.4 | 63.6 | 46.8 | 2.89 |
| M5 | 1443 | 87.4 | 62.9 | 85.3 | 62.6 | 46.2 | 2.70 |
| M10 | 721 | 87.2 | 63.6 | 87.4 | 63.9 | 47.5 | 3.04 |
| M15 | 465 | 86.0 | 66.0 | 88.2 | 67.2 | 48.0 | 2.80 |
| M30 | 252 | 84.5 | 68.1 | 87.3 | 62.4 | 46.5 | 3.50 |
| H1 | 126 | 89.7 | 65.5 | 84.1 | 61.1 | 45.1 | 3.26 |

Per-POI-type breakdown is in `backtest_results/stats.csv` (Hidden Bases have the
highest 1R/2R hit-rate; OBs the biggest average excursion). These are *reaction*
statistics of the POI selection, not a full trading system with entries/management.

---

## 4b. Small-target backtest (0.3R / 0.4R / 0.5R)
Out-of-sample Apr–Sep 2026, quality bot, mid-zone limit entry, SL = far edge + 0.5 ATR, net of spread:
TP 0.3R → +0.083 R/trade (87% win, PF 1.61) · **TP 0.4R → +0.104 R (82%, PF 1.56, DD −9 R)** · TP 0.5R → +0.107 R (77%, PF 1.44)
vs TP 1R → +0.04 R (PF 1.08) and TP 2R → +0.02 R (PF 1.04). Positive on every timeframe and every full month.
Tight stops (+0.1 ATR) are negative at every target — the zone gets swept first. Full report: `study_results/SMALL_TARGETS.md`
(`python compare_modes.py --csv <csv>` then `python report_small_targets.py`).

## 5. Project layout
```
lubot/regime.py            v13 market REGIME from closed daily bars (adr_ratio / er / adr_pct; metric of day D from days < D; latest_metric for the live bot)
run_v13_diag.py            v13 diagnosis of the weak months (v12-A replay, per-month slices, ladder legs reached, regime, filtered-POI replay) -> study_results/v13_diag/
run_v13_levers.py          v13 lever grid on top of v12-A (RG_/LAD_/LOCK_/RISK_ families + neighbourhood, --stress) -> study_results/v13_levers/, v13_levers.csv, v13_stress.csv
run_v13_all.sh / run_v13_stage4.sh / run_v13_neigh.sh   v13 resumable launchers with 4-min autosave (grid / stress / neighbourhood)
walkforward_v13.py         v13 walk-forward + neighbourhood summary from the jsons -> v13_walkforward.csv, v13_neighbourhood.csv
make_v13_report.py         v13 report -> study_results/WEAK_MONTHS_V13.md + charts/v13_*.png
verify_bat_v13.py          replays the exact run_trader.bat strings in the simulator (must equal the v13-A study json)
lubot/martingale.py        v14 Martingale state machine (mult / add / fib / deficit / anti, caps, gates per TF / side / quality / regime, mart_scope all|tf, asymmetric mart_ungated_scale, replay() for the live bot, grid_wanted)
v14_common.py              v14 shared: v13-A config exactly as shipped, year loader, the loss-side judge (gross $ lost, avg loss, worst day %eq, max risk %eq, ulcer, IS/OOS PF)
run_v14_diag.py            v14 diagnosis (streaks, P(win | k losses), post-loss edge per slice, classic schemes on the sequence, drawdown anatomy, MAE buckets) -> study_results/v14_diag/
run_v14_levers.py          v14 grid of 140 sizing variants on top of v13-A (MU/FIB/ADD/DEF/SHR/ANTI/LAD/TF/GR/CMB families, --stress) -> study_results/v14_levers/, v14_levers.csv, v14_stress.csv
shuffle_v14.py             v14 shuffle / block-bootstrap test of the finalists (sizing replayed on resampled trade orders, paired with flat) -> v14_shuffle.csv
walkforward_v14.py         v14 walk-forward on the IS/OOS halves from the trade lists -> v14_halves.csv, v14_walkforward.csv
make_v14_report.py         v14 report -> study_results/MARTINGALE_V14.md + charts/v14_*.png
verify_bat_v14.py          replays the exact run_trader.bat v14-A strings in the simulator (must equal the v14-A study json)
backtest_v14_final.py      FINAL BACKTEST of the shipped v14-A on the CSV (+ v13-A alongside) -> study_results/FINAL_BACKTEST_V14.md, final_v14/*, charts/final_v14_equity.png
smoke_v14.py               v14 smoke run of 16 variants (parity + first look)
v16_common.py              v16 shared: v15-A config exactly as shipped, reference scorecard, judge16, load_year16 (v16 top-K streams cut at max_rank)
record_selections_v16.py   v16 resumable recorder: top-K qualified candidates per side per slot (`rank`), M20 timeframe, monthly chunks with carry-over
run_v16_record.sh          v16 full-year recording Sep25-Sep26 in monthly chunks (all TFs + M20) -> study_results/parts_v16/, merged sel_v16_<TF>.pkl
run_v16_levers.py          v16 grid of 171 variants on top of v15-A (R2 / R2C / R3 / KD / M20 / M20C / M20N / M20SC / CMB families, --stress) -> study_results/v16_levers/, v16_levers.csv, v16_stress.csv
run_v16_all.sh / run_v16_stress.sh   v16 unattended launchers (recorder + grid / stress + walk-forward) with autosave (commit + push) every 4 min
walkforward_v16.py         v16 walk-forward on the IS/OOS halves from the trade lists -> v16_walkforward.csv/json
make_v16_report.py         v16 report -> study_results/MORE_TRADES_V16.md + charts/v16_*.png
verify_bat_v16.py          replays the exact run_trader.bat v16-A strings in the simulator (must equal the v16-A study json)
backtest_v16_final.py      FINAL BACKTEST of the shipped v16-A on the CSV (+ v15-A alongside) -> study_results/FINAL_BACKTEST_V16.md, final_v16/*, charts/final_v16_equity.png
smoke_v16.py               v16 parity smoke (v15-A through the v16 simulator on the v10 streams)
tests/test_v16_levers.py / tests/test_trader_v16.py / tests/test_bat_v16.py   v16 tests (rank slots, rank-2 gates, tf_risk_scale, live ranked lists, M20 live gating, bat == study config)
v15_common.py              v15 shared: v14-A config exactly as shipped, reference scorecard, judge15 (more_trades / more_profit / hold_loss / hold_oos / score)
run_v15_diag.py            v15 diagnosis (funnel, would-be outcome of every rejected POI by band, re-arm after SL, front offset, confluent-vs-plain signal) -> study_results/v15_diag/
run_v15_levers.py          v15 grid of 209 variants on top of v14-A (CS / CM / TIER / DD / CMB families, --stress) -> study_results/v15_levers/, v15_levers.csv, v15_stress.csv
run_v15_all.sh             v15 unattended grid runner with autosave (commit + push) every 4 min
walkforward_v15.py         v15 walk-forward on the IS/OOS halves from the trade lists -> v15_walkforward.csv/json
make_v15_report.py         v15 report -> study_results/MORE_TRADES_V15.md + charts/v15_*.png
verify_bat_v15.py          replays the exact run_trader.bat v15-A strings in the simulator (must equal the v15-A study json)
backtest_v15_final.py      FINAL BACKTEST of the shipped v15-A on the CSV (+ v14-A alongside) -> study_results/FINAL_BACKTEST_V15.md, final_v15/*, charts/final_v15_equity.png
smoke_v15.py               v15 smoke run of 11 variants (parity + first look)
tests/test_v15_levers.py / tests/test_trader_v15.py / tests/test_bat_v15.py   v15 tests (defaults, conviction sizing, memory, tier scope, mart gate, live bot restart, bat strings)
tests/test_v14_martingale.py / tests/test_trader_v14.py / tests/test_bat_v14.py   v14 tests (state machine, caps, gates, sim parity, live bot restart replay vs fake MT5, bat strings)
tests/test_v13_regime.py / tests/test_bat_v13.py / tests/test_trader_live.py::test_v13_*   v13 tests (metric, ladder switch, sim parity, live bot vs fake MT5, bat strings)
run_v12_funnel.py / run_v12_levers.py / run_v12_stress.py / rank_v12.py / make_v12_report.py / verify_bat_v12.py   v12 more-trades study -> study_results/MORE_TRADES_V12.md
lubot/trade_filter.py      v8 per-timeframe TRADE FILTER (cost_r / quality / zone-ATR / sessions / hours / sides / kinds / optional model)
lubot/plan_replay.py       v8 single-plan M1 replayer (same mechanics as portfolio_sim; tests/test_plan_replay.py = parity test)
label_plan_outcomes.py     v8 plan-outcome labels for every training candidate -> models/plan_labels_<TF>.pkl
experiments_m5_filter.py / insample_filter_grid.py   v8 in-sample diagnostics + rule selection (study_results/m5_filter_*.csv, filter_grid_insample_labels.csv)
train_trade_filter.py      v8 optional LightGBM plan-outcome gate (models/trade_filter_M5_*.json; OFF - no skill on the bot's picks)
run_v8_record.sh           v8 chunked, resumable recorder of the M5 stream WITH features (study_results/sel_v8_M5.pkl, parts_v8/)
run_filter_study.py / run_v8_compare.py / run_v8_stress.py / make_v8_report.py   v8 studies -> study_results/TRADER_V8.md, trader_v8_*
run_rm_study.py / rm_insample.py / rm_stress.py / make_rm_report.py / run_v9_all.sh   v9 RISK-MANAGEMENT STUDY (580 exit systems OOS + in-sample + stress) -> study_results/RISK_MGMT_STUDY.md, rm_*
tests/test_rm_systems.py   v9 hand-built M1 scenarios for every management mechanic (partial fraction, BE trigger, trail, ladder, ratchet, time stop, BE offset)
trader.py                  LIVE TRADING BOT (attach to open MT5, no login; limit at zone start, SL zone end; v10 4-leg ladder, v11/v12 confluence + keep-replaced, v13 regime-adaptive ladder, v14 asymmetric martingale sizing via --trader)
lubot/execution.py         v7 TradePlan / TraderConfig / SymbolSpec / sizing
lubot/portfolio_sim.py     v7 M1-precision portfolio simulator (fills on ask/bid, intrabar path, legs, costs, swaps, margin)
lubot/mt5_broker.py        v7 MT5 adapter (orders, positions, place/cancel/modify/close, retcode handling)
record_selections.py       v7 resumable recorder of the scanner's selection stream (input of the simulator)
backtest_trader.py         v7 single portfolio backtest + report;  run_trader_study.py = 35 variants + TRADER_BACKTEST.md
run_v7_record.sh / run_v7_study.sh   resumable launchers;  run_trader.bat / run_trader_dryrun.bat = Windows launchers
tests/fake_mt5.py          in-memory MT5 terminal used by tests/test_trader_live.py
bot.py                     CLI (backtest / scan / live) - v6 scanner
lubot/config.py            StrategyConfig (all thresholds, ATR based)
lubot/data.py              CSV & MT5 loaders, M1→HTF resampler, ATR, Candles view
lubot/structure.py         swings, liquidity, sweeps, EQH/EQL, sessions, QM & trading range
lubot/poi.py               OB / BB / IMB / HB / UW detectors + mitigation tracking
lubot/engine.py            per-TF engine, order-flow filter, rule set, context + HTF-confluence features, 2-POI selection
lubot/indicators.py        v5 indicator set (RSI, Stoch, MACD, ADX, BB, KC, Donchian, VWAP, volume, SuperTrend, EMA ribbon, Ichimoku, pivots, regime)
lubot/levels.py            v6 level memory (rolling volume/time profile, value area, reaction counts of the zone area; lv_/cl_/hlv_ features)
lubot/lgbm_export.py       LightGBM -> bot JSON trees (exact), so the bot runs on numpy only
lubot/quality.py           bounce-probability models (GBM/LightGBM JSON trees, two-member mixing, numpy inference, explanations; v6 = 258 features)
train_v6.py / experiments_v6.py / ablation_v6.py / pilot_v6.py   v6 model + studies
build_all_train_v6.sh / run_v6_parts.sh / summarize_v6.py        v6 resumable pipeline
lubot/trainset.py          compact float32 training-set loader
build_approach_set.py / train_approach.py   v4 approach-stage rows + model
experiments_v5.py          v5 univariate / ablation / regularisation / importance (resumable)
save.sh / restore.sh / PROGRESS.md   checkpoint + recovery
experiments_v4*.py         v4 grids (params, feature groups, touch-time PA, rolling origin, approach stage)
experiments_v3.py / experiments_v3b.py   v3 model grids (features, regularisation, bagging)
rescore_imputed_spread.py  re-price cached results with the imputed spread
experiments_gbm.py         model / regularisation grid on a train-val-test time split
lubot/study.py             bounce study (M1-precision scoring, scenarios)
build_training_set.py / train_quality.py / compare_modes.py   model pipeline
lubot/backtest.py          walk-forward backtest & statistics
lubot/plotting.py          chart rendering
lubot/mt5_connector.py     MetaTrader5 connection / rates / live price
tests/                     131 tests (detectors, execution, portfolio sim, plan replay parity, live trader vs fake MT5, trade filter, management systems, regime, martingale)
backtest_results/          stats.csv, charts/
v16b_common.py             v16b shared: v16-A config exactly as shipped (cross-checked against the bat), REF16B, judge16b (less_loss / hold_profit / hold_oos / no_worse_day)
run_v16b_diag.py           v16b diagnosis of the 114 stop-outs of v16-A (side, counter-trend, regime x side, fill age, MFE path, clusters, static estimate) -> study_results/v16b_diag/
run_v16b_levers.py         v16b grid of 96 variants on top of v16-A (T trend gate / F fast-fill guard / RS range-sell size / BE / DL / C_ combos, --stress) -> v16b_levers/, v16b_levers.csv, v16b_stress.csv
run_v16b_all.sh / run_v16b_stress.sh / run_v16b_final.sh   v16b resumable launchers with 4-min autosave (grid / stress + walk-forward / final backtest + verify)
judge_v16b_stress.py       v16b stress judged scenario by scenario vs the v16-A rows of v16_stress.csv -> v16b_stress_judged.csv, v16b_stress_summary.csv
walkforward_v16b.py        v16b walk-forward on the IS/OOS halves from the trade lists -> v16b_walkforward.csv/.json
backtest_v16b_final.py     FINAL BACKTEST of the bat strings (v16b-A) with the v16-A reference alongside -> study_results/FINAL_BACKTEST_V16B.md, final_v16b/*
verify_bat_v16b.py         replays the exact run_trader.bat strings in the simulator (must equal the v16b-A study json)
make_v16b_report.py        v16b report -> study_results/LESS_LOSS_V16B.md + charts/v16b_*.png
smoke_v16b.py              v16b parity smoke (v16-A through the v16b simulator = 467 / +301.75 / -5.82)
tests/test_v16b_levers.py, tests/test_trader_v16b.py, tests/test_bat_v16b.py   v16b lever / live fake-MT5 / bat tests
```

## 6. Not implemented / next steps
- v7 trader: trailing stop after TP2 / time-based exit, news filter, Telegram alerts of fills (per-timeframe risk: done in v16, `tf_risk_scale`; pre-fill loss filters: done in v16b)
- v16b follow-ups: judge v16b-A on the demo account (stop %, $ lost, DD, worst day, PF vs FINAL_BACKTEST_V16B); if the live fast-fill guard costs more than one spread per case, try `fast_fill_tfs=M5|M10` (F3_m510, the most robust single lever in the stress); a native pending-order expiry per bar would make the guard free
- Retrain the quality model on data that includes bearish gold months (sells under-perform OOS) - after v16 this is THE remaining lever: more trades at the same loss percentage now needs a better entry model, not more trade sources or admission rules
- Trend-line liquidity (needs a subjective line-fit; not used for POI selection)
- Entry models from the PDF (Confirmation / PA / Direct entry), stacking, hedging – the bot delivers the POIs; execution is left to the trader or a follow-up module
- Order placement through MT5 (`order_send`) – easy to add on top of `select()`
- Telegram / webhook alerts when a selection changes (`--json` already exposes the state)

Last updated: 2026-10-10 (v16b: fast-fill guard 2 min + range-regime sells at half size — 446 trades / +33 831 $ / DD 5.55 % / PF 3.00 / stop-outs 23.8 % / $ lost -16 921 (-23 %) vs v16-A 467 / +30 175 / 5.82 / 2.37 / 24.4 / -22 102; FINAL_BACKTEST_V16B.md)
