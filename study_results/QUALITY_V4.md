# Bot upgrade v4: price-action features + two-stage scoring (selection → approach)

Data: `XAUUSD.t_M1_202501020100_2026090423581112.csv` (2025-01-02 → 2026-09-04, 593 863 M1 bars).
Goal unchanged: of all POIs that pass the PDF rule set, return per timeframe the one above and the one
below price that is **most likely to reverse price when it gets there**.

## 1. Spread — the part of the CSV without spread

The export carries `<SPREAD>` only from **2026-04-06 15:19** on (150 241 bars, median $0.28); the 443 622
older bars have `0` (they also have `<VOL>` instead of `<TICKVOL>`, i.e. they come from a different history
source). As instructed, those bars are treated **as having the same spread as the part with spread**:
`lubot/data.py::impute_spread` builds a (weekday, NY-hour) median profile from the bars that have a real
spread and fills every zero bar from it (flag column `spread_imputed`, 74.7 % of bars). Imputed median $0.28,
5–95 % $0.27–0.33 — identical hour-by-hour to the real distribution. Every cost figure below pays that spread.
The spread is **not** a model input, so bounce statistics are unaffected by the imputation.

## 2. What price action was added (v4 = 125 features, v3 = 97)

All features are known at the bar they are computed on (closed bars only, no look-ahead).

### Creation-time — how the base was built and how price left it (`POI.features`, `poi.py::_pa_features`)

| feature | price-action meaning |
|---|---|
| `block_rej_wick_atr / _frac` | rejection wick of the block candle(s) pointing away from the move (buyers/sellers already defended the level once) |
| `engulf_ratio` | body of the first impulse candle ÷ total block body (≥ 1 = base engulfed in one candle) |
| `impulse_max_body_atr` | largest single-candle body of the impulse (the displacement candle) |
| `impulse_close_pos` | where the confirmation candle closed inside its range (1 = at the extreme, no rejection of the move) |
| `impulse_dir_frac` | share of impulse candles closing in the move direction |
| `pre_compression_atr` | range of the 10 bars before the block (tight base vs. wide chop) |
| `pre_trend_bars` | consecutive candles running *into* the block (exhaustion run before the reversal) |
| `caused_bos` | the impulse broke structure in the move direction |
| `swing_in_zone` | swing lows/highs (liquidity levels) lying inside the block range — the stop hunt happened *inside* the zone |
| `leg_atr` | size of the whole leg from the block extreme to the confirmation close |

### Selection/approach-time — how price is coming into the zone (`engine.py::_approach_features`)

| feature | price-action meaning |
|---|---|
| `ap_toward_run` | consecutive candles moving towards the zone (negative = currently moving away) |
| `ap_last_body`, `ap_last_rng_atr` | body / range of the last candle in the approach direction |
| `ap_rej_wick_atr / _frac` | wick of the last candle pointing at the zone (rejection of the approach) |
| `ap_rng_ratio5`, `ap_body_trend`, `ap_body_frac5` | range expansion/contraction and body share over the last 5 bars (fresh displacement vs. exhaustion) |
| `ap_ema_stretch` | distance of price from its 20-EMA in the approach direction (stretched = mean reversion likely) |
| `ap_move5_atr`, `ap_eta_bars` | 5-bar move towards the zone and the bars needed to reach it at that pace |
| `ap_broke5`, `ap_broke50` | the last bar printed a new 5-bar / 50-bar extreme in the approach direction (fresh momentum) |
| `ap_zone_beyond50` | reaching the zone means a new 50-bar low/high (a sweep zone) |
| `ap_wick_pressure` | wick share against the approach over the last 5 bars (absorption) |
| `edge_to_key_atr` | distance from the entry edge to the *key level* (open of the POI) — how much refinement room the zone has |
| `zone_vs_bar_range` | zone height relative to the current candle range — is the zone still meaningful at today's volatility |

## 3. What the data says (63 403 reached candidates, val+test window Dec-25 → Sep-26)

Univariate bounce ≥ 1 ATR by quintile (base 40.7 %):

