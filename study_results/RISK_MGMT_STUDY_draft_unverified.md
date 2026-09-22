# RISK-MANAGEMENT STUDY (v9) — which exit system makes the LU-POI trader most profitable?

**Question.** The trader's management is *"close 50 % at +0.4R, move the stop to break-even, TP2 fixed at +1.5R"*.
Test different numbers **and** different systems and find the most profitable one.

**Method.** Entries are held fixed at the v8 recommended configuration (v8 M5 filter, `min_quality 0.60` on M10/M15/M30/H1,
1 % risk, $10 000, real costs: per-minute spread, $7/lot commission, $0.10 stop slippage, swaps).  Only the management
changes.  **580 managements** were run on the realistic portfolio simulator (`lubot/portfolio_sim.py`, M1 precision,
MT5-tester intrabar path) **out-of-sample 2026-03-02 → 2026-09-04** (`run_rm_study.py`).  The 88 most interesting were
then replayed **in-sample Jan 2025 → Feb 2026** on the 1 270 plans the same trader would have taken (`rm_insample.py`:
the same simulator code, one plan at a time) so that the choice is not fitted to six months.  Finalists were stress-tested
(`rm_stress.py`).  Every number below is net of costs; R = zone height (entry at the near edge, SL at the far edge).

Families tested: **A** two-leg partial (partial level 0.2–1.0R × fraction 25–75 % × TP2 1–3R × BE on/off) · **B** single
target with/without a BE trigger · **C** partial + trailing runner (0.3–1.5R trail, with/without TP2, activation level,
close- or extreme-based) · **C2** trailing stop on the whole position · **D** three-leg ladders (± stop ratchet) ·
**E** time stops · **F** BE offset (+0.05…+0.2R or −0.1R).  Charts: `study_results/charts/rm_*.png`.

---

## 1. Result in one table

OOS = out-of-sample portfolio (Mar–Sep 2026, 127–133 trades).  IS = in-sample replay (Jan 2025–Feb 2026, 1 270 plans).

