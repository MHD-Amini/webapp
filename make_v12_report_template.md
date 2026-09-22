# MORE TRADES AT THE SAME LOSS PROFILE, round 2 (v12) — what is left after v11?

**Question.**  The v11-B trader (confluence zones traded on both timeframes, M30/H1 quality 0.57, 4-leg ladder, v8 M5 filter, loss
rules) takes **{r0[trades]} trades a year** (Sep 2025 → Sep 2026: {r0[return_%]:+.1f} %, max drawdown {r0[max_dd_%]:.2f} %, PF
{r0[profit_factor]:.2f}, win {r0[win_%]:.1f} %, stop-rate {r0[sl_%]:.1f} %, worst day {r0[worst_day_%]:.2f} %, out-of-sample PF
{r0[OOS_PF]:.2f}).  Find a way to make **more trades** while **keeping the loss percentage** where it is.

**Answer in one line.**  Two mechanical levers add trades without touching the loss profile: (1) **do not cancel a pending order the
moment the scanner *replaces* its zone by a better one on the same slot — keep it one bar of its timeframe** (`keep_replaced_bars=1`,
higher timeframes only), and (2) **judge a zone that is already active on another timeframe by a looser M10 quality bar** (confluence
filter, M10 0.50 instead of 0.60).  Together with a plain M10 quality 0.57 this is **v12-A: {ra[trades]} trades ({pa:+.0f} %),
{ra[return_%]:+.0f} %, max DD {ra[max_dd_%]:.2f} %, PF {ra[profit_factor]:.2f}, win {ra[win_%]:.1f} %, stop-rate {ra[sl_%]:.1f} %, worst
day {ra[worst_day_%]:.2f} %, OOS PF {ra[OOS_PF]:.2f}, {ra[months_pos]}/13 months positive** — every loss metric inside the v11 band on the
full year *and* on the out-of-sample half, and **more robust than v11-B when the spread doubles** (DD 6.6 % vs 9.3 %).  The conservative
choice **v12-C** (keep-replaced alone) gives {rc[trades]} trades ({pc:+.0f} %) at PF {rc[profit_factor]:.2f} / OOS PF {rc[OOS_PF]:.2f}; the
aggressive **v12-B** (+ M15 confluence 0.50) gives {rb[trades]} trades ({pb:+.0f} %) but its full-year PF ({rb[profit_factor]:.2f}) and worst
day ({rb[worst_day_%]:.2f} %) leave the band.  **Re-entering a zone after a break-even exit** adds many trades but *not* edge (the re-entries
are break-even as a group, worst day −4 %, DD 10 % at double spread) and is rejected; so is any relaxation of the M5 gates.

![equity](charts/v12_equity.png)

---

## 0. Method

* **Reference** = the v11-B trader exactly (`run_v12_funnel.py` reproduces the v11 study run byte for byte: {r0[trades]} trades,
  {r0[return_%]:+.2f} %, DD {r0[max_dd_%]:.2f} %).  Full-year selection streams `sel_v10_<TF>.pkl` (Sep 2025 → Sep 2026), M1 portfolio
  simulator, real per-minute spread (imputed where missing), $7/lot commission, $0.10 stop slippage, swaps, 1 % risk on $10 000, ≤ 4 open
  positions, mirror order policy, G ladder 25 % × 4 @ 0.6/1.2/2.4/4.8R with BE after leg 1, loss rules 4.5 % / 9 %, `dedupe_cross_tf=false`,
  filter `M5:cost 0.08 / q 0.55 / no NY-pm; M10|M15 q 0.60; M30|H1 q 0.57`.
* **Honesty.**  The entry model was trained until 2026-03-01: Sep 2025 – Feb 2026 is **in-sample (IS)**, Mar – Sep 2026 **out-of-sample
  (OOS)**.  Every variant is judged on the OOS half; the IS half is shown but distrusted (section 5 shows why, again).
* **Loss profile held** (`hold_loss`, full year): max DD not more than 0.5 pt deeper (0.7 pt used in the tables), PF ≥ ref − 0.05, win ≥
  ref − 3 pts, worst day ≥ ref − 0.5 pt.  `hold_oos`: the same on the OOS half (PF, win, stop-rate + 2 pts) plus the DD condition.
* Steps: (1) funnel `run_v12_funnel.py`; (2) three new simulator levers, defaults byte-identical to v11 (parity exact), 6 unit tests;
  (3) grid `run_v12_levers.py`: 61 singles + {n_x} combinations = {n_all} full-year runs, resumable (one json per run in
  `study_results/v12_levers/`); (4) stress × 6 + walk-forward `run_v12_stress.py`; (5) this report `make_v12_report.py`.  Both winning
  levers are ported to the live bot (`trader.py`, 2 fake-MT5 tests).  **104 tests pass.**  The whole pipeline ran unattended
  (`run_v12_all.sh`, autosave every 4 minutes) and survived seven sandbox migrations without losing a run.

