# MORE TRADES AT THE SAME LOSS PROFILE (v11) — how can the bot trade more without losing more?

**Question.**  The v10 trader (4-leg ladder, v8 filter, loss rules) takes **{r0[trades]} trades a year** (full year Sep 2025 → Sep 2026,
{r0[return_%]:+.1f} %, max drawdown {r0[max_dd_%]:.1f} %, PF {r0[profit_factor]:.2f}, win {r0[win_%]:.0f} %, worst day {r0[worst_day_%]:.1f} %).  Find a way to make
**more trades** while **keeping the loss percentage** (drawdown, stop-rate, worst day, profit factor) where it is.

**Answer in one line.**  The single biggest robust lever is not a looser filter but the **cross-timeframe de-duplication**: v10 refuses a zone
when another timeframe already has an order on the same level.  Those are *confluence* zones and they are among the best trades of the
year.  Trading them (`dedupe_cross_tf=false`, **v11-A**) gives **{alt[trades]} trades ({alt_pct:+.0f} %), {alt[return_%]:+.0f} % (v10 {r0[return_%]:+.0f} %), max DD {alt[max_dd_%]:.1f} %
(v10 {r0[max_dd_%]:.1f} %), PF {alt[profit_factor]:.2f} (v10 {r0[profit_factor]:.2f}), win {alt[win_%]:.0f} %**, out-of-sample PF {alt[OOS_PF]:.2f} (v10 {r0[OOS_PF]:.2f}).  Adding a slightly lower quality bar
on the two slow timeframes (M30/H1 0.60 → 0.57; each held the loss profile alone) gives the recommendation **v11-B: {rec[trades]} trades
({rec_pct:+.0f} %), {rec[return_%]:+.0f} %, max DD {rec[max_dd_%]:.1f} %, PF {rec[profit_factor]:.2f}, win {rec[win_%]:.0f} %, {rec[months_pos]}/{rec[months]} months positive, OOS PF {rec[OOS_PF]:.2f}**.
Everything that adds trades by *waiting longer for a fill* (persisting or grace-period orders), by *entering in front of the zone*, or by
*lowering the M5 / M10 quality bar* adds trades **and** losses — drawdown 7–16 %, out-of-sample PF 1.0–1.3 — and is rejected.  The price
of the extra trades is a worse worst-day ({rec[worst_day_%]:.1f} % vs {r0[worst_day_%]:.1f} %) and a deeper drawdown when the spread doubles (9.3 % vs 6.8 %): two plans on
the same level can now be stopped together.

![equity](charts/v11_equity.png)

---

## 0. Method (every number has a file behind it)

* **Reference** = the v10 trader exactly (`run_v11_funnel.py` reproduces the v10 full-year run byte for byte: {r0[trades]} trades, {r0[return_%]:+.2f} %,
  DD {r0[max_dd_%]:.2f} %).  Full-year selection streams `sel_v10_<TF>.pkl` (Sep 2025 → Sep 2026), M1 portfolio simulator, real per-minute
  spread (imputed where missing), $7/lot commission, $0.10 stop slippage, swaps, 1 % risk on $10 000, ≤ 4 open positions, mirror order
  policy, G ladder 25 % × 4 @ 0.6/1.2/2.4/4.8R with BE after leg 1, loss rules 4.5 % / 9 % on.
* **Honesty.**  The entry (quality) model was trained until 2026-03-01, so Sep 2025 – Feb 2026 is **in-sample (IS)** for the entries and
  Mar – Sep 2026 is **out-of-sample (OOS)**.  Every variant is judged on the OOS half (`OOS_R`, `OOS_PF`); the IS half is shown but
  distrusted — the M10 quality relaxation below is the textbook example (IS +50 R, OOS collapses).
* **"Loss profile held"** (`hold_loss`): max DD not more than 0.5 pt deeper than the reference, PF ≥ ref − 0.05, win-rate ≥ ref − 3 pts,
  worst day ≥ ref − 0.5 pt.
* Steps: (1) funnel diagnosis `run_v11_funnel.py`; (2) grid A = {n_lev} single existing levers `run_v11_levers.py`; (3) three new simulator
  levers (`dedupe_cross_tf`, `overlap_mode=allow|share`, `cancel_grace_min`; defaults byte-identical to v10, parity check exact, 4 tests)
  and grid B ({n_b} singles) + {n_c} combinations `run_v11_combos.py`; (4) stress × 6 of the finalists + walk-forward check; (5) this report
  `make_v11_report.py`.  `dedupe_cross_tf` is ported to the live bot (`trader.py`, 2 fake-MT5 tests).  **97 tests pass.**  All runs are
  resumable (one json per run in `study_results/v11_levers/`).

---

## 1. Where do the trades get lost?  (funnel of the v10 reference)

The scanner showed **{T[shown]} unique POIs** in the year; **{T[traded]} became trades ({traded_pct:.1f} %)**.

{T[funnel]}

Detailed reasons (unique POIs, top 14):

{T[reasons]}

![funnel](charts/v11_funnel.png)

Reading: two thirds of the POIs die in the v8 trade filter (M5 mostly on the cost gate — thin zones; the other timeframes on the
quality bar), 18 % had an order that was cancelled before the fill because the scanner stopped showing the POI (mirror policy), and
**9 % were refused because another timeframe already had an order on the same level** ("overlaps pending", mostly M10/M15/M30).  The
traded population has median quality 0.61 vs 0.54 for everything shown.  The fill rate of placed orders is 26 %.

---

## 2. Grid A — relax one existing gate at a time ({n_lev} variants)

{T[gridA]}