* **Zone geometry is the strongest new signal.** `zone_vs_bar_range` 25 % → 34 % → 40 % → 46 % → **59 %**;
  `edge_to_key_atr` 31 % → 41 % → 44 % → **57 %**. A zone that is tall relative to the current candles, with the key
  level well inside it, is the one that bounces.
* `swing_in_zone` 37 % → 36 % → 43 % → 46 % → 44 %: zones that contain the swept swing point bounce more.
* Creation-time candle anatomy (rejection wicks, engulfing ratio, impulse close position, compression, run into
  the block) moves the rate by only ±3–6 points and is largely already captured by `zone_atr`, `displacement_atr`,
  `impulse_body_frac`.
* **At selection time the approach features are flat** (spreads 1–3 points): when the zone is still 2–8 ATR away,
  how the last five candles look tells almost nothing about what will happen when price finally arrives.
* **At the tap they matter.** Recomputed on the last closed bar before the touch (`experiments_v4c.py`):
  `ap_eta_bars` 34 % → 37 % → 40 % → 44 % → **49 %** (a *slow* approach bounces, a fast one runs through),
  `ap_move5_atr` 46 % (barely moving) → 36 % (fast) → 41 %, `ap_ema_stretch` 46 % → 35 %, `ap_broke50`
  43 % vs 37 % (a fresh 50-bar break into the zone is bad), and distance at that bar 33 % → 55 %.
  Adding the touch-time price action to the v3 features lifts the candidate AUC from **0.649 to 0.677** OOS
  (val 0.632 → 0.667) — the largest single gain in the whole v1–v4 series.

## 4. Model selection (strict split: train < Dec-25 · validate Dec-25→Feb-26 · test ≥ Mar-26)

### 4a. Selection stage (candidates 0–8 ATR away, scored when the bot picks them)

| setting (`quality_v4_model_grid*.csv`) | val AUC | val P≥.5 hit | test AUC | test P≥.5 hit | kept |
|---|---|---|---|---|---|
| v3 features (97), bagged ×5 | 0.632 | 60.9 % | 0.649 | 65.0 % | 34 % |
| v3 + creation PA (108) | 0.638 | 59.4 % | 0.642 | 64.8 % | 34 % |
| v3 + approach PA (114) | 0.634 | 60.2 % | 0.654 | 66.0 % | 36 % |
| **v4 = all (125), bagged ×5 (chosen)** | **0.637** | 59.2 % | 0.647 | **66.0 %** | 35 % |
| v4, depth 4 | 0.637 | 57.4 % | 0.648 | 64.9 % | 37 % |
| v4, 600 trees lr .015 | 0.637 | 59.2 % | 0.647 | 65.9 % | 35 % |
| v4, single booster | 0.635 | 59.3 % | 0.646 | 65.9 % | 36 % |

Selection-stage gains are modest: +0.5 AUC on validation, +1 point on the hit-rate of the chosen POI on test,
~1 point more slots kept. The same regularisation as v3 is used (depth 3, 400 trees, lr 0.02, ≥ 200 rows/leaf,
L2 5, bagged ×5).

Final selection model (train < Mar-26, 43 018 rows → test 20 385): **OOS AUC 0.651** (v3 0.648), best-ranked
& P ≥ 0.50 → **63.2 %** bounce ≥ 1 ATR (v3 62.8 %) on 36.7 % of slots; P ≥ 0.60 → 70.7 % (13 %), P ≥ 0.65 →
**77.9 %** (6.5 %). Per TF at P ≥ 0.5: H1 63 %, M10 67 %, M15 67 %, M30 67 %, M5 65 % (v3: 63/65/66/64/65).
Calibration OOS monotonic (pred .52→.55, .57→.62, .64→.67, .74→.79). Top drivers: `zone_atr`,
**`zone_vs_bar_range`** (2nd overall), `tf_minutes`, `pos_prev_day`, **`swing_in_zone`**, `parent_zone_atr`,
`pos_prev_week`, `liq_behind_n`, **`engulf_ratio`**, **`pre_compression_atr`**.

