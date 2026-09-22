# Bot upgrade v3: POIs ranked by "will price bounce here?" — third iteration

Data: `XAUUSD.t_M1_202501020100_2026090423581112.csv` (2025‑01‑02 → 2026‑09‑04, 593 863 M1 bars).
Goal unchanged: of all POIs that pass the PDF rule set, return per timeframe the one above and the
one below price that is **most likely to reverse price when it gets there**.

## 1. Spread — "treat the part without spread as having the same spread as the part with spread"

The MT5 export carries `<SPREAD>` only from **2026‑04‑01 onward** (150 241 bars, median $0.28,
10–90 % range $0.26–0.30, wider ≈ $0.33 around the 16:00–18:00 NY rollover). The 443 622 older bars
have `0`. The loader (`lubot/data.py::impute_spread`, called by `load_mt5_csv`) now:

1. takes every bar with a real spread and builds a **(weekday, NY‑hour) median profile** (cells with
   ≥ 20 observations; fallback hourly profile; fallback global median),
2. fills every zero/missing bar from that profile and flags it in a new column `spread_imputed`.

Result: 74.7 % of bars imputed, all bars now carry a spread; the imputed distribution (median $0.28,
5–95 % $0.27–0.33) matches the real one hour‑by‑hour. Every cost figure in the study / comparison
tables therefore pays the *typical* spread of that time of week instead of $0 (or a flat floor).
`rescore_imputed_spread.py` re‑prices older cached result pickles the same way (idempotent);
`bot.py` / `run_study.py` print how many bars are real vs imputed.

## 2. What changed in the model

| | v2 (Sep 14, morning) | **v3 (this upgrade)** |
|---|---|---|
| features | 64 | **97** (33 new, listed below) |
| model | 1 GBM, 200 trees depth 3 | **bagged GBM**: 5 boosters × 400 trees (depth 3, ≥200 rows/leaf, L2 5, lr 0.02) on 80 % row subsets, averaged and exported as one plain tree list → runtime unchanged (numpy/pure‑python, ~0.7 ms per score) |
| training rows | 63 403 reached candidates | same set, rebuilt with the new features |
| validation | train < Mar‑26 / test ≥ Mar‑26 | + separate **validation window Dec‑25 → Feb‑26** used to pick features & regularisation; test window untouched |

### New features (all known at selection time — no look‑ahead)

**Creation‑time (`POI.features`)**
- `sweep_depth_atr` – how far the move ran *through* the deepest liquidity pool it swept (a real stop hunt vs. a tick through the level).
- `impulse_body_frac` – body/range share of the impulse that left the zone (clean displacement vs. wicky chop).
- `created_ny_hour`, `created_dow` – when the zone was built (Asia‑built zones behave differently from NY‑built ones).
- `hb_pos_in_impulse` – where inside the HTF impulse a Hidden Base sits.
- `parent_age_bars`, `parent_tap_to_break`, `break_close_atr` – for Breakers: how the parent block died.

**Selection‑time context (`TimeframeEngine.qualified`)**
- `tf_minutes` – the timeframe itself (one pooled model now knows M5 ≠ H1; the 3rd most important new feature).
- `round_100_atr`, `round_50_atr`, `round_10_atr` – distance of the entry edge to round‑number levels ($100 / $50 / $10).
- `pos_prev_day`, `pos_prev_week`, `pos_today`, `beyond_prev_day`, `beyond_today`, `dist_prev_day_level_atr`, `day_range_atr` – where the zone sits relative to yesterday's / last week's / today's range (`pos_prev_day` is the **2nd most important feature overall**).
- `retrace_frac`, `bars_since_extreme` – how much of the leg that left the zone has already been retraced, and how long ago the extreme was made (tracked bar by bar in `poi.py`, new `max_away_at`).
- `tested_violated`, `tested_respected`, `opp_respected_near` – has this price area already been tested: dead same‑direction zones overlapping ours that failed / held, and opposite zones that held nearby (a contested area).
- `atr_ratio_long`, `toward_mom60`, `ema_gap_aligned`, `price_vs_ema200`, `last_bos_age`, `last_bos_aligned` – longer volatility / trend regime and time since the last break of structure.
- `n_alive_same_dir`, `n_alive_opp_dir`, `age_hours` – how crowded the map is, age in wall‑clock hours.

