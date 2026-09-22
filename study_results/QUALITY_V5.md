# Bot upgrade v5: classic indicators as POI-quality context

Data: `XAUUSD.t_M1_202501020100_2026090423581112.csv` (2025-01-02 → 2026-09-04, 593 863 M1 bars).
Goal unchanged: of all POIs that pass the PDF rule set, return per timeframe the one above and the one
below price that is **most likely to bounce price when it gets there**. v5 adds **94 indicator features**
on top of the v4 structure / price-action features (219 model columns).

## 1. Spread — the part of the CSV without spread

The export carries `<SPREAD>` only from **2026-04-06 15:19** on (150 241 bars, median 28 points = $0.28);
the 443 622 older bars have `0` (they come from a different history source: `<VOL>` instead of `<TICKVOL>`).
As instructed, those bars are treated **as having the same spread as the part with spread**:
`lubot/data.py::impute_spread` builds a (weekday, NY-hour) median profile from the bars that carry a real
spread and fills every zero bar from it (flag column `spread_imputed`, 74.7 % of bars). Every cost figure in
the bot-level tables pays that spread. The spread is **not** a model input.

The same scale break exists for volume (old `VOL` median 12 vs new `TICKVOL` median 207). Volume is
therefore only used **relative to its own rolling 50-bar median** (`relvol`, OBV / MFI on relvol), so the
model cannot learn the calendar date from the volume level.

## 2. What was added (`lubot/indicators.py`, `IndicatorSet`)

All series are computed once per timeframe from closed bars and read at bar `i` only (unit test
`test_indicators_are_backward_looking` changes every bar after `i` and asserts nothing at `i` moves).
Every signed quantity is **oriented to the zone direction**: positive = the indicator favours a bounce from
that zone (oversold RSI for a bullish zone, overbought for a bearish one, …), so one model serves both sides.

| group | indicators | features |
|---|---|---|
| **creation** `cr_*` (22) — indicator state when the base was built | RSI (level, regular divergence at the block), Stochastic, MACD histogram, ADX / DI *against* the coming move, Bollinger / Keltner pierce of the block extreme, BB width, relative volume of block and impulse, volume climax, OBV confirmation, SuperTrend flip in the impulse, EMA-ribbon alignment, zone vs EMA50 / session VWAP, distance to the nearest daily pivot, ATR percentile (500-bar), Choppiness, CCI, fib depth of the zone in the 55-bar range | `poi.py::_ind_features` |
| **selection** `ind_*` (61) — state at the bar the bot ranks the candidate | RSI level / slope / regular & hidden divergence (from the tracked swing points), Stoch K/D/cross, MACD line/hist/slope, ADX / slope / DI spread, Bollinger %B / width / squeeze and *zone beyond band*, Keltner, Donchian 20/55 position, fib depth of the zone (20 / 55) and **OTE (61.8–78.6 %)**, CCI, Williams %R, ROC, session VWAP distance / slope / zone at VWAP ±1σ/±2σ, relative volume, volume trend, OBV slope, climax, SuperTrend direction / distance / age, EMA-8/21/50/200 ribbon, zone at a MA (count of EMA21/50/200, SMA20, Kijun inside the zone), Ichimoku Kijun / cloud, daily pivots (distance, which pivot, zone at pivot), ATR percentile, Choppiness, efficiency ratio, MFI, Ultimate oscillator, bars since the last RSI extreme | `engine.py::qualified` |
| **HTF** `htf_*` (11) — parent-TF state (M5→M30, M10/M15→H1, M30/H1→H4) | RSI, ADX, DI, MACD hist, SuperTrend, EMA ribbon, BB %B, zone vs EMA50, ATR percentile, Stoch, zone beyond BB | `engine.py::_htf_features` |

`bot.py` prints one `indicators:` line per returned POI (RSI, ADX with/against, zone vs BB, squeeze,
MA-confluence count, VWAP band, pivot, OTE, SuperTrend, HTF RSI, relvol, ATR percentile).

## 3. What the data says (63 403 reached candidates)

Univariate bounce ≥ 1 ATR by quintile on the val+test rows (base 40.7 %, `quality_v5_univariate.csv`):

