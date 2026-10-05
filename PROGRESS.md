# PROGRESS — v15 MORE TRADES & MORE PROFIT for the v14-A trader AT THE SAME LOSS PERCENTAGE — IN PROGRESS (started 2026-10-05)

**Recovery (read this first):** `git clone https://github.com/MHD-Amini/webapp.git /home/user/webapp`, `bash restore.sh`
(relinks the CSV to `data/xauusd_m1.csv`, pip, tests), read this file, continue from the FIRST UNCHECKED step below.  Every step ends
with `bash save.sh "msg"` (commit + push to GitHub origin = https://github.com/MHD-Amini/webapp).  Long jobs are resumable (one json per
run, they skip outputs that exist) and run under `run_v15_all.sh`, which autosaves (commit + push) every 4 minutes.
Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (593 863 M1 bars 2025-01-02 -> 2026-09-04; symlink
`data/xauusd_m1.csv`).  Sandbox: 2 cores, ~1 GB RAM -> simulator with `--workers 1`, never two full-year runs at once.

## User spec (v15)
1. Make the v14 trading bot (run_trader.bat = v14-A) take MORE TRADES and MORE PROFIT while MAINTAINING THE LOSS PERCENTAGE.
2. Save the process after EVERY step without exception, recoverable if the session dies (GitHub + PROGRESS.md + resumable jobs).

## Reference (v14-A, FINAL_BACKTEST_V14.md, full year 2025-09-01 -> 2026-09-04, $10 000, 1 % base risk)
430 trades, +227.53 %, max DD -5.84 %, PF 2.249, win 74.7 %, stop-outs 24.9 %, worst day -1.99 % eq, OOS PF 2.15 (224 tr), 13/13 months,
gross loss -18 220 $, avg loss -167 $, max risk 2.24 % eq.  "Loss percentage maintained" (hold_loss) = stop-out rate <= ref + 2 pt,
win rate >= ref - 3 pt, max DD <= ref + 0.5 pt, worst day >= ref - 0.5 pt, PF >= ref - 0.10, and the same on the OOS half (hold_oos).
"More trades" = trades > 430; "more profit" = net $ > +22 753 AND OOS net $ > +14 524.

## Ideas (v15) — what was NOT tried in v11/v12 (those tried: quality bars, cost bars, sessions, keep_replaced, confluence, re-entry,
## entry offset, max_open, grace periods -> MORE_TRADES_STUDY.md / MORE_TRADES_V12.md)
  A. TIERED ADMISSION: POIs that fail the quality bar by a little (e.g. M10 0.50-0.57, M15 0.55-0.60, M5 0.50-0.55) are traded at a
     REDUCED risk (`tier_risk_scale`, e.g. 0.5) instead of being skipped -> more trades, each loss smaller; the loss PERCENTAGE of
     the whole stays close because the tier adds many small trades.  Same for the M5 cost bar (0.08-0.12 at half risk).
  B. SECOND CANDIDATE: the scanner keeps up to N candidates per slot (`candidates` column) but trades only the top one; trade the 2nd
     ranked zone of the slot too (if it does not overlap the first) at reduced risk.  (Needs the candidate list - check the stream.)
  C. RE-ARM AFTER STOP: after a stop-out the zone is often re-tested; v12 tested re-entry only after BE exits (rejected).  Not retested.
  D. PROFIT side: the v14 martingale step-up gate (htf buys) could be widened to the new tier trades; range_risk_scale; swap of the
     M5 ladder.  Judge every lever on the OOS half first.
  E. NEW TRADE SOURCE: the quality model only (no scanner slot limit) is NOT available in the recorded streams -> out of scope unless
     the candidates column carries the full list.

