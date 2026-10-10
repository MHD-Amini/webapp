#!/usr/bin/env python3
"""v16c step 1 - DIAGNOSIS of the DRAWDOWN of the shipped v16b-A trader (study_results/final_v16b/v16bA_{trades,equity}.csv).

Where does the max drawdown (-5.55 % equity) come from?  The top drawdown episodes of the equity path are cut out and the trades
inside each are profiled (TF, side, kind, regime, confluent, martingale step, risk scale, risk in % of equity, concurrency, clusters,
hold, MAE/MFE); the floating vs realised share of each trough is measured; then a STATIC re-walk of the trade list estimates what
DD-aware levers would have done (risk throttle while in drawdown, loss-streak throttle, day-loss soft cap, open-risk cap, same-side
concurrency cap, week-loss cap) - DD cut vs net given up - before anything is re-simulated.  Every table -> study_results/v16c_diag/*.csv,
summarised in v16c_diag/DIAG.md.

    python3 run_v16c_diag.py            # ~15 s, no CSV needed (trade list + equity curve only)
"""
from __future__ import annotations

import glob
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v14_common import OOS_SPLIT  # noqa: E402
from v16c_common import REF16C, dd_episodes  # noqa: E402

warnings.filterwarnings("ignore")
OUT = "study_results/v16c_diag"
TRADES = "study_results/final_v16b/v16bA_trades.csv"
EQUITY = "study_results/final_v16b/v16bA_equity.csv"
TOP = 5


def agg(d: pd.DataFrame) -> pd.Series:
    return pd.Series({"n": len(d), "sl": int((d.outcome == "sl").sum()),
                      "sl_%": round(100 * (d.outcome == "sl").mean(), 1) if len(d) else np.nan,
                      "net_$": round(d.net.sum()), "loss_$": round(d[d.net < 0].net.sum()),
                      "risk_$": round(d.risk_money.sum()), "avg_risk_%eq": round(d.risk_pct_eq.mean(), 2) if len(d) else np.nan})


def table(t: pd.DataFrame, by, name: str, lines: list, title: str) -> pd.DataFrame:
    keys = [by] if isinstance(by, str) else list(by)
    g = t.groupby([t[k].rename(f"_{k}") for k in keys], observed=True).apply(agg)
    g.index.names = keys
    g.to_csv(f"{OUT}/{name}.csv")
    lines.append(f"\n### {title}\n")
    lines.append(g.to_markdown())
    return g


def asof(series: pd.Series, when: pd.Series) -> np.ndarray:
    """last sample at or before each time (hourly equity samples -> value at an arbitrary minute)."""
    pos = np.searchsorted(series.index.values, when.values.astype("datetime64[ns]"), side="right") - 1
    return series.values[np.clip(pos, 0, len(series) - 1)]


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    t = pd.read_csv(TRADES, parse_dates=["selected_time", "entry_time", "close_time"])
    eq = pd.read_csv(EQUITY, index_col=0, parse_dates=True)
    # equity at the fill (hourly samples, forward-filled) -> the plan's risk in % of equity
    t["eq_at_entry"] = asof(eq.equity, t.entry_time)
    t["risk_pct_eq"] = 100 * t.risk_money / t.eq_at_entry
    t["half"] = np.where(t.close_time >= OOS_SPLIT, "OOS", "IS")
    t["day"] = t.close_time.dt.normalize()
    t["loss"] = t.net < 0
    # concurrency at the fill: open positions (other plans) whose life spans this entry
    same, total = [], []
    for i, r in t.iterrows():
        o = t[(t.entry_time <= r.entry_time) & (t.close_time > r.entry_time) & (t.index != i)]
        total.append(len(o))
        same.append(int((o.side == r.side).sum()))
    t["open_at_fill"] = total
    t["same_side_at_fill"] = same
    # open risk at the fill (sum of the risk $ of the open plans incl. this one) in % of equity
    t["open_risk_%eq"] = [100 * (t[(t.entry_time <= r.entry_time) & (t.close_time > r.entry_time)].risk_money.sum()) / r.eq_at_entry
                          for _, r in t.iterrows()]
    return t, eq