* **`cr_atr_pctile`** (volatility regime when the zone was built) is the strongest new feature:
  37.7 → 35.3 → 41.1 → 38.8 → **50.7 %**. Zones built in the top-quintile volatility regime bounce 10
  points more often — a high-volatility displacement leaves a base that is respected.
* `cr_macd_hist_aligned` 38 → 37 → 41 → 40 → **47 %**: a base whose impulse already turned the MACD
  histogram in the zone direction.
* `cr_adx` 34 % in the lowest quintile vs 42–43 % otherwise: bases built in a no-trend chop are weak.
* `cr_rsi_extreme` / `cr_stoch_extreme` are **inverted**: 46 % when the block formed with RSI *against* the
  zone direction (bullish block built with RSI high) vs 37–40 % for blocks built at an oversold extreme.
  A block that appears in an already-oversold market is often just a pause inside the sell-off.
* Selection-time oscillators are flat: `ind_rsi_aligned` 40–42 % across quintiles, `ind_adx` 42→39,
  `ind_di_aligned` 41→38, `htf_rsi_aligned` 39–42 — when the zone is still 2–8 ATR away, the oscillator of
  the current bar says almost nothing about what happens on arrival (same finding as the v4 approach
  features). Binary confluence flags (zone beyond BB, at a MA, at a VWAP band, at a pivot, in OTE,
  SuperTrend aligned) each move the rate by < 1 point.

## 4. Model selection (strict split: train < Dec-25 · validate Dec-25→Feb-26 · test ≥ Mar-26)

Bagged ×5 GBM, v4 production parameters unless stated (`quality_v5_model_grid.csv`, `_c.csv`).
Hyper-parameters chosen on validation only.

| feature set | n | val AUC | val P≥.5 hit | val P≥.6 | val P≥.65 | test AUC | test P≥.5 hit | test P≥.6 | test P≥.65 |
|---|---|---|---|---|---|---|---|---|---|
| v4 (reproduced) | 125 | 0.6372 | 59.2 % | 61.0 % | 56.7 % | 0.6472 | 66.0 % | 70.2 % | 76.1 % |
| v4 + creation indicators | 147 | 0.6401 | 60.0 % | 60.8 % | 59.2 % | 0.6488 | 66.2 % | 69.9 % | 76.8 % |
| v4 + selection indicators | 186 | 0.6365 | 58.9 % | 61.3 % | 57.4 % | 0.6480 | 65.8 % | 70.7 % | 77.2 % |
| v4 + HTF indicators | 136 | 0.6384 | 59.0 % | 60.7 % | 57.9 % | 0.6480 | 65.9 % | 70.4 % | 76.3 % |
| **v5 = all** | 219 | **0.6401** | **61.0 %** | **62.2 %** | **60.4 %** | 0.6487 | 66.2 % | 70.8 % | 76.7 % |
| v5 without volume group | 208 | 0.6401 | 60.6 % | 61.4 % | 60.6 % | 0.6490 | 66.4 % | 70.6 % | 77.2 % |
| indicators only (+ distance, zone_atr, tf) | 110 | 0.6252 | 61.4 % | 66.3 % | 76.1 % | 0.6412 | 64.9 % | 73.0 % | 77.6 % |

Regularisation on the full v5 set: depth 3 / ≥ 300 rows per leaf / L2 10 gave the best validation AUC
(**0.6427**, test 0.6497) and is used for the final model; depth 4 overfits (train 0.81), depth 2 is
slightly worse on validation.

Reading: the indicators add **+0.3–0.5 AUC** on validation and **+1.8 points** on the hit-rate of the chosen
POI at `P ≥ 0.5` (59.2 → 61.0 %), +3.7 points at `P ≥ 0.65`. The gain comes from the **creation-time**
group (regime, MACD, ADX, RSI-at-the-block); the selection-time oscillators alone are worth nothing on top of
v4, exactly as the univariate picture says. Interesting: a model built from the indicators alone (110
columns) reaches AUC 0.625/0.641 — the classic indicators carry most of the information the structural
features carry, but not more.

### Final selection model (train < Mar-26, 43 018 rows → test 20 385)