| management | OOS return | OOS max DD | OOS PF | OOS R/trade | win % | H1 R / H2 R | +months | IS R/plan | IS PF | IS win % | IS max DD (R) | IS +months |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **current spec** 50 % @ 0.4R → BE, TP2 1.5R | +12.3 % | −3.2 % | 1.46 | +0.098 | 80.9 | 10.6 / 2.2 | 5/7 | +0.165 | 1.88 | 80.8 | −20.1 | 11/14 |
| 50 % @ 0.4R → BE, TP2 **3R** | +16.3 % | −4.2 % | 1.59 | +0.126 | 80.9 | 11.1 / 5.5 | 3/7 | +0.178 | 1.95 | 80.8 | −19.3 | 12/14 |
| 50 % @ **0.6R** → BE, TP2 1.5R | +14.7 % | −4.4 % | 1.36 | +0.113 | 70.2 | 13.3 / 1.5 | 4/7 | +0.254 | 2.07 | 76.5 | −18.4 | 11/14 |
| 50 % @ 0.6R → BE, TP2 3R | +22.9 % | −3.2 % | 1.53 | +0.173 | 70.2 | 17.0 / 5.6 | 4/7 | +0.259 | 2.10 | 76.5 | −19.1 | 12/14 |
| 33 % @ 0.6R → BE, TP2 2.5R | +28.9 % | −4.1 % | 1.68 | +0.211 | 70.9 | 21.0 / 5.8 | 6/7 | +0.298 | 2.25 | 76.0 | −20.7 | 12/14 |
| **★ 25 % @ 0.6R → BE, TP2 3R** | **+34.6 %** | **−3.7 %** | **1.81** | **+0.248** | 70.9 | 21.5 / **10.0** | **6/7** | +0.279 | 2.17 | 76.0 | −22.8 | **13/14** |
| 25 % @ 0.6R → BE, TP2 2.5R | +29.4 % | −4.3 % | 1.68 | +0.215 | 70.9 | 21.8 / 5.6 | 6/7 | **+0.308** | **2.29** | 76.0 | −20.9 | 12/14 |
| 25 % @ 0.8R → BE, TP2 3R | +32.0 % | −4.6 % | 1.62 | +0.231 | 65.4 | 24.6 / 4.7 | 5/7 | +0.294 | 1.95 | 69.1 | −27.8 | 13/14 |
| 25 % @ 1.0R → BE, TP2 2.5R | +30.4 % | −5.5 % | 1.50 | +0.219 | 59.8 | 27.7 / 0.1 | 6/7 | +0.338 | 1.94 | 64.3 | −31.0 | 12/14 |
| 33 % @ 1.0R → BE, TP2 3R | +36.9 % | −5.3 % | 1.60 | +0.264 | 59.8 | 28.7 / 4.9 | 6/7 | +0.319 | 1.89 | 64.6 | −29.2 | 12/14 |
| 50 % @ 0.4R, **no BE**, TP2 3R | +24.1 % | −3.6 % | 1.46 | +0.173 | 31.3 | 17.9 / 4.7 | 6/7 | +0.248 | 1.74 | 35.0 | −30.8 | 12/14 |
| single TP 1.5R, no partial (B) | +16.8 % | −11.4 % | 1.21 | +0.121 | 45.5 | 22.5 / −6.5 | 4/7 | +0.348 | 1.76 | 54.6 | −35.4 | 12/14 |
| single TP 3R, no partial | +31.6 % | −8.9 % | 1.31 | +0.226 | 31.1 | 25.9 / 3.9 | 5/7 | +0.363 | 1.55 | 34.8 | −55.5 | 12/14 |
| single TP 3R, **BE after 1R** | +39.5 % | −6.4 % | 1.58 | +0.270 | 23.5 | 31.8 / 3.8 | 5/7 | +0.334 | 1.90 | 23.5 | −31.2 | 11/14 |
| 50 % @ 0.4R + **0.3R trail** on the runner, TP2 1.5R (C) | +18.0 % | **−2.5 %** | 1.65 | +0.134 | 80.9 | 13.6 / 3.9 | 6/7 | +0.150 | 1.80 | 81.5 | −19.8 | 12/14 |
| 50 % @ 0.4R + 0.5R trail, no TP2 | +15.5 % | −3.0 % | 1.56 | +0.117 | 80.9 | 13.8 / 1.5 | 5/7 | +0.134 | 1.72 | 80.9 | −20.8 | 12/14 |
| whole position, **2R trail**, no TP (C2) | +56.8 % | −11.9 % | 1.57 | +0.381 | 34.4 | 55.4 / **−5.5** | 4/7 | +0.387 | 1.80 | 40.1 | −53.4 | 11/14 |
| whole position, 1R trail | −0.7 % | −6.4 % | 0.98 | −0.004 | 41.7 | 3.1 / −3.7 | 4/7 | +0.231 | 1.77 | 45.7 | −30.9 | 11/14 |
| ladder 34/33/33 @ 0.4/1.0/2.0R (D) | +17.0 % | −3.2 % | 1.65 | +0.132 | 81.0 | 13.5 / 3.2 | 6/7 | +0.170 | 1.91 | 81.2 | −20.7 | 12/14 |
| ladder 25/25/50 @ 0.6/1.2/2.0R | +26.4 % | −4.0 % | 1.62 | +0.193 | 70.9 | 21.3 / 3.2 | 6/7 | +0.281 | 2.18 | 76.0 | −21.3 | 12/14 |
| ladder + stop ratchet to the previous target | +10.6 % | −4.0 % | 1.42 | +0.084 | 81.0 | 7.4 / 3.2 | 4/7 | +0.184 | 1.97 | 80.8 | −19.5 | 11/14 |
| current spec + 15-min time stop (E) | +15.1 % | −2.9 % | 1.67 | +0.111 | 72.2 | 11.6 / 3.1 | 5/7 | **+0.062** | 1.36 | 63.9 | −19.6 | 10/14 |
| current spec, BE at +0.2R instead of entry (F) | +15.7 % | −3.1 % | 1.58 | +0.120 | 80.9 | 11.7 / 3.9 | 5/7 | +0.155 | 1.83 | 81.0 | −19.3 | 11/14 |

Full grid: `rm_study_grid.csv` (580 rows) · in-sample vs OOS: `rm_is_vs_oos.csv` (88 rows, Spearman rank correlation of
R/trade between the two periods **0.73** — the ranking is real, not noise) · this table: `rm_summary_table.csv`.

![equity](charts/rm_equity_finalists.png)

---

## 2. What the data says

**2.1 The 0.4R partial is too early and the 1.5R target too close.**  With SL = zone edge, 81 % of fills reach +0.4R, but
70 % also reach +0.6R, 58 % +1R, 44 % +1.5R, 35 % +2R and 25 % +3R (OOS; in-sample 82 / 77 / 65 / 53 / 40 / 25 %,
`rm_mfe_survival.png`).  *Given* a trade reached +0.6R it reaches +1.5R 63–69 % of the time and +3R 33–36 %.  The current
spec sells half of every winner for +0.4R and caps the other half at 1.5R, so the whole system makes **+0.098 R/trade**
from a trade population whose average uncapped excursion is **2.2 R**.

![mfe](charts/rm_mfe_survival.png)