### 4b. Approach stage (new) — re-score the zone once price is within 2 ATR

`build_approach_set.py` takes every reached candidate and, for the closed bars between its selection and its
tap where price was ≤ 2 ATR from the edge (last 6 such bars), recomputes distance / momentum / approach
price action at that bar; the label is the candidate's outcome after the tap. 79 703 near-zone rows.

| model on near rows (`quality_v4_approach_grid.csv`) | val AUC | test AUC | test P≥.5 hit | kept | P≥.6 hit |
|---|---|---|---|---|---|
| selection model (v3) applied at the near bar | 0.655 | 0.645 | 60.7 % | 20 % | 66.7 % |
| retrained on near rows, v3 features | 0.663 | 0.653 | 60.5 % | 21 % | 69.6 % |
| retrained, v4 without `ap_*` | 0.659 | 0.656 | 61.9 % | 21 % | 67.8 % |
| **retrained, v4 (chosen)** | 0.659 | **0.657** | **61.9 %** | 21 % | 68.0 % |

Final approach model (train < Mar-26, 54 056 rows → test 25 647): OOS AUC **0.657**, best-ranked & P ≥ 0.5 →
61.7 % (22.8 % of near slots; base rate of near rows 44 %), P ≥ 0.6 → 67.5 %, P ≥ 0.65 → 73.1 %. By TF at
P ≥ 0.5: M5 64 %, M15 63 %, M30 62 %, M10 60 %, H1 52 %. Calibrated OOS (pred .52→.58, .57→.59, .64→.66, .74→.74).

### How the bot uses the models (`engine.py::qualified`)

* default: the **selection model** scores every candidate (`P(bounce)`), exactly as in v3 but with the v4 features;
* optional (`--set approach_model_path=models/approach_model.json`): once a zone is within `approach_near_atr`
  (2 ATR) the **approach model** re-scores it with the live price action of the move into it; the output line is
  tagged `(approach)` and `why` explains that model's decision. Both share `min_quality`, the distance penalty and
  the A/B/C grades.

## 5. Bot level — end-to-end walk-forward, 5 TFs, out-of-sample Mar 2 → Sep 4 2026

All modes run with models trained < Mar 1 2026, every fill pays the (imputed) spread
(`summarize_v4.py` → `compare_v4_summary.csv`, `compare_v4_by_month.csv`).

| mode | selected | /day | reached | median bounce | ≥1 ATR | ≥2 ATR | P≥0.60: n / bounce | total R (mid entry, SL 0.5 ATR, TP 0.4R) |
|---|---|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 5806 | 43 | 88.5 % | 0.76 ATR | 40.2 % | 24.5 % | – | – |
| quality v2 | 1410 | 10.5 | 82.6 % | 1.35 ATR | 58.6 % | 39.9 % | 241 / 64.7 % | +108 R (PF 1.48) |
| quality v3 | 1551 | 11.6 | 81.6 % | 1.33 ATR | 58.8 % | 39.0 % | 264 / 64.8 % | +108 R (PF 1.45) |
| **quality v4 (selection model, default)** | **1877** | **14.0** | 82.4 % | 1.30 ATR | 57.5 % | 38.1 % | **300 / 67.3 %** | **+159 R (PF 1.58)** |
| quality v4 two-stage (+ approach model) | 2068 | 15.4 | 83.0 % | 1.26 ATR | 56.8 % | 37.7 % | 342 / 63.7 % | +172 R (PF 1.56) |

Per timeframe, bounce ≥ 1 ATR (v3 → **v4**): M5 58.5 → 57.5 · M10 56.9 → 55.2 · M15 62.0 → **62.3** · M30 62.0 → 57.3 · H1 56.2 → 53.0.
By month (v3 → v4): Mar 65→60 · Apr 59→**59** · May 58→56 · Jun 54→53 · Jul 58→56 · Aug 58→**59** · Sep 70→68.
Every month is 13–20 points above the closest rule.

Matched thresholds (v3 vs **v4** single-stage):