---

## 1. Where do the trades get lost now?  (funnel of the v11-B reference)

The scanner showed **{shown} unique POIs** in the year; **{r0[trades]} became trades ({ex[e_oos][n]} of them out-of-sample)**.

{T[funnel]}

Top reasons (unique POIs):

{T[reasons]}

What the funnel says about the remaining levers:

* **'price already at/through entry' skips: {ex[a_price_through_entry_pois]}** in the whole year → deferring the entry is *not* a lever.
* **{ex[b_replaced_pois]} POIs had an order that was cancelled because the scanner *replaced* the zone by another one** on the same slot —
  and **{ex[b_replaced_then_reshown]} of them were shown again later**, i.e. the zone was still valid.  In v11 the *grace period* lever
  (keep every cancelled order N minutes) failed because it also kept orders of zones the scanner had *dropped*; keeping only the *replaced*
  ones, and only on the slow timeframes, is the new lever `keep_replaced_bars`.
* **{ex[c_quality_rejects_confluent_with_a_trade]} quality-rejected POIs overlapped (≥ 50 %) a zone that another timeframe actually
  traded** within ± 2 days (M10 {ex[c_confluent_by_tf][M10]}, M15 {ex[c_confluent_by_tf][M15]}, M5 {ex[c_confluent_by_tf][M5]},
  M30 {ex[c_confluent_by_tf][M30]}, H1 {ex[c_confluent_by_tf][H1]}; median quality {ex[c_confluent_quality_quantiles][0.5]}).  v11 showed
  that confluence zones are the best trades of the year → a *confluence-conditional* quality bar is lever #2 (`confluence_filter`).
* **A traded POI is never re-shown by the scanner** ({ex[d_traded_pois_reshown_after_close]} cases) → a re-entry after a break-even exit
  must be driven by the trader itself (`reentry_bars`, tested and rejected below).
* Winners and losers have the **same median quality per timeframe** (M5 0.60 vs 0.59, M10 0.63 vs 0.63) — above 0.55 the quality bar has
  little ranking power, which is why relaxing it *where extra evidence exists* is defensible and relaxing it blindly is not.

---

## 2. New levers (all default to the v11 behaviour)

`TraderConfig` / `--trader` keys, simulator and live bot share the code:

* `keep_replaced_bars=N` + `keep_replaced_tfs=M10|M15|M30|H1` — mirror policy: an order whose POI was *replaced* on its slot stays N bars
  of its timeframe (re-shown in time → kept for good); a *cleared* slot ('no longer shown') still cancels at once.
* `confluence_filter=<filter string>` (CLI `--confluence-filter`) — used *instead of* `--trade-filter` when the plan's zone overlaps
  (≥ `dedupe_overlap`) an active order/position of *another* timeframe.
* `reentry_bars=N`, `reentry_max`, `reentry_tfs`, `reentry_outcomes` — after a break-even exit the same plan is re-armed as a fresh limit
  order for N bars (tested, **not recommended**).

## 3. Single levers ({n_all} − {n_x} runs)

{T[singles]}

* **Keep replaced (KR).**  All timeframes: +53 … +109 trades but the extra M5 orders lose (−11 R on 36 trades) and the DD goes to 6.7–8.9 %.
  **Higher timeframes only** (`KR_htf_b1`): +23 trades, PF 1.99, win 73 %, stop-rate 26 %, OOS PF 1.84 — better than the reference on every
  loss metric except a 0.6-pt deeper DD.  Longer keeps (2–6 bars) add trades but dilute (OOS PF 1.65–1.75).
* **Confluence filter (CF).**  M10 quality 0.50 for zones active on another TF: +21 trades, PF 1.90, OOS PF 1.72 (neutral).  M15 0.50/0.52:
  +23…31 trades, OOS PF 1.69/1.70 (slightly negative OOS).  Both M10+M15 at 0.50: +55 trades, PF 1.83, OOS PF 1.64.  Dropping the HTF bar
  completely for confluence zones (+79): DD 7.3 %.  H1 confluence extras lose (−5.7 R / 10).  M5 variants change nothing (M5 is rarely the
  *second* timeframe on a level).
* **Re-entry (RE).**  All TFs, 1 bar: +134 trades of which 69 BE / 52 SL / 13 TP = −1.8 R.  M10/M15 only: +52 trades, OOS PF 1.82, but
  worst day −4.0 % and (section 4) DD 10.6 % at double spread.  Wider windows only add stops.
