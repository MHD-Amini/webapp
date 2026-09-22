#!/usr/bin/env python3
"""v14 step 1 - DIAGNOSIS of the LOSS STRUCTURE of the v13-A trader (the thing a martingale acts on).

1. Reproduce v13-A exactly (run_trader.bat strings): 430 trades, +188.65 %, max DD -5.45 %.
2. Sequence statistics (in CLOSE order, the order a live martingale sees):
   * run lengths of consecutive losses (all trades / per timeframe / per side), how often k = 1..8 happen;
   * P(win | k consecutive losses before) and the mean R of the trade after k losses  -> is there ANY dependence the
     martingale can exploit, or are the trades independent (then a martingale only reshuffles variance)?
   * the deficit ($ and R) after a streak of k and the number of trades needed to recover it under flat sizing;
   * how many trades were OPEN when a loss closed (a martingale on the NEXT order vs on positions already open);
3. What a classic martingale would have done: risk 1 % x 2^k, x1.5^k, x1.25^k, d'Alembert +1 % per loss, on the SAME trade
   sequence with the SAME R outcomes (sequence-only approximation, no re-simulation): equity curve, max DD, max single risk,
   how often the daily 4.5 % rule would have fired  -> the ruin argument in numbers.
4. Drawdown anatomy: the 5 deepest equity drawdowns - start / trough / end, trades inside, streak inside.
5. MAE / bounce diagnostics for the grid (zone-averaging) idea: of the trades that were stopped, how far into the zone did
   price go first (mae_r) and of the winners, how deep did price go before turning (mae_r) -> is there room for a second
   entry deeper in the zone?

Outputs: study_results/v14_diag/{ref.json, trades.csv, streaks.csv, after_k.csv, classic_mart.csv, drawdowns.csv, mae.csv}
    python run_v14_diag.py --csv data/xauusd_m1.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lubot.execution import SymbolSpec  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from v14_common import CSV, EXPECT_V13A, judge, load_year, v13a_config  # noqa: E402

OUT = Path("study_results/v14_diag")


def runs_of_losses(loss: np.ndarray) -> list[int]:
    runs, cur = [], 0
    for v in loss:
        if v:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def streak_table(tr: pd.DataFrame, label: str) -> dict:
    loss = (tr.net < 0).to_numpy()
    runs = runs_of_losses(loss)
    row = {"slice": label, "trades": len(tr), "losses": int(loss.sum()), "loss_%": round(100 * loss.mean(), 1) if len(tr) else np.nan,
           "runs": len(runs), "max_run": max(runs) if runs else 0, "mean_run": round(np.mean(runs), 2) if runs else 0.0}
    for k in range(1, 9):
        row[f"runs>={k}"] = int(sum(r >= k for r in runs))
    # expected max run under independence with the same loss rate
    p = loss.mean() if len(tr) else 0.0
    n = len(tr)
    row["indep_expected_max_run"] = round(np.log(n * (1 - p)) / -np.log(p), 1) if 0 < p < 1 and n > 1 else np.nan
    return row


def after_k(tr: pd.DataFrame) -> pd.DataFrame:
    """P(win | k consecutive losses immediately before, in close order) and mean R after k."""
    net = tr.net.to_numpy()
    r = tr.r_net.to_numpy()
    k_before = np.zeros(len(tr), dtype=int)
    cur = 0
    for i in range(len(tr)):
        k_before[i] = cur
        cur = cur + 1 if net[i] < 0 else 0
    rows = []
    for k in range(0, 7):
        m = k_before == k if k < 6 else k_before >= k
        if m.sum() == 0:
            continue
        rows.append({"k_losses_before": k if k < 6 else "6+", "n": int(m.sum()), "win_%": round(100 * (net[m] > 0).mean(), 1),
                     "mean_R": round(r[m].mean(), 3), "median_R": round(np.median(r[m]), 3), "sum_R": round(r[m].sum(), 2),
                     "sl_%": round(100 * (tr.outcome.to_numpy()[m] == "sl").mean(), 1)})
    return pd.DataFrame(rows)


def classic_martingale(tr: pd.DataFrame, start: float = 10_000.0, base_pct: float = 1.0, daily_rule: float = 4.5,
                       total_rule: float = 9.0) -> pd.DataFrame:
    """Sequence-only approximation: same trades, same r_net, risk of trade i = f(k losses before).  Compounding on equity.
    The daily / total loss rules are checked on the closed-trade equity (approximation: no floating)."""
    r = tr.r_net.to_numpy()
    days = tr.close_time.dt.floor("D").to_numpy()
    schemes = {
        "flat 1%": lambda k: 1.0,
        "x2^k (classic)": lambda k: 2.0 ** k,
        "x2^k cap 3 steps": lambda k: 2.0 ** min(k, 3),
        "x1.5^k": lambda k: 1.5 ** k,
        "x1.5^k cap 3": lambda k: 1.5 ** min(k, 3),
        "x1.25^k": lambda k: 1.25 ** k,
        "dAlembert +1 per loss": lambda k: 1.0 + k,
        "dAlembert +0.5 cap 3": lambda k: 1.0 + 0.5 * min(k, 3),
        "fib(k)": lambda k: [1, 1, 2, 3, 5, 8, 13, 21, 34][min(k, 8)],
        "anti x0.5^k": lambda k: 0.5 ** k,
    }
    rows = []
    for name, f in schemes.items():
        eq = start
        peak = start
        dd = 0.0
        k = 0
        max_risk = 0.0
        day_start = start
        cur_day = None
        daily_hits = 0
        halted_at = ""
        losses_sum = 0.0
        n_traded = 0
        risk_pcts = []
        for i in range(len(r)):
            if days[i] != cur_day:
                cur_day = days[i]
                day_start = eq
            if halted_at:
                break
            if eq <= day_start * (1 - daily_rule / 100):
                # daily rule fired: skip the rest of this day
                continue
            risk_pct = base_pct * f(k)
            risk = eq * risk_pct / 100
            risk_pcts.append(risk_pct)
            max_risk = max(max_risk, risk_pct)
            pnl = risk * r[i]
            eq += pnl
            n_traded += 1
            if pnl < 0:
                losses_sum += pnl
                k += 1
            else:
                k = 0
            peak = max(peak, eq)
            dd = min(dd, eq / peak - 1)
            if eq <= day_start * (1 - daily_rule / 100):
                daily_hits += 1
            if eq <= start * (1 - total_rule / 100):
                halted_at = str(pd.Timestamp(days[i]).date())
        rows.append({"scheme": name, "traded": n_traded, "end_equity": round(eq, 0), "return_%": round(100 * (eq / start - 1), 1),
                     "max_dd_%": round(100 * dd, 2), "gross_loss_$": round(losses_sum, 0), "max_risk_%": round(max_risk, 2),
                     "mean_risk_%": round(np.mean(risk_pcts), 2) if risk_pcts else 0, "daily_rule_hits": daily_hits,
                     "halted_at": halted_at})
    return pd.DataFrame(rows)


def drawdowns(res, top: int = 5) -> pd.DataFrame:
    eq = res.equity.equity
    peak = eq.cummax()
    dd = eq / peak - 1
    tr = res.trades
    rows = []
    in_dd = False
    start = None
    for t, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start = True, t
        elif v == 0 and in_dd:
            seg = dd[start:t]
            trough = seg.idxmin()
            inside = tr[(tr.close_time >= start) & (tr.close_time <= t)]
            loss = (inside.net < 0).to_numpy()
            runs = runs_of_losses(loss)
            rows.append({"start": start, "trough": trough, "end": t, "depth_%": round(100 * seg.min(), 2),
                         "days": round((t - start).total_seconds() / 86400, 1), "trades": len(inside), "losses": int(loss.sum()),
                         "max_streak": max(runs) if runs else 0, "sum_R": round(inside.r_net.sum(), 2),
                         "tfs": ",".join(f"{k}:{v}" for k, v in inside.tf.value_counts().items())})
            in_dd = False
    if in_dd:
        seg = dd[start:]
        inside = tr[tr.close_time >= start]
        rows.append({"start": start, "trough": seg.idxmin(), "end": pd.NaT, "depth_%": round(100 * seg.min(), 2), "days": np.nan,
                     "trades": len(inside), "losses": int((inside.net < 0).sum()), "max_streak": 0, "sum_R": round(inside.r_net.sum(), 2), "tfs": ""})
    return pd.DataFrame(rows).sort_values("depth_%").head(top).reset_index(drop=True)


def mae_table(tr: pd.DataFrame) -> pd.DataFrame:
    """How deep into the zone did price go (mae_r, negative = against) - for the grid / zone-averaging idea."""
    rows = []
    t = tr.copy()
    t["won"] = t.net > 0
    for label, g in [("all", t), ("winners", t[t.won]), ("losers", t[~t.won]), ("stopped (sl)", t[t.outcome == "sl"])]:
        if not len(g):
            continue
        mae = g.mae_r.clip(lower=0)          # stored as a positive magnitude (R against the position)
        rows.append({"slice": label, "n": len(g), "mae_mean_R": round(mae.mean(), 3), "mae_median_R": round(mae.median(), 3),
                     "mae>=0.3R_%": round(100 * (mae >= 0.3).mean(), 1), "mae>=0.5R_%": round(100 * (mae >= 0.5).mean(), 1),
                     "mae>=0.7R_%": round(100 * (mae >= 0.7).mean(), 1), "mfe_mean_R": round(g.mfe_r.mean(), 3)})
    # winners that went deep first: the population a deeper second entry would have improved
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    m1, sel = load_year(a.csv)
    res = PortfolioSimulator(m1, sel, v13a_config(), SymbolSpec()).run()
    s = res.summary()
    got = (s["trades"], s["return_%"], s["max_dd_%"])
    print(f"v13-A replay: {got}  expected {EXPECT_V13A}  IDENTICAL: {got == EXPECT_V13A}")
    assert got == EXPECT_V13A, "parity broken"
    j = judge(res)
    json.dump({"summary": s, "judge": j}, open(OUT / "ref.json", "w"), indent=1, default=str)
    tr = res.trades.sort_values("close_time").reset_index(drop=True)
    tr.to_csv(OUT / "trades.csv", index=False)

    # 2) streaks
    rows = [streak_table(tr, "ALL")]
    for tf, g in tr.groupby("tf"):
        rows.append(streak_table(g.sort_values("close_time"), f"tf={tf}"))
    for sd, g in tr.groupby("side"):
        rows.append(streak_table(g.sort_values("close_time"), f"side={sd}"))
    for rg, g in tr.groupby("regime"):
        rows.append(streak_table(g.sort_values("close_time"), f"regime={rg}"))
    st = pd.DataFrame(rows)
    st.to_csv(OUT / "streaks.csv", index=False)
    print("\n== consecutive-loss runs (close order)")
    print(st.to_string(index=False))

    ak = after_k(tr)
    ak.to_csv(OUT / "after_k.csv", index=False)
    print("\n== the trade AFTER k consecutive losses (all TFs, close order)")
    print(ak.to_string(index=False))
    # per-TF version of after_k (the martingale could be scoped per timeframe)
    per = []
    for tf, g in tr.groupby("tf"):
        x = after_k(g.sort_values("close_time").reset_index(drop=True))
        x.insert(0, "tf", tf)
        per.append(x)
    pd.concat(per).to_csv(OUT / "after_k_by_tf.csv", index=False)


    # where is the trade AFTER a loss still good?  (the martingale gate question)
    net = tr.net.to_numpy(); kb = np.zeros(len(tr), dtype=int); cur = 0
    for i in range(len(tr)):
        kb[i] = cur; cur = cur + 1 if net[i] < 0 else 0
    t2 = tr.assign(k_before=kb, after_loss=kb >= 1,
                   q_bucket=pd.cut(tr.quality, [0, 0.55, 0.60, 0.65, 0.70, 1.0], labels=["<0.55", "0.55-0.60", "0.60-0.65", "0.65-0.70", ">=0.70"]))
    rows = []
    for dim in ("tf", "regime", "confluent", "side", "q_bucket", "kind"):
        for val, g in t2.groupby(dim, observed=True):
            a, b = g[g.after_loss], g[~g.after_loss]
            if len(a) < 5:
                continue
            rows.append({"dim": dim, "value": str(val), "n_after_loss": len(a), "win_after_%": round(100 * (a.net > 0).mean(), 1),
                         "meanR_after": round(a.r_net.mean(), 3), "sumR_after": round(a.r_net.sum(), 2),
                         "n_other": len(b), "win_other_%": round(100 * (b.net > 0).mean(), 1), "meanR_other": round(b.r_net.mean(), 3)})
    gate = pd.DataFrame(rows)
    gate.to_csv(OUT / "after_loss_gates.csv", index=False)
    print("\n== the trade after >=1 loss, by slice (where would a step-up be safe?)")
    print(gate.to_string(index=False))

    # open positions when a loss closed
    closes = tr[tr.net < 0].close_time.to_numpy()
    n_open = []
    for c in closes:
        n_open.append(int(((tr.entry_time.to_numpy() < c) & (tr.close_time.to_numpy() > c)).sum()))
    print(f"\nopen positions at the moment a loss closed: mean {np.mean(n_open):.2f}, 0 open in {100 * (np.array(n_open) == 0).mean():.0f} % of the losses")
    # gap to the next entry after a loss
    gaps = []
    ent = tr.entry_time.sort_values().to_numpy()
    for c in closes:
        nxt = ent[ent > c]
        if len(nxt):
            gaps.append((nxt[0] - c) / np.timedelta64(1, "m"))
    print(f"minutes from a loss to the NEXT fill: median {np.median(gaps):.0f}, mean {np.mean(gaps):.0f}, <60 min in {100 * (np.array(gaps) < 60).mean():.0f} %")

    # 3) classic martingale on the same sequence
    cm = classic_martingale(tr)
    cm.to_csv(OUT / "classic_mart.csv", index=False)
    print("\n== classic martingale schemes on the SAME trade sequence (sequence-only approximation, compounding, 4.5 % / 9 % rules)")
    print(cm.to_string(index=False))

    # 4) drawdowns
    dd = drawdowns(res)
    dd.to_csv(OUT / "drawdowns.csv", index=False)
    print("\n== 5 deepest drawdowns")
    print(dd.to_string(index=False))

    # 5) MAE
    mae = mae_table(tr)
    mae.to_csv(OUT / "mae.csv", index=False)
    print("\n== MAE (how deep into the zone before the outcome) - room for a second, deeper entry?")
    print(mae.to_string(index=False))
    # winners by MAE bucket: the deeper the pullback, the more a second entry would have added
    t = tr.assign(mae_b=pd.cut(tr.mae_r.clip(lower=0), [-0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 1.01, 99], labels=["0-0.1", "0.1-0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", "0.9-1", ">1 (slip)"]))
    g = t.groupby("mae_b", observed=True).agg(n=("net", "size"), win_pct=("net", lambda x: round(100 * (x > 0).mean(), 1)),
                                               mean_R=("r_net", "mean"), sum_R=("r_net", "sum"), sl_pct=("outcome", lambda x: round(100 * (x == "sl").mean(), 1)))
    g.to_csv(OUT / "mae_buckets.csv")
    print("\n== outcome by MAE bucket (R against before the outcome)")
    print(g.round(3).to_string())

    # daily loss anatomy: worst days relative to day-start equity
    d = tr.set_index("close_time").net.resample("1D").sum()
    eqd = res.equity.equity.resample("1D").first().ffill()
    rel = (d / eqd.reindex(d.index).ffill() * 100).dropna()
    worst = rel.nsmallest(8)
    print("\n== worst days (% of day-start equity)")
    print(worst.round(2).to_string())
    pd.DataFrame({"net_$": d.reindex(worst.index), "pct_eq": worst}).to_csv(OUT / "worst_days.csv")


if __name__ == "__main__":
    main()