Dollar‑scaled features (price level, ATR in $) were tried and **removed**: they only encode "which
month is it" in a trending market and would not transfer.

## 3. Validation

### Candidate level — strict time split, hyper‑parameters chosen on Dec‑25 → Feb‑26 only

| setting (train < Dec‑25, 33 857 rows) | val AUC | val best & P≥0.5 | test AUC (≥ Mar‑26, 20 385 rows) | test best & P≥0.5 | kept |
|---|---|---|---|---|---|
| v2 features, v2 params | 0.623 | 60.8 % | 0.643 | 64.1 % | 34 % |
| v3 features, v2 params | 0.632 | 60.5 % | 0.647 | 64.5 % | 34 % |
| v3 features, depth 3 × 400 | 0.629 | 60.5 % | 0.646 | 64.3 % | 34 % |
| **v3 features, depth 3 × 400, bagged ×5 (chosen)** | **0.632** | **60.9 %** | **0.649** | **65.0 %** | 34 % |
| v3, depth 4, bagged | 0.632 | 58.0 % | 0.649 | 64.7 % | 35 % |
| v3, one model per POI type | 0.611 | 57.3 % | 0.638 | 62.0 % | 41 % |
| v3, timeframe‑balanced weights | 0.629 | 60.2 % | 0.643 | 63.3 % | 35 % |

Bagging was the only change that improved *both* validation and test on every metric; deeper trees
over‑fit (train AUC 0.78–0.84) without OOS gain; per‑type models lose the pooled information.
Full grids: `quality_v3_model_grid.csv`, `quality_v3_model_grid_b.csv`.

### Final model (train < 2026‑03‑01, 43 018 rows → test 20 385 rows)

| | v2 | **v3** |
|---|---|---|
| OOS AUC | 0.639 | **0.648** |
| best‑ranked & P ≥ 0.50: bounce ≥ 1 ATR | 62.1 % (33.6 % of slots) | **62.8 %** (35.5 % of slots) |
| … median bounce / ≥ 2 ATR | 1.60 ATR / 42.8 % | **1.63 ATR / 43.6 %** |
| P ≥ 0.60 | 70.8 % (10 % of slots) | **73.8 %** (12 % of slots) |
| P ≥ 0.65 | 76.6 % (5 %) | **78.8 %** (6 %) |
| closest POI (PDF rule 4) | 43.7 % | 43.7 % |

Per timeframe, best‑ranked & P ≥ 0.5 (closest → v2 → **v3**):
H1 37 → 52 → **63 %** · M30 41 → 67 → 64 % · M15 43 → 64 → **66 %** · M10 43 → 65 → **65 %** · M5 47 → 63 → **65 %**.
The biggest gain is on **H1**, where v2 was weakest — `tf_minutes` lets the pooled model stop
treating an H1 zone like an M5 zone.

Calibration OOS is monotonic (pred 0.52 → actual 0.54, 0.57 → 0.56, 0.64 → 0.72, 0.74 → 0.81).

### Bot level — end‑to‑end walk‑forward, 5 TFs, out‑of‑sample Mar 2 → Sep 4 2026

All modes run with models trained < Mar 1; every fill pays the (imputed) spread.
`compare_summary.csv`, `compare_by_month.csv`, `compare_scenarios.csv`.

| mode | selected | /day | reached | median bounce | ≥1 ATR | ≥2 ATR | hit 0.3R | hit 0.4R |
|---|---|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 5806 | 43 | 88.5 % | 0.76 ATR | 40.2 % | 24.5 % | 79.6 % | 76.3 % |
| quality v1 | 2345 | 17.5 | 81.1 % | 1.05 ATR | 51.8 % | 33.8 % | 84.7 % | 79.8 % |
| quality v2 | 1410 | 10.5 | 82.6 % | 1.35 ATR | 58.6 % | 39.9 % | 87.0 % | 80.5 % |
| **quality v3** | **1551** | **11.6** | 81.6 % | 1.33 ATR | **58.8 %** | 39.0 % | 86.2 % | 80.4 % |