OOS AUC **0.652** (v4 0.651), calibrated (pred .52→.58, .57→.64, .64→.70, .74→.82). Best-ranked & P ≥ 0.50
→ **65.0 %** bounce ≥ 1 ATR on 36 % of slots (v4 63.2 % on 37 %), P ≥ 0.55 → 68.4 %, P ≥ 0.60 → **71.2 %**
(v4 70.7 %), P ≥ 0.65 → 77.7 % (v4 77.9 %), P ≥ 0.70 → 80.7 %. Per TF at P ≥ 0.5: H1 62 %, M10 68 %,
M15 67 %, M30 73 %, M5 67 % (v4: 63/67/67/67/65).

Top OOS drivers (permutation): `zone_atr`, `zone_vs_bar_range`, `pos_prev_day`, `tf_minutes`, `liq_behind_n`,
`parent_zone_atr`, **`cr_atr_pctile`**, `swing_in_zone`, `pos_prev_week`, **`cr_adx`**, `impulse_body_frac`,
**`cr_rsi_extreme`**, **`cr_chop`**.

## 5. Bot level — end-to-end walk-forward, 5 TFs, out-of-sample Mar 2 → Sep 4 2026

All modes run with models trained < Mar 1 2026, every fill pays the (imputed) spread
(`run_v5_parts.sh`, `run_v5ens_parts.sh`, `summarize_v5.py` → `compare_v5_summary.csv`, `compare_v5_by_month.csv`).

| mode | selected | /day | reached | median bounce | ≥1 ATR | ≥2 ATR | P≥0.60: n / bounce | P≥0.65: n / bounce | R (mid entry, SL 0.5 ATR, TP 0.4R) |
|---|---|---|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 5806 | 43 | 88.5 % | 0.76 ATR | 40.2 % | 24.5 % | – | – | +0.095 R/trade, PF 1.51 |
| quality v4 | 1877 | 14.0 | 82.4 % | 1.30 ATR | 57.5 % | 38.1 % | 300 / 67.3 % | 127 / 70.1 % | +0.107 R, PF 1.58 |
| **quality v5** | 1738 | 13.0 | 81.6 % | 1.26 ATR | 57.2 % | 37.7 % | 280 / 65.7 % | 121 / **71.9 %** | +0.098 R, PF 1.51 |
| quality v4+v5 ensemble | 1794 | 13.4 | 81.8 % | 1.28 ATR | 57.1 % | 37.8 % | 287 / 66.6 % | 116 / **72.4 %** | +0.106 R, PF 1.57 |

Threshold sweep (bot level, v4 → **v5** → ensemble):

| min_quality | selected | ≥1 ATR | ≥2 ATR | median bounce (ATR) |
|---|---|---|---|---|
| 0.50 | 1877 → 1738 → 1794 | 57.5 → 57.2 → 57.1 % | 38.1 → 37.7 → 37.8 % | 1.30 → 1.26 → 1.28 |
| 0.55 | 800 → 746 → 766 | 61.7 → **64.1** → 61.4 % | 42.7 → **44.2** → 42.1 % | 1.48 → **1.61** → 1.46 |
| 0.60 | 375 → 349 → 355 | **67.3** → 65.7 → 66.6 % | 49.7 → 48.2 → 49.5 % | 1.95 → 1.83 → 1.93 |
| 0.65 | 165 → 161 → 157 | 70.1 → **71.9** → 72.4 % | 53.5 → **55.4** → 56.9 % | 2.35 → **2.42** → 2.46 |
| 0.70 | 70 → 69 → 70 | 65.4 → **74.0** → 67.9 % | 50.0 → **58.0** → 52.8 % | 2.05 → **2.75** → 2.38 |

Per timeframe, bounce ≥ 1 ATR (v4 → **v5**): M5 57.5 → 57.5 · M10 55.2 → 53.3 · M15 62.3 → 62.2 · M30 57.3 → **60.4** ·
H1 53.0 → 50.8. By month (v4 → v5): Mar 60→60 · Apr 59→58 · May 56→**58** · Jun 53→52 · Jul 56→55 · Aug 59→58 ·
Sep 68→**77**. Every month stays 13–20 points above the closest rule. Calibration of v5 at the bot level is the
best of the series: predicted 0.52 → actual 0.52, 0.57 → 0.62, 0.62 → 0.61, 0.67 → 0.72, **0.74 → 0.73** (v4's top
bucket 0.74 → 0.65 was over-confident).

### What the bot-level run says