# ------------------------------------------------------------------ static re-walk of the trade list with DD levers
def rewalk(t: pd.DataFrame, rule, start: float = 10_000.0) -> dict:
    """Walk the trades in close order; ``rule(state, trade) -> scale`` (0 = skipped, 1 = unchanged).  The trade's net is scaled
    by ``scale x balance / eq_at_entry`` (the sizing is proportional to equity: compounding is kept).  Returns the closed-balance
    metrics (max DD on the balance path, net, PF, stop rate of the kept trades).  Static: fills / slots / confluence memory are
    assumed unchanged (the simulator decides in step 3)."""
    tt = t.sort_values(["close_time", "entry_time"]).reset_index(drop=True)
    bal, peak, dd_max = start, start, 0.0
    st = {"bal": start, "peak": start, "dd_%": 0.0, "streak": 0, "day_pnl": {}, "week_pnl": {}, "day_start": {}, "week_start": {}}
    nets = []
    for _, r in tt.iterrows():
        st["bal"], st["peak"], st["dd_%"] = bal, peak, 100 * (bal / peak - 1)
        d = r.entry_time.normalize()
        wk = r.entry_time.to_period("W").start_time
        st["day_pnl_now"] = st["day_pnl"].get(d, 0.0)
        st["week_pnl_now"] = st["week_pnl"].get(wk, 0.0)
        st["day_start_bal"] = st["day_start"].setdefault(d, bal)
        st["week_start_bal"] = st["week_start"].setdefault(wk, bal)
        sc = rule(st, r)
        n = r.net * sc * (bal / r.eq_at_entry)
        bal += n
        nets.append(n)
        cd = r.close_time.normalize()
        st["day_pnl"][cd] = st["day_pnl"].get(cd, 0.0) + n
        cw = r.close_time.to_period("W").start_time
        st["week_pnl"][cw] = st["week_pnl"].get(cw, 0.0) + n
        if sc > 0:
            st["streak"] = st["streak"] + 1 if n < 0 else 0
        peak = max(peak, bal)
        dd_max = min(dd_max, 100 * (bal / peak - 1))
    tt["net2"] = np.array(nets)
    kept_m = tt.net2 != 0
    wins, losses = tt.net2[tt.net2 > 0].sum(), -tt.net2[tt.net2 < 0].sum()
    oos = tt[tt.close_time >= OOS_SPLIT]
    return {"trades": int(kept_m.sum()), "net_$": round(bal - start), "OOS_net_$": round(oos.net2.sum()), "bal_dd_%": round(dd_max, 2),
            "PF": round(wins / losses, 3) if losses else np.inf, "sl_%": round(100 * ((tt.outcome == "sl") & kept_m).sum() / max(kept_m.sum(), 1), 1),
            "gross_loss_$": round(-losses)}