* **Quality bars.**  M30 0.60 → 0.57/0.55/0.52 adds 9/19/28 trades with OOS +33/+33/+36 R (ref +26.7) and PF 1.80/1.72/1.70 → **holds**.
  H1 0.57 (+4 trades, OOS +30 R) holds.  M15 0.57 (+17) is neutral.  **M10** relaxation is the trap: +55…156 trades, in-sample +50 R, but
  **out-of-sample falls to +15…20 R** — lower-quality M10 POIs are exactly what the entry model learned on.  M5 below 0.55: OOS +16…23 R,
  DD 7–11 %.
* **M5 cost / session gates.**  cost 0.12 (+32 trades, OOS +27 R, PF 1.60) and all-sessions (+48, OOS +27 R, PF 1.66) are neutral OOS but
  raise the worst day to −2.9 %; the in-sample half likes them (that is where the nypm rule was chosen).  Not recommended.
* **Order handling.**  `persist` orders (keep waiting up to N bars): +76…361 trades, **DD 11–16 %, OOS PF 1.1–1.25** — the scanner drops a
  POI for a reason.  Entering in front of the zone (`entry_offset_frac` < 0): more fills, DD 7–12 %.  Entering deeper: fewer trades.
* **Never binding:** `max_open_positions` 6/8 and `one_trade_per_poi=false` change nothing (the scanner never re-shows a traded POI).
* **`dedupe_overlap` off** (`dedupe1.01`): 334 trades, +129 %, PF 1.84, OOS +34.8 R — the discovery that led to grid B.

---

## 3. Grid B — new levers ({n_b} singles) and combinations ({n_c})

New `TraderConfig` fields (all default to the v10 behaviour): `dedupe_cross_tf=false` — the overlap check only looks at plans of the
*same* timeframe, so a level shown on two timeframes is traded on both; `overlap_mode=allow|share` + `overlap_risk_frac` — trade the
overlapping plan at full or reduced risk; `cancel_grace_min=N` — keep a mirrored order N minutes after the scanner drops the POI.

{T[gridB]}

* **`dedupe_cross_tf=false` is the lever.**  +80 trades; every loss metric inside the band except the worst day (−2.75 % vs −1.94 %).  The
  extra trades are M15 +31 (win 81 %, +0.67 R/trade), M10 +28, M30 +13, H1 +7 — confluence zones.  Max concurrent positions 2 → 4.
* **Sharing the risk** on the second plan (25/50/75 %) keeps the trade count but *lowers* return and PF: the confluence trades are the better
  half, cutting their size hurts.  `allow` (= dedupe fully off) ≈ `xtf` with a slightly deeper DD (same-TF overlaps are noise, not confluence).
* **Grace periods** 5–60 min: +144…+340 trades, DD 12–16 %, OOS PF 1.04–1.14 → rejected for the same reason as persisting orders.

Best combinations (max DD ≤ 6 %, sorted by OOS R, top 16):

{T[combos]}

![scatter](charts/v11_scatter.png)

Walk-forward check: ranking the 114 non-grace variants on the **in-sample half only** puts `xtf` in 11 of the top 12; Spearman(IS R, OOS R)
= 0.54 (p = 6e-10).  The IS half also favours `m5sess` (all M5 sessions), whose OOS PF is 1.42–1.64 — an in-sample artefact, not recommended.

---

## 4. Stress of the finalists (full year; return / max DD / OOS PF)

{T[stress]}

The recommendation stays ahead of the reference on return and OOS PF in every scenario.  Its weak point is the **drawdown at double
spread (9.3 % vs 6.8 %)**: with the spread doubled the small M5 zones lose their edge on every system, and two confluence plans can be
stopped in the same move (April 2026: −$673).  At half risk (0.5 %) v11-B makes +63 % at 2.4 % DD.

---

## 5. What the extra trades are (v11-B vs v10)

Per timeframe, full year (n / R):

{T[bytf]}

The {T[n_extra]} trades v11-B takes and v10 does not:

{T[extra]}

{T[extra_line]}

![monthly](charts/v11_monthly.png)

---

## 6. Recommendation

**v11-B** — `dedupe_cross_tf=false` + `M30|H1:min_quality=0.57` (everything else as v10): **{rec[trades]} trades / year ({rec_pct:+.0f} %), {rec[return_%]:+.0f} %,
max DD {rec[max_dd_%]:.1f} %, PF {rec[profit_factor]:.2f}, win {rec[win_%]:.0f} %, Sharpe {rec[sharpe_daily]:.2f}, {rec[months_pos]}/{rec[months]} months positive, OOS PF {rec[OOS_PF]:.2f}.**

```
python trader.py --symbol XAUUSD.t --risk 1.0 --commission 7 --timeframes M5,M10,M15,M30,H1 ^
  --trader "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false" ^
  --trade-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15:min_quality=0.60/M30|H1:min_quality=0.57"
```

**v11-A** (conservative: only the dedupe change, v8 filter untouched): {alt[trades]} trades, {alt[return_%]:+.0f} %, DD {alt[max_dd_%]:.1f} %, PF {alt[profit_factor]:.2f}.

Caveats, honestly: the worst single day moves from {r0[worst_day_%]:.1f} % to {rec[worst_day_%]:.1f} % (v11-A {alt[worst_day_%]:.1f} %) and up to 4 positions can be open at once
on correlated levels — the 4.5 % daily limit is now closer (theoretical one-bar worst case 4 × 1 % + slippage).  Keep risk at 1 % or less;
the loss rules never triggered in the year at 1 %.  The M30/H1 relaxation rests on 33 + 14 trades — small samples; v11-A is the part that
is robust on both halves and in every stress scenario.  Do **not** add grace/persist orders, front entries or M10/M5 quality
relaxations — all of them add trades and losses.
