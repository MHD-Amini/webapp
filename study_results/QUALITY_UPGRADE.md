# Bot upgrade: from "closest POI" to "POI most likely to bounce"

## What changed

| | before (`selection_mode=closest`) | after (`selection_mode=quality`, default) |
|---|---|---|
| Rule 4 | literally the closest qualifying POI above / below | rank by **modelled P(bounce ≥ 1 ATR before violation)**, softly penalised by distance |
| Order flow | any respected same-direction POI in 600 bars (never rejected anything) | must be **relevant**: respected within 3 ATR of the candidate or within the last 100 bars |
| Eligibility | unmitigated + liquidity between | + **quality ≥ 0.50** and **≤ 8 ATR away** (beyond that <50% are ever reached); if no candidate passes → `none - waiting` |
| Output | zone, distance, liquidity, OF count | + `P(bounce>=1ATR)=xx%` and the top feature drivers |

### Features the model sees (all known at selection time — no look-ahead)
- **POI creation:** zone height (ATR), displacement of the move (ATR), impulse bars, block candles, imbalance inside the impulse, body/candle ratio, liquidity the move swept (count, quality: swing < day/Asia < equal/weekly)
- **Context:** distance (ATR), liquidity between price and POI (count, quality), relevant order flow (near / recent), confluence with other same-direction POIs, HTF-range alignment, premium/discount, age, session (NY), direction
- Model: one logistic regression per POI type (+ pooled fallback), standardised & clipped inputs, weights in `models/quality_model.json` (no sklearn at runtime).

### How it was trained / validated
- Training set: every qualifying candidate (not just the closest) sampled every few bars across all 5 timeframes, 13 months → **39,188 reached candidates**, each labelled with "bounced ≥ 1 ATR from the edge before the far edge (+0.1 ATR) was violated".
- Strict time split: **train < 2026‑04‑01 (21k), test ≥ 2026‑04‑01 (18k)**. Threshold and distance penalty were tuned on the train period only.
- Then the **whole bot** was re-run in both modes over the test period with the train-only model.

## Out-of-sample results (Apr → Sep 2026, bot run end-to-end)

| mode | selected | /day | reached % | median bounce (ATR) | median bounce ($) | ≥1 ATR | ≥2 ATR | ≥3 ATR | median penetration |
|---|---|---|---|---|---|---|---|---|---|
| closest | 4833 | 43 | 89.1 | 0.76 | 5.1 | **40.1%** | 24.4% | 17.5% | 1.65 zones |
| **quality** | 1927 | 17 | 82.7 | **1.02** | **7.4** | **50.8%** | **33.4%** | **24.2%** | **1.33 zones** |

Per timeframe (≥ 1 ATR bounce, closest → quality): H1 35→44% · M30 37→50% · M15 39→52% · M10 42→47% · M5 41→53%.
Every month of the test period improved (Apr 39→49, May 42→52, Jun 36→45, Jul 41→53, Aug 41→55).

What the model actually does, in plain terms:
- **Drops Hidden Bases entirely** (0.1‑ATR zones, 24% bounce rate) and halves the share of Imbalances; selected set is now ⅓ OB, ⅓ UW, ⅓ IMB.
- Picks **taller zones** (median 0.75 ATR vs 0.42) that are a bit **farther away** (1.9 vs 1.3 ATR) — the closest POI is often just the last candle's body.
- Prefers POIs with **little liquidity stacked between price and the zone** (the market tends to stop at the first pool), created by moves that swept **equal highs/lows** (for OBs), and touches in **NY / Pre‑NY** rather than London Close.
- Fewer signals: ~17/day across 5 TFs instead of 43 — by design; the "wait" case is now common.

Calibration on the test period: predicted 0.52 → actual 0.47; 0.64 → 0.59; 0.75 → 0.61. Slightly over-confident at the top but monotonic, so the ranking is trustworthy; the absolute number is a rough guide.

## What did NOT change
- **Mechanical P&L is still ≈ break-even** (net R/trade −0.04 … +0.04 in both modes). The bounces are bigger and more frequent, but the R-multiple scenarios use tighter stops on *larger* zones, and price still sweeps ~1.3 zone-heights before turning. The upgrade improves **where** to look; the entry model (confirmation after the sweep, stop beyond the sweep) is still the missing piece for a tradable edge.
- Trend dependence: bullish POIs 54% vs bearish 47% in the test period (bull market).

## Caveats
- One instrument, one broker, 13 months; the model should be **retrained periodically** (`bash build_all_train.sh && python train_quality.py --split <date> --final`).
- Logistic model with ~27 features: intentionally simple and inspectable; a tree model could squeeze a few more points but would be harder to trust.
- `min_quality=0.50` trades signal count for accuracy; 0.45 gives ~60% of slots at ~55% bounce rate, 0.55 gives ~35% of slots at ~59%.

## Files
- `models/quality_model.json` (all data, used live) · `models/quality_model_trainonly.json` (validated one)
- `study_results/compare_summary.csv`, `compare_closest.pkl`, `compare_quality.pkl`
- `build_training_set.py`, `build_all_train.sh`, `train_quality.py`, `compare_modes.py`