## Plan (v15)
- [x] 0. Session start: restore env (131 tests pass), PROGRESS v15 header + plan, first save.
- [x] 1. Diagnosis `run_v15_diag.py`: reproduce v14-A (430 / +227.53 / -5.84), funnel of the v14-A reference (per TF: filtered by
        which gate, never filled, traded), would-be outcome of EVERY filtered POI by quality band / cost band / TF via
        `lubot.plan_replay` (R, win, fill rate) -> study_results/v15_diag/*.csv.  Check what the `candidates` column holds.
- [x] 2. Levers in TraderConfig / simulator (defaults byte-identical, parity test): tiered admission (`tier_filter` + `tier_risk_scale`),
        second-candidate trading if available, re-arm after SL (`rearm_sl_bars`), unit tests (tests/test_v15_levers.py), smoke.
- [x] 3. Grid `run_v15_levers.py` (resumable, workers 1) under `run_v15_all.sh` (autosave) -> study_results/v15_levers/ + v15_levers.csv;
        judge: trades, net $, OOS net $, hold_loss, hold_oos.
- [x] 4. Stress x6 + walk-forward of the finalists; port to trader.py + run_trader.bat (v15-A) + verify_bat_v15.py + fake-MT5 tests.
- [ ] 5. Final backtest `backtest_v15_final.py` -> study_results/FINAL_BACKTEST_V15.md, report MORE_TRADES_V15.md, README, final save.

## Log (v15)
- 2026-10-05 21:00  step 4b DONE: run_trader.bat ships v15-A (header rewritten; v15-B / v15-C / v14-A fallbacks documented in the REMs);
  verify_bat_v15.py reads the strings FROM the bat and replays them: 448 tr / +29 744.95 $ / +297.45 % / DD -5.82 / PF 2.375 / 210 confluent
  = IDENTICAL to study_results/v15_levers/CMB_cm240_cs1.25_0.9.json.  tests/test_bat_v15.py -> 140 tests pass.  verify_bat_v14.py is now
  expected to differ (the bat carries v15-A); the v14-A reference is reproduced by backtest_v15_final.py (strings minus the v15 keys).
- 2026-10-05 20:50  step 4a DONE.  WALK-FORWARD (walkforward_v15.py, from the trade lists, split at 2026-03-01, worst day in R):
  Spearman IS->OOS of the deltas vs ref: trades +0.90, net $ +0.84, PF +0.27 -> the extra trades and the extra dollars are population
  properties and carry over; 126/208 variants pass the v15 band on BOTH halves; the IS-chosen top 12 pass OOS in 10/12 cases.
  STRESS x6 (v15_stress.csv / v15_stress_table.csv, v14-A reference from v14_stress.csv):
  * CMB_cm240_cs1.25_0.9: net AND OOS net above v14-A in 6/6 (comm x2 +25.2 k vs +19.8 k; slip x3 +27.5 vs +21.0; worst intrabar +29.8 vs
    +23.1; spread x2 +15.7 vs +12.2; risk 0.5 +9.6 vs +8.8; risk 2 +84.5 vs +79.8); DD within +0.5 pt in 5/6 (risk 2: 14.1 vs 9.9 - the
    x1.25 on a 2 % base is 2.5 % per confluent plan, out of spec); OOS PF above ref in 6/6.  WEAK POINT: spread x2 worst day -4.55 % vs
    -1.95 % (one day of clustered confluent losers at the bigger size); 11/13 months at spread x2 (ref 12/13).
  * +Tm10q55 (477 tr): same pattern, +3-4 k$ more, DD +0.3, OOS PF 0.1 lower; spread x2 DD 8.3 (fails).
  * CM_960 (pure memory, no sizing): more trades in 6/6, net above ref in 6/6 (+1-3 k$), worst day UNCHANGED in 6/6, DD within band in 5/6.
  * mc2 == cs1.25_0.9 at 1 % risk (the cap only binds at risk 2: +70 k vs +84 k, same DD) -> not worth a key.  rr75: lowest DD, least $.
  DECISION: v15-A = confluence_memory_min=240 + confluent_risk_scale=1.25 + plain_risk_scale=0.9 (448 tr, +29 745 $, OOS +19 264, DD 5.82,
  PF 2.375, win 74.8, sl 24.8, wd -2.42, OOS PF 2.26, 13/13).  v15-B (most trades) = v15-A + tier_filter=M10:min_quality=0.55,
  tier_risk_scale=0.5 (477 tr, +32 637).  v15-C (conservative, loss profile byte-for-byte) = confluence_memory_min=960 only (459 tr, +24 619).
- 2026-10-05 20:15  step 3 DONE: 209 variants (study_results/v15_levers.csv; 2 sandbox resets during the grid, the 4-min autosave +
  resumable jsons lost nothing).  Scores: 4/4 = 24, 3/4 = 11, 2 = 127, 1 = 47.  Ref 430 tr / +22 753 $ / OOS +14 524 / DD 5.84 / PF 2.249.
  * CONFLUENCE MEMORY alone (more trades, same sizing): every window 30-960 min scores 4/4 except 15/240 (OOS net a hair below ref):
    CM_960 459 tr +24 619 OOS +15 377 DD 5.92; CM_120 443 tr +23 619; CM_240 448 tr +23 105 DD 5.32.  Loss profile untouched
    (win 74.5-75.1, sl 24.5-25.1, wd -1.95..-2.01).  'open' memory adds fewer trades; 'pending' == 'all' at 60 min.
  * CONVICTION SIZING alone: x1.25 with plain 0.75-0.8 scores 3 (fails more_trades only): +24.8-25.1 k$, DD 6.2, PF 2.45-2.51.
    x1.5+ raises DD to 7.2-8.7 and worst day to -2.8..-4.6 % -> fails hold_loss.
  * TIER: with the TF-scope fix the tiers add 25-75 trades; m5c12 (M5 cost 0.08-0.12 at q >= 0.57) x0.35 = 455 tr, 4/4 but no profit
    gain; m10q55/htfq55 raise DD to 6.4-6.7 and drop OOS PF to 1.9-2.0 -> only m5c12 / m10q55 as a small add-on.
  * DD BUY-BACKS alone: mc2 (-0.22 DD, -384 $), mo3 (-7 trades, -1.1 k$), rr75 (-2.8 k$) -> cheap: mc2.
  * COMBINATIONS (the answer): CMB_cm240_cs1.25_0.9 = 448 tr, +29 745 $ (+31 %), OOS +19 264 (+33 %), DD 5.82, PF 2.375, win 74.8,
    sl 24.8, wd -2.42, OOS PF 2.26, 13/13, max risk 2.81 % -> 4/4.  + tier m10q55 x0.5: 477 tr, +32 637 (+43 %), OOS +19 892, DD 6.08,
    PF 2.33, OOS PF 2.12 -> 4/4 (more trades, slightly weaker OOS PF).  + mc2 (martingale cap 2 %): 448 tr +29 589 DD 5.84 max risk 1.99 %.
    CAVEAT: the DD pass of cs1.25 depends on the 240-min memory window (cm30/60/120 with the same sizing: DD 6.8-7.4 = fail by 1-1.5 pt,
    worst day -2.4); conviction x1.25 raises the worst day from -1.99 to -2.4 % in every combination (inside the -0.5 pt band, but real).
  FINALISTS for step 4 stress x6 + walk-forward: CMB_cm240_cs1.25_0.9 (candidate v15-A), CMB_cm240_cs1.25_0.9_Tm10q55 (v15-B, most trades),
  CMB_cm240_cs1.25_0.9_mc2 (v15-C, capped risk), CMB_cm240_cs1.25_0.8_rr75 (lowest DD 5.38), CM_960 (pure more-trades, no sizing), CS_1.25_0.8.
- 2026-10-05 16:40  SANDBOX RESET during step 3 (back to the last pushed commit = step 1): recovered steps 2 from the uploaded git
  bundle (https://www.genspark.ai/api/files/s/CLYdwzHt), GitHub auth re-established, pushed.  Re-created run_v15_levers.py (209
  variants) + run_v15_all.sh (autosave 4 min) and relaunched the grid (resumable).  trader.py v15 port DONE in parallel: tier filter,
  conviction sizing, confluence memory persisted in trader_state.json ('memory' list, restored on restart), mart gate;
  tests/test_trader_v15.py (2 fake-MT5 tests) -> 139 pass.
- 2026-10-05 16:05  step 2 DONE: lubot/execution.py TraderConfig v15 keys (confluent_risk_scale, plain_risk_scale, confluence_memory_min,
  confluence_memory_kind, tier_filter, tier_risk_scale, mart_confluent_only; TradePlan.tier), lubot/portfolio_sim.py (_apply_v15 sizing,
  confluence memory of plans that left the books, tier admission, mart gate; trades frame + summary carry tier / risk_scale).
  tests/test_v15_levers.py (6 tests) -> 137 pass.  smoke_v15.py (11 variants, study_results/v15_smoke.jsonl): PARITY IDENTICAL
  (430 / +227.53 / -5.84).  Smoke reading vs ref net +22 753 / OOS +14 524 / DD 5.84 / PF 2.249 / win 74.7 / sl 24.9 / wd -1.99:
   * CONVICTION sizing alone (430 tr): x1.5 conf -> net +35 514 OOS +23 540 PF 2.42 but DD 7.30 wd -2.76 (fails hold_loss on DD/worst day);
     x1.5/0.75 -> +30 438 DD 7.24 PF 2.58; x2.0/0.75 -> +44 475 DD 8.26 PF 2.76.  Profit lever confirmed; DD must be bought back.
   * CONFLUENCE MEMORY alone: 60 min -> 436 tr, +23 073, OOS +14 795, DD 5.95, PF 2.257 = score 4/4 (T P L O) - the first 4/4;
     240 min -> 448 tr +23 105 DD 5.32 (OOS net slightly below ref); 240/open -> 435 tr.
   * TIER admission: M10 0.50 at half risk -> 1144 tr (!), PF 1.48, DD 10.2 = the tier bar admits far too much (the funnel count was
     unique POIs, the tier re-admits every re-show); TIER_all -> 762 tr PF 1.74.  -> tiers need a much tighter bar (M10 0.55 only) or OUT.
   * mart_confluent_only: -3 k$ (the htf-buy step-ups that pay are mostly plain) -> OUT.
   * CMB cs1.5/0.75 + cm240: 448 tr, +35 002, OOS +22 489, PF 2.52, DD 6.51, wd -2.81 -> fails DD by 0.17 and wd by 0.32.
  NEXT (step 3 grid): conviction x1.25-1.5 with plain 0.75-1.0 x memory 30-240 min (all/open) x a DD buy-back (max_open 3, range_risk_scale
  0.75, mart_max_risk_pct 2) x tight tiers (M10 0.55, confluence-tier).  The sandbox migrated during step 2 (GitHub creds lost): save.sh
  now writes a git bundle fallback; unpushed bundle uploaded: https://www.genspark.ai/api/files/s/qJGgEtvY
- 2026-10-05 14:05  step 1 DONE (run_v15_diag.py -> study_results/v15_diag/, 19 s; v14-A reproduced IDENTICAL 430 / +227.53 / -5.84).
  FUNNEL (unique POIs): trade filter rejects 2462 (M5 1344, M10 444, M15 415, M30 164, H1 95); 964 orders never filled; 430 traded;
  overlaps 24.  max_open never binds (2 cancels at fill time).  `candidates` column = a COUNT only -> the 2nd-candidate idea is OUT.
  WOULD-BE OUTCOME of the rejected POIs (plan replayer, order live while the slot shows the POI, 0.6/1.2R two-leg approx; the same
  replayer agrees with the simulator on 95.6 % of the traded population's signs):
    * quality-rejected: M10 59 fill / win 72.9 % / avg +0.10 R / OOS +0.6 R (24 tr) = thin positive; M15 50 / 46 % / -0.36 R;
      M5 26 / 50 % / -0.25 R; M30 11 / -0.08 R; H1 7 / -0.24 R  -> only M10 0.50-0.57 is a (weak) tier candidate.
    * M5 cost-rejected (0.08+): 73 fill / 58.9 % / -0.11 R (band 0.08-0.10 -0.30 R, 0.10-0.12 +0.02, 0.12-0.15 +0.28 (15 tr), >=0.15 -0.41).
    * M5 session-rejected (nypm): 22 fill / 72.7 % / +0.15 R / OOS -0.3 R.
    -> ADMISSION relaxation is nearly exhausted (v11/v12 said the same); a tier at reduced risk can add ~60-100 trades at ~0 to +0.1 R.
  RE-ARM AFTER A STOP: 106/107 stopped plans have the price THROUGH the entry at the stop -> 1 re-fill in the year -> DEAD.
  FRONT OFFSET for the never-filled orders (0.1-0.3 of the zone in front): fills 4-15 % of them at avg R -0.04..+0.09 -> DEAD (as v11).
  THE SIGNAL: CONFLUENT plans (zone active on another TF at placement, 153 of 430) win 81.7 % / stop 17.6 % / avg +0.47 R vs plain
  70.8 % / 28.9 % / +0.18 R, and it holds IS (79.5 / 19.2 / +0.49) AND OOS (84.0 / 16.0 / +0.45); confluent in the range regime 86.5 %
  win.  Confluent net +13 349 $ from 153 trades vs plain +9 404 $ from 277.  => the PROFIT lever is CONVICTION SIZING (confluent plans
  x1.25-2.0, plain x0.75-1.0) and the MORE-TRADES lever is a WIDER CONFLUENCE DEFINITION (a plan of another TF that was active on the
  same level within the last N minutes/bars counts too -> more plans judged by the looser confluence filter) + a reduced-risk TIER.
  Step 2 levers: tier_filter/tier_risk_scale, confluent_risk_scale/plain_risk_scale, confluence_memory_min, mart_confluent gate.
- 2026-10-05 13:40  step 0 done: repo cloned from GitHub (commit 4144052), restore.sh OK (CSV linked, 131 tests pass), v15 header written.

---
# PROGRESS — v14 MARTINGALE / LOSS-RECOVERY SIZING for the v13-A trader — ALL STEPS COMPLETE (2026-10-03 15:45)

**Recovery (read this first):** `git clone https://github.com/MHD-Amini/webapp.git /home/user/webapp`, `bash restore.sh`
(relinks the CSV to `data/xauusd_m1.csv`, pip, tests), read this file.  Every step ends with `bash save.sh "msg"` (commit + push to
GitHub origin).  Long jobs are resumable (they skip outputs that exist).
Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (symlink `data/xauusd_m1.csv`).
History: steps 0-4b ran in Genspark sandboxes with sb-git backup repos (10 migrations, nothing lost); the session died during step 4a stress /
step 5; 2026-10-03 the project was continued from https://github.com/MHD-Amini/webapp (the last pushed state, commit 63c68a6) and finished there.
Sandbox RAM is ~1 GB: run the simulator with `--workers 1` (a full-year run needs ~400-600 MB), never two at once.

## User spec (v14)
1. Create a MARTINGALE strategy for the trading bot (v13-A, run_trader.bat) that REDUCES THE LOSSES of the trades.  Be creative.
2. Save the process after EVERY step without exception, recoverable if the session dies (git backup repo + PROGRESS.md +
   resumable jobs).

## Design notes (v14) - what "martingale that reduces losses" means here
Classic martingale (double the size after every loss) is ruin-prone: the bot's 1 % risk x 2^k with k = 5 consecutive stops
(which the year contains) -> 32 % risk on one trade, and the daily/total loss rules (4.5 % / 9 %) would halt the account
before the recovery trade.  So the creative version has to be a *bounded, edge-aware* martingale:
  A. LOSS-RECOVERY sizing (soft martingale): after a losing trade the NEXT trade's risk = base x mult^k (k = consecutive
     losses, capped at `mart_max_steps`, total risk capped at `mart_max_risk_pct` of equity), reset on a win.  Variants:
     recover only the realised deficit (`mart_mode=deficit`: risk = base + deficit / target_R of the plan, capped),
     grow only with quality (`mart_min_quality`), only in the trend regime (`mart_regime`), only for the TF that lost
     (`mart_scope=tf`) or account-wide (`mart_scope=all`), fixed step multiplier (`mart_mode=mult`) or Fibonacci
     (`mart_mode=fib`), and a d'Alembert-style additive step (`mart_mode=add`).
  B. ANTI-martingale (reverse) as the control: grow after wins, shrink after losses (`mart_mult < 1`).
  C. GRID / ZONE-AVERAGING martingale on the SAME plan: when a filled plan moves against us by x R WITHOUT reaching the
     stop, add a second limit leg deeper in the zone (a real martingale on price, bounded by the zone) -> lower average
     entry, same stop -> reduces the loss of the plan when price bounces late.  Bounded by `grid_max_adds` and the total
     risk of the plan (`grid_total_risk_scale`).
  D. RECOVERY of the loss through the LADDER: after a loss, the next plan uses a tighter ladder (take the money earlier,
     `mart_ladder`) -> higher probability of the recovery trade paying.
Judged on the full year Sep25-Sep26 + OOS half (Mar-Sep 2026) against v13-A (430 tr, +188.7 %, DD 5.45 %, PF 2.01, win
75.3 %, worst day -2.28 %, OOS PF 1.91, 13/13 months): "reduces losses" = lower max DD / lower total $ lost / lower worst
day / lower avg loss at equal or better return, and the sequence-dependence must survive a shuffle test (the trade order
in a martingale matters: a bootstrap over the trade sequence shows whether the gain is real or a lucky order).

## Plan (v14)
- [x] 0. Extract lubot_trader_v13_final.tar.gz into /home/user/webapp, wire save.sh to the new backup repo, link CSV, deps,
        113 tests pass, PROGRESS v14 header, first save.
- [x] 1. Diagnosis (`run_v14_diag.py`): reproduce v13-A exactly (430 tr / +188.65 % / DD -5.45 %), then the LOSS STRUCTURE of
        the year: consecutive-loss run lengths (per TF / all), P(win | k losses before), R of the trade after k losses,
        deficit size after a streak, time to recovery, the largest daily loss clusters, how big a martingale step is affordable
        under the 4.5 % daily rule -> study_results/v14_diag/*.csv + notes.  Also the drawdown anatomy (which streaks made
        the -5.45 %).
- [x] 2. Levers in TraderConfig / PortfolioSimulator (defaults byte-identical, parity test): mart_mode / mart_mult /
        mart_max_steps / mart_max_risk_pct / mart_scope / mart_reset / mart_min_quality / mart_regime / mart_ladder + the
        grid (zone-averaging) adds.  Unit tests (tests/test_v14_martingale.py).  Smoke (smoke_v14.py).
- [x] 3. Grid (`run_v14_levers.py`, resumable, workers 1): every family x parameters on top of v13-A -> study_results/v14_levers/
        + v14_levers.csv.  Judge: DD, $ lost, worst day, avg loss, return, PF, OOS PF, months positive.
- [x] 4a. Stress (spread x2, comm x2, slip x3, worst intrabar, risk 0.5/2) + shuffle/bootstrap test of the finalists +
        walk-forward -> v14_stress.csv, v14_shuffle.csv, v14_halves.csv / v14_walkforward.csv.
- [x] 4b. Port to trader.py (live sizing reads the closed-trade history from trader_state.json) + run_trader.bat v14-A +
        verify_bat_v14.py (bat strings replayed == study json) + fake-MT5 tests.
- [x] 5. Report study_results/MARTINGALE_V14.md + charts (make_v14_report.py), README section 0g, final save.
- [x] 6. FINAL BACKTEST of the shipped v14-A on the CSV (backtest_v14_final.py -> study_results/FINAL_BACKTEST_V14.md), pushed to GitHub.

## Log (v14)
- 2026-10-03 15:45 steps 4a / 5 / 6 DONE (session continued from GitHub, commit 63c68a6; 131 tests pass; save.sh/restore.sh now push to origin =
  github.com/MHD-Amini/webapp).
  * 4a stress was already complete on disk (42/42 runs in v14_stress.csv: 6 finalists + ref x 6 scenarios).  v14-A ahead of the reference on return
    and OOS PF in 6/6 scenarios (spread x2 +122 % DD 6.2 OOS 1.68 vs +88 / 7.1 / 1.51; comm x2 +198 / 6.0 / 2.01 vs +162 / 5.1 / 1.86; slip x3
    +210 / 5.6 / 2.06; worst intrabar +231 / 5.9 / 2.21; risk 0.5 +88 / 3.9; risk 2 +798 / 9.9); v14-B / v14-C lose less $ than ref in 6/6.
  * 4a walk-forward (walkforward_v14.py, from the trade lists, split on close time at 2026-03-01): Spearman IS->OOS of the d$lost vs ref = +0.98,
    DD$ +0.88, PF +0.31 -> the loss side of a sizing rule is a population property and carries over; the PF edge only weakly.  70/140 variants
    pass 3 of 4 IS tests, of those 50 still lose less than ref OOS, 41 keep OOS PF >= ref.  v14-A IS PF 2.46 -> OOS 2.15, $ lost -11 % IS /
    +1.6 % OOS in dollars (-1.9 % relative to its OOS-start equity: it compounds faster).  v14-B/C: -12/-11 % IS, -13/-11 % OOS.
  * 5 report: make_v14_report.py (+ walk-forward section) -> study_results/MARTINGALE_V14.md (213 lines) + charts/v14_{equity,drawdown,scatter,
    losses,risk,monthly,shuffle}.png.  README: title v14, command table (live v14-A string, final backtest, v14 study), section 0g, project layout.
  * 6 FINAL BACKTEST (backtest_v14_final.py: strings READ from run_trader.bat, v13-A = same strings minus mart_*): 359 813 M1 bars 2025-09-01 ->
    2026-09-04, 430 trades, +227.53 % ($10 000 -> $32 753), max DD -5.84 %, PF 2.249, win 74.7 %, 13/13 months, worst day -1.99 % eq, max risk
    2.24 % eq, OOS PF 2.15 (224 tr, +$14 524), 0 halts; stepped up 38 (92 % win, +$7 078) / down 71 (62 %, +$1 257); IDENTICAL to the study json.
    -> study_results/FINAL_BACKTEST_V14.md, final_v14/{v14A,ref}_{summary.json,trades.csv,equity.csv,monthly.csv,by_tf.csv}, charts/final_v14_equity.png.
- 2026-09-22 07:05 step 4b DONE: run_trader.bat ships v14-A = TF_1.5_c3_htfbuy_dn0.5 (mart_mode=mult,mart_mult=1.5,mart_max_steps=3,
  mart_max_risk_pct=3,mart_scope=tf,mart_tfs=M10|M15|M30|H1,mart_sides=buy,mart_ungated_scale=0.5 on top of the v13-A strings);
  verify_bat_v14.py reads the strings FROM the bat and replays them: 430 tr / +227.53 % / DD -5.84 / PF 2.249 / up 38 / down 71 = IDENTICAL
  to the study json.  trader.py: Martingale state rebuilt from trader_state.json 'closed' list (tf, net $, r_net, step), realised P&L from
  MT5 deal history (MT5Broker.position_pnl), deep grid leg as plan '<key>+g' cancelled with its edge; status line shows the streaks.
  tests/test_trader_v14.py (4 fake-MT5 tests incl. restart replay) + tests/test_bat_v14.py -> 131 tests pass.
  DECISION v14-A = TF_1.5_c3_htfbuy_dn0.5: the only 5/5 variant with 13/13 months AND the best PF (2.249) / OOS PF (2.15) of the whole
  grid; loss reduction is modest (-2.6 % $ lost, avg loss -5 %, worst day -1.99 vs -2.04) but return +39 pt, r/dd 39.0 vs 34.6, max risk
  2.24 % of equity.  v14-B (the loss cutter) = FIB_c3_r3_htfbuy_dn0.5 (-12.7 % $ lost, avg loss -17 %, DD 4.78, 13/13, return -13 pt);
  v14-C (fewest rules) = MU_1.0_c3_r3_htf_dn0.5 = pure step-DOWN (-11 % $ lost, DD 4.79, max risk 1 %, return -9 pt).
  SHUFFLE n=1000 (v14_shuffle.csv): v14-A beats flat on $ lost in 88 % of shuffles / 94 % of block bootstraps, on return 63 % / 93 %, on
  return/DD 62 % / 86 %; historical rank on return/DD 0.97 (shuffle) / 0.62 (bootstrap) -> the DD advantage of the historical order is
  partly luck, the loss reduction and the return are robust.  v14-B: $ lost less than flat in 98 % / 99 %, return > flat only 35 % / 84 %.
  v14-C (pure step-down): $ lost less in 100 % / 100 %, return > flat 6 % / 66 % (as expected: it only removes size).
  Stress (6 x 7 = 42 runs) running detached -> v14_stress.csv; then make_v14_report.py, README 0g, final save + tar.
- 2026-09-22 06:25 step 3 DONE (140 variants, study_results/v14_levers.csv; 7 sandbox migrations during the grid, resumable -> nothing lost).
  Ref v13-A: +188.7 % / DD 5.45 / PF 2.008 / lost -18 711 $ / avg loss -176.5 $ / worst day -2.04 % eq / OOS PF 1.91 / 13/13 / r/dd 34.6.
  * SCORE 5/5 (reduce_loss + hold_loss + better_rd + keep_return + keep_oos) = 5 variants, ALL asymmetric (gated step-up + step-down):
      TF_1.5_c3_htfbuy_dn0.5      +227.5 % DD 5.84 PF 2.249 lost -18.2 k (-2.6 %) avgL -167 wd -1.99 maxR 2.24 % OOS 2.15 13/13 r/dd 39.0 (per-TF streaks)
      MU_1.5_c3_r3_htfbuy_dn0.5   +209.0 % DD 5.57 PF 2.176 lost -17.8 k (-5.0 %) avgL -160 OOS 2.03 12/13
      MU_1.25_c3_r3_htf_dn0.75    +201.3 % DD 5.38 PF 2.081 lost -18.6 k avgL -176 OOS 2.01 13/13
      MU_1.25_c3_r3_htf_dn0.5     +192.2 % DD 5.17 PF 2.087 lost -17.7 k (-5.5 %) avgL -164 (-7 %) maxR 1.85 % OOS 1.99 13/13 r/dd 37.2
      MU_1.25_c3_r3_htfbuy_dn0.75 +193.3 % DD 5.43 PF 2.070 lost -18.1 k OOS 1.96 13/13
  * STRONGER LOSS CUTS at a small return cost (score 4: keep_return fails by 5-13 pt): FIB_c3_r3_htfbuy_dn0.5 +175.3 % DD 4.78 (-0.67 pt)
    PF 2.074 lost -16.3 k (-12.7 %) avgL -146 (-17 %) wd -1.97 OOS 1.94 13/13;  MU_1.0_c3_r3_htf_dn0.5 (PURE step-down, no step-up at all)
    +179.4 % DD 4.79 lost -16.6 k (-11 %) maxR 1.0 % OOS 1.98 13/13;  SHR_0.5_c2_m5 (halve only M5 after a loss) +176.6 % DD 4.77 lost -16.6 k;
    MU_1.25_c3_r3_htfbuy_dn0.5 +181.5 % DD 4.98 lost -16.7 k 12/13.
  * ZONE GRID: own-ladder deep leg = the deepest loss cut with 13/13: GR_0.5_0.6/0.4_own +152 % DD 4.07 (-1.4 pt) lost -14.6 k (-22 %) avgL -84
    ulcer 1.385 (-21 %) OOS 1.87 -> but return -37 pt;  GR_0.5_0.5/0.5_own_m5 (deep leg only on M5) +163 % DD 4.15 lost -15.6 k r/dd 39.3.
    Equal-budget grids with the SAME exit prices raise return AND DD and drop OOS PF to 1.6-1.8 (the deep leg is a coin flip).
    CMB (asym + grid 0.3/0.6-0.4): +208 % DD 5.13 PF 2.108 lost -18.8 k avgL -83 13/13 - not better than asym alone on $ lost.
  * REJECTED: every ungated step-up (lost -19..-35 k), deficit recovery (DD 8.5-13.5, PF down to 1.75), anti-martingale (lost -28..-46 k,
    11/13), recovery ladders LAD_* (return +243..+259 but lost -21..-24 k), shrink everywhere (return -40..-65 pt), lr0.05/0.5 (no effect).
  FINALISTS for step 4a (stress x6 + shuffle n=2000): TF_1.5_c3_htfbuy_dn0.5, MU_1.25_c3_r3_htf_dn0.5, FIB_c3_r3_htfbuy_dn0.5,
  MU_1.0_c3_r3_htf_dn0.5, GR_0.5_0.6/0.4_own, MU_1.5_c3_r3_htfbuy_dn0.5.
- 2026-09-21 23:10 step 3 IN PROGRESS (49/140 runs; the MU family complete) + step 4b trader.py port DONE + step 4a shuffle tool written.
  MU family (sequence step-up after a loss) on the full year, ref +188.7 % / DD 5.45 / PF 2.008 / loss -18.7 k / avgL -176 / wd -2.04 / OOS 1.91:
  * UNGATED step-ups ALL raise the $ lost (x1.25: -21.3..-22.2 k, x1.5: -24.4 k, x2: -30..-31 k) and the DD (6.0-10.4) - they buy return
    (+225..+344 %) with drawdown; return/DD 37-48 vs 34.6 but "reduce losses" = NO.  x2 with cap 1 = +344 % DD 7.2 (the 123 after-loss
    trades at 2 %: lucky, worst day -3.9 %).
  * GATED step-ups (htf / buy / htfbuy): loss$ -19.9..-23 k (still MORE than ref), DD 5.6-6.4, PF 2.09-2.19, OOS PF 1.98-2.05 -> better
    risk-adjusted (r/dd 38-43) but still not a loss reduction.  trend / q60 gates: no better than ungated.
  * ASYMMETRIC (gated up + ungated x0.5/x0.75 down) = the only family that REDUCES the losses AND keeps the return:
      MU_1.25_c3_r3_htf_dn0.5     +192.2 % DD 5.17 PF 2.087 loss -17.7 k (-5.5 %) avgL -164 (-7 %) wd -2.25 OOS 1.99 13/13 r/dd 37.2 maxRisk 1.85 %
      MU_1.25_c3_r3_htf_dn0.75    +201.3 % DD 5.38 PF 2.081 loss -18.6 k avgL -176 OOS 2.01 13/13 r/dd 37.4
      MU_1.5_c3_r3_htfbuy_dn0.5   +209.0 % DD 5.57 PF 2.176 loss -17.8 k avgL -160 wd -1.96 OOS 2.03 12/13 (one month -$) r/dd 37.5 maxRisk 2.98 %
      MU_1.25_c3_r3_htfbuy_dn0.5  +181.5 % DD 4.98 PF 2.086 loss -16.7 k (-11 %) avgL -149 (-15 %) OOS 1.96 12/13 (return -7 pt)
    -> the step-DOWN of the weak post-loss slices (M5, sells: 76 trades) is what cuts the losses; the step-UP of the strong slices pays the
    return back.  htf-gate (up on M10/M15/M30/H1 buys AND sells) keeps 13/13 months; htfbuy is stronger on PF but loses a month.
  * SHUFFLE (shuffle_v14.py, n=200, sequence-only): MU_1.5_c3_r3_htfbuy_dn0.5 beats flat on return in 80 % of shuffles / 99 % of block
    bootstraps, on return/DD in 59 % / 98 %, on gross loss in 63 % / 80 %; the HISTORICAL order ranks 0.99 on return/DD among shuffles
    (= the historical order WAS lucky for the DD; the bootstrap that keeps the local clustering ranks it 0.61 = normal).  MU_1.5_htf
    (no step-down): loss less than flat in 0 % of shuffles -> a pure step-up never reduces losses, in any order.  Conclusion: the
    return gain is robust to the order, the DD gain is partly order luck, the loss reduction comes from the step-down and is robust.
  Remaining grid: FIB/ADD/DEF/SHR/ANTI/LAD/TF/GR/CMB (~90 runs, ~25 min).  Then: stress x6 + shuffle n=2000 of the 4-6 finalists.
- 2026-09-21 22:20 step 2 DONE: lubot/martingale.py (Martingale state machine: mult/add/fib/deficit/anti, caps, gates, mart_scope,
  asymmetric mart_ungated_scale, replay() for the live bot; grid_wanted), execution.py (TraderConfig mart_* / grid_* keys, TradePlan
  mart_step/mart_scale/grid_leg/grid_parent, key '+g' for the deep leg, size_plan x mart_scale, apply_mart_ladder, grid_deep_plan),
  portfolio_sim.py (_apply_v14 at placement + re-entry, _place_deep, deep leg takes no slot / no dedupe / cancelled with the edge or
  on its first partial, mart.on_close for every closed EDGE plan, trades frame + summary columns).  Defaults byte-identical (parity
  430/+188.65/-5.45 verified 3x).  tests/test_v14_martingale.py 13 tests -> 126 pass.  smoke_v14.py (16 variants) -> see the smoke log
  entry below.  Step 3 grid: run_v14_levers.py (resumable, 1 worker, autosave every 5 runs) - started with nohup.
- 2026-09-21 22:05 step 2 SMOKE (smoke_v14.py -> study_results/v14_smoke.jsonl, logs/smoke_v14.log; parity IDENTICAL 430/+188.65/-5.45;
  125 tests pass).  v13-A ref: +188.7 % / DD 5.45 / PF 2.008 / gross loss -18.7 k$ / avg loss -176 $ / OOS PF 1.91 / 13/13.
  A sequence sizing (step up after a loss):  x2 cap3 -> +323 % but DD 10.7, loss -31 k, max risk 16 % of start eq (ruin path);
    x1.5 cap3 <=3 % -> +247 % DD 9.9 loss -24 k;  fib cap3 -> +205 % DD 5.59 PF 2.06 loss -19.4 k (nearly neutral);  d'Alembert +0.5 ->
    +267 % DD 6.3;  deficit-recovery -> +265 % DD 13.5 PF 1.75 (worst: chases costs-only losses);  GATED x1.5 (no M5, buys only, 54
    stepped trades) -> +234 % DD 5.64 PF 2.114 OOS PF 1.98 13/13 = the best risk-adjusted A (return/DD 41.6 vs ref 34.6) but the $ lost
    still rises (-21 k);  + tight recovery ladder -> +227 % DD 9.7 (worse than without).
  B shrink x0.5 after losses -> +114 % DD 4.46 loss -12.9 k (cuts losses 31 % but return -74 pt, return/DD 25.6 = worse);  anti x1.3 after
    wins -> +333 % DD 11.8, 11/13 months (worst).
  C zone grid (deep leg): 0.4R 50/50 -> +198 % DD 5.30 PF 1.95 OOS PF 1.68 12/13;  0.5R 50/50 -> +231 % DD 6.26 OOS 1.62 11/13;  0.5R 50/30
    -> +133 % DD 4.54 loss -14.9 k;  0.3R 60/40 -> +192 % DD 5.33 OOS 1.76;  keep after partial -> +243 % DD 7.4 11/13;  0.5R OWN ladder
    (deep leg exits on its own shorter R) -> +125 % DD 5.11 PF 1.98 OOS PF 1.89 13/13, loss -12.9 k (-31 %), avg loss -71 $, worst trade
    -1.13 % (ref -2.95 %), ulcer 1.47 (ref 1.76) = the smoothest curve but return/DD 24.5.  The deep leg is a coin flip (fills on the 106
    losers + the 111 winners with MAE >= 0.5 R -> 51 % win) with a better R:R; the equal-budget grid raises return and DD together, the
    OOS PF falls (1.6-1.8) -> the grid is NOT a free lunch on this stream.
  LESSONS -> step 3 grid design: (1) judge on RISK-NORMALISED loss metrics (return/DD, ulcer, loss$/return, worst day % of day-start
  equity, max risk % of equity at the time - the smoke's worstD/maxRisk are % of START balance and overstate late-year values);
  (2) the promising creative lever is ASYMMETRIC: step UP where the post-loss edge is positive (M10/M15/M30/H1, buys) and step DOWN
  where it is negative (M5, sells) -> new key mart_ungated_scale (size of an after-loss plan that fails the gate); (3) fib / gated
  x1.25-1.5 / cap 2-3 / max 2-3 % are the plausible A range; (4) grid only with own ladder or small add_frac, and combined with A.
- 2026-09-21 21:40 step 1 DONE: run_v14_diag.py reproduces v13-A EXACTLY (430 / +188.65 % / -5.45 %; 13 s, 380 MB peak -> workers=1
  is safe).  Outputs study_results/v14_diag/ (ref.json, trades.csv, streaks.csv, after_k*.csv, after_loss_gates.csv, classic_mart.csv,
  drawdowns.csv, mae*.csv, worst_days.csv), log logs/v14_diag.log.  FINDINGS (the facts a martingale has to live with):
  * LOSS STREAKS ARE SHORT: 106 losses (24.7 %) in 76 runs, max run 3 (6 runs of 3, 24 of >=2, NEVER 4) - fewer/shorter than
    independence predicts (expected max run 4.1).  Per TF max run 1-3.  -> a martingale needs at most 3 steps; step 4+ never fires.
  * THE TRADE AFTER A LOSS IS WORSE, NOT BETTER: win 76.5 % / mean +0.312 R after 0 losses, 68.4 % / +0.127 R after 1, 75 % / +0.091 R
    after 2, 100 % / +0.73 R after 3 (n = 6 only).  Per slice after a loss: M5 -0.021 R (60 % win, n 43) and SELLS -0.064 R (n 40) are
    NEGATIVE; M15 +0.66 R (n 10), buys +0.285 R (n 66), M10 +0.195 R, range/trend +0.14/+0.17 R.  Quality >= 0.70 after a loss:
    -0.19 R (n 5).  -> stepping the size UP after a loss puts more money on a weaker trade: the classic martingale can only win here by
    compounding a positive expectancy, not by exploiting mean reversion of luck.  Gates (M5 excluded, sells excluded) are needed.
  * CLASSIC MARTINGALE ON THE SAME SEQUENCE (sequence-only approximation, compounding, 4.5 %/9 % rules): flat +215 % DD 4.42 gross loss
    -20.6 k; x2^k +400 % but DD 7.01, max risk 8 %, gross loss -38.8 k, 4 daily halts; x1.5^k +285 % DD 5.06 loss -27.3 k; x1.25^k +240 %
    DD 4.75; d'Alembert +1 %/loss +299 % DD 6.02 4 halts; fib(k) +251 % DD 4.33 (!) loss -22.9 k; ANTI x0.5^k +186 % DD 4.14 loss -16.7 k.
    -> every step-up scheme INCREASES the $ lost (more size on the weaker post-loss trades) and buys return with drawdown; only the
    anti-martingale reduces the losses (-20 %) and it costs return (-30 pt).  A pure sizing martingale cannot "reduce the losses".
  * LOSSES CLOSE ALONE: 84 % of the losses close with 0 other positions open; median 535 min from a loss to the next fill (6 % < 1 h)
    -> the next-order sizing lever (live: read the last closed deals) is realistic; a hedge/recovery order at the moment of the loss is not.
  * DRAWDOWNS: the -5.45 % (Aug 6-10 2026) = 5 trades, 3 losses in a row, M5+M10; the other four deep DDs (-4.5..-4.0 %) = 10-16 trades
    with 2-6 losses over 3-13 days.  Worst days -2.04 % / -1.95 % / -1.92 % of day-start equity (never near the 4.5 % rule).
  * MAE = THE GRID OPPORTUNITY: all 106 losers go the full zone; of the 324 WINNERS 55.9 % first go >= 0.3 R against, 34.3 % >= 0.5 R,
    14.8 % >= 0.7 R before turning (median MAE 0.33 R).  By MAE bucket: 0-0.9 R deep -> 100 % win (310 trades, +205 R); 0.9-1.0 R deep
    -> 50 % win (24); > 1 R = stopped (96).  -> a SECOND LIMIT DEEPER IN THE ZONE (0.3-0.7 R) fills on 50-67 % of the trades, is a winner
    whenever the first leg wins, and lets the FIRST leg be smaller: risk budget split between the zone edge and the zone interior =
    a price-martingale bounded by the zone -> a stopped plan loses LESS than 1 R (the deep leg's stop distance is shorter and it often
    never fills), a shallow winner earns less.  This is the creative "martingale that reduces the losses" candidate (family C).
  NEXT (step 2): implement in the simulator (a) sequence sizing mart_* incl. anti-martingale and gates, (b) zone-averaging grid_*
  (second limit at grid_add_r deep in the zone, base leg grid_base_frac of the budget, add leg grid_add_frac), (c) mart_ladder for the
  recovery trade, (d) deficit-recovery mode.  Defaults byte-identical (parity test).
- 2026-09-21 21:15 step 0 DONE: extracted lubot_trader_v13_final.tar.gz (git history intact, HEAD 36c8792 v13 complete) into
  /home/user/webapp; origin -> genspark-2ffbc30b (save.sh repointed, stale token URL removed); restore.sh: CSV linked,
  113 tests pass.  Sandbox: 1 GB RAM, 20 GB disk free.  PROGRESS v14 header written.

---
# (history) PROGRESS — v13 FIX THE WEAK MONTHS — ALL STEPS COMPLETE (2026-09-21 10:20)

## User spec (v13)
1. The v12-A trader (run_trader.bat) shows a NEGATIVE month 2026-04 (-$132) and a WEAK month 2025-09 (+$332; note Sep 2025 is a
   partial month in the stream and 2026-09 only has 4 days).  Find the PROBLEM behind those months and find a way to make a good
   profit out of them - WITHOUT breaking the other 11 months (judge every fix on the full year + OOS half, same loss band as v12:
   max DD not > 0.5 pt deeper, PF >= ref - 0.05, win >= ref - 3 pt, worst day >= ref - 0.5 pt).
2. Save the process after EVERY step without exception, recoverable if the session dies (git backup repo + PROGRESS.md +
   resumable jobs).

## Plan (v13)
- [x] 0. Extract lubot_trader_v12_final.tar.gz into /home/user/webapp, wire save.sh to the new backup repo, link CSV, deps,
        104 tests pass, PROGRESS v13 header, first save.
- [x] 1. Diagnosis (`run_v13_diag.py`): reproduce v12-A exactly (427 tr / +179.51 % / DD -5.28 %), then dissect 2026-04 and
        2025-09 trade by trade: per TF / direction / session / outcome / confluence / kept-order / day-of-month; compare with the
        good months; look at the market regime (ATR, trend, range of the month, big news days) and at the funnel of those months
        (were good POIs filtered out? did the loss rules or max-open block anything?) -> study_results/v13_diag*.csv + .md notes.
- [x] 2. Hypotheses -> new simulator levers (defaults byte-identical, parity test) for whatever the diagnosis points at
        (candidates: regime / volatility gate, direction-vs-HTF-trend gate, session gate per TF, correlated-position cap,
        daily loss streak pause, month-specific management) -> unit tests.
- [x] 3. Grid (`run_v13_levers.py`, resumable): each lever on top of v12-A, judged on 2026-04 + 2025-09 AND on the full year / OOS
        -> study_results/v13_levers.csv.
- [x] 4a. Stress (6 scenarios x 6 finalists + ref = 42 runs, v13_stress.csv) + walk-forward + neighbourhood of v13-A (10 extra
        variants, run_v13_neigh.sh) -> walkforward_v13.py -> v13_walkforward.csv, v13_neighbourhood.csv.
- [x] 4b. Port to run_trader.bat (trader.py already carries the regime code + 3 fake-MT5 tests) + verify_bat_v13.py (bat strings replayed
        in the simulator must equal the study json).
- [x] 5. Report study_results/WEAK_MONTHS_V13.md + charts (make_v13_report.py), README section 0f, tests, final tar link.

## Log (v13)
- 2026-09-21 10:20 step 5 DONE: make_v13_report.py (every number read from the result files) -> study_results/WEAK_MONTHS_V13.md +
  charts/v13_{equity,monthly,regime,scatter,walkforward,drawdown}.png; README v13 header, command table (v13-A live command + study
  pipeline), section 0f, layout; restore.sh v13 hints; 113 tests pass.  ALL v13 STEPS COMPLETE.
  RESULT: v13-A = v12-A + regime_metric=adr_ratio (5/20 closed days) < 1.0 -> range ladder 0.5|1.0|1.5|2.5 x25 % + sl_after_leg 0|0.3|x|x:
  430 tr, +188.7 %, DD 5.45 %, PF 2.01, win 75.3 %, worst day -2.28 %, OOS PF 1.91, 13/13 months; Apr 2026 -$132 -> +$343; Sep 2025 unchanged
  (+3.35 R, opportunity starvation, honest).  Range-managed trades 220: +41.0 R vs +37.4 R under the old management on the same fills.
  Robust: 6/6 stress scenarios ahead of ref, walk-forward Spearman +0.23, 22/22 neighbours April-positive.
- 2026-09-21 10:00 step 4b DONE: run_trader.bat ships v13-A (regime_metric=adr_ratio,regime_threshold=1.0,regime_short=5,regime_long=20,
  range_tp_levels=0.5|1.0|1.5|2.5,range_tp_fracs=1|1|1|1,range_sl_after_leg=0|0.3|x|x on top of the v12-A strings); verify_bat_v13.py reads the
  strings FROM the bat and replays them: 430 tr / +188.65 % / DD -5.45 / PF 2.008 / 220 range trades = IDENTICAL to the study json.
  trader.py status line now shows the regime + metric value every minute; tests/test_bat_v13.py guards the bat strings.  113 tests pass.
- 2026-09-21 09:45 step 4a DONE.  STRESS of the finalists (return / DD / OOS PF / Apr26 R; ref in brackets):
  v13-A RG_adr1.0_tight_l03: base +189/5.45/1.91/+1.75 (ref +180/5.28/1.78/-0.72) | spread x2 +88/7.1/1.51/-0.8 (ref +80/6.6/1.48/-0.8) |
  comm x2 +162/5.1/1.86/+2.9 (ref +145/5.7/1.71/+0.6) | slip x3 +176/5.3/1.86/+1.3 (ref +167/5.4/1.72/-1.2) | worst intrabar +192/5.2/1.96/+2.3
  (ref +176/5.3/1.76/-0.9) | risk 0.5 % +74/2.6 (ref +72/3.1) | risk 2 % +672/10.1/1.84 (ref +658/10.2/1.74).
  -> v13-A beats the reference on return AND OOS PF in EVERY scenario; April stays positive in every scenario except spread x2 (where the
  reference is equally negative: at double spread 110 M5 trades disappear through the cost gate and the year has 315 trades for every variant).
  v13-B (adr0.9 w3_20): lowest base DD (4.38) but spread x2 Apr -1.6, risk 2 % return 532 (worse than ref) -> less robust than A.
  RG_er0.4_G_l03_10: highest return (+201 %) but April only +0.18 and Sep25 gain comes from the lock -> not the weak-month fix asked for.
  WALK-FORWARD (177 variants): Spearman(IS_R, OOS_R) +0.23 (p 0.002), (IS_PF, OOS_PF) +0.36 (p 1e-6), RG family alone +0.21 -> positive
  (management levers generalise, unlike the v11/v12 selection levers).  Picking on the IS half alone (IS PF >= ref-0.05, sort by IS R):
  top-12 OOS PF median 1.77 = ref 1.78 -> no IS-overfit gain but no OOS loss either; 3 of the 12 fix the weak months.  v13-A ranks 37/177
  IS and 34/177 OOS (consistent, not an OOS-picked outlier; ref 56/69).  Spearman(Apr R, other months R) = -0.11 n.s.
  NEIGHBOURHOOD of v13-A (22 variants: threshold 0.8..1.1, windows 3-10/10-40, locks be2/l03/l05/l03_10, t2 ladder, front fracs):
  April POSITIVE in 22/22, 13/13 months in 22/22, both loss bands held in 20/22 (the two misses are w3_20 DD 5.79 and w7_20 DD 6.79),
  PF 1.87-2.03 (ref 1.87).  Threshold 0.95 / 1.0 / 1.05 with l03: +189 / +189 / +185 %, Apr +1.8 / +1.75 / +2.6, OOS PF 1.95 / 1.91 / 1.88.
  -> the plateau is smooth; v13-A sits in its middle.  DECISION: ship v13-A = v12-A + regime_metric=adr_ratio (5/20 days) < 1.0 ->
  range ladder 0.5|1.0|1.5|2.5 R x25 % + stop schedule 0|0.3|x|x (BE after leg 1, +0.3R after leg 2).  Alternative v13-C (RG_adr1.0_tight,
  no lock) for a user who wants the fewest new rules.  Sep 2025 remains +3.35 R (opportunity starvation, honest: no fix from the same stream).
- 2026-09-21 09:15 RECOVERY (session 2 of v13): previous session died after step 4's stress runs.  User re-uploaded webapp (1).tar.gz
  (1.7 GB, 42 stress jsons + v13_stress.csv intact), lubot_trader_v12_final.tar.gz, CSV.  Extracted into /home/user/webapp (git history
  kept), remotes origin+genspark -> genspark-134bcfcf, save.sh repointed, CSV linked, lightgbm installed, 112 tests pass.
  Continuing step 4: (a) read the stress results, (b) walk-forward over the 167 variants, (c) port to trader.py + run_trader.bat.
- 2026-09-20 22:30 step 3 DONE (3 more migrations survived: 24efb858 -> f5954810 -> d43e692b -> c588d4f3; the resumable grid +
  4-min autosave lost no run).  run_v13_levers.py: 167 variants on top of v12-A -> study_results/v13_levers/ + v13_levers.csv.
  Ref v12-A: 427 / +179.5 % / DD 5.28 / PF 1.874 / win 72.6 / wd -2.65 / IS +64.1 R / OOS +50.7 R PF 1.78 / Apr26 -0.72 R (-$132) /
  Sep25 +3.35 R / other 11 months +112.1 R / 12/13 months.  23 variants hold BOTH v12 loss bands AND fix the weak months (April
  positive, no negative month, other months not worse than -3 R) - ALL of them are regime-adaptive ladders (RG_*):
  * RG_adr1.0_tight_l03 (ADR5/ADR20 < 1.0 -> ladder 0.5/1.0/1.5/2.5 x25 + stop -> +0.3R after leg 2): 430 tr, +188.7 %, DD 5.45,
    PF 2.008, win 75.3, wd -2.28 (better than ref), OOS +52.3 R / PF 1.91, Apr26 +1.75 R (+$343), Sep25 +3.35, worst month +0.72,
    13/13 months, other months +-0.0 R (unchanged).  220 range-managed trades: +41.0 R (ref management on the same trades +39.2).
  * RG_adr0.9_tight_w3_20 (ADR3/ADR20 < 0.9): +185.8 %, DD 4.38 (!), PF 1.983, OOS PF 1.93, Apr +1.15, 13/13.
  * RG_adr1.0_tight: +184.7 %, PF 2.002, OOS PF 1.90, Apr +0.99, 13/13.  RG_adr0.9_tight: +181.1 %, PF 1.946, Apr +0.88, 13/13.
  * RG_adr1.1_three (0.6/1.2/2.4 x33): +185.2 %, DD 4.54, Apr +1.39.  RG_er0.2_three: +195.5 %, OOS PF 1.86, Apr +0.35.
  * Threshold neighbourhood is SMOOTH (adr 0.8/0.9/1.0/1.1 with tight: Apr +0.21/+0.88/+0.99/+1.53; l03 lock adds +0.2..+0.8) ->
    not a single lucky cell.  Spearman(IS_R, OOS_R) over 167 variants = +0.25 (p 0.001), (IS_PF, OOS_PF) +0.32 - positive this
    time (management levers, not selection levers).  Spearman(Apr R, other-months R) = -0.14 (n.s.): fixing April does NOT
    systematically cost the other months.
  * REJECTED: the alternative ladder for EVERY plan (LAD_tight +147 %, LAD_t3 +104 %, LAD_two15 +136 %: the far legs earn the year
    in trending months - the switch IS needed); stop locks for every plan (LOCK_l03_10: Apr still -0.48); 'mid' ladder 0.6/1.2/1.8/3
    (Apr -1.1..-1.8 everywhere); one-leg 1R (Apr +6.5 but DD 7.75, win 68); adr_pct (absolute vol level) as metric (kills the
    good months: other -8..-36 R); risk scale 0.5 in a range (Apr still -$100, return 159 %); er >= 0.4 thresholds with tight (OOS
    falls to +42 R); short windows s3 / w5_10 (Sep25 drops).
  * Sep 2025 is NOT touched by any adaptive variant (ADR ratio 1.13, er 0.65 = steady low-vol trend, no 'range' plans) - honest:
    that month stays +3.35 R (+3.3 % of equity); the only variants that lift it (RG_er0.4_G_l03_10 +4.64, er0.5_three +4.77) do it
    through the lock on the er metric and are weaker elsewhere (Apr +0.2 / +0.0).
  Finalists for step 4 (stress + walk-forward): RG_adr1.0_tight_l03 (v13-A), RG_adr0.9_tight_w3_20 (v13-B, lowest DD),
  RG_adr1.0_tight (v13-C, simplest), RG_adr1.1_three, RG_er0.2_three, RG_er0.4_G_l03_10.
- 2026-09-20 20:45 step 2 DONE (2 more migrations survived: 5a71f43d -> 24efb858; working tree came back intact each time).
  lubot/regime.py: regime metric from CLOSED daily bars (adr_ratio = ADR short/long, er = efficiency ratio, adr_pct), value of
  day D from days < D; latest_metric() for the live bot.  TraderConfig v13 keys (defaults byte-identical, parity 427/+179.51/-5.28
  exact): regime_metric, regime_threshold, regime_short=5, regime_long=20, range_tp_levels / range_tp_fracs (alternative ladder for
  plans PLACED in a "range" regime = metric < threshold), range_sl_after_leg (alternative stop schedule), range_risk_scale (0 = do
  not trade in a range), range_tfs.  TradePlan carries regime + sl_after_leg; trades frame has a `regime` column; summary has
  range_trades / range_plans.  tests/test_v13_regime.py (5 tests) -> 109 pass.  SMOKE (smoke_v13.py, v12-A base; ref 427 tr /
  +179.5 % / DD 5.28 / PF 1.874 / win 72.6 / OOS PF 1.78 / Apr26 -0.7 R / worst month -0.7 R / 12/13 months):
  * adr_ratio<0.9 -> tight ladder 0.5/1.0/1.5/2.5 x25: 428 tr, +181.1 %, DD 5.24, PF 1.946, win 74.3, sl 25.2, OOS PF 1.86,
    Apr26 +0.9 R, worst month +0.7, 13/13 months POSITIVE (121 range trades).  <- lever works: April flips positive, nothing else
    gets worse.
  * er5<0.3 -> tight: 428 tr, +181.2 %, DD 4.38 (!), PF 1.940, OOS PF 1.85, Apr26 +0.3, 13/13.
  * adr<0.9 -> mid 0.6/1.2/1.8/3.0: worse (Apr -1.8); G + lock 0/0.3/1.0: worse (Apr -1.0, OOS 1.73); half risk: Apr -1.6,
    return 157 %; no trading in a range: 307 tr, +128 %, PF 2.04, Apr +1.5 but -51 % return -> the range trades are worth
    keeping, just managed tighter.
  Next: step 3 grid over metric x threshold x ladder x stop schedule x TF subset (run_v13_levers.py, resumable).
- 2026-09-20 19:40 step 1 DONE (sandbox migrated once: 0b1d85ea -> ebb64241, files intact, save.sh repointed).  run_v13_diag.py
  reproduces v12-A EXACTLY (427 / +179.51 % / -5.28 %).  Outputs study_results/v13_diag/ (by_month, slices_*, regime, funnel_month,
  filtered_replay, ladder_month, days, trades_enriched3.csv + measure_*.py / screen_*.py).  FINDINGS:
  * 2026-04 (38 tr, -0.72 R, PF 0.95, win 66 %, sl 34 %, tp2 5 %): NOT a lack of trades (38 = normal; funnel 290 shown / 37 traded =
    normal) and NOT one bad slice: sells -4.6 R (47 % win), M10 -3.8 R (44 % win), counter-trend -3.6 R, preny -4.0 R - but every one
    of those slices is strongly POSITIVE over the year and OOS, so filtering them would cost more elsewhere.  The real driver is the
    LADDER: reach 1.2R only 26 % (year 40-56 %), reach 2.4R 18 %, reach 4.8R 5 % (year 9-18 %), legs closed 1.13 (year 1.4-1.8),
    R_if_flat_1R = +12 (a flat 1R exit would have been positive).  Regime: April = post-crash range after March -11.6 %: chop 20.8
    (year 1.4-9 except Jul 31), trend_eff -0.12, month range 8 % (lowest since Dec), 4 EMA20 flips.  -> the far ladder legs are
    never paid in a range, partials return to BE, stops 34 %.  Filtered POIs of April replayed: ALL negative (M10 q -4.0 R, M15
    -4.2, M5 cost -5.1, M5 q -0.7) -> the filter threw nothing good away.  Worst days 04-08 -2.31 % (2 confluence stops within 18 min:
    M30+M10 sells at 4784), 04-27 -1.98 % (2 stops).  Spearman(monthly R, avg daily range %) = +0.56, (daily vol) +0.59: the bot
    earns with volatility.
  * 2025-09 (19 tr, +3.35 R, PF 1.62): OPPORTUNITY STARVATION, not bad trades (avg 0.18 R/tr = normal; M10 11 tr +4.75 R).  Gold at
    3 500 with the lowest volatility of the year (avg daily range $54 = 1.56 %, vs 2-3.6 % later): M5 zones median $2.33 (year $4-7)
    -> cost_r = 0.35/2.33 = 0.15 >> 0.08 -> 160 of 180 M5 POIs rejected by the cost gate (year 23-105), only 4 M5 trades (year
    8-23).  Replay of those 160: +0.7 R GROSS over 130 fills = zero edge before commission -> the gate was RIGHT; M15 quality rejects
    replayed -12 R, M10 -4.3 R -> nothing to add from the same stream.  Also only 13 trading days with a trade; equity was $10k so
    the $ figure looks small (+3.3 % of equity is Dec/Jun/Jul level).
  * Screens of candidate levers on the 427 trades (weak-month R / full-year R / OOS R):
    - daily-stop pause: trades after the 1st stop of the day +26.8 R (12 in weak months +1.0) -> NO.
    - approach velocity / fill-bar size / hours since opposite stop / range location (1-10 d) / D1 efficiency ratio / vol ratio as a
      TRADE FILTER: no bucket is negative over the year; April's loss is spread over all buckets -> a selection filter cannot fix it.
    - LADDER by MFE (estimate, no costs): ref G 117 R (Apr +0.3, Sep +4.9); tight 0.5/1.0/1.5/2.5 x25 117 (Apr +4.0, Sep +5.5,
      vol-ratio<0.9 bucket 32.4 vs 26.4, er5<0.3 35.5 vs 31.7, but trending buckets 81.5 vs 85.6); back-loaded 10/20/30/40 128 (OOS
      59 vs 54, Apr -0.2); wide 0.8/1.6/3.2/6.4 52 (!); one-leg 1.0 R 101 (Apr +5.0).  -> a REGIME-ADAPTIVE ladder (tight targets when
      the recent volatility / trend efficiency is low, G otherwise) is lever #1; stop lock-in after leg 2 (sl_after_leg) lever #2;
      back-loaded fractions lever #3 (general, not weak-month specific).
  * Fast stops: 55 of 115 stops close within 15 min of the fill (-55 R); 36 stops had MFE >= 0.4R before the stop.
  HYPOTHESIS for step 2: April cannot be fixed by trading less or differently selected - it needs MANAGEMENT that adapts to a ranging
  regime (tighter ladder + earlier lock-in when ADR5/ADR20 < ~0.9 or D1 efficiency ratio is low), judged on the full year + OOS.
  Sep 2025 can only be improved marginally (regime-conditional M5 cost gate to test, expected ~0) - to be stated honestly.
- 2026-09-20 18:55 step 0 DONE: v12 archive (1.3 GB) -> /home/user/webapp (existing git kept), remote `genspark` ->
  genspark-0b1d85ea, save.sh repointed, CSV linked, lightgbm+tabulate+scipy installed, 104 tests pass.  Env: py3.13, 2 cores, 1 GB RAM.

---

# PROGRESS — v12 MORE TRADES AT THE SAME LOSS PROFILE, round 2 — ALL STEPS COMPLETE (2026-09-20 17:00)

**Recovery (read this first):** `git clone <backup repo url from save.sh> /home/user/webapp` (or extract the latest tar
link below into /home/user), `bash restore.sh` (relinks the CSV to `data/xauusd_m1.csv`, pip, tests), read this file,
continue from the first unchecked step.  Every step ends with `bash save.sh "msg"` (commit + push to the Genspark backup
repo).  Long jobs are resumable (they skip outputs that already exist) and `bash run_v12_all.sh` runs the whole remaining
pipeline unattended with an autosave every 4 minutes.
If the sandbox migrated: `git remote get-url origin` shows the new repo -> restore.sh `sed`s it into save.sh.
Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (symlink `data/xauusd_m1.csv`).
Backup repo of this session: see `git remote get-url origin` (migrated once already: 643efd71 -> 8b58236f).

## User spec (v12)
1. Find a way for the robot to make MORE TRADES while MAINTAINING the loss percentage.  Reference = the v11-B trader shipped in
   run_trader.bat (dedupe_cross_tf=false + M30|H1 min_quality 0.57): full year Sep25-Sep26 348 trades, +147.9 %, max DD 5.2 %,
   PF 1.91, win 72 %, worst day -2.3 %, OOS PF 1.73.  Loss profile to hold (same band as v11): max DD not > 0.5 pt deeper,
   PF >= ref - 0.05, win >= ref - 3 pt, worst day >= ref - 0.5 pt, sl_% not higher; judged on the OOS half (Mar-Sep26).
2. Save the process after EVERY step without exception, recoverable if the session dies (git backup repo + PROGRESS.md +
   resumable jobs + tar links).

## Plan (v12)
- [x] 0. Extract lubot_trader_v11_final.tar.gz into /home/user/webapp, git init, wire save.sh to the new backup repo, link
        CSV, deps (lightgbm), 97 tests pass, first push (250 MB ok), PROGRESS v12 header, save.
- [x] 1. Baseline + funnel of the v11-B reference (`run_v12_funnel.py`): reproduce 348 tr / +147.93 % / DD -5.22 % exactly,
        then attribute every shown POI to the stage where it is lost NOW (after v11) -> study_results/v12_funnel*.csv.
        Measure specifically: (a) skips 'price already at/through entry', (b) orders cancelled as 'replaced' vs 'no longer
        shown', (c) POIs re-shown by the scanner after they were traded, (d) quality-gate rejects that overlap an active
        plan of another TF (confluence candidates).
- [x] 2. New simulator levers in lubot/portfolio_sim.py + TraderConfig (defaults byte-identical to v11, parity test):
        `confluence_quality=<TF:q;...>` (quality gate relaxed to q when the zone overlaps an active plan of ANOTHER TF),
        `keep_replaced=true` (mirror policy: an order whose POI was merely replaced by a better one on the same slot stays
        until clear / invalidation / max_pending_bars; 'no longer shown' still cancels), `defer_entry_bars=N` (a POI skipped
        for 'price already at/through entry' is re-checked on the following bars while still shown and placed once the price
        is back in front of the zone), `reentry_after_be=N` (after a BE / partial exit, re-arm the same zone once for N bars).
        Unit tests for each.
- [x] 3. Grid (`run_v12_levers.py`, resumable, 2 workers): singles of the new levers on top of v11-B + combos with the
        v11 levers that were neutral-positive (M15 q0.57, M5 cost 0.10/0.12) -> study_results/v12_levers.csv, judged OOS.
- [x] 4. Stress (spread x2, commission x2, slippage x3, worst intrabar, risk 0.5/2 %) + walk-forward (pick on IS, verify OOS)
        of the finalists -> v12_stress.csv.  Port the winning lever(s) to trader.py (live bot) + fake-MT5 tests.
- [x] 5. Report study_results/MORE_TRADES_V12.md + charts, README section 0e, run_trader.bat, tests, final tar link.

## Log (v12)
- 2026-09-20 17:00 step 5 DONE (two more migrations survived: a6305205 -> 8e5f23b7 -> cbdbe294): make_v12_report.py +
  make_v12_report_template.md -> study_results/MORE_TRADES_V12.md + charts/v12_{equity,scatter,monthly,drawdown}.png; trader.py
  --confluence-filter CLI; run_trader.bat ships v12-A and verify_bat_v12.py replays its exact strings to 427 / +179.51 % / -5.28 % / PF 1.874
  = identical to the study run; README section 0e + command table; 104 tests pass.  ALL v12 STEPS COMPLETE.
  RESULT: v12-A = v11-B + keep_replaced_bars=1 (M10|M15|M30|H1) + confluence filter M10 q0.50 + M10 q0.57: 427 trades (+23 %), +180 %,
  DD 5.28 %, PF 1.87, win 72.6 %, sl 26.9 %, worst day -2.65 %, OOS PF 1.78, 12/13 months; more robust than v11-B at double spread.
  v12-C (keep_replaced only) 371 / PF 1.99 / OOS 1.84; v12-B (+ M15 confluence 0.50) 468 / PF 1.80 / wd -3.25 (outside the band).
  Rejected: re-entry after BE, keep-replaced on M5, M15 confluence < 0.57, grace/persist, M5 relaxations.
- 2026-09-20 16:40 step 4 DONE (migration 72650129 -> eea0470e survived; 36 stress runs + walk-forward intact; trader.py port done
  earlier, 104 tests).  STRESS (return / DD / OOS PF):
  ref            base +148/5.2/1.73 | spread x2 +58/9.3/1.29 | comm x2 +124/6.2/1.65 | slip x3 +136/5.9/1.69 | worst +148/5.1/1.74 | risk0.5 +63/2.4 | risk2 +449/10.8
  KR_htf_b1      +166/5.8/1.84 | +81/5.7/1.58 | +140/5.8/1.77 | +157/6.0/1.80 | +166/5.8/1.84 | +74/2.5 | +500/13.2
  v12-A          +180/5.3/1.78 | +80/6.6/1.48 | +145/5.7/1.71 | +167/5.4/1.72 | +176/5.3/1.76 | +72/3.1 | +658/10.2
  v12-B          +192/5.4/1.72 | +84/6.9/1.44 | +154/5.5/1.67 | +175/5.6/1.65 | +186/5.4/1.71 | +74/4.0 | +533/15.4
  RE_m10m15_b1   +157/5.5/1.82 | +61/10.6/1.37 (!) | ... worst day -4.0 to -5.6 -> confirms the rejection of re-entry.
  -> v12-A/C are MORE robust than the reference at double spread (DD 5.7-6.6 vs 9.3 %), because the kept HTF orders have wide zones.
  WALK-FORWARD (212 variants): Spearman(IS_R, OOS_R) = -0.29 (!), Spearman(IS_PF, OOS_PF) = +0.37.  The top-12 by in-sample R are ALL
  heavy confluence relaxations (M15 q0.50/0.52 + keep 2-3 bars): IS +71..77 R, OOS PF 1.49-1.69 (ref 1.73) -> in-sample artefact, same
  trap as v11's M10 relaxation.  Finalists' ranks IS/OOS: v12-B 33/4, v12-A 82/24, CF_m10+KR 73/52, KR_htf_b1 119/74, ref 136/165.
  HONEST READING: the finalists were chosen on the OOS half, so their OOS numbers carry selection bias.  Decomposition by lever, OOS R vs
  ref +42.0: KR_htf_b1 +47.6 / PF 1.84 (mechanical lever, independent of the entry model -> the robust part); CF_m10_q0.5 +41.7 / PF 1.72
  (neutral OOS, adds 21 trades); F_m10_q0.57 +44.0 / 1.70 (neutral, +30 trades); CF M15 relaxations 1.65-1.69 (slightly negative OOS ->
  v12-B's weakest link).  RECOMMENDATION: v12-A (427 tr, +23 %, loss profile held on both halves and in every stress scenario);
  v12-C = KR_htf_b1 alone as the conservative choice; v12-B only for a user who accepts PF 1.80 / worst day -3.25 %.
- 2026-09-20 16:05 step 3 DONE: 212 variants (61 singles + 150 combos + ref) in v12_levers/, v12_levers.csv, v12_combos.csv,
  v12_rank.csv (rank_v12.py; migration 4723c620 -> 72650129 survived with every json).  RESULT (ref 348 / +148 % / DD 5.22 / PF 1.91 /
  win 71.6 / sl 27.9 / wd -2.29 / OOS +42.0 R PF 1.73 win 70.7 sl 29.3):
  * v12-A (holds BOTH bands, most trades): X_CF_m10_q0.5+KR_htf_b1+F_m10_q0.57 = confluence filter (M10 quality 0.50 when the level is
    active on another TF) + keep a replaced M10/M15/M30/H1 order 1 bar + plain M10 quality 0.57:
    427 tr (+79 = +23 %), +179.5 %, DD 5.28, PF 1.87, win 72.6, sl 26.9, wd -2.65, OOS +50.7 R / PF 1.78 / win 72.8 / sl 27.2, 12/13 months.
  * v12-B (more trades, OOS band held, full-year PF 1.80 just below ref-0.05, wd -3.25): X_CF_m10m15_q0.5+KR_htf_b1+F_m10_q0.57 =
    468 tr (+120 = +34 %), +191.5 %, DD 5.36, PF 1.80, win 71.6, sl 28.0, OOS +53.0 R / PF 1.72 / win 71.9 / sl 28.1.
  * Conservative: KR_htf_b1 alone 371 tr (+23), +166 %, DD 5.83, PF 1.99, OOS PF 1.84; X_CF_m10_q0.5+KR_htf_b1 397 tr, PF 1.98, OOS 1.83.
  * Re-entry (RE) is positive alone on M10/M15 (400 tr, OOS PF 1.82) but its worst day is -4.0 % and every RE combo with CF/KR blows the
    DD (7.8-10.6 %) -> not recommended.  keep_replaced on M5 loses (-11 R / 36 extra trades) -> HTF only.
  Next: step 4 stress + walk-forward of the finalists (run_v12_stress.py), then the report.
- 2026-09-20 15:20 stage B 107/150 combos (migration c276aa80 -> 4723c620 survived, relaunched).  rank_v12.py -> v12_rank.csv.
  FINALIST CANDIDATES (ref 348 / +148 % / DD 5.22 / PF 1.91 / win 71.6 / wd -2.29 / OOS PF 1.73):
  * STRICT (both bands, DD <= ref+0.7): X_CF_m10_q0.5+KR_m10m15_b1 = 391 tr (+43, +12 %), +173 %, DD 5.88, PF 1.95, win 72.9, sl 26.6,
    wd -2.64, OOS +47.2 R / PF 1.80 / win 72.5.  KR_htf_b1 alone 371 / PF 1.99 / OOS 1.84.  X_CF_m10_q0.5+KR_m10m15_b2 399 / PF 1.90 / OOS 1.72.
  * MORE TRADES (OOS band held, full-year PF 1.80 < ref-0.05, worst day -3.25): X_CF_m10m15_q0.5+KR_htf_b1+F_m10_q0.57 = 468 tr
    (+120, +34 %), +192 %, DD 5.36, PF 1.80, win 71.6, sl 28.0, OOS +53.0 R / PF 1.72 / win 71.9 / sl 28.1, 12/13 months.
    Middle: X_CF_m10_q0.5+KR_m10m15_b1+F_m10_q0.57 421 tr, +173 %, DD 5.26, PF 1.84, wd -2.62, OOS PF 1.74.
  * Anything with RE (re-entry) beyond m10m15_b1 alone: DD 7.8-10.6, PF 1.46-1.62 -> rejected in combos (re-entries stack with
    confluence plans on the same level -> correlated stops).  RE_m10m15_b1 alone 400 / DD 5.50 / PF 1.83 / OOS 1.82 but wd -3.99.
- 2026-09-20 14:45 step 3 stage A2 done (HTF-only RE/KR via new `reentry_tfs` / `keep_replaced_tfs`, 102 tests):
  * KR_htf_b1 (keep a replaced M10/M15/M30/H1 order 1 bar): 371 tr (+23), +166 %, DD 5.83, PF 1.99 (!), win 73.0, sl 26.4, worst day
    -2.50, OOS +47.6 R / PF 1.84 (ref 1.73).  KR_m10m15_b1 366 / PF 1.95 / OOS 1.80.  Longer keeps (b2-b6) 373-395 tr, PF 1.85-1.92,
    OOS PF 1.65-1.75.  Every loss metric better than the ref except DD (+0.6 pt: 5.83 vs 5.22).
  * RE_m10m15_b1 (re-arm M10/M15 zone 1 bar after a BE exit): 400 tr (+52), +157 %, DD 5.50, PF 1.83, win 70.5, sl 29.0, OOS +51.6 R /
    PF 1.82; worst day -3.99 (a re-entry and its original can't lose together, but two re-entries stacked with confluence did).
    RE_htf_b1 421 tr, PF 1.76, OOS 1.74.  b2+ worse.  max2: 422 tr, OOS PF 1.78.
  * CF_m10q0.5_m15q0.52: 394 tr, +169 %, DD 5.63, PF 1.87, OOS PF 1.67.
  Stage B (150 combos of CF x RE/KR x F) running.
- 2026-09-20 14:20 step 3 stage A done (41 singles, v12_levers.csv; migration 15886613 -> c276aa80 survived, 43 jsons intact, pipeline
  relaunched resumable).  Ref 348 / +147.9 % / DD 5.22 / PF 1.91 / win 71.6 / OOS +42.0 R PF 1.73.  READING (extra trades vs ref):
  * RE (re-entry after BE): b1 481 tr (+134 extra: -1.8 R, OOS +1.3 R; outcomes 69 BE / 52 SL / 13 TP), DD 5.8, PF 1.59, OOS PF 1.54.
    Wider windows only add losers (b3 509 / DD 7.2 / PF 1.53, b12 525 / DD 8.8).  Per TF the extra M5 re-entries LOSE (-4.4 R / 60),
    M10 +2.5 R / 34, M15 +1.5 / 17 -> re-entry only on HTFs to test.  max2 worse.
  * KR (keep replaced): b1 401 (+53), PF 1.77, DD 6.7, OOS PF 1.71; extra M5 -11 R / 36, M10 +3.1 / 12, M15 +1.8 / 7, M30 +1.3 / 6.
    b2+ DD 8.4-8.9 -> rejected.  Same picture: M5 extras lose, HTF extras win.
  * CF (confluence quality): m10m15 q0.50 403 tr (+55: +12.8 R, win 78 % M10 / 62 % M15, OOS only +2.1 R), +168 %, DD 5.53, PF 1.83,
    win 71.2, OOS PF 1.64.  m15 q0.52: 371 (+23), DD 5.51, PF 1.87, OOS PF 1.69 (hold_oos).  m10 q0.5: 369 (+21), PF 1.90, OOS PF 1.72.
    HTF off / q0.5 (427): DD 7.3 -> no.  H1 confluence extras lose (-5.7 R / 10).  M5 confluence variants change ~nothing (M5 is rarely
    the second TF on a level).
  * F (plain relaxations re-checked on v11-B): m10 q0.57 378 (+30) PF 1.81 DD 6.3 OOS PF 1.70; m5 cost 0.12 383 (+35) PF 1.77 DD 5.9.
  None of the singles adds > 20 trades while holding the full v11 band.  Next: HTF-only variants of RE / KR (new `reentry_tfs`,
  `keep_replaced_tfs`), then combos (stage B running).
- 2026-09-20 13:40 step 2 done (2 more migrations survived: 8b58236f -> 15886613; uncommitted files came back with the snapshot,
  committed at once).  lubot/execution.py TraderConfig + lubot/portfolio_sim.py: `confluence_filter=<filter string>` (used INSTEAD of
  trade_filter when the zone overlaps an active plan of ANOTHER TF), `keep_replaced_bars=N` (a 'replaced' order stays N TF bars; clear
  still cancels), `reentry_bars=N` / `reentry_max` / `reentry_outcomes` (after a BE exit the same plan is re-armed as a fresh limit
  order, key 'TF#id~k', armed once price is back in front of the entry).  Defaults byte-identical (parity 348/+147.93/-5.22 exact),
  4 unit tests, 101 pass.  Trades frame has `reentry` and `confluent` columns; summary has reentries_placed / reentry_trades /
  confluent_trades.  SMOKE (smoke_v12.py -> logs/smoke_v12.log), full year, ref = 348 / +147.9 % / DD 5.22 / PF 1.91 / OOS +42.0 R PF 1.73:
  * keep_replaced_bars=3: 447 tr, +128 %, DD 8.9 %, PF 1.59, OOS +35.8 R / 1.44 -> adds trades AND losses (same as v11 grace/persist).
  * reentry_bars=6: 514 tr (199 re-entries placed, 169 filled), +140 %, DD 7.2 %, PF 1.54, win 67, OOS +44.3 R / 1.47 -> the re-entries
    are ~break-even as a group; loss profile not held at this width.
  * confluence_filter HTF q0.52 (all of M10/M15/M30/H1): 403 tr (+55, 182 confluent), +151 %, DD 5.6 %, PF 1.75, OOS +37.1 R / 1.53 ->
    closest; needs per-TF tuning (M10/M15 only, q 0.55/0.57) -> step 3 grid.
- 2026-09-20 12:50 step 1 done: run_v12_funnel.py reproduces v11-B EXACTLY (348 tr, +147.93 %, DD -5.22 %, PF 1.909, win 71.6 %,
  sl 27.9 %, OOS 184 tr / +42.05 R / PF 1.73; 20 s per run).  FUNNEL of 3 882 shown POIs (v12_funnel*.csv, v12_funnel_extra.json):
  traded 348 (9 %) | trade filter 2 666 (69 %: M5 cost_r 976, quality M10 650 / M15 414 / M5 295 / M30 164 / H1 94, M5 session 73) |
  order placed never filled 849 (22 %: 'no longer shown' 605, 'replaced' 323 - and 165 of the replaced POIs were RE-SHOWN later, i.e.
  still valid) | overlaps open 19.  (a) 'price already through entry' skips: 2 -> NOT a lever.  (c) 324 quality-rejected POIs overlap
  (>= 50 %) a zone another TF actually TRADED within +-2 days (M10 126, M15 101, M5 55, M30 29, H1 13; median quality 0.53) ->
  confluence-conditional filter is lever #1.  (d) a traded POI is never re-shown by the scanner (0) -> any re-entry must be driven by the
  simulator/bot itself (re-arm the zone after a BE exit).  (e) winners vs losers have the SAME median quality per TF (M5 0.60 vs 0.59,
  M10 0.63 vs 0.63) -> the quality bar has little ranking power above 0.55, so relaxing it where confluence gives extra evidence is
  defensible.  Outcomes ref: partial_be 63 %, sl 28 %, tp 9 %.  Max concurrent 4; median gap between entries 13 h.
  Levers for step 2: confluence_filter (alternative filter string when the zone overlaps an active plan of ANOTHER TF), keep_replaced_bars
  (a 'replaced' order stays N TF bars instead of being cancelled), reentry_bars (after a BE/partial exit re-arm the same zone once for N bars).
  12:55 sandbox migrated (history squashed to one commit by the platform; all files intact) -> restore.sh repointed save.sh to genspark-8b58236f.
- 2026-09-20 12:35 step 0 done: v11 archive (1.2 GB) -> /home/user/webapp, git init (no .git in the tar), remotes origin+genspark
  -> genspark-643efd71, save.sh repointed, CSV linked, lightgbm+sklearn installed, 97 tests pass, first push ok (~2 min).
  Env: py3.13, 2 cores, 1 GB RAM.

---

# PROGRESS — v11 MORE TRADES AT THE SAME LOSS PROFILE — ALL STEPS COMPLETE (2026-09-20 10:00)

**Recovery (read this first):** `git clone <backup repo url from save.sh> /home/user/webapp` (or extract the latest tar
link below into /home/user), `bash restore.sh` (relinks the CSV to `data/xauusd_m1.csv`, pip, tests), read this file,
continue from the first unchecked step.  Every step ends with `bash save.sh "msg"` (commit + push to the Genspark backup
repo).  Long jobs are resumable (they skip outputs that already exist) and `bash run_v11_all.sh` runs the whole remaining
pipeline unattended with an autosave every 4 minutes.
If the sandbox migrated: `git remote get-url origin` shows the new repo -> restore.sh `sed`s it into save.sh.
Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (symlink `data/xauusd_m1.csv`).

## User spec (v11)
1. Find a way for the robot to make MORE TRADES while MAINTAINING the loss percentage (drawdown / loss rate must not get worse
   than the v10 reference: full year Sep25-Sep26 251 trades, +80.7 %, max DD 5.5 %, PF 1.75, win 69 %, worst day -1.9 %).
2. Save the process after EVERY step without exception, recoverable if the session dies.

## Plan (v11)
- [x] 0. Extract lubot_trader_v10_final.tar.gz into /home/user/webapp, repoint save.sh to the new backup repo, link CSV,
        deps, 91 tests pass, PROGRESS v11 header, first save.
- [x] 1. Diagnosis: where do the trades get lost?  Count, per timeframe, the selection events in the full-year streams
        (sel_v10_*.pkl) and the reason each one does NOT become a trade (quality gate, cost gate, session gate, 1-per-POI,
        max-open, mirror cancel before fill, never filled ...) -> study_results/v11_funnel.csv.
- [x] 2. Lever grid A (no new code): relax each gate one at a time on the full-year streams with the v10 G ladder
        (min_quality M5 0.55->0.50/0.45, others 0.60->0.55/0.50; max_cost_r 0.08->0.10/0.12; NY-pm session allowed;
        max_open 4->6/8; order policy) -> v11_levers.csv: trades vs return vs DD vs win.
- [x] 3. Lever grid B (new simulator features, defaults byte-identical): re-entry on the same POI after a BE / partial exit,
        second fill of a mirrored order, pending order life-time, multiple concurrent plans per timeframe -> tests.
- [x] 4. Combine the levers that add trades WITHOUT raising DD / lowering PF; walk-forward: tune on Sep25-Feb26 (IS half),
        verify on Mar-Sep26 (OOS half); stress (spread x2, commission x2, slippage x3).
- [x] 5. Report study_results/MORE_TRADES_STUDY.md + charts, README section 0d, run_trader.bat, tests, final tar.

## Log (v11)
- 2026-09-20 08:00 step 0 done: v10 archive -> /home/user/webapp (1.1 GB incl. study_results), backup repo genspark-ed05b51a
  (first push 230 MB ok, save.sh push timeout 90 -> 400 s), CSV linked, lightgbm installed, 91 tests pass.  Env: py3.13, 2 cores, 1 GB RAM.
- 2026-09-20 08:10 step 1 done: run_v11_funnel.py reproduces the v10 reference EXACTLY (251 trades, +80.74 %, DD -5.49 %, PF 1.747,
  win 69.3 %; 15 s per full-year run).  FUNNEL of the 3 882 unique POIs shown Sep25-Sep26 (study_results/v11_funnel*.csv):
  traded 251 (6.5 %) | trade filter 2 550 (66 %: M5 cost_r 958, quality gates M5 295 / M10 593 / M15 358 / M30 172 / H1 102,
  M5 nypm session 72) | order placed but cancelled before the fill 716 (18 %: 'no longer shown' 494, 'replaced' 382 - the mirror
  policy) | overlaps a pending order 343 (9 %, mostly M10/M15 = same level seen on two TFs) | overlaps open 22.
  Fill rate of placed orders 26 %.  Traded quality median 0.614 vs shown 0.538.  M10 is the best TF (52 tr, +0.59 R/tr, PF 3.6) and
  loses 64 % of its POIs to min_quality 0.60 -> quality relaxation on M10 and a grace period before the mirror cancel are the
  first levers to test.  Loss metrics to hold: max DD <= 5.5 %, win >= 69 %, PF >= 1.75, worst day >= -1.9 %, sl_% <= 30 %.
- 2026-09-20 08:05 step 2 done: run_v11_levers.py (53 single-lever variants, 2 workers, ~15 s each, resumable in
  study_results/v11_levers/, summary v11_levers.csv; run_v11_all.sh drives it with a 4-min autosave).  READING (judge on the OOS
  half Mar-Sep26 = +26.7 R / PF 1.64 for the reference; the IS half is contaminated by the entry model):
  * dedupe_overlap off (same level traded on 2 TFs): 334 tr (+83), +129 %, PF 1.84, win 71 %, OOS +34.8 R, DD 6.3 % (ref 5.5),
    worst day -2.7 % (ref -1.9).  M15 14 -> 45 trades (+1.3 -> +21.9 R): confluence zones are GOOD, the dedupe threw them away.
  * M30 min_quality 0.60 -> 0.52/0.55/0.57: +28/+19/+9 tr, OOS +36.5/+32.7/+33.1 R, DD 5.2/5.0/5.2 %, PF 1.70/1.72/1.80 -> holds.
  * H1 0.57 (+4 tr, OOS +29.9 R), M15 0.57 (+17, OOS +27.5 R, PF 1.65), M5 all sessions (+48, OOS +27.3 R, PF 1.66, worst day -2.9),
    M5 cost 0.12 (+32, OOS +27.0 R, PF 1.60): neutral-to-slightly-positive OOS.
  * REJECT: M10 quality relaxation (+55..156 tr, IS +50 R but OOS FALLS to +15..20 R = pure in-sample artefact), M5 quality < 0.55
    (OOS +16..23 R, DD 7-11 %), persist orders (DD 11-16 %), entry in front of the zone (DD 7-12 %), all-HTF 0.52 (OOS +6.5 R).
  * max_open 6/8 and one_trade_per_poi=false change NOTHING (never binding; a traded POI is never re-shown by the scanner).
  Next: step 3 = new simulator levers (re-entry after a BE exit, second-best POI per TF, mirror grace) + combos, judged OOS.
- 2026-09-20 08:40 step 3 done (two more sandbox migrations survived: files came back from git each time, restore.sh repointed
  save.sh to genspark-8eed6fe8 then genspark-52344393).  New simulator levers (lubot/execution.py TraderConfig, portfolio_sim.py;
  defaults byte-identical to v10, parity check on the full year exact; 4 tests, 95 pass):
  `dedupe_cross_tf=false` (overlap check only within the same TF -> a level shown on two TFs is traded on both),
  `overlap_mode=allow|share` + `overlap_risk_frac` (overlapping plan at full / reduced risk), `cancel_grace_min` (keep a
  mirrored order N minutes after the scanner drops the POI).  run_v11_combos.py: 106 runs (grid B singles + combos) ->
  study_results/v11_combos.csv.  RESULT:
  * dedupe_cross_tf=false ALONE: 331 tr (+80 = +32 %), +136 % (ref +81 %), DD 5.7 % (5.5), PF 1.89 (1.75), win 72 % (69),
    OOS +35.2 R / PF 1.65 (ref +26.7 / 1.64), IS +59 R.  The 80 extra trades: M15 +31 (win 81 %, +0.67 R/tr), M10 +28, M30 +13,
    H1 +7; 75 % of them are confluence zones the v10 dedupe threw away.  Worst day -2.75 % (ref -1.94) because two same-level
    plans can now stop together (14 such pairs in the year); max 4 concurrent positions (ref 2).
  * share (0.25/0.5/0.75 risk on the 2nd plan): same trade count, LOWER return and PF than full risk (1.68-1.72) -> the
    confluence trades are the better half, cutting their size hurts.  allow (= dedupe_overlap off) ~ xtf but slightly worse DD.
  * cancel_grace_min 5..60: +144..+340 trades but DD 12-16 %, OOS PF 1.04-1.14 -> REJECTED.  The scanner drops a POI for a
    reason; the orders that fill during the grace are the losers.  Same finding as persist orders in grid A.
  * best combos (loss profile held, judged OOS): m30q57 + xtf: 343 tr, +148 %, DD 5.18 %, PF 1.91, win 71.7 %, OOS +40.5 R /
    PF 1.71, worst day -2.29 %;  m30q57 + h1q57 + xtf: 348 tr, +148 %, DD 5.22 %, PF 1.91, OOS +42.0 R / PF 1.73, 12/13 months.
    Adding m5 all-sessions: 405 tr, +166 % but DD 5.8 %, worst day -3.1 %, OOS PF 1.64 -> more trades, loss profile slightly worse.
  Next: step 4 = stress the finalists (spread x2, commission x2, slippage x3, worst intrabar, risk 0.5 / 2 %).
- 2026-09-20 09:05 step 4 done: stress of 6 finalists x 6 scenarios (v11_stress.csv; return / DD / OOS PF):
  ref: spread x2 +33 % / 6.8 / 1.11, commission x2 +64 / 5.1 / 1.48, slippage x3 +74 / 5.7 / 1.57, worst intrabar +79, risk 0.5 % +33 / 3.1, risk 2 % +198 / 10.6.
  m30q57+h1q57+xtf: spread x2 +58 / 9.3 / 1.29, commission x2 +124 / 6.2 / 1.65, slippage x3 +136 / 5.9 / 1.69, worst intrabar +148 / 5.1 / 1.74,
  risk 0.5 % +63 / 2.4 / 1.80, risk 2 % +449 / 10.8 / 1.75.  Ahead of the reference in every scenario on return and OOS PF; the only
  weaker point is the drawdown at DOUBLE spread (9.3 vs 6.8 %) - the extra M15/M30 trades have wider zones and pay less spread per R,
  but two confluence plans stopping together add up (Apr 2026 -$673).  B_xtf alone: spread x2 +52 / 7.0 / 1.21.
  Walk-forward (pick on the IS half only, IS_PF >= 1.9 sorted by IS_R): the top-12 are all m5sess/xtf/share combos with OOS
  +33..42 R, PF 1.42-1.64 - m5sess is in-sample favoured (nypm session) -> NOT recommended; xtf is in 11 of 12.  Spearman IS_R vs
  OOS_R over 114 variants 0.54 (p 6e-10).  dedupe_cross_tf ported to trader.py (+2 fake-MT5 tests, 97 pass).
  DECISION: recommend `dedupe_cross_tf=false` + M30/H1 min_quality 0.57 (348 tr, +39 % more trades, +148 %, DD 5.2 %, PF 1.91,
  win 72 %, OOS PF 1.73, 12/13 months); conservative alternative = `dedupe_cross_tf=false` alone (331 tr, +136 %, DD 5.7 %).
- 2026-09-20 10:00 step 5 done (4th migration recovered first: save.sh -> genspark-ce520088): make_v11_report.py +
  make_v11_report_template.md -> study_results/MORE_TRADES_STUDY.md + charts/v11_{equity,scatter,funnel,monthly}.png; README 0d +
  command table; run_trader.bat ships v11-B (dedupe_cross_tf=false + M30|H1 quality 0.57) - the exact bat strings replayed in the
  simulator give 348 tr / +147.93 % / DD -5.22 % = identical to the study run.  97 tests pass.  ALL v11 STEPS COMPLETE.
  RESULT: v11-B 348 trades (+39 %) at +148 % / DD 5.2 % / PF 1.91 / win 72 % / OOS PF 1.73 vs v10 251 / +81 % / 5.5 % / 1.75 / 69 % / 1.64.

---

# PROGRESS — v10 MULTI-TP + LOSS LIMITS + FULL-YEAR BACKTEST — ALL STEPS COMPLETE (2026-09-20 06:30)

**Recovery:** clone the backup repo (`git remote -v` / save.sh) into `/home/user/webapp`, `bash restore.sh`
(relinks the CSV to `data/xauusd_m1.csv`, pip, tests), read this file, continue from the first unchecked step.
Every step ends with `bash save.sh "msg"` (commit + push).  Long jobs are resumable (skip existing outputs) and
`bash run_v10_all.sh` runs the whole remaining pipeline unattended with a 4-min autosave.
If the sandbox migrated: `git remote get-url origin` shows the new repo -> `sed -i` it into save.sh (restore.sh does this).

## User spec (v10)
1. Test whether MORE THAN 2 take-profits (3, 4, 5 legs; ladders, runners, creative exits) raise profitability; explore more ideas.
2. Add to the trading bot: (a) max daily loss 4.5 % -> stop trading for the day; (b) max total loss 9 % -> bot stops for good.
3. Full-YEAR backtest result (not six months).
4. Save after every step, recoverable.

## Plan (v10)
- [x] 0. PROGRESS header, plan, save.
- [x] 1. Full-year selection streams (30 monthly chunks, merged 20:48 -> sel_v10_{H1,M30,M15,M10,M5}.pkl, Sep25-Sep26): `run_v10_record.sh` records Sep 2025 -> Sep 2026 for M5 (with features) and M10/M15/M30/H1
        in monthly chunks (parts_v10/), each chunk committed; merged -> study_results/sel_v10_<TF>.pkl.
        NOTE: the quality model is trained until 2026-03-01 -> Sep25-Feb26 entries are IN-SAMPLE, Mar-Sep26 OOS; the report labels both.
- [x] 2. Simulator loss rules (`lubot/portfolio_sim.py`, TraderConfig `max_daily_loss_pct=4.5`, `max_total_loss_pct=9.0`):
        realised+floating equity vs day-start balance -> close everything, cancel orders, no new orders until the next
        server day; total -> flatten and halt forever.  Tests.
- [x] 3. Live bot (`trader.py`): same rules, day anchor + peak/start balance persisted in the crash-safe state file, halted flag; tests vs fake MT5.
- [x] 4. Simulator extensions for creative exits (TraderConfig): `sl_after_leg=x|0|1.0` (per-leg stop schedule in R: leave / BE /
        lock +xR after the k-th leg - replaces be_on_partial), `trail_after_leg=k` (runner trail only after k legs), `tp_unit=atr`
        (ATR-based ladders), `ladder_fallback=merge` (small legs merged instead of rejecting the plan).  7 tests (89 pass).
- [x] 5. `run_v10_study.py` (887 variants: L3 306 / L4 330 / L5 112 / runner R 28 / ATR 42 / geometric G 30 / two-leg ref A2 36 +
        base_v8 + v9): `--mode oos` portfolio Mar-Sep26 -> study_results/v10_study/, v10_study_grid.csv; `--mode is` in-sample replay
        (1270 plans) -> v10_insample/, v10_insample.csv.  Parity with v9 exact (base +12.32 % / +0.1648 R).  DONE: 887/887 OOS + 887/887 IS.
- [x] 6. `run_v10_year.py` DONE: 7 systems x rules on/off x 7 stress = 112 runs -> v10_year_summary.csv, v10_year_monthly.csv: full-year portfolio backtest Sep25-Sep26 (streams from step 1) of current spec / v9 / best v10, with and
        without the loss rules, monthly table, per-half; stress.
- [x] 7. Report `study_results/MULTI_TP_STUDY.md` + charts (make_v10_report.py), README 0c, run_trader.bat (4-leg ladder), 91 tests, archive.

## Log (v10)
- 2026-09-20 06:30 ALL v10 STEPS COMPLETE (session 3, ~9 sandbox migrations survived via autosave).  RESULT: 4-leg geometric
  ladder 25 % each @ 0.6/1.2/2.4/4.8R, BE after leg 1 (`tp_levels=0.6|1.2|2.4|4.8,tp_fracs=1|1|1|1,ladder_fallback=merge`):
  full year Sep25-Sep26 +80.7 % / DD 5.5 % / PF 1.75 / 11 of 13 months (v9 +60.5 % / 6.8 %, current spec +28.6 % / 4.4 %);
  OOS grid +31.5 % / 4.1 % (v9 +29.4 / 4.3); IS +0.301 R/plan, DD -17.8 R (v9 +0.308 / -20.9).  More legs per se does NOT help
  (median 3-5 leg system worse than median 2-leg); first leg >= 0.6R, last leg >= 3R, BE after leg 1 are what matter.  Loss rules
  (4.5 % day / 9 % total) implemented sim + live, never trigger at 1 % risk over the year (worst day -2.5 %).  Report:
  study_results/MULTI_TP_STUDY.md; README 0c; run_trader.bat updated; 91 tests pass.
- 2026-09-19 18:55 RECOVERY (session 3): webapp.tar.gz extracted into /home/user/webapp, remotes + save.sh repointed to
  genspark-c53ca3da, CSV linked, deps present, 82 tests pass.  Step 1 state at recovery: H1 6/6, M30 6/6, M15 6/6, M10 1/6, M5 0/6
  chunks.  run_v10_record.sh relaunched (resumable).  Continuing with steps 4-7 while it records.
- 19:10 sandbox migrated again (history squashed to one commit by the platform; code + 23 chunks intact). Restored: save.sh ->
  genspark-3d528252, CSV relinked, lightgbm reinstalled, 89 tests pass, recorder relaunched.
- 21:55 migration again (backup repo now genspark-a53c36fd).  OOS 887/887 done, IS 527/887.  Relaunched run_v10_all.sh.
- 21:15 migration again (backup repo now genspark-ef07eed4).  OOS grid 882/887 (5 ATR/G variants crashed on a merge-sizing edge case
  when the whole plan is one 0.01 lot -> fixed in execution.py, 91 tests).  IS grid 127/887.  Relaunched run_v10_all.sh (2 workers).
- 20:50 another migration (backup repo now genspark-26b35330); state kept by autosave: OOS grid 813/887, all 30 stream chunks
  recorded (merge pending), IS grid 5/887.  Relaunched recorder (merge only) + run_v10_all.sh.
- 19:30 two more migrations (each squashes history; autosave kept the files).  trader.py: v10 N-leg ladder support (one limit
  leg per target, _manage_ladder applies sl_after_leg / classic BE / ratchet when a target leg closes) + 2 fake-MT5 tests (91 pass).
  run_v10_year.py written + smoke-tested on the H1 stream.  Backup repo now genspark-a97983a5.
- 19:20 step 5 code done + launched: run_v10_study.py, run_v10_all.sh (OOS grid -> IS grid -> waits for sel_v10_M5 -> year -> report,
  4-min autosave).  ~5 s/variant OOS, ~3 s IS with 1 worker (recorder uses the other core).
- 19:02 step 4 done: lubot/execution.py + lubot/portfolio_sim.py v10 fields (sl_after_leg, trail_after_leg, tp_unit, ladder_fallback,
  merge_small_legs); defaults byte-identical to v9 (guard test).  tests/test_rm_systems.py +7 -> 89 pass.
- 17:00 step 0 + run_v10_record.sh launched (H1/M30 chunks ~20 s, M15/M10 minutes, M5 ~5 min/chunk with features).
- 17:15 step 2 done: TraderConfig max_daily_loss_pct / max_total_loss_pct; simulator checks equity (realised+floating) every M1 bar,
  daily -> flatten+cancel+block until next server day (day-start balance = equity at the day change), total -> flatten+halt;
  outcomes daily_halt/halt, summary daily_halts/halted/halt_time; 4 tests (79 pass).  Sandbox migrated once (recovered from git).
- 17:40 step 3 done: trader.py check_risk_limits() runs first in every loop (equity = terminal balance + floating): total limit -> cancel all,
  close all, state.risk.halted=True (survives restarts; start_balance persisted); daily limit -> same flatten, daily_halt_day set, reset
  when the server day changes (day_start_equity = equity at day change).  CLI --max-daily-loss 4.5 / --max-total-loss 9.0 (0 = off);
  run_trader.bat header.  3 fake-MT5 tests (82 pass).  2nd migration of the session recovered.

---

# PROGRESS — v9 RISK-MANAGEMENT STUDY (current work)  — recovery log

**Recovery:** clone the backup repo (`git remote -v` / save.sh) into `/home/user/webapp`, then
`bash restore.sh` (relinks the CSV to `data/xauusd_m1.csv`, runs tests) and continue from the first
unchecked step below.  Every step ends with `bash save.sh "msg"` (commit + push).  The study runner
`run_rm_study.py` is resumable: one json per variant in `study_results/rm_study/`, finished variants are skipped.
`bash run_v9_all.sh` runs the whole remaining pipeline (resumable, commits after every stage).

**2026-09-18 20:30 RECOVERY NOTE (session 2).**  The previous session died.  Its archive (webapp.tar.gz) contained
109/580 OOS variants (A_p0.2-0.5 only), the in-sample population + base_v8 replay, and a *report*
(`RISK_MGMT_STUDY.md`) whose numbers for p0.6+, families B-F, the in-sample table, stress tests and charts had
NO backing files (rm_study_grid.csv, rm_stress.py, make_rm_report.py, charts/rm_*.png were all missing).
That draft was renamed `RISK_MGMT_STUDY_draft_unverified.md` and is NOT to be trusted; every number is being
recomputed from scratch below.  Backup repo now genspark-5a347557 (save.sh repointed).

## User spec (v9)
- Current management: close 50 % at +0.4R, SL -> break-even, TP2 fixed at +1.5R.
- Task: test different numbers AND different systems for the risk management and find the most profitable one.
- Save the process after every step, recoverable if the session dies.

## Plan (v9)
- [x] 0. Extract archive -> /home/user/webapp, link CSV, 62 tests pass, v8 baseline reproduced exactly
        (98 M5 trades +10.11 % / all-TF recommended 131 trades +12.3 %, PF 1.46).
- [x] 1. Simulator extended (`lubot/execution.py`, `lubot/portfolio_sim.py`), defaults byte-identical to v8:
        `partial_frac=0` (single target), `tp2_r=0` (runner without target), `tp_levels/tp_fracs` (3+ leg ladder),
        `ratchet_sl`, `be_on_partial`, `be_trigger_r`, `be_offset_r`, `trail_r/trail_start_r/trail_after_partial/trail_source`,
        `max_hold_min`.  New outcomes: trail, time, be.  Session 2: `tests/test_rm_systems.py` (11 hand-built scenarios
        covering every new mechanic, 73 tests pass).
- [x] 2. `run_rm_study.py` — OOS grid (Mar-Sep 2026, v8 entries fixed, 580 management variants), resumable -> rm_study_grid.csv.
- [x] 3. In-sample check (`rm_insample.py --all`, parallel, resumable): EVERY management replayed on the cached
        population `study_results/rm_insample_population.pkl` (1270 bot-like plans Jan25-Feb26 after the v8 gates:
        M5 503, M10 362, M15 239, M30 118, H1 48).  Parity verified again in session 2: base_v8 = +0.1648 R/plan, PF 1.877.
- [x] 4. Stress tests of the finalists (`rm_stress.py`, finalists picked automatically from OOS ret/DD + IS avg R):
        spread x1.5/x2, slippage x3, worst intrabar, BE delay, netting, commission x2, risk 0.5/2 %, max 2 open, no costs.
- [x] 5. `make_rm_report.py` (tables, charts, IS-vs-OOS correlation) -> report `study_results/RISK_MGMT_STUDY.md`,
        README section, final save + backup archive.
        `bash run_v9_all.sh` runs 2 -> 5 unattended (resumable, commits after every stage).
- [x] 6. README section 0b + layout, run_trader*.bat ship the v9 management, live-bot test of the 25/75 legs, 75 tests pass.

## Log (v9, session 2)
- 20:30 recovered from the uploaded tar (109/580 variants); draft report renamed *_draft_unverified.md; deps, 62 tests.
- 20:35-21:14 OOS grid 109 -> 580 (2 workers, ~5 s/variant), then `rm_insample.py --all` (580 replays, parallel), stress of
  6 auto-picked finalists, make_rm_report.py - all driven by run_v9_all.sh with a 4-min autosave; three sandbox migrations
  happened during the session, every time the state came back from git (restore = repoint save.sh, relink CSV, pip, pytest).
- 21:20 tests/test_rm_systems.py (11 scenarios) + live-bot test of the recommended 25/75 legs -> 75 tests pass.
- 21:25 second stress batch for the 0.6R family (14 finalists x 12 scenarios = 168 runs), charts regenerated.
- 21:40 RESULT: recommended management = close 25 % at +0.6R -> BE, TP2 2.5R (twin: TP2 3R).  IS +0.308 vs +0.165 R/plan
  (paired t 7.1, 13/14 months), OOS +29.4 % vs +12.3 % (DD 4.3 vs 3.2 %), Spearman IS/OOS over 580 systems 0.61.
  Report study_results/RISK_MGMT_STUDY.md; README 0b; bat files updated.  ALL v9 STEPS COMPLETE.

---

# PROGRESS — v8 M5 TRADE FILTER (make the 5-minute trades profitable again)

This file is the recovery log. Every step is committed + pushed (`bash save.sh "msg"`) AND archived
(ProjectBackup tar / uploaded tar - links appended below).  If the session dies: extract the last tar
(or clone the Genspark backup repo, URL in `save.sh`) into /home/user/webapp, run `bash restore.sh`,
read this file, continue from the first unchecked step.  Long jobs are resumable (they skip outputs
that already exist).  NOTE: /mnt/aidrive is NOT a real mount in this sandbox -> backups go to git +
ProjectBackup + uploaded tar links.

Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (symlink `data/xauusd_m1.csv`).
Spread: bars with `<SPREAD>=0` are filled from the (weekday, NY-hour) median profile of the bars that carry one
(`lubot/data.py::impute_spread`) = "same spread as the part with spread" (unchanged from v7).

## User spec (v8)
- v7 result: all-TF trader loses (-14.3 %); dropping M5 + min-quality 0.60 is profitable. User wants the M5
  trades made GOOD again: a way to filter M5 POIs / trade setups and hand-pick the ones with a higher
  probability of profit.  Backtest accurately and realistically.  Save after EVERY step (recoverable).

## Diagnosis (from v7 base trades, OOS Mar-Sep 2026)
- M5: 267 trades, -0.047 R/trade net (-0.034 gross).  Costs on M5 = 0.066 R/trade (median zone $6.3, spread
  $0.28 + $0.07 commission) vs 0.04-0.05 R on higher TFs.  Smallest zone quartile (< $4.1) -0.18 R/trade.
- M5 quality 0.50-0.55: -0.18 R (n=126); >= 0.55: +0.07 R (n=141).  Sells -0.23 R, buys +0.09 R.  IMB -0.11 R.
- Root cause: the quality model predicts P(bounce >= 1 ATR) - not the outcome of THIS plan (partial 0.4R /
  TP2 1.5R with R = zone height) net of costs.  -> v8 trains an M5 *trade-outcome* filter on the plan's real
  R (labelled on M1 bars, before 2026-03-01 only) and verifies it out-of-sample in the portfolio simulator.

## Plan (v8)

- [x] 0. Restore v7 archive into /home/user/webapp, repoint save.sh/remotes to the new backup repo, link CSV,
        pip deps, 59 tests pass, PROGRESS v8 header
- [x] 1. `label_plan_outcomes.py`: for every reached candidate of models/train_M5.pkl (and the other TFs)
        replay the v7 plan on M1 bars (limit at the near edge on ask/bid, SL far edge, partial 0.4R -> BE,
        TP2 1.5R, spread-aware) -> r_gross / outcome / cost_r  => models/plan_labels_<TF>.pkl (resumable)
- [x] 2. `experiments_m5_filter.py`: in-sample (< 2026-03-01) diagnostics of the plan R on M5 - cost-aware
        rules (zone $ / cost_r), univariate feature ranking, session/side/kind; validation Dec25-Feb26
- [x] 3. `train_trade_filter.py`: M5 trade-outcome model (LightGBM, POI-weighted, train < 2026-03-01,
        early-stop on val) -> models/trade_filter_M5.json (numpy inference via QualityScorer format);
        candidate-level OOS check (>= 2026-03-01) by score decile; threshold chosen on VALIDATION only
- [x] 4. Re-record the M5 selection stream (OOS Mar-Sep 2026 -> sel_v8_M5.pkl AND in-sample Feb25-Feb26 -> sel_v8is_M5.pkl) WITH the selected POI's feature vector at each set event
        (`record_selections.py --with-features`, resumable, ~30 min background) -> study_results/sel_v8_M5.pkl
- [x] 5. Trader integration: TraderConfig `trade_filter_path` / `trade_filter_min` / `max_cost_r` (per TF),
        portfolio_sim gate, trader.py live gate (features carried on the selection dict), tests
- [x] 6. Realistic OOS portfolio backtest Mar-Sep 2026: v7 base vs v8 (M5 filtered) vs q0.60, threshold and
        sub-period robustness, charts, `study_results/TRADER_V8.md`
- [x] 7. README, PROGRESS final, tests, final tar (ProjectBackup + upload link)

## Log (v8)

- 2026-09-18 06:45  step 1 done: lubot/plan_replay.py (single-plan M1 replayer, same mechanics as portfolio_sim; parity test
  tests/test_plan_replay.py on 120 random plans: entry/fill minute/outcome/R identical), label_plan_outcomes.py -> models/plan_labels_{M5,M10,M15,M30,H1}.pkl
  (aligned with models/train_*.pkl; 9 s per TF).  NOTE sandbox migrated mid-step (restore.sh recovered everything, backup repo now genspark-f1799d8f).
  Labels over ALL reached candidates (not only the bot's picks): M5 27.5k filled plans, outcome sl 61% / partial_be 22% / tp2 17%,
  avg -0.79 R gross, median cost 0.23 R (!) - zones < $1 (35% of candidates) lose -1.8 R/trade because the spread alone is 0.3-0.65 R.
  The bot's actual M5 picks (v7) had median zone $6.3 -> the candidate pool is dominated by tiny zones the selection rarely takes.
  Step 4 (sel_v8 streams with features, background) launched early so it overlaps with steps 2-3.
- 2026-09-18 06:55  step 2 done: experiments_m5_filter.py -> study_results/m5_filter_*.csv (+ logs/m5_filter_experiments.log).
  In-sample bot-like M5 rows (best of slot, q>=0.50, Jan25-Feb26): 2300 plans / 1074 POIs, avg -0.075 R net (OOS v7 was -0.047).
  * cost is the killer: cost_r (spread+comm)/R > 0.15 -> -0.12 R (n=567), > 0.3 -> -0.41 R; zone <= $2 -> -0.23 R.  cost_r 0.04-0.06 -> +0.08 R.
  * quality: 0.50-0.55 -0.15 R, 0.55-0.60 -0.10, 0.60-0.65 +0.01, >= 0.65 +0.12 (n=237) - monotone but weak; q>=0.60 +0.07 train / -0.01 val.
  * sessions: nypm (NY afternoon) -0.19 R (n=631) worst; lclose/preny/ny ~0.  sells -0.12 vs buys -0.05.  OB worst kind (-0.11; TP2 only 15%).
  * univariate features: only cr_adx (ADX at creation, gap +0.29 train / +0.27 val) and ind_vwap_dist/htf_rsi_aligned/swing_in_zone are
    stable; atr_ratio / round-number features flip sign on validation.  Hand rules based on $ thresholds are unstable because gold's
    price level (and zone $) grew ~2x during the sample -> use ratios (cost_r, zone_atr) and a multivariate model, not $ rules.
  Decision: step 3 = LightGBM trade-outcome model P(plan not stopped | features) + a hard cost_r cap in the trader.
- 2026-09-18 07:20  (sandbox migrated again before this; restore.sh recovered everything, backup repo now genspark-9baad531)
  step 3 done: train_trade_filter.py -> models/trade_filter_M5_{trainonly,trainwindow}.json, study_results/trade_filter_M5_*.csv.
  HONEST RESULT: on ALL filled M5 candidates the plan-outcome model ranks well (test AUC_w 0.72; top features zone_usd, cost_r_est,
  zone_atr) - but that is the zone-size/cost effect.  On the BOT-LIKE population (best of slot, q>=0.50 = what the trader sees)
  it has NO out-of-sample skill: val AUC 0.50, test AUC 0.50, early stopping after 6 rounds; score quintiles OOS are flat.
  => a second ML model cannot hand-pick among the scanner's M5 picks with these features.  The filter must come from the robust,
  interpretable levers found in step 2 (cost_r cap, higher M5 quality threshold, session, side) tuned with the REAL portfolio
  simulator on an in-sample stream, then validated OOS.  Model files kept as optional (`trade_filter_path`), default OFF.
- 2026-09-18 07:50  (3rd sandbox migration; recovered via restore.sh, backup repo now genspark-2053c97d)  step 5 done:
  lubot/trade_filter.py (TradeFilter: per-TF rules max_cost_r / min_quality / min|max_zone_atr / sessions / hours / sides / kinds /
  optional model_path+model_min; string syntax "M5:max_cost_r=0.08;min_quality=0.55;sessions=london|ny/M10:..."),
  TraderConfig.trade_filter, portfolio_sim gate (uses the spread of the placing minute; filter_reasons()), trader.py gate (live
  ask-bid spread), backtest_trader prints rejections, tests: 62 pass.  Same code path live and in the backtest.
- 2026-09-18 07:30  4th migration killed the 30-min recorders twice -> run_v8_record.sh now records in MONTHLY CHUNKS (6-week
  warm-up each, carry-over of the POI shown at the chunk start, unique ids on merge), each chunk committed+pushed (max loss ~6 min).
  Order: OOS Mar-Sep 2026 (6 chunks) -> sel_v8_M5.pkl, then in-sample Feb25-Feb26 (7 chunks) -> sel_v8is_M5.pkl.
  run_filter_study.py (grid of interpretable M5 filters, resumable) ready; runs on sel_v8is first (tuning), then sel_v8 (verify).
- 2026-09-18 08:30  step 4 (OOS part) done: sel_v8_M5.pkl (6 monthly chunks, 8610 events, features attached).  Sanity: unfiltered
  replay = 280 trades / -15.2 % (v7 tf_M5: 275 / -14.3 %) -> chunking faithful.  In-sample chunks (sel_v8is) keep recording in
  the background (only used for an extra check; the rule choice is based on the plan labels).
- 2026-09-18 08:45  step 6 done (several more migrations; everything recovered from git each time):
  * insample_filter_grid.py: grid on bot-like in-sample plan labels -> chosen M5 rule = max_cost_r 0.08 + min_quality 0.55 +
    no NY-afternoon selections (train +0.063 R, val +0.077 R, 10/14 months positive).
  * run_v8_compare.py OOS Mar-Sep 2026: v7 base -16.6 % (395 tr) | q0.60 +5.1 % | v8 M5 only +10.1 % (98 tr, PF 1.49, DD 4.2 %) |
    v8 all TFs (others q0.60) +12.3 % (131 tr, PF 1.46, DD 3.2 %, Sharpe 2.35).  M5 = +9.8 R of +12.8 R.  H1 +10.4 % / H2 +2.2 %.
  * run_v8_stress.py: 2x spread +6.9 %, 3x slippage +10.7 %, worst intrabar +13.2 %, BE delay +13.0 %, netting +12.5 %,
    risk 0.5 % +6.2 %, commission x2 +10.9 %; cost cap 0.06/0.10 and no-session-rule all positive.
  * study_results/TRADER_V8.md + charts/trader_v8_equity.png.
- 2026-09-18 09:10  step 7 done: trader.py --trade-filter (default = V8_FILTER), run_trader*.bat (--commission 7), README section 0a +
  layout + recommended settings (update_readme_v8.py is idempotent), 62 tests pass.  ALL v8 STEPS COMPLETE.  In-sample chunk
  recording (sel_v8is) is optional extra evidence and may still be running in the background (resumable, harmless).

- 2026-09-18 06:20  step 0 done: v7 restored from lubot_trader_v7_final.tar.gz into /home/user/webapp (git history kept),
  remotes -> genspark-01f92a70, CSV linked, deps installed (py3.13, pandas 2.2.3, sklearn 1.6.1, lightgbm 4.7.0), 59 tests pass.
  Env: 2 cores, ~1 GB RAM.

---
# PROGRESS — v7 TRADER (execution + partial-close risk management + realistic backtest + live MT5 bot)

This file is the recovery log. Every step is committed + pushed (`bash save.sh "msg"`).
If the session dies: extract the last tar (links below) or clone the Genspark backup repo (URL in `save.sh`)
into /home/user/webapp, run `bash restore.sh`, read this file, continue from the first unchecked step.
Long jobs are resumable (they skip outputs that already exist).

Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv` (symlink `data/xauusd_m1.csv`).
Spread: bars with `<SPREAD>=0` (before 2026-04-06) are filled from the (weekday, NY-hour) median profile of
the bars that carry one (`lubot/data.py::impute_spread`) = "same spread as the part with spread".

## User spec (v7)
- Turn the v6 POI scanner into a TRADING bot.
- Entry = START of the POI (near edge, limit order), SL = END of the POI (far edge).
- Risk management = partial close: at +0.4R close HALF and move SL to break-even; TP2 fixed at 1.5R.
- Live bot: NO login option; works when the MT5 terminal is already open/logged-in on Windows.
- Backtest accurately & realistically (M1 precision, spread (imputed where missing), commission, slippage,
  broker rounding, out-of-sample model, one position per zone, realistic partial-close mechanics).
- Save/checkpoint after EVERY step.

## Plan (v7)

- [x] 0. Restore v6 archive into /home/user/webapp, rewire save.sh/remotes to the new backup repo, link CSV, plan
- [x] 1. `lubot/execution.py`: TradePlan (entry/SL/TP1/TP2 from a POI dict, spread-aware bid/ask), position sizing
        (risk % -> lots with broker volume step/min), MT5-realistic fill/trigger rules; unit tests
- [x] 2. `record_selections.py` (resumable per-TF stream of bot selections, train-only model) +
        `lubot/portfolio_sim.py` (M1-precision portfolio simulator: pending limit orders, fills, SL/TP on bid/ask,
        partial close at 0.4R -> BE, TP2 1.5R, costs, equity curve) + `backtest_trader.py`
- [x] 3. Run OOS selection streams (2026-03-01 -> 2026-09-04, model trained until 2026-03-01) per TF in the
        background; commit each TF as it finishes
- [x] 4. Portfolio backtest + sensitivity (slippage, commission, min_quality, TFs), charts,
        `study_results/TRADER_BACKTEST.md`
- [x] 5. `trader.py`: live MT5 bot (attach to open terminal, no login), order sync, partial-close manager,
        persistent state file (crash-safe), `--dry-run`; tested against a fake MT5 module
- [x] 6. README, `run_trader.bat`, requirements, final tar to AI Drive + ProjectBackup

## Log (v7)

- 2026-09-17 08:45  step 0 done: v6 restored to /home/user/webapp (from lubot_quality_v6_final.tar.gz), remotes -> genspark-4cd9bbeb, CSV linked. Env: py3.13, 2 cores, ~1 GB RAM.

- 2026-09-17 09:05  step 1 done: lubot/execution.py (SymbolSpec, TraderConfig, TradePlan.from_poi: entry=near edge, SL=far edge, TP1 0.4R partial 50% -> BE, TP2 1.5R; size_plan with broker volume rounding, split/netting modes) + tests/test_execution.py (9 tests, 41 total pass). record_selections.py written (resumable per-TF selection stream). NOTE: sandbox migrated mid-step -> backup repo is now genspark-8d5c2bcd (save.sh repointed).
- 2026-09-17 09:40  step 2 done: lubot/portfolio_sim.py (M1 portfolio simulator: limit fills on ask/bid, MT5-tester intrabar path O->L->H->C / O->H->L->C, SL/TP on the correct side, split legs (leg1 TP1 / leg2 TP2, BE after TP1), netting fallback, stop slippage, commission, swaps, margin/stop-out, mirror/persist order policy, 1 trade per POI, overlap dedupe, equity-based sizing) + tests/test_portfolio_sim.py (12 tests; 53 total pass) + backtest_trader.py (CLI + report). Smoke-tested on a 2-day M5 stream (7 trades, outcomes tp2/partial_be/sl). Next: step 3 = bash run_v7_record.sh (background, resumable).
- 2026-09-17 10:05  step 5 done (done before step 4 while the recorder runs): lubot/mt5_broker.py (attach-only MT5 adapter, NO login; orders/positions/limit/cancel/modify/close, retcode retry), trader.py (live loop: scan on closed bars, mirror pending orders, split legs A(TP1)/B(TP2) on hedging accounts, netting fallback with bot partial close, BE move after leg A closes, crash-safe JSON state + re-adoption by magic/comment, --dry-run/--once), tests/fake_mt5.py + tests/test_trader_live.py (6 tests: full life-cycle, mirror cancel, restart adoption, netting, dry-run). 59 tests pass. Recorder: H1, M30 done; M15 running (M10, M5 next).
- 2026-09-17 10:20  step 3: H1/M30/M15/M10 streams done (sel_v7_*.pkl committed), M5 recording (~30 min). run_trader_study.py written (35 variants, resumable, commits per variant). Preliminary base on 4 TFs: 186 trades, win 74.7%, partial hit 75%, TP2 19%, SL 25%, PF 1.10, +4.8%, maxDD 6.0% -> marginal edge; M10/M30/OB/grade A positive, M15/H1/IMB/UW negative. run_trader.bat / run_trader_dryrun.bat + restore.sh updated for v7.
- 2026-09-17 11:20  steps 3+4 done: all 5 streams (sel_v7_*.pkl). Fixed the fill-minute replay (after a limit fill the rest of the bar's adverse extreme is now walked; first run had leaked a too-optimistic worst_intrabar 69%). 35 variants re-run (study_results/trader_v7_var_*.json, old run in old_v7_run1/). RESULT base (user spec, all TFs, q>=0.50, $10k 1%): 395 trades, win 71.9%, partial hit 72%, TP2 17%, SL 28%, PF 0.87, -14.3%, maxDD 24.7%; no_costs +4.5% -> edge thinner than costs (~0.05R/trade). Positive subsets: q0.60 (96 tr, PF 1.21, +4.0%, DD 5.3%), tf_M10 (+6.1%, PF 1.23), tf_M30 (+3.4%, PF 1.48), buys_only (+11.8%, PF 1.21), grades_AB (+2.1%). persist_orders -53% (mirror policy essential). mgmt_no_partial -26% -> the partial close IS the best of the tested managements. Report + charts written.
- 2026-09-17 11:45  step 6 done: README section 0 (trader, live usage, backtest method, results table, honest reading, recommended stricter settings), layout + next steps, requirements (tabulate; MetaTrader5 for live). 59 tests pass. Final archive links below. ALL v7 STEPS COMPLETE.

---
# (previous) # PROGRESS — quality v6 (honest learning + new information: volume profile / level memory)

This file is the recovery log. Every step is committed + pushed (`bash save.sh "msg"`).
If the session dies: clone the Genspark backup repo (URL in `save.sh`) or extract the last
tar from AI Drive, run `bash restore.sh`, read this file, continue from the first unchecked step.
Long jobs are resumable (they skip outputs that already exist).

Data: `/home/user/uploaded_files/XAUUSD.t_M1_202501020100_2026090423581112.csv`
(symlinked at `data/xauusd_m1.csv`). Spread: bars with `<SPREAD>=0` (before 2026-04-06) are
filled from the (weekday, NY-hour) median profile of the bars that carry one
(`lubot/data.py::impute_spread`) — "same spread as the part with spread". Unchanged in v6.

Training sets `models/train_{H1,M30,M15,M10,M5}.pkl` (v5 features) are in git history at
commit 039f7b4 (`git checkout 039f7b4 -- models/train_*.pkl`) and are re-committed here.

## Plan (v6)

- [x] 0. Restore v5 archive into /home/user/webapp, rewire save.sh to the new backup repo, restore train pkls
- [x] 1. Honest evaluation harness `experiments_v6.py` Part A: POI-level duplication, cross-split leakage,
        group-aware weights (1/dups per POI), slot-level top-1 metrics; v5 baseline re-measured honestly
- [x] 2. Learner upgrade (no rebuild): LightGBM (binary + lambdarank per slot), tuned on validation,
        exported to the existing JSON tree format (numpy inference, `lubot/quality.py`); compare with v5 GBM
- [x] 3. New information features `lubot/levels.py`: rolling volume/time-at-price profile (zone LVN/HVN score,
        POC distance, value-area position/edge), long-memory level strength (historical swing reactions at
        the zone over ~3000 bars), arrival-time session features; wired into engine + quality.py; unit tests
- [x] 4. Pilot on one TF (M15): rebuild train set with v6 features, measure val AUC delta -> decide full rebuild
- [x] 5. Full rebuild of training sets (`build_all_train.sh`, resumable, commit per TF)
- [x] 6. Final v6 model (train-only + all-data), candidate-level OOS; keep v5 in `models/v5/`
- [x] 7. Bot-level OOS walk-forward per TF (`run_v6_parts.sh`, resumable) + `summarize_v6.py`
- [x] 8. `study_results/QUALITY_V6.md`, README, backup tar to AI Drive

## Log

- 2026-09-16 16:30  step 0 done. Environment: py3.13, sklearn 1.6.1, 2 cores, 1 GB RAM (expect resets on big jobs).
- 2026-09-16 17:05  steps 1+2 done (experiments_v6.py -> study_results/quality_v6_{baseline,lgb_grid,rank,bag_compare}.csv).
  Findings (val = Dec25-Feb26, test >= Mar26; slot-level top-1 metrics):
  * 70% of training rows are re-records of the same POI (mean 3.4 rows/POI, labels identical). Weighting rows
    1/rows-per-POI is the single biggest win: v5 GBM val AUC_w 0.655->0.662, val hit at P>=.60 60.9%->71.7%,
    P>=.65 59.8%->75.6%; test AUC 0.650->0.657, P>=.60 70.0->72.9%, P>=.65 75.7->78.4%.
  * LightGBM (l15 d4, POI weights, 364 it) ~= weighted v5 GBM (val AUC_w 0.664, test AUC 0.658); ensemble of both
    is best at strict thresholds (val P>=.60 72.3%, P>=.65 77.8%; test P>=.60 72.3%). Export to bot JSON exact (1e-16).
  * lambdarank (slot groups) is worse (val AUC 0.62); soft bounce target = higher precision but keeps only 23-30% of slots.
  * Ranking skill inside a slot is real but small: chosen candidate beats the slot mean by +9.5 pts.
  Decision: v6 model = POI-weighted, LightGBM+GBM ensemble; the remaining lever is NEW information -> step 3 (level memory).
- 2026-09-16 17:10  step 3a: lubot/levels.py LevelMemory written + verified backward-looking (future-bar mutation -> 0 diffs),
  0.3-0.5 ms per feature call. Next: wire into engine/quality, unit tests, M15 pilot.
- 2026-09-16 18:05  step 3 done: LevelMemory wired (cl_* creation snapshot in poi.py, lv_*/hlv_* selection in engine.py,
  258 model columns, use_levels flag, ~+30% CPU). 32 tests pass. train_v6.py written (POI-weighted LightGBM+GBM
  ensemble stored in ONE json: models ALL + ALL2, mixed in probability space by QualityScorer, exact numpy inference).