* **End-to-end, v5 and v4 are statistically the same bot** at the default threshold (57.2 vs 57.5 % on ~1 450
  reached zones; one standard error is ≈ 1.3 points). The +1.8-point candidate-level gain of the indicators does
  not survive the bot's own rule set — liquidity between price and the zone, order-flow support, the 8-ATR
  distance cap and the distance penalty already remove most of what the indicator features learn to reject.
  This is the third time the pattern shows (v4 approach model, v4 price action, v5 indicators): once the PDF
  filters have run, additional *context* mostly re-ranks zones that are all reasonable.
* **Where v5 is better: the top of the ranking.** At `min_quality ≥ 0.65` (≈ 1.2 zones/day) v5 bounces 71.9 %
  vs 70.1 %, at ≥ 0.70 74.0 % vs 65.4 % with a much larger median bounce (2.75 vs 2.05 ATR), and the probabilities
  are calibrated all the way up. At 0.55 v5 is also ahead (64.1 vs 61.7 %); at 0.60 v4 is ahead (67.3 vs 65.7 %).
  These are small samples (70–375 zones) — read them as "equal, slightly better at the strict end".
* **The ensemble** (average of v4 and v5, `--set quality_model_path=models/v4/quality_model.json+models/quality_model.json`)
  is the most stable variant: it matches v4's total R (PF 1.57 vs 1.58), keeps v4's 0.60 hit-rate (66.6 %) and
  has the best A-grade rate (72.4 % at P ≥ 0.65). Costs two model evaluations per candidate (negligible).
* Small-target scenarios net of spread stay positive on every timeframe except H1 (all modes, tiny sample) and
  are equal within noise: mid-zone entry / SL 0.5 ATR / TP 0.4R → v4 +0.107 R/trade (PF 1.58), v5 +0.098 (1.51),
  ensemble +0.106 (1.57); edge entry / SL 0.1 ATR / TP 0.3R → PF 1.60 / 1.54 / 1.60.

### Recommendation

* Default stays the **v5 model** (`models/quality_model.json`): same end-to-end performance as v4, better
  calibrated at the top, and the bot now shows the indicator picture of every zone. Use `min_quality=0.55`
  for ~5 zones/day at ~64 % or `0.65` for ~1 zone/day at ~72 % with a median bounce of 2.4 ATR.
* The most conservative choice is the **ensemble** — never below either member by more than noise at any
  threshold, best on A-grades.
* Further *context* features are unlikely to move the end-to-end hit-rate; the remaining levers are the
  **rule set itself** (which zones enter the candidate pool) and the **execution model** (entry / stop placement
  inside the zone), not the ranking.

## 5b. Honest summary

* Indicators are a real but small signal for *where a base was built* (volatility regime, ADX, MACD, RSI at the
  block): +0.5 AUC on validation, +1.8 points hit-rate of the chosen candidate, best calibration so far.
* The oscillator state of the approach (RSI, Stoch, MACD, DI, BB %B, VWAP, SuperTrend at the selection bar) is
  flat: when the zone is still 2–8 ATR away it does not predict what happens on arrival.
* At the bot level the upgrade is neutral at the default threshold and slightly positive at strict thresholds.
  Everything remains a ranking edge (AUC ≈ 0.65): a "72 %" zone still fails 3 in 10.

## 6. Files

```
lubot/indicators.py                IndicatorSet: all indicator series + selection/creation/htf feature builders
lubot/poi.py::_ind_features        creation-time indicator features on OB / IMB / UW (BB & HB inherit)
lubot/engine.py                    selection features + HTF indicator features in qualified()/_htf_features()
lubot/quality.py                   NUMERIC_V5_*, FEATURE_ORDER (219) / FEATURE_ORDER_V4 (125)
lubot/config.py                    use_indicators (default True)
bot.py                             'indicators:' line per POI
build_training_set.py              memory-lean float32 rows (the M5 set no longer exceeds 1 GB)
experiments_v5.py                  univariate / ablation / regularisation grid / importance (resumable)
train_quality.py --features v5     final model -> models/quality_model.json  (v4 kept in models/v4/)
run_v5_parts.sh + summarize_v5.py  bot-level OOS comparison (resumable, per timeframe)
study_results/quality_v5_*.csv     all tables above
save.sh / restore.sh / PROGRESS.md checkpoint + recovery
```
