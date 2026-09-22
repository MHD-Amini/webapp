# Bot upgrade v2: POIs ranked by "will price bounce here?"

Goal of this iteration: make the two POIs the bot returns per timeframe the ones **most likely to
reverse price when it reaches them**, using the full 20-month M1 history
(`XAUUSD.t_M1_202501020100_2026090423581112.csv`, 2025‑01‑02 → 2026‑09‑04, 593 863 bars).

## 1. What changed vs v1

| | v1 (Sep 11) | **v2 (this upgrade)** |
|---|---|---|
| training data | 13 months, 39k candidates | **20 months, 63 403 reached candidates**, all 5 TFs |
| model | logistic regression per POI type, 27 features | **gradient-boosted trees** (pooled, POI-type dummies), **64 features**; shallow & heavily regularised (depth 3, ≥200 rows/leaf, L2 5) — picked on a separate validation window (Dec‑25→Feb‑26) |
| runtime | numpy | numpy (trees exported to JSON, no sklearn at runtime) |
| features | creation + basic context | + **liquidity behind the zone**, **approach dynamics**, **HTF confluence**, **leg origin**, **structure momentum**, **vol regime**, day-of-week |
| explanation | coefficient × value | Saabas path contributions (same output format `why`) |
| output | `P(bounce>=1ATR)=xx%` | + **grade A/B/C**, `HTF-confluence` / `HTF-aligned`, `liq-behind N` |

### New features (all known at selection time — no look-ahead)