- 2026-09-16 18:20  step 4 done (M15 pilot, models/v6/train_M15.pkl, study_results/quality_v6_pilot_*.csv):
  * univariate: lv_rev_with / cl_rev_with (swing lows formed at the zone area before, for a bullish zone) AUC 0.60 alone,
    bounce by quintile 28.5 -> 48.9%; lv_rev_per_visit 0.595; rev_against 0.58; slice_frac / va_pos / zone_outside_va ~0.54.
    Profile densities (LVN/HVN, POC) are weak (0.50-0.53). Strongest new univariate signal of the whole project.
  * multivariate on M15 alone (10.9k rows): v6 vs v5 at fixed 150 iters test AUC_w 0.647 vs 0.642 (+0.5 pt); early-stopped
    val is noisy (0.661 vs 0.662). Features are correlated with tested_respected / liq_behind. Decide on pooled set.
  Decision: full rebuild (step 5) -> pooled ablation v5 vs v6 in train_v6 -> bot-level OOS.
  NOTE: the sandbox has been migrated/reset several times; after each: bash restore.sh (relinks data, reinstalls lightgbm),
  fix the repo id in save.sh to `git remote get-url origin`, then re-launch the first unchecked step (all resumable).
- 2026-09-16 18:35  WIP tar (code+models+train pkls, before full rebuild): https://www.genspark.ai/api/files/s/SKlAQR9g  (extract to /home/user, then bash webapp/restore.sh)
- 2026-09-16 19:30  step 5 done: models/v6/train_{H1,M30,M15,M10,M5}.pkl (same 63 403 reached rows as v5, +39 columns). Ablation running (logs/ablation_v6.log).
- 2026-09-16 19:45  step 6 ablation (study_results/quality_v6_ablation.csv): pooled v6 vs v5 features = same AUC (val_w 0.6645 vs 0.6653, test_w 0.6604 vs 0.6606); v6 slightly better at strict thresholds (test P>=.60 73.8 vs 71.8%, P>=.65 76.7 vs 75.9%, small n). Reaction memory univariate 0.57 but redundant with tested_respected/liq_behind. Real gain = POI weighting + ensemble learner. Training final v6 model (v6 features, weighted LGBM+GBM): logs/train_v6.log
- 2026-09-16 20:15  step 6 done: models/quality_model.json = v6 (258 feats, POI-weighted, LightGBM x5 (270 it) + GBM x5, mixed 50/50; ALL+ALL2 in one JSON). Candidate-level OOS (>= Mar26): AUC 0.657 (v5 0.652), top-1 P>=.50 64.6% (v5 65.0), P>=.55 69.8 (68.4), P>=.60 73.0 (71.2), P>=.65 76.3 (77.7), calibrated (.62->.72, .67->.78). v5 kept in models/v5/. bot.py prints a 'level memory:' line. Step 7 running: run_v6_parts.sh (logs/compare_v6_*.log).
- 2026-09-16 20:20  tar with final v6 model + all train sets: https://www.genspark.ai/api/files/s/SWEiPraN
- 2026-09-16 21:00  step 7 done (5 parts, compare_v6_summary.csv): bot-level OOS v6 = 57.3% ge1 at P>=.50 (v5 57.2, v4 57.5);
  P>=.60: 408 zones / 68.0% (v5 349 / 65.7%) -> 17% more strict-grade zones at better hit-rate; calibration .62->.68, .73->.73.
- 2026-09-16 21:10  step 8 done: study_results/QUALITY_V6.md, README (section 1b rewritten for v6), requirements note.
  Verified: 32 tests pass; bot scan runs with lightgbm+sklearn imports blocked (numpy-only inference of the ensemble JSON).
  ALL v6 STEPS COMPLETE. Final archive link below.