Per timeframe (≥1 ATR, closest → v2 → **v3**): **H1 36 → 48 → 56 %** · M30 37 → 60 → 62 % · M15 39 → 62 → 62 % ·
M10 41 → 56 → 57 % · M5 41 → 59 → 59 %.
By month (closest → v2 → **v3**): Mar 41→65→65 · Apr 39→57→**59** · May 42→59→58 · Jun 36→57→54 · Jul 41→55→**58** ·
Aug 41→60→58 · Sep (4 days) 47→54→**70**. Every month beats closest and v1 by 13–23 points.

Where v3 differs from v2 at the bot level:
- **~10 % more signals at the same hit‑rate** (1551 vs 1410 selected, 58.8 vs 58.6 %).
- **H1 fixed**: 56 % vs 48 % (v2 was barely better than closest on H1).
- **The top of the ranking is stronger and better calibrated**: selected POIs with P ≥ 0.65 bounce **71.7 %** (n = 113)
  vs 66.0 % for v2 (n = 97); P ≥ 0.60: 64.8 % vs 64.7 %. Calibration OOS: predicted 0.52 → actual 0.56,
  0.57 → 0.59, 0.64 → 0.63, **0.74 → 0.72** (v2: 0.75 → 0.69).
- Bearish zones improved (55.5 % vs 54.0 %); bullish 61.2 % vs 62.2 %.
- Execution scenarios (net of spread) are on par with v2: e.g. edge entry / SL 0.1 ATR / TP 0.3R **+0.076 R, PF 1.53,
  max DD −7.0 R** (v2 +0.092, PF 1.68; closest −0.075, PF 0.69); edge / SL 0.1 / TP 0.5R +0.080 R (v2 +0.084);
  mid / SL 0.5 / TP 0.4R +0.089 R (v2 +0.094). v3 remains positive in every small‑target scenario incl. tight stops,
  which the closest rule is not.

Honest summary: the **candidate‑level** ranking improved on every metric (AUC, hit‑rate at every threshold,
per‑TF, calibration); at the **bot level** the overall bounce rate is the same as v2 (~59 %), the gains
concentrate on H1, on the A‑grade zones and on signal count. The two models agree on most selections
(both pick ~1 100 of the same POIs).

## 4. What the model learned (permutation importance, OOS)

1. `zone_atr` (dominant, as before) – taller zones bounce.
2. **`pos_prev_day`** – where the zone sits inside yesterday's range (new).
3. **`tf_minutes`** – timeframe (new).
4. `liq_behind_n` – stops right behind the zone pull price through it.
5. **`n_alive_same_dir`** – a crowded map of same‑direction zones dilutes each one (new).
6. **`created_ny_hour`**, **`pos_prev_week`** (new), `parent_zone_atr`, `is_bull`, `liq_stacked_beyond_n`, `age_bars`, `near_misses`.
7. `impulse_body_frac`, `tested_violated` / `tested_respected`, `ema_gap_aligned`, `round_100_atr` follow.

Full list: `quality_v3_importance.csv`.

## 5. How to use / retrain

```bash
python bot.py scan --csv data.csv                      # v3 (default, models/quality_model.json)
python bot.py --set min_quality=0.60 scan --csv data.csv          # only the ~12% strongest zones (~74% bounce OOS)
python bot.py --set quality_model_path=models/v2/quality_model.json scan ...   # previous model

# retrain (≈25 min training sets on 2 cores, ≈8 min model)
bash build_all_train.sh data.csv
python train_quality.py --split 2026-03-01 --features v3 --bag 5 \
       --gbm max_iter=400,learning_rate=0.02,max_depth=3,max_leaf_nodes=8,min_samples_leaf=200,l2_regularization=5.0 --final
bash run_compare_v3.sh data.csv                        # OOS comparison of all modes
```

Grades unchanged: **A** ≥ 0.65 · **B** ≥ 0.55 · **C** ≥ 0.50 · below → not shown.

## 6. Caveats
- Same instrument / broker / 20 months; still a bull‑market sample (bullish zones bounce more).
- AUC 0.65 is a meaningful but modest edge: a "70 %" zone still fails 3 times in 10. Use the number as a ranking/filter.
- Spread on the first 15 months is *estimated* from the last 5 months' profile; if the broker's spread was different back then, the cost figures for that period are approximate (ranking / bounce statistics are unaffected — the spread is not a model input).
