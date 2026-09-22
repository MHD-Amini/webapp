# Bot upgrade v6: honest learning + level memory

Data: `XAUUSD.t_M1_202501020100_2026090423581112.csv` (2025-01-02 → 2026-09-04, 593 863 M1 bars).
Goal unchanged: of all POIs that pass the PDF rule set, return per timeframe the one above and the one below
price that is **most likely to bounce price back when it gets there**.

v6 attacks the problem from two sides that v3–v5 had not touched:

1. **How the model learns** (weights, learner, evaluation) — this is where the measurable gain is.
2. **What the model knows** — a new information source, the *memory of the price level* (volume / time profile
   and past reactions of the zone's price area), which the structure, price-action and indicator features of
   v2–v5 never looked at.

## 1. Spread — the part of the CSV without spread (unchanged from v5)

`<SPREAD>` exists only from **2026-04-06 15:19** (150 241 bars, median 28 points = $0.28); the 443 622 older
bars carry `0`. As instructed they are treated **as having the same spread as the part with spread**:
`lubot/data.py::impute_spread` builds a (weekday, NY-hour) median profile from the bars with a real spread and
fills every zero bar from it (`spread_imputed` flag). Every cost figure in the bot-level tables pays that spread.
The spread is not a model input. Same for volume: only *relative* volume is used (VOL/TICKVOL scale break).

## 2. Honest evaluation first (`experiments_v6.py`, Part A)

Three problems in how v2–v5 were trained and measured, all fixed in v6:

| problem | size | fix |
|---|---|---|
| **Duplicated rows.** A living POI is re-recorded every 25 bars, so 70 % of the 63 403 training rows are re-records (mean 3.4 rows / POI, up to 13; labels identical within a POI). Long-lived zones dominate the fit and inflate every unweighted metric. | 18 760 distinct POIs behind 63 403 rows | rows weighted **1 / rows-of-that-POI** in training and in the reported `AUC_w` |
| **Row-level metrics ≠ bot behaviour.** The bot returns one candidate per (bar, side) slot; row AUC rewards separating rows the bot never has to choose between. | 20 635 slots, 3.1 candidates each, 37 % singletons | every setting reported with **slot-level top-1** hit-rate / kept-share per threshold and the *in-slot lift* |
| **Learner never re-visited.** v2–v5 always used sklearn HistGradientBoosting, depth 3, fixed 400 iterations. | – | LightGBM grid with early stopping on validation, lambdarank, soft target, POI weights, bagging, ensemble |

Strict windows throughout: train < Dec-25 · **validate** Dec-25 → Feb-26 (all choices made here) · **test** ≥ Mar-26 (reported only).

### 2a. Weighting alone (v5 production GBM, same features, same parameters)

| | val AUC | val AUC_w | val top-1 P≥.60 | val P≥.65 | test AUC | test P≥.60 (kept) | test P≥.65 (kept) |
|---|---|---|---|---|---|---|---|
| v5 GBM, unweighted (as shipped) | 0.6427 | 0.6551 | 60.9 % | 59.8 % | 0.6497 | 70.0 % (15.3 %) | 75.7 % (9.2 %) |
| **v5 GBM, POI weights** | 0.6428 | **0.6624** | **71.7 %** | **75.6 %** | **0.6566** | **72.9 %** (13.8 %) | **78.4 %** (6.0 %) |

One vote per POI instead of one per row is the single biggest improvement of the v3–v6 series: +0.7 weighted
AUC points, and the strict-threshold hit-rates of the *chosen* candidate jump 10–15 points on validation
because the probabilities are no longer stretched by long-lived zones.

### 2b. Learner grid (`quality_v6_lgb_grid.csv`, 20 settings; `quality_v6_rank.csv`; `quality_v6_bag_compare.csv`)

* **LightGBM binary, POI weights** — best `lgb_l15_d4|pw` (15 leaves, depth 4, ≥300 rows/leaf, feature
  fraction 0.7, L2 10, 364 rounds): val AUC_w **0.6671**, test AUC 0.6571, test P≥.60 72.4 %. Without POI
  weights every LightGBM setting is 0.8–1.2 AUC_w points worse.
* **Soft target** (clipped bounce in ATR): higher precision (val P≥.50 62–65 %) but the probabilities compress —
  only 23–30 % of slots survive P≥.50. Not used.
* **lambdarank on slot groups** (binary or graded relevance): val AUC 0.62, in-slot lift not better than binary,
  scores need separate calibration. Rejected.
* **Bagging ×5 + ensemble with the weighted v5-GBM**: val AUC_w 0.664, test AUC 0.658, test P≥.60 **72.3 %**,
  P≥.65 **77.5 %**; calibrated on test all the way up (pred .52→.56, .57→.64, .62→.72, .67→.78, .72→.83).
  The JSON export of the LightGBM trees reproduces its predictions to 1e-16 (`lubot/lgbm_export.py`), so the
  bot needs neither LightGBM nor sklearn at runtime.
* In-slot lift: the chosen candidate beats the average candidate of its slot by **+9.5 points** (val). Ranking
  skill inside a slot is real but modest — most of the model's value is in *rejecting slots* (the threshold).

## 3. Level memory (`lubot/levels.py`, `LevelMemory`)

New information, computed incrementally per timeframe from closed bars only (unit test mutates every bar after
`i` and asserts nothing at `i` changes):

| group | features | idea |
|---|---|---|
| **profile** | `lv_vol_density`, `lv_time_density`, `lv_lvn_score`, `lv_vol_density_recent`, `lv_behind_density`, `lv_path_density` | rolling 3000-bar volume / time-at-price histogram (0.1-ATR bins, relative volume): is the zone a low-volume node (price moved through fast) or a high-volume node (chop area)? Is the area behind it thin? |
| **value area** | `lv_poc_dist_atr`, `lv_va_pos`, `lv_zone_at_va_edge`, `lv_zone_outside_va`, `lv_poc_beyond` | point of control and 70 % value area; zone position relative to them (oriented to the zone direction) |
| **reaction memory** | `lv_rev_with`, `lv_rev_against`, `lv_rev_ratio`, `lv_rev_per_visit`, `lv_visits`, `lv_slice_frac`, `lv_bars_since_visit` | how often swing reversals formed in the zone's price area (±0.25 ATR) in the zone direction vs against it, how many bars visited it, what share of visits sliced through it with the candle body, how fresh it is |
| **creation snapshot** `cl_*` (11) | the same at the bar the base was built | was the block built at a level that had already reversed price? |
| **evolution / HTF** | `lv_visits_since_create`, `lv_density_change`, `hlv_*` (8) | how the area changed since the base was built; the parent timeframe's memory of the same area |

39 features, 258 model columns in total; ~+30 % CPU per bar (0.3–0.5 ms per candidate). `bot.py` prints a
**`level memory:`** line per returned POI (reversals with/against, rev/visit, sliced share, last visit, LVN/HVN,
value-area position, HTF reversals).

### What the data says (`quality_v6_univariate.csv`, val+test, POI-weighted)

* **`lv_rev_per_visit`** (reversals in the zone direction per visit) is the strongest single new feature of the
  whole project: AUC 0.578 alone, bounce by quintile **31.1 → 36.9 → 40.6 → 43.4 → 51.6 %**. `lv_rev_with`
  0.572 (33 → 52 %), `hlv_rev_with` 0.564 (36 → 54 %), `cl_rev_with` 0.553. A zone in an area where price has
  reversed before bounces 20 points more often than one in an area it never respected.
* `lv_rev_against` is *also* positive (35 → 50 %): reversals of either kind mark an area the market cares about;
  what hurts is an area with no reaction history at all.
* Profile densities and value-area position are weak alone (0.50–0.53): whether the zone is an LVN or HVN, at
  the POC or outside value, tells little about the bounce once the PDF filters have run.

### Ablation on the rebuilt sets (`quality_v6_ablation.csv`; same 63 403 rows, LightGBM POI-weighted, 3 seeds)

| feature set | cols | val AUC_w | test AUC_w | test top-1 P≥.60 (kept) | test P≥.65 (kept) |
|---|---|---|---|---|---|
| v5 | 219 | 0.6653 | 0.6606 | 71.8 % (14.1 %) | 75.9 % (7.0 %) |
| **v6** | 258 | 0.6645 | 0.6604 | **73.8 %** (14.8 %) | **76.7 %** (7.4 %) |
| v6 without profile group | 236 | 0.6641 | 0.6593 | 72.4 % | 75.0 % |
| v6 without reaction memory | 241 | 0.6651 | 0.6602 | 72.0 % | 74.6 % |
| v6 without creation snapshot | 247 | 0.6653 | 0.6597 | 74.0 % | 76.8 % |

Reading: **AUC does not move** (0.660 either way, ±0.001). The reaction-memory signal that is so clear
univariately is already carried by the structural features (`tested_respected`, `liq_behind_n`,
`swing_in_zone`, order-flow support) — the model had the information, expressed differently. Where the new
features help is the *top of the ranking*: +2 points at P≥.60 and +1 at P≥.65 on test with a few more slots
kept, and the reaction memory is now visible to the trader. Per-TF test AUC_w (v5 → v6): M5 0.641 → 0.644 ·
M10 0.646 → 0.646 · M15 0.674 → 0.670 · M30 0.713 → 0.709 · H1 0.685 → 0.686.

## 4. Final v6 model (`train_v6.py`)

`models/quality_model.json` = **POI-weighted ensemble**: bagged LightGBM (5 seeds × 270 rounds, 15 leaves,
depth 4, ≥300 rows / leaf, feature fraction 0.7, L2 10) **+** bagged sklearn GBM (5 × 400 trees, depth 3,
≥300 rows / leaf, L2 10), both on the v6 feature set, probabilities averaged 50/50. Stored as two members
(`ALL`, `ALL2`) in one JSON; `QualityScorer` mixes them, explains them jointly (Saabas) and runs on numpy only.
Rounds chosen by early stopping on the last three months before the split. v5 is kept in `models/v5/`.

Candidate-level, trained < Mar-26, tested Mar → Sep 2026 (20 385 reached candidates, 6 648 slots):

| selection (best-ranked per slot) | slots kept | bounce ≥1 ATR | median bounce | ≥2 ATR |
|---|---|---|---|---|
| any (closest-like) | 100 % | 51.3 % | 1.04 ATR | 33.0 % |
| v6, P ≥ 0.50 | 36.8 % | 64.6 % | 1.60 | 43.2 % |
| v6, P ≥ 0.55 | 23.6 % | 69.8 % | 1.89 | 47.6 % |
| v6, P ≥ 0.60 | 13.4 % | **73.0 %** | 2.08 | 51.6 % |
| v6, P ≥ 0.65 | 5.5 % | **76.3 %** | 2.40 | 55.1 % |
| *(v5, same rows)* P ≥ 0.50 / 0.60 / 0.65 | 36 / 13 / 6 % | 65.0 / 71.2 / 77.7 % | 1.64 / 2.19 / 2.47 | 44.3 / 52.7 / 61.5 % |

OOS AUC **0.657** (v5 0.652), weighted 0.660. Calibration on test: predicted .52 → actual .56, .57 → .64,
.62 → .72, .67 → .78, .72 → .77 — v6 is slightly *under*-confident at the top, v5 was over-confident there.
Per TF at P ≥ 0.5: H1 57 %, M10 65 %, M15 67 %, M30 73 %, M5 63 %.

## 5. Bot level — end-to-end walk-forward, 5 TFs, out-of-sample Mar 2 → Sep 4 2026

All modes run with models trained < Mar 1 2026, every fill pays the (imputed) spread
(`run_v6_parts.sh`, `summarize_v6.py` → `compare_v6_summary.csv`, `compare_v6_by_month.csv`).

| mode | selected | /day | reached | median bounce | ≥1 ATR | ≥2 ATR | P≥0.60: n / bounce | P≥0.65: n / bounce | R (mid entry, SL 0.5 ATR, TP 0.4R) |
|---|---|---|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 5806 | 43 | 88.5 % | 0.76 ATR | 40.2 % | 24.5 % | – | – | +0.095 R, PF 1.51 |
| quality v4 | 1877 | 14.0 | 82.4 % | 1.30 | 57.5 % | 38.1 % | 300 / 67.3 % | 127 / 70.1 % | +0.107 R, PF 1.58 |
| quality v5 | 1738 | 13.0 | 81.6 % | 1.26 | 57.2 % | 37.7 % | 280 / 65.7 % | 121 / 71.9 % | +0.098 R, PF 1.51 |
| v4+v5 ensemble | 1794 | 13.4 | 81.8 % | 1.28 | 57.1 % | 37.8 % | 287 / 66.6 % | 116 / 72.4 % | +0.106 R, PF 1.57 |
| **quality v6** | 1913 | 14.3 | 81.3 % | 1.28 | 57.3 % | 38.0 % | **338 / 68.0 %** | 130 / 69.2 % | +0.097 R, PF 1.50 |

Threshold sweep (bot level, v5 → **v6**):

| min_quality | selected | reached | ≥1 ATR | ≥2 ATR | median bounce |
|---|---|---|---|---|---|
| 0.50 | 1738 → **1913** | 81.6 → 81.3 % | 57.2 → 57.3 % | 37.7 → 38.0 % | 1.26 → 1.28 |
| 0.55 | 746 → **807** | 81.5 → 82.0 % | 64.1 → 62.4 % | 44.2 → 43.2 % | 1.61 → 1.48 |
| 0.60 | 349 → **408** | 80.2 → **82.8 %** | 65.7 → **68.0 %** | 48.2 → 48.5 % | 1.83 → 1.93 |
| 0.65 | 161 → 163 | 75.2 → **79.8 %** | 71.9 → 69.2 % | 55.4 → 52.3 % | 2.42 → 2.38 |
| 0.70 | 69 → 50 | 72.5 → 76.0 % | 74.0 → 73.7 % | 58.0 → 50.0 % | 2.75 → 2.05 |

Per timeframe, bounce ≥1 ATR (v5 → **v6**): M5 57.5 → 57.8 · M10 53.3 → **54.1** · M15 62.2 → 59.2 · M30 60.4 → **63.2** ·
H1 50.8 → **51.6**. By month (v4 / v5 / **v6**): Mar 60 / 60 / **63** · Apr 59 / 58 / 56 · May 56 / 58 / 58 · Jun 53 / 52 / **54** ·
Jul 56 / 55 / 53 · Aug 59 / 58 / **60** · Sep (29 zones) 68 / 77 / 59. Every month 13–22 points above the closest rule.
Calibration at the bot level: predicted 0.52 → actual 0.54, 0.57 → 0.56, 0.62 → **0.68**, 0.67 → 0.69, 0.73 → 0.73.

### What the bot-level run says

* **End-to-end, at the default threshold v6 = v5 = v4** (57.3 / 57.2 / 57.5 % on ~1 500 reached zones; one
  standard error ≈ 1.3 points). This is the fourth version in a row where a large candidate-level change (here:
  +0.7 weighted AUC, +2–4 points hit-rate of the chosen candidate at strict thresholds) shrinks to noise once the
  PDF rule set has done its filtering. The rule set — liquidity between price and the zone, order-flow support,
  8-ATR cap, distance penalty — is the dominant factor; the ranking model re-orders zones that are all reasonable.
* **Where v6 is better: throughput at the strict thresholds.** At `min_quality 0.60` v6 returns **17 % more
  zones (408 vs 349, ≈ 3 / day)** that are reached more often (82.8 vs 80.2 %) and bounce slightly more often
  (68.0 vs 65.7 %). More A/B-grade signals at equal or better quality is the practical gain of the POI-weighted
  ensemble. At 0.65 the samples (160 zones) are too small to separate v4/v5/v6 (69–72 %).
* **Calibration** is the best of the series in the bucket that matters most for a trader (0.60–0.65: predicted 0.62,
  actual 0.68); v6 does not over-promise at the top (0.73 → 0.73).
* Small-target scenarios net of spread are equal within noise across v4/v5/v6 (mid entry / SL 0.5 ATR / TP 0.4R:
  PF 1.58 / 1.51 / 1.50; edge entry / SL 0.1 ATR / TP 0.3R: PF 1.60 / 1.54 / 1.56); positive on every timeframe.

### Recommendation

* Default = **v6 model** (`models/quality_model.json`): same end-to-end hit-rate, best calibration, the most
  zones at P ≥ 0.60, and the output now shows the *level memory* of every zone. Use `min_quality=0.60`
  for ~3 zones/day at ~68 % or `0.55` for ~6 zones/day at ~62 %.
* Previous models stay available: `--set quality_model_path=models/v5/quality_model.json` (v5),
  `models/v4/quality_model.json` (v4), or any `+`-joined ensemble of them.
* Honest summary: the *learning* fixes (POI weights, learner, ensemble) are real and measurable at the candidate
  level and in calibration; the *level memory* is the strongest new univariate signal found so far but adds
  little once the structural features are in the model. The remaining lever, as concluded in v5, is the **rule
  set** (which zones enter the candidate pool at all) and the **execution model**, not the ranking.

## 6. Files

```
lubot/levels.py            LevelMemory: rolling profile / value area / reaction memory (lv_*, cl_*, hlv_*)
lubot/lgbm_export.py       LightGBM booster -> bot JSON trees (exact)
lubot/quality.py           NUMERIC_V6_*, FEATURE_ORDER (258) / FEATURE_ORDER_V5 (219); two-member mixing (ALL + ALL2)
lubot/engine.py, poi.py    level features at selection (lv_/hlv_) and creation (cl_); config.use_levels
bot.py                     'level memory:' line per POI
experiments_v6.py          Part A honest baseline · B LightGBM grid · C lambdarank · D bagging / ensemble
pilot_v6.py, ablation_v6.py  M15 pilot; pooled v5-vs-v6 ablation on the rebuilt sets
train_v6.py                final POI-weighted ensemble -> models/quality_model.json (+ _trainonly)
build_all_train_v6.sh, run_v6_parts.sh, summarize_v6.py   resumable rebuild / bot-level OOS / summary
models/v6/train_*.pkl      v6 training sets; models/v5/  previous model
study_results/quality_v6_{baseline,lgb_grid,rank,bag_compare,pilot_*,univariate,ablation,threshold_sweep}.csv
study_results/compare_v6parts_*_quality.pkl, compare_v6_summary.csv, compare_v6_by_month.csv
save.sh / restore.sh / PROGRESS.md   checkpoint + recovery (every step committed and pushed)
```