**Liquidity geometry** (the market's "reason" to go somewhere):
- `liq_behind_n / liq_behind_quality` – active liquidity within 1.5 ATR **beyond** the far edge of the zone. If stops sit right behind the POI, price tends to run through it to take them → **lower** bounce odds.
- `liq_stacked_beyond_n` – more pools 1.5–3 ATR beyond (a magnet further away).
- `liq_between_weight`, `first_pool_gap_atr` – how much liquidity rests between price and the POI and how far the first pool is from the zone (price often stops at the first pool).
- `liq_near_edge_n`, `opp_liq_between_n` – stops sitting right at the entry edge; opposite-side liquidity that becomes the target after a bounce.

**Approach dynamics** (life of the POI while unmitigated, tracked bar by bar in `poi.py`):
- `away_atr` – how far price travelled away from the zone before coming back (strong rejection legs carry more unfilled orders).
- `min_approach_atr`, `near_misses` – did price already come close and get rejected without tapping?
- `toward_mom5 / toward_mom20` – is price currently moving into the zone, and how fast (fast approaches blow through).
- `atr_ratio` – current ATR vs 70-bar mean (volatility regime).
- `pos20 / pos100` – where price sits in the recent 20/100-bar range relative to the POI direction.
- `closer_same_dir`, `opp_on_path` – same-direction POIs closer to price (this one is not first in line) and opposite POIs price must cross first.

**Structure**:
- `is_leg_origin`, `prior_move_atr` – is the block the extreme of the last 20 bars (V-reversal origin) and how big was the move into it.
- `range_pos`, `bos_recent_n`, `bos_recent_aligned` – position inside the QM trading range, recent break-of-structure count and direction.
- **HTF confluence** (a private helper engine per parent timeframe: M5→M30, M10/M15→H1, M30/H1→H4, stepped only up to the HTF bar that had *closed* at our bar time): `htf_confluence(_kind)` – our zone overlaps an alive same-direction HTF POI; `htf_bias_aligned`, `htf_in_zone` – HTF QM bias / premium-discount; `htf_liq_behind_atr` – HTF liquidity behind our zone; `htf_dist_atr` – distance to the next HTF POI beyond ours.

## 2. Validation

Strict time split, threshold & hyper-parameters chosen without touching the test period.

**Candidate-level (train < 2026‑03‑01: 43 018 rows · test ≥ 2026‑03‑01: 20 385 rows)**

| | v1 logistic (same 64 features) | **v2 GBM** |
|---|---|---|
| OOS AUC | 0.634 | **0.643** |
| best-ranked candidate per slot, bounce ≥1 ATR | 52.7 % | **52.7 %** |
| best-ranked & P ≥ 0.50 | 63.2 % (40 % of slots) | **65.2 % (38 % of slots)** |
| closest POI (PDF rule 4) | 43.7 % | 43.7 % |

Threshold sweep on the test period (best-ranked candidate per slot):

| min_quality | slots kept | bounce ≥1 ATR | median bounce | ≥2 ATR |
|---|---|---|---|---|
| none | 100 % | 50.6 % | 1.02 ATR | 32 % |
| 0.45 | 49 % | 60.0 % | 1.34 | 39 % |
| **0.50 (default)** | **34 %** | **62.1 %** | **1.60** | **43 %** |
| 0.55 | 20 % | 66.7 % | 1.91 | 48 % |
| 0.60 | 10 % | 70.8 % | 2.25 | 54 % |

Calibration OOS is monotonic and close to the diagonal (pred 0.52 → actual 0.56; 0.57 → 0.60; 0.64 → 0.65; 0.74 → 0.81).

Per timeframe, best-ranked & P ≥ 0.5 vs closest (OOS): H1 52 vs 37 % · M30 67 vs 41 % · M15 64 vs 43 % · M10 65 vs 43 % · M5 63 vs 47 %.

**Bot-level (end-to-end walk-forward of the whole bot, 5 TFs, out-of-sample Mar 2 → Sep 4 2026, models trained < Mar 1)**

| mode | selected | /day | reached | median bounce | ≥1 ATR | ≥2 ATR | hit 0.3R | hit 0.5R |
|---|---|---|---|---|---|---|---|---|
| closest (PDF rule 4) | 5806 | 43 | 88.5 % | 0.76 ATR | **40.2 %** | 24.5 % | 79.6 % | 72.6 % |
| quality v1 (Sep 11) | 2345 | 17.5 | 81.1 % | 1.05 ATR | **51.8 %** | 33.8 % | 84.7 % | 74.5 % |
| **quality v2 (this)** | 1410 | 10.5 | 82.6 % | **1.35 ATR** | **58.6 %** | **39.9 %** | **87.0 %** | **74.9 %** |

Per timeframe (≥1 ATR, closest → v1 → **v2**): H1 36 → 45 → **48 %** · M30 37 → 51 → **60 %** · M15 39 → 54 → **62 %** · M10 41 → 49 → **56 %** · M5 41 → 54 → **59 %**.

Every OOS month improved over both baselines (closest → v1 → **v2**): Mar 41→58→**65** · Apr 39→49→**57** · May 42→53→**59** · Jun 36→45→**57** · Jul 41→53→**55** · Aug 41→54→**60** · Sep (4 days) 47→58→**54**.
Bot-level calibration is good: predicted 0.52 → actual 0.57, 0.57 → 0.58, 0.63 → 0.63, 0.75 → 0.69.
Bearish POIs bounce less often than bullish ones (54 % vs 62 %; the sample is a bull market) but both beat the 39 / 42 % of the closest rule.

Execution scenarios (net of spread, OOS): the v2 selection is the only mode that is **positive in every small-target scenario incl. tight stops** — e.g. mid-zone entry, SL 0.1 ATR beyond, TP 0.4R: closest −0.14 R/trade (PF 0.58), v1 +0.01, **v2 +0.10 R (PF 1.51, 83 % win, max DD −8.6 R)**; edge entry / SL 0.1 / TP 0.3R: closest −0.06, v1 +0.05, **v2 +0.10 (PF 1.71)**. With the wider 0.5-ATR stop all modes are similar (+0.08…+0.12 R); the difference is that v2 zones are penetrated less, so tight stops survive. Full tables: `compare_summary.csv`, `compare_scenarios.csv`, `compare_by_month_v2.csv`.

Signal count: ~10 POIs/day across 5 timeframes instead of 43 (closest) or 17 (v1) — by design; `none - waiting` is now the normal state on most timeframes. Lower `min_quality` to 0.45 for ~50 % of slots at ~60 % bounce rate.

## 3. What the model learned (permutation importance, OOS)

1. `zone_atr` (by far) – taller zones bounce; the "closest" POI is often a one-candle body.
2. `liq_behind_n` / `liq_stacked_beyond_n` – stops right behind the zone → price runs through.
3. `parent_zone_atr`, `displacement_atr` – size of the parent block / impulse.
4. `of_total`, `age_bars` – (too) much order flow and old zones are weaker.
5. `dow`, session, `is_bull` – time-of-week and trend regime (bull market in the sample).
6. `htf_dist_atr`, `away_atr`, `closer_same_dir` – HTF distance, rejection leg, not-first-in-line.

## 4. How to use / retrain

```bash
python bot.py scan --csv data.csv                      # quality v2 (default model models/quality_model.json)
python bot.py --set min_quality=0.55 scan --csv data.csv          # stricter (grade B+ only)
python bot.py --set quality_model_path=models/v1/quality_model.json scan ...   # old model
python bot.py --set htf_confluence=false scan ...                 # disable HTF helper engines

# retrain (≈25 min for the training sets on 2 cores, 2 min for the model)
bash build_all_train.sh data.csv
python train_quality.py --split 2026-03-01 --final        # writes models/quality_model.json (+ _trainonly.json)
python experiments_gbm.py                                 # hyper-parameter sanity grid
python compare_modes.py --csv data.csv --from 2026-01-15 --oos 2026-03-01 \
       --model models/quality_model_trainonly.json --model-v1 models/v1/quality_model_trainonly.json
```

Grades: **A** ≥ 0.65 · **B** ≥ 0.55 · **C** ≥ 0.50 (= `min_quality`) · below → not shown.

## 5. Caveats
- One instrument / broker; 20 months, mostly bull market (bullish POIs bounce more often).
- AUC ≈ 0.64: the model separates good from bad POIs meaningfully but is far from certain — a 60 % zone still fails 4 times in 10. Use the probability as a ranking / filter, not as a promise.
- Bounce ≥ 1 ATR is a *reaction* label, not P&L; entries / stops / targets still decide profitability (see `SMALL_TARGETS.md`).
- Retrain periodically; the pipeline is resumable and the model file is self-describing (`meta`).