**2.2 Moving the partial from 0.4R to 0.6R is the single biggest improvement, and it is monotone in-sample.**  In-sample
R/plan for a 50 % partial with TP2 1.5R: 0.2R +0.087 · 0.3R +0.109 · **0.4R +0.165** · 0.5R +0.210 · **0.6R +0.254** ·
0.8R +0.270 · 1.0R +0.297.  OOS the same sweep gives +7.6 / +8.3 / +12.3 / +11.8 / +14.7 / +14.4 / +20.0 %.  The cost is
a lower hit-rate (81 → 77 → 70 → 65 % in-sample) and a deeper drawdown beyond 0.6R (OOS max DD 3–4 % up to 0.6R, 8–9 % at
0.8–1.0R).  0.6R is the knee: most of the gain, almost none of the extra drawdown.

**2.3 Take a smaller partial and let more run.**  With the partial at 0.6R, closing **25 %** instead of 50 % adds ~+0.02–0.05
R/plan in-sample and +6–12 % OOS at equal drawdown (25 % / 33 % / 50 % @ 0.6R, TP2 3R: OOS +34.6 / +33.3 / +22.9 %, IS
+0.279 / +0.273 / +0.259).  Below 25 % the two legs cannot be sized on a 0.01-lot account at small risk.

**2.4 TP2 2.5–3R beats 1.5R** in every partial system (heat-map `rm_heat_partial_tp.png`); 2.5R and 3R are equivalent
in-sample (+0.308 vs +0.279 for 25 % @ 0.6R), 3R was better OOS (+34.6 vs +29.4 %) and had the best second half (+10 R
Jun–Sep, the period where every other system struggles).  1.0R is also better than 1.5R OOS (+15.9 vs +12.3 %) but worse
in-sample — 1.5R is simply a poor spot in this distribution.

![heat](charts/rm_heat_partial_tp.png)

**2.5 Break-even stays.**  Removing the BE move raises the average (in-sample +0.240 vs +0.165 at 0.4R/1.5R) but the
win-rate collapses (81 → 55 %) and the drawdown in R grows 20–50 %; the same money is made with far less pain by a later,
smaller partial.  A **BE trigger without a partial** (single TP 3R, BE once price closed ≥ 1R away) is the best single-target
system (+39.5 % OOS, +0.334 IS) but has a 23 % win-rate, 6.4 % OOS drawdown and −31 R in-sample drawdown — very hard to
trade live.  Locking a few ticks (BE at +0.2R) adds ≈ +0.01 R/plan; it is a harmless tweak, not a system change.

**2.6 Trailing stops: a tight trail on the runner protects, a wide trail on the whole position is a regime bet.**
Adding a 0.3R trail to the runner of the current spec is the *lowest-drawdown* system of the study (OOS +18 %, DD −2.5 %,
Sharpe 3.6) but does not add expectancy in-sample (+0.150 vs +0.165).  Trailing the whole position by 2R with no target is
the OOS return winner (+56.8 %) and the in-sample winner (+0.387 R/plan) — but it is entirely a trend-following overlay: 34 %
win-rate, 12 % OOS drawdown, −53 R in-sample drawdown, **negative in the second OOS half (−5.5 R)**, 4-hour average hold
(swaps, weekend exposure), and 1R / 1.5R trails are far worse (−0.7 % / +15.6 %).  It is not a robust choice.

**2.7 Ladders, ratchets, time stops do not help.**  A 3-leg ladder never beats the equivalent 2-leg system (25/25/50 @
0.6/1.2/2.0R: +26.4 % vs +34.6 % for 25 % @ 0.6R → 3R); ratcheting the stop to the previous target costs 6 % OOS (it stops
runners in noise).  A 15-minute time stop looks good OOS (+15 %) but is the **worst** system in-sample (+0.062 R/plan) — a
textbook OOS-only artefact; do not use.  BE latency (2 min), netting accounts and worst-case intrabar path change nothing.

![isoos](charts/rm_is_vs_oos.png)

---

## 3. Recommendation

**Change the management to: close 25 % at +0.6R, move the stop to break-even, TP2 = +3R** (`A_p0.6_f0.25_tp3.0`):

```
python trader.py --symbol XAUUSD.t --risk 1.0 --commission 7 --trader partial_r=0.6,partial_frac=0.25,tp2_r=3.0
```