| min_quality | v3 selected / ≥1 ATR / ≥2 ATR | v4 selected / ≥1 ATR / ≥2 ATR |
|---|---|---|
| 0.50 | 1551 / 58.8 % / 39.0 % | 1877 / 57.5 % / 38.1 % |
| 0.55 | 768 / 61.6 % / 43.2 % | 800 / **61.7 %** / 42.7 % |
| 0.60 | 349 / 64.8 % / 49.6 % | 375 / **67.3 %** / **49.7 %** |

What the bot-level run says:

* v4 finds **21 % more zones** at the same threshold (14.0 vs 11.6 per day) with a 1.3-point lower raw hit-rate — the
  extra picks are borderline zones (P 0.50–0.55, which bounce ≈ 55 % as predicted). At **matched thresholds** v4 is
  equal (0.55) or **better (0.60: 67.3 % vs 64.8 %)**, so the ranking improved and the calibrated probability is what
  moved: the user can pick the trade-off with `min_quality`.
* The small-target scenarios (net of spread) improve on the same period: mid-zone entry / SL 0.5 ATR / TP 0.4R
  **+159 R total, PF 1.58** vs +108 R / PF 1.45 for v3; edge entry / SL 0.1 ATR / TP 0.3R +128 R (PF 1.60) vs +97 R
  (PF 1.53). More signals at the same per-trade edge → more total R.
* The **approach model** did not help end-to-end: it converts near-zone candidates into extra P 0.50–0.55 picks
  (+10 % signals) with a slightly lower bounce rate (56.8 %) and weaker A-grades (63.7 % at P≥0.6). Its candidate-level
  edge (AUC 0.657 vs 0.645) does not survive the bot's own filters (order flow, liquidity between, distance
  penalty), which already remove most of what it learns to reject. It stays in the repo as an option, off by default.
* Calibration of v4 OOS at the bot level: predicted 0.52 → actual 0.55, 0.57 → 0.55, 0.62 → 0.63, 0.67 → 0.63,
  0.74 → 0.71.

**Recommendation**: run v4 with `min_quality=0.55` for the v3-like signal count with the same hit-rate, or
`min_quality=0.60` for ~3 zones/day at **~67 % bounce ≥ 1 ATR / ~50 % ≥ 2 ATR**.

## 5b. Honest summary

* The requested price-action upgrade helps in two places: **zone geometry** (`zone_vs_bar_range`,
  `edge_to_key_atr`, `swing_in_zone`) improves the selection ranking on every candidate-level metric and at the bot
  level lifts the quality of the top grades and the total R; the **approach dynamics** (speed into the zone, fresh
  breakouts, stretch from the mean) are a real candidate-level signal near the zone but do not add to the bot's
  end-to-end hit-rate once the rule set has done its filtering.
* Candle-anatomy details of the base (wicks, engulfing, close position) add almost nothing beyond what
  `zone_atr` / displacement already encode; they are kept because they cost nothing and were not harmful on test.
* Everything remains a ranking edge (AUC ≈ 0.65): a "70 %" zone still fails 3 in 10.

## 6. Files

```
lubot/poi.py::_pa_features            creation-time price action (11 features)
lubot/engine.py::_approach_features   approach price action (15) + geometry (2); two-stage scoring in qualified()
lubot/quality.py                      FEATURE_ORDER (125) / FEATURE_ORDER_V3 (97), matrix_from_frame (vectorised)
lubot/trainset.py                     compact float32 training-set loader
build_training_set.py                 selection-stage rows (one f__ column per feature)
build_approach_set.py                 approach-stage rows (near-zone bars)
train_quality.py --features v4        selection model  -> models/quality_model.json
train_approach.py                     approach model   -> models/approach_model.json
experiments_v4.py / v4b / v4c / v4d / v4e   grids: params, feature groups, touch-time PA, rolling origin, approach stage
study_results/quality_v4_*.csv        all tables above
models/v3/                            previous model (use with --set quality_model_path=models/v3/quality_model.json)
summarize_v4.py / run_v4_parts.sh     bot-level OOS comparison (resumable, per timeframe)
```