* **Plain relaxations re-checked on v11-B:** M10 0.57 (+30, OOS PF 1.70, neutral), M5 cost 0.12 (+35, DD 5.9, worst day −3.0).

## 4. Combinations ({n_x} runs) — those holding the OOS band (max DD ≤ 6 %), by trades

{T[combos_hold]}

Most trades regardless of the loss profile (all contain re-entry):

{T[combos_top]}

![scatter](charts/v12_scatter.png)

Every combination that contains re-entry blows the drawdown (7.8–10.6 %): a re-entry can stack with a confluence plan on the same
level and they stop together.  The keep-replaced + confluence family is the one that adds trades *and* keeps the profile.

### Stress of the finalists (full year; return / max DD / OOS PF)

{T[stress]}

v12-A and v12-C are **more robust than the reference at double spread** (DD 6.6 / 5.7 % vs 9.3 %): the kept orders are on wide
higher-timeframe zones that pay little spread per R.  Re-entry collapses at double spread (DD 10.6 %, OOS PF 1.37).

![drawdown](charts/v12_drawdown.png)

---

## 5. Walk-forward — can the in-sample half pick the winner?

{T[wf_line]}  **No.**  The 12 variants with the best in-sample R are *all* heavy confluence relaxations (M15 0.50/0.52 + keep 2–3 bars):

{T[wf_top]}

They rank 60th–190th out-of-sample — exactly the in-sample trap v11 found with the M10 relaxation.  The finalists:

{T[wf_fin]}

**Honest reading.**  The finalists were *chosen* on the OOS half, so their OOS numbers carry selection bias.  What survives that caveat:
the **keep-replaced lever is mechanical** (it does not depend on the entry model's scores) and is positive on both halves and in every stress
scenario — that is the robust core.  The M10 confluence bar (0.50) and the plain M10 0.57 are *neutral* out-of-sample (PF 1.72 / 1.70 vs
1.73) and add ~50 trades between them; the M15 relaxations (v12-B) are slightly negative OOS (1.65–1.69) — v12-B's weak link.

---

## 6. What the extra trades are

Per timeframe, full year (n / R):

{T[bytf]}

**v12-A vs v11-B.**  {T[extra_line_A]}

{T[extra_tf_A]}

{T[extra_how_A]}

**v12-B vs v11-B.**  {T[extra_line_B]}

{T[extra_tf_B]}

![monthly](charts/v12_monthly.png)

---

## 7. Recommendation

**v12-A** — v11-B + `keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1` + confluence filter with M10 quality 0.50 + plain M10
quality 0.57: **{ra[trades]} trades / year ({pa:+.0f} %), {ra[return_%]:+.0f} %, max DD {ra[max_dd_%]:.2f} %, PF {ra[profit_factor]:.2f},
win {ra[win_%]:.1f} %, stop-rate {ra[sl_%]:.1f} %, Sharpe {ra[sharpe_daily]}, {ra[months_pos]}/13 months positive, OOS PF {ra[OOS_PF]:.2f}.**

```
python trader.py --symbol XAUUSD.t --risk 1.0 --commission 7 --timeframes M5,M10,M15,M30,H1 ^
  --trader "tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge,dedupe_cross_tf=false,keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1" ^
  --trade-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.57/M15:min_quality=0.60/M30|H1:min_quality=0.57" ^
  --confluence-filter "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.50/M15:min_quality=0.60/M30|H1:min_quality=0.57"
```

**v12-C** (conservative — only the mechanical lever): v11-B + `keep_replaced_bars=1,keep_replaced_tfs=M10|M15|M30|H1`:
{rc[trades]} trades ({pc:+.0f} %), {rc[return_%]:+.0f} %, DD {rc[max_dd_%]:.2f} %, PF {rc[profit_factor]:.2f}, OOS PF {rc[OOS_PF]:.2f}.

**v12-B** (aggressive): v12-A with M15 also at 0.50 in the confluence filter: {rb[trades]} trades ({pb:+.0f} %), {rb[return_%]:+.0f} %, DD
{rb[max_dd_%]:.2f} %, PF {rb[profit_factor]:.2f}, worst day {rb[worst_day_%]:.2f} %, OOS PF {rb[OOS_PF]:.2f} — outside the band on PF and worst day.

Caveats: the extra trades are concentrated on M10/M15 and sit on levels already traded by another timeframe, so up to 4 correlated
positions can be open; keep risk at 1 % or less (at 2 % the DD is 10–15 %).  The worst day moves from −2.3 % to −2.65 %.  Do **not** add
re-entries, grace/persist orders, M5 relaxations or the M15 confluence bar below 0.57 — every one of them adds trades *and* losses.