| | current spec | recommended | change |
|---|---|---|---|
| OOS return (Mar–Sep 2026, $10k, 1 %) | +12.3 % | **+34.6 %** | ×2.8 |
| OOS profit factor / R per trade | 1.46 / +0.098 | **1.81 / +0.248** | |
| OOS max drawdown | −3.2 % | −3.7 % | +0.5 pt |
| OOS Sharpe (daily) / positive months | 2.35 / 5 of 7 | **3.53 / 6 of 7** | |
| OOS second half (Jun–Sep, the hard period) | +2.2 R | **+10.0 R** | |
| in-sample R per plan (1 270 plans, 14 months) | +0.165 | **+0.279** | +69 % |
| in-sample PF / positive months | 1.88 / 11 of 14 | **2.17 / 13 of 14** | |
| win-rate | 81 % | 71 % | −10 pt |
| outcome mix (OOS) | 62 % partial→BE, 19 % TP2, 19 % SL | 51 % partial→BE, 20 % TP2, 29 % SL | |
| avg hold | 43 min | 125 min | |
| M5 / other TFs / buys / sells (OOS R) | +9.8 / +3.0 / +13.6 / −0.8 | +22.9 / +8.6 / +30.4 / +1.1 | every subset improves |

*Why this one and not the +37–57 % systems:* it is the best **return / drawdown** of all 580 variants (9.3), one of the two
managements in the top-10 both OOS and in-sample, it has the best Jun–Sep result, 13 of 14 in-sample months positive, and
its parameters sit on a plateau (0.6R × 25–33 % × 2.5–3R are all +29–35 % OOS / +0.27–0.31 R in-sample) rather than on a
spike.  The single-target-3R-with-BE-after-1R and the 2R-trail systems make more in the trending spring of 2026 but have
2–3× the drawdown, ≤ 34 % win-rates and negative or flat second halves.

**If lower drawdown matters more than return:** `partial_r=0.4,trail_r=0.3` (current partial + 0.3R trail on the runner):
OOS +18 %, max DD 2.5 %, Sharpe 3.6, win-rate unchanged at 81 % — but no in-sample gain over the current spec.

**Stress tests of the recommendation** (OOS, `rm_stress.csv`, `charts/rm_stress.png`): spread ×1.5 +17.2 %, spread ×2
+6.5 %, slippage ×3 +31.4 %, worst intrabar path +34.6 %, 2-min BE delay +34.4 %, netting account +28.5 %, commission ×2
+24.0 %, risk 0.5 % +10.4 % / DD 2.5 %, risk 2 % +63.8 % / DD 7.6 %, max 2 open positions +34.6 %.  It stays ahead of the
current spec in every cell.  Its only weak spot is the same as the whole bot's: doubling the spread halves the result.

![stress](charts/rm_stress.png)

---

## 4. Honest caveats

* Six OOS months / 127 trades: the t-statistic of the recommended system's mean R is 2.3 (current spec 1.8).  The in-sample
  replay (1 270 plans, t ≈ 9) is what makes the direction credible — the *size* of the OOS gain (+22 pt) is partly spring-2026
  trend luck; expect something like the in-sample ratio (+60–70 % more R per trade than the current spec), not ×2.8.
* Sells remain ≈ 0 under every management; the edge is in the buys.  Fewer, later partials mean more full −1R stops (29 %
  vs 19 %) and 2–3 h holds: psychologically harder than the current 81 %-win system although it makes more.
* The in-sample replay uses each plan in isolation (no position limits, no compounding); the OOS uses the full portfolio.
  Parity of the two engines on the current spec is exact (1 270 / 1 270 identical outcomes).
* All partial systems are executable with the existing live bot: two limit legs (25 % / 75 %) with server-side TPs and the
  BE modification after leg A closes — no new order type is needed.  `trail_r`, `be_trigger_r`, `max_hold_min` and ladders
  exist in the simulator only; the live bot would need the corresponding stop-modification loop before those could be used
  (not required for the recommendation).

## 5. Files

* `run_rm_study.py` → `rm_study_grid.csv`, `rm_study/<variant>.json|_trades.csv|_equity.csv` (580 variants, resumable)
* `rm_insample.py` → `rm_insample.csv`, `rm_insample/<variant>.json|_trades.csv`, population `rm_insample_population.pkl`
* `rm_stress.py` → `rm_stress.csv`, `rm_stress/*.json` · `make_rm_report.py` → `charts/rm_*.png`, `rm_is_vs_oos.csv`, `rm_summary_table.csv`
* `run_v9_all.sh` — runs the whole pipeline (resumable, commits after every step)
* simulator additions (`lubot/execution.py::TraderConfig`, `lubot/portfolio_sim.py`): `partial_frac=0`, `tp2_r=0`, `tp_levels/tp_fracs`,
  `ratchet_sl`, `be_on_partial`, `be_trigger_r`, `trail_r/trail_start_r/trail_after_partial/trail_source`, `max_hold_min`
  — defaults reproduce v8 byte-for-byte (62 tests).
