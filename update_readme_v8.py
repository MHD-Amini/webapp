#!/usr/bin/env python3
"""v8 step 7 - idempotent README update (re-runnable after a sandbox migration)."""
p = "README.md"
s = open(p).read()
if "## 0a. v8" in s:
    print("README already has the v8 section")
    raise SystemExit

s = s.replace("# LU-POI TRADER — Liquidity University POI trading bot for XAUUSD.t (MT5)   *(v7)*",
              "# LU-POI TRADER — Liquidity University POI trading bot for XAUUSD.t (MT5)   *(v8)*")
s = s.replace("| **Live trading** (Windows, MT5 open) | `run_trader.bat`  or  `python trader.py --symbol XAUUSD.t --risk 1.0` |",
              "| **Live trading** (Windows, MT5 open) | `run_trader.bat`  or  `python trader.py --symbol XAUUSD.t --risk 1.0 --commission 7` (v8 M5 filter ON by default) |")
s = s.replace("| **Realistic portfolio backtest** | `python backtest_trader.py --csv data.csv` (after `bash run_v7_record.sh`) |",
              "| **Realistic portfolio backtest** | `python backtest_trader.py --csv data.csv --sel \"study_results/sel_v*_*.pkl\" --trader \"trade_filter=...\"` (after `bash run_v7_record.sh` / `bash run_v8_record.sh`) |\n"
              "| **v8 M5-filter study** (in-sample choice, OOS check, stress) | `python insample_filter_grid.py; python run_v8_compare.py --filter ...; python run_v8_stress.py; python make_v8_report.py` → `study_results/TRADER_V8.md` |")
s = s.replace("→ **Results: section 0 below and `study_results/TRADER_BACKTEST.md`.**\n\n---\n", """→ **Results: section 0a/0 below, `study_results/TRADER_V8.md` (v8) and `study_results/TRADER_BACKTEST.md` (v7).**

---

## 0a. v8 — the M5 trade filter (what changed since v7)

v7 lost −14 % because the **M5 trades** (68 % of all trades) lost −0.05 R each: the M5 zone is a few dollars, so spread +
commission eat ~0.07 R per trade, and the scanner's P(bounce ≥ 1 ATR) is not the probability that *this plan* (limit at the
near edge, SL at the far edge, half at +0.4R, TP2 +1.5R) works.  v8 adds `lubot/trade_filter.py` — per-timeframe,
interpretable gates checked with the live spread, the same code in the backtest and in `trader.py`:

```
trade_filter = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10|M15|M30|H1:min_quality=0.60"
```
* `max_cost_r` — (spread + commission/oz) / 1R must be ≤ 8 % → no thin zones
* `min_quality` — M5 needs the quality model's score ≥ 0.55; the other timeframes ≥ 0.60
* `sessions` — no new M5 orders from selections made 13:00–17:00 New York (the "nypm" session, worst in-sample)
* also available: `min_zone_atr`, `max_zone_atr`, `hours`, `sides`, `kinds`, and an optional ML gate `model_path`/`model_min`

The rules were chosen **in-sample only** (every M5 candidate of 2025-01 → 2026-02 replayed as a v7 plan on M1 bars,
`label_plan_outcomes.py`; train < Dec 2025, validation Dec 2025 – Feb 2026), then verified out-of-sample with the portfolio
simulator.  A second ML model trained on plan outcomes had *no* skill on the bot's own picks (AUC 0.50) and is OFF.

**Out-of-sample 2026-03-02 → 2026-09-04, $10 000, 1 % risk, real costs** (`study_results/TRADER_V8.md`):

| configuration | trades | win % | PF | R/trade | return | max DD | Mar–May | Jun–Sep |
|---|---|---|---|---|---|---|---|---|
| v7 base (all TFs, no filter) | 395 | 71.4 | 0.85 | −0.044 | **−16.6 %** | −26.0 % | +3.4 % | −18.1 % |
| v7 `min_quality=0.60` | 98 | 80.6 | 1.27 | +0.057 | +5.1 % | −5.3 % | +5.6 % | 0.0 % |
| v7 without M5 | 181 | 73.5 | 1.02 | +0.008 | +1.2 % | −5.9 % | +4.0 % | −0.6 % |
| **v8 M5 only (filtered)** | 98 | 80.6 | 1.49 | +0.104 | **+10.1 %** | −4.2 % | +11.6 % | −1.6 % |
| **v8 all TFs (recommended, default)** | 131 | 80.9 | **1.46** | +0.098 | **+12.3 %** | **−3.2 %** | +10.4 % | +2.2 % |

The M5 trades went from the main loss (−15 R) to the main profit source (+9.8 R of +12.8 R).  Stress tests of the
recommended configuration: 2× spread +6.9 %, 3× slippage +10.7 %, worst-case intrabar path +13.2 %, 2-min BE delay
+13.0 %, netting +12.5 %, commission ×2 +10.9 %, risk 0.5 % +6.2 % / DD 1.4 %.  Honest caveats: 131 trades in six months,
the second half is much weaker than the first (July negative for every configuration), sells are still negative — the M5
edge after costs is ~0.10 R per trade, not more.  Start with `--dry-run`, then 0.5 % risk.

`--trade-filter ""` restores the v7 behaviour; `python backtest_trader.py ... --trader "trade_filter=M5:max_cost_r=0.06"`
tests other rules on the recorded streams (`study_results/sel_v8_M5.pkl` carries the feature vectors, so `model_path` rules
work in the backtest too).

---
""")
s = s.replace("""**Recommended live settings** (`run_trader.bat` uses the plain spec; the stricter, back-tested-positive one is):
```
python trader.py --symbol XAUUSD.t --risk 0.5 --min-quality 0.60 --timeframes M10,M15,M30,H1 --trader max_open_positions=2
```""", """**Recommended live settings (v8)** — `run_trader.bat` already applies the v8 filter (section 0a); for a cautious start:
```
python trader.py --symbol XAUUSD.t --risk 0.5 --commission 7 --trader max_open_positions=2
```
(v7 alternative without M5: `--trade-filter "" --min-quality 0.60 --timeframes M10,M15,M30,H1`)""")
open(p, "w").write(s)
print("README updated")