def rules() -> dict:
    R = {}
    R["ref"] = lambda st, r: 1.0
    # A. drawdown throttle: while the balance is more than x % below its peak, size x s
    for x in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        for s in (0.75, 0.6, 0.5, 0.25):
            R[f"DDT_{x}_x{s}"] = (lambda x=x, s=s: (lambda st, r: s if st["dd_%"] < -x else 1.0))()
    # A2. graded throttle: size x (1 - dd/x) floored at s (a linear ramp instead of a step)
    for x in (4.0, 6.0):
        for s in (0.5, 0.25):
            R[f"DDR_{x}_f{s}"] = (lambda x=x, s=s: (lambda st, r: max(s, 1.0 + st["dd_%"] / x)))()
    # B. loss-streak throttle: after k consecutive losing closes, size x s until a winner
    for k in (2, 3):
        for s in (0.5, 0.25):
            R[f"STK_{k}_x{s}"] = (lambda k=k, s=s: (lambda st, r: s if st["streak"] >= k else 1.0))()
    # C. day-loss soft cap: once the day's realised P&L is below -x % of the day-start balance, no new fills that day
    for x in (1.0, 1.5, 2.0, 2.5):
        R[f"DAY_{x}"] = (lambda x=x: (lambda st, r: 0.0 if st["day_pnl_now"] < -x / 100 * st["day_start_bal"] else 1.0))()
        R[f"DAY_{x}_x0.5"] = (lambda x=x: (lambda st, r: 0.5 if st["day_pnl_now"] < -x / 100 * st["day_start_bal"] else 1.0))()
    # D. week-loss soft cap
    for x in (2.0, 3.0):
        R[f"WEEK_{x}"] = (lambda x=x: (lambda st, r: 0.0 if st["week_pnl_now"] < -x / 100 * st["week_start_bal"] else 1.0))()
    # E. same-side concurrency cap: skip a fill when n same-side plans are already open
    for n in (1, 2):
        R[f"SAME_{n}"] = (lambda n=n: (lambda st, r: 0.0 if r.same_side_at_fill >= n else 1.0))()
        R[f"SAME_{n}_x0.5"] = (lambda n=n: (lambda st, r: 0.5 if r.same_side_at_fill >= n else 1.0))()
    # F. open-risk cap: skip when the open risk (this plan included) exceeds x % of equity
    for x in (2.0, 2.5, 3.0):
        R[f"RISK_{x}"] = (lambda x=x: (lambda st, r: 0.0 if r["open_risk_%eq"] > x else 1.0))()
        # F2. ... or scale the new plan so that the open risk fits under the cap
        R[f"RISK_{x}_fit"] = (lambda x=x: (lambda st, r: min(1.0, max(0.0, (x - (r["open_risk_%eq"] - r.risk_pct_eq)) / r.risk_pct_eq))
                                            if r["open_risk_%eq"] > x else 1.0))()
    # G. the max-risk cap per plan: a single plan never risks more than x % of equity
    for x in (1.0, 1.25, 1.5):
        R[f"CAP_{x}"] = (lambda x=x: (lambda st, r: min(1.0, x / r.risk_pct_eq) if r.risk_pct_eq > x else 1.0))()
    # H. combos of the two families that act on different episodes (realised throttle + floating cap)
    for x, s in ((3.0, 0.5), (3.0, 0.75), (2.5, 0.75), (2.0, 0.75)):
        for c in (2.5, 3.0):
            R[f"C_DDT_{x}_x{s}+RISK_{c}_fit"] = (lambda x=x, s=s, c=c: (lambda st, r: (s if st["dd_%"] < -x else 1.0) * (
                min(1.0, max(0.0, (c - (r["open_risk_%eq"] - r.risk_pct_eq)) / r.risk_pct_eq)) if r["open_risk_%eq"] > c else 1.0)))()
    return R


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    t, eq = load()
    t.to_csv(f"{OUT}/trades_enriched.csv", index=False)
    L = [f"# v16c diagnosis - the drawdown of v16b-A ({len(t)} trades, net {t.net.sum():.0f} $, max DD {REF16C['max_dd_%']} % eq)\n"]
    # ---- 1. episodes
    eps = dd_episodes(eq.equity, TOP)
    bal_eps = dd_episodes(eq.balance, TOP)
    rows = []
    for i, e in enumerate(eps):
        w = t[(t.close_time >= e["start"]) & (t.close_time <= e["trough"])]
        opened = t[(t.entry_time >= e["start"]) & (t.entry_time <= e["trough"])]
        # the trough split: realised (balance) vs floating (equity - balance) at the trough minute
        tr_idx = eq.index.get_indexer([e["trough"]], method="nearest")[0]
        peak_eq = eq.equity[: e["start"]].max()
        bal_at = eq.balance.iloc[tr_idx]
        eq_at = eq.equity.iloc[tr_idx]
        op = t[(t.entry_time <= e["trough"]) & (t.close_time > e["trough"])]
        rows.append({"ep": i + 1, "start": e["start"], "trough": e["trough"], "end": e["end"], "depth_%": e["depth_%"], "days": e["days"],
                     "peak_eq": round(peak_eq), "trough_eq": round(eq_at), "realised_%": round(100 * (bal_at / peak_eq - 1), 2),
                     "floating_%": round(100 * (eq_at - bal_at) / peak_eq, 2), "open_at_trough": len(op),
                     "open_risk_at_trough_%": round(100 * op.risk_money.sum() / eq_at, 2), "open_final_net_$": round(op.net.sum()),
                     "closed_n": len(w), "closed_sl": int((w.outcome == "sl").sum()),
                     "closed_net_$": round(w.net.sum()), "closed_loss_$": round(w[w.net < 0].net.sum()), "closed_win_$": round(w[w.net > 0].net.sum()),
                     "opened_n": len(opened), "avg_risk_%eq": round(w.risk_pct_eq.mean(), 2) if len(w) else np.nan,
                     "max_risk_%eq": round(w.risk_pct_eq.max(), 2) if len(w) else np.nan,
                     "sells_n": int((w.side == "sell").sum()), "sells_loss_$": round(w[(w.side == "sell") & (w.net < 0)].net.sum()),
                     "mart_up_n": int((w.mart_step > 0).sum()), "mart_up_loss_$": round(w[(w.mart_step > 0) & (w.net < 0)].net.sum()),
                     "confluent_n": int(w.confluent.sum()), "confluent_loss_$": round(w[w.confluent & (w.net < 0)].net.sum()),
                     "max_same_side": int(w.same_side_at_fill.max()) if len(w) else 0,
                     "max_open_risk_%eq": round(w["open_risk_%eq"].max(), 2) if len(w) else np.nan,
                     "days_with_2+_sl": int((w[w.outcome == "sl"].groupby("day").size() >= 2).sum())})
    ep = pd.DataFrame(rows)
    ep.to_csv(f"{OUT}/episodes.csv", index=False)
    L.append("\n## 1. The drawdown episodes (equity path, hourly samples)\n")
    L.append(ep.drop(columns=["end"]).to_markdown(index=False))
    L.append("\nBalance-path (closed trades only) episodes: " + "; ".join(f"{b['depth_%']} % from {str(b['start'])[:10]}" for b in bal_eps))
    # ---- 2. the trades of each top-3 episode
    for i, e in enumerate(eps[:3]):
        w = t[(t.close_time >= e["start"]) & (t.close_time <= e["trough"])].sort_values("close_time")
        cols = ["tf", "side", "kind", "quality", "entry_time", "close_time", "hold_min", "regime", "confluent", "mart_step", "risk_scale",
                "risk_money", "risk_pct_eq", "open_at_fill", "same_side_at_fill", "open_risk_%eq", "net", "r_net", "outcome", "mfe_r", "mae_r"]
        w[cols].to_csv(f"{OUT}/episode{i + 1}_trades.csv", index=False)
        L.append(f"\n## 2.{i + 1} Episode {i + 1}: {e['depth_%']} % from {e['start']} to the trough {e['trough']} ({e['days']} days)\n")
        L.append(w[cols].round(2).to_markdown(index=False))
        op = t[(t.entry_time <= e["trough"]) & (t.close_time > e["trough"])]
        if len(op):
            L.append(f"\nopen AT the trough (floating part):\n" + op[cols].round(2).to_markdown(index=False))
        for by, nm in (("side", "side"), ("tf", "tf"), ("regime", "regime"), ("mart_step", "mart_step"), ("confluent", "confluent")):
            g = w.groupby(by).apply(agg)
            L.append(f"\nby {nm}:\n" + g.to_markdown())
    # ---- 3. all losers: where are they relative to the running DD?  (does the DD deepen through many small or few big losses)
    tt = t.sort_values("close_time").reset_index(drop=True)
    before = tt.close_time - pd.Timedelta(minutes=1)
    eq_before = asof(eq.equity, before)
    peak_before = asof(eq.equity.cummax(), before)
    tt["dd_before_%"] = 100 * (eq_before / peak_before - 1)
    tt["dd_band"] = pd.cut(tt["dd_before_%"], [-10, -4, -3, -2, -1, -0.001, 0.001], labels=["<-4", "-4..-3", "-3..-2", "-2..-1", "-1..0", "at peak"])
    table(tt, "dd_band", "by_dd_band", L, "3. Trades by the drawdown the account was in when they closed (closing -> realised path)")
    L.append("\nIf the trades closed while already > 2 % under water lose money, a throttle in drawdown saves $ AND depth; if they earn, it costs recovery.")
    table(tt, ["dd_band", "side"], "by_dd_band_side", L, "3b. ... by side")
    table(tt, ["dd_band", "regime"], "by_dd_band_regime", L, "3c. ... by regime")
    # ---- 4. loss streaks and the trade after k losses
    streak, pl = 0, []
    for _, r in tt.iterrows():
        pl.append(streak)
        streak = streak + 1 if r.net < 0 else 0
    tt["prev_losses"] = np.minimum(pl, 4)
    table(tt, "prev_losses", "by_prev_losses", L, "4. Trades by the number of consecutive losing closes before them (account-wide)")
    # ---- 5. sizing: risk % of equity (the martingale and the confluence x1.25 add up) and the open risk at the fill
    tt["risk_band"] = pd.cut(tt.risk_pct_eq, [0, 0.5, 0.9, 1.1, 1.4, 2.0, 5.0])
    table(tt, "risk_band", "by_risk_band", L, "5. Trades by the plan's risk in % of equity at the fill")
    tt["open_risk_band"] = pd.cut(tt["open_risk_%eq"], [0, 1, 2, 3, 4, 10])
    table(tt, "open_risk_band", "by_open_risk", L, "5b. Trades by the TOTAL open risk (% eq, this plan included) at the fill")
    table(tt, "same_side_at_fill", "by_same_side", L, "5c. Trades by the number of same-side plans already open at the fill")
    # ---- 6. days: the realised day P&L distribution and the day-loss soft cap potential
    day = tt.groupby("day").agg(n=("net", "size"), net=("net", "sum"), sl=("loss", "sum")).sort_values("net")
    day.to_csv(f"{OUT}/days.csv")
    L.append("\n### 6. The 12 worst days (realised)\n" + day.head(12).round(0).to_markdown())
    rows = []
    for x in (0.5, 1.0, 1.5, 2.0):
        after, n_after = 0.0, 0
        for d, g in tt.groupby("day"):
            g = g.sort_values("close_time")
            cum = g.net.cumsum().shift(1).fillna(0.0)
            eqd = g.eq_at_entry.iloc[0]
            m = cum < -x / 100 * eqd
            after += g.net[m].sum()
            n_after += int(m.sum())
        rows.append({"x_%": x, "trades_after": n_after, "net_after_$": round(after)})
    da = pd.DataFrame(rows)
    da.to_csv(f"{OUT}/day_soft_cap_static.csv", index=False)
    L.append("\n### 6b. Trades closed after the day was already down x % (static, by close order)\n" + da.to_markdown(index=False))
    # ---- 7. static re-walk with the lever rules
    res = []
    for name, rule in rules().items():
        r = rewalk(t, rule)
        r["name"] = name
        res.append(r)
    rw = pd.DataFrame(res).set_index("name")
    ref = rw.loc["ref"]
    rw["d_dd_pt"] = (rw["bal_dd_%"] - ref["bal_dd_%"]).round(2)
    rw["net_%ref"] = (100 * rw["net_$"] / ref["net_$"]).round(1)
    rw["OOS_%ref"] = (100 * rw["OOS_net_$"] / ref["OOS_net_$"]).round(1)
    rw = rw.sort_values(["d_dd_pt", "net_$"], ascending=[False, False])
    rw.to_csv(f"{OUT}/static_levers.csv")
    L.append("\n## 7. STATIC re-walk of the trade list with DD levers (closed-balance path; sizing follows the re-walked equity;"
             " fills / slots unchanged)\n")
    L.append(f"ref balance-path DD {ref['bal_dd_%']} % (the equity-path DD is {REF16C['max_dd_%']} %: floating adds the rest).  "
             "d_dd_pt > 0 = shallower.  Candidates = shallower DD with net >= 97 % of ref.\n")
    L.append(rw.to_markdown())
    cand = rw[(rw.d_dd_pt >= 0.2) & (rw["net_%ref"] >= 97) & (rw["OOS_%ref"] >= 97)]
    L.append("\n### 7b. Static candidates (DD shallower by >= 0.2 pt, net and OOS net >= 97 %)\n")
    L.append(cand.to_markdown() if len(cand) else "none")
    with open(f"{OUT}/DIAG.md", "w") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L[:3]))
    print(ep.drop(columns=["end"]).to_string(index=False))
    print(rw.to_string())
    print(f"\nwritten: {OUT}/DIAG.md + {len(glob.glob(OUT + '/*.csv'))} csv")


if __name__ == "__main__":
    main()
