#!/usr/bin/env python3
"""v12 step 3 - LEVER GRID on top of the v11-B reference (dedupe_cross_tf=false + M30|H1 quality 0.57).

Reference: full year Sep 2025 -> Sep 2026, 348 trades, +147.9 %, max DD 5.2 %, PF 1.91, win 71.6 %, OOS (Mar-Sep26) +42.0 R / PF 1.73.

Families (every run = full year through the M1 portfolio simulator, judged on the OOS half):
  CF_*   confluence_filter: quality bar for a zone that is ALSO active on another timeframe, per TF and level
  RE_*   reentry_bars: re-arm the same zone after a break-even exit (N bars of the TF), reentry_max 1/2, outcomes
  KR_*   keep_replaced_bars: keep an order whose POI was replaced on its slot for N bars
  F_*    v11 single levers that were neutral-positive (M15 q0.57, M5 cost 0.10/0.12, M10 q0.57) re-checked on top of v11-B
  X_*    combinations of the families' winners (added by --combos once the singles are in)
Resumable: one json per variant in study_results/v12_levers/, summary -> study_results/v12_levers.csv.

    python run_v12_levers.py --csv data/xauusd_m1.csv --workers 2 [--combos] [--stress name1,name2]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_trader import load_selections, spec_override  # noqa: E402
from lubot import load_mt5_csv  # noqa: E402
from lubot.execution import SymbolSpec, TraderConfig  # noqa: E402
from lubot.portfolio_sim import PortfolioSimulator  # noqa: E402
from run_rm_study import KEYS  # noqa: E402
from run_v12_funnel import REF_FLT, REF_T, TFS  # noqa: E402

OUT = Path("study_results/v12_levers")
OOS_SPLIT = "2026-03-01"
M5_RULE = "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose"


def flt(m10=0.60, m15=0.60, m30=0.57, h1=0.57, m5_cost=0.08, m5_q=0.55) -> str:
    m5 = f"M5:max_cost_r={m5_cost};min_quality={m5_q};sessions=asia|london|preny|ny|lclose"
    return f"{m5}/M10:min_quality={m10}/M15:min_quality={m15}/M30:min_quality={m30}/H1:min_quality={h1}"


assert flt() == "M5:max_cost_r=0.08;min_quality=0.55;sessions=asia|london|preny|ny|lclose/M10:min_quality=0.6/M15:min_quality=0.6/M30:min_quality=0.57/H1:min_quality=0.57"


def variants_single() -> dict[str, tuple[str, str]]:
    """name -> (trade_filter, extra trader overrides).  confluence_filter is passed inside the overrides as CF=<filter>
    (the ',' and '=' inside a filter string are escaped by run_one)."""
    v: dict[str, tuple[str, str]] = {"ref": (REF_FLT, "")}
    # --- CF: confluence filter = same as the main filter except the quality bar of the listed TFs
    for q in (0.57, 0.55, 0.52, 0.50):
        v[f"CF_m10_q{q}"] = (REF_FLT, cf(flt(m10=q)))
        v[f"CF_m15_q{q}"] = (REF_FLT, cf(flt(m15=q)))
        v[f"CF_m10m15_q{q}"] = (REF_FLT, cf(flt(m10=q, m15=q)))
        v[f"CF_htf_q{q}"] = (REF_FLT, cf(flt(m10=q, m15=q, m30=min(q, 0.57), h1=min(q, 0.57))))
        v[f"CF_m5_q{q}"] = (REF_FLT, cf(flt(m5_q=q)))
    v["CF_m5_cost0.12"] = (REF_FLT, cf(flt(m5_cost=0.12)))
    v["CF_m5_q0.52_cost0.12"] = (REF_FLT, cf(flt(m5_q=0.52, m5_cost=0.12)))
    v["CF_all_q0.52_cost0.12"] = (REF_FLT, cf(flt(m10=0.52, m15=0.52, m30=0.52, h1=0.52, m5_q=0.52, m5_cost=0.12)))
    v["CF_htf_off"] = (REF_FLT, cf(M5_RULE))                  # confluence: no quality gate at all on the HTFs
    # --- RE: re-entry after a BE exit
    for n in (1, 2, 3, 6, 12):
        v[f"RE_b{n}"] = (REF_FLT, f"reentry_bars={n}")
    v["RE_b3_max2"] = (REF_FLT, "reentry_bars=3,reentry_max=2")
    v["RE_b3_tpbe"] = (REF_FLT, "reentry_bars=3,reentry_outcomes=partial_be")           # only after a partial + BE
    # --- KR: keep replaced orders
    for n in (1, 2, 3, 6):
        v[f"KR_b{n}"] = (REF_FLT, f"keep_replaced_bars={n}")
    # --- stage A2: HTF-only versions (stage A showed the M5 extras lose, the HTF extras win)
    for n in (1, 2, 3, 6):
        v[f"RE_htf_b{n}"] = (REF_FLT, f"reentry_bars={n},reentry_tfs=M10|M15|M30|H1")
        v[f"RE_m10m15_b{n}"] = (REF_FLT, f"reentry_bars={n},reentry_tfs=M10|M15")
    v["RE_m10m15_b2_max2"] = (REF_FLT, "reentry_bars=2,reentry_max=2,reentry_tfs=M10|M15")
    for n in (1, 2, 3, 6):
        v[f"KR_htf_b{n}"] = (REF_FLT, f"keep_replaced_bars={n},keep_replaced_tfs=M10|M15|M30|H1")
        v[f"KR_m10m15_b{n}"] = (REF_FLT, f"keep_replaced_bars={n},keep_replaced_tfs=M10|M15")
    v["KR_m10m15m30_b3"] = (REF_FLT, "keep_replaced_bars=3,keep_replaced_tfs=M10|M15|M30")
    # confluence: M10 + M15 at different bars
    v["CF_m10q0.5_m15q0.52"] = (REF_FLT, cf(flt(m10=0.50, m15=0.52)))
    v["CF_m10q0.52_m15q0.55"] = (REF_FLT, cf(flt(m10=0.52, m15=0.55)))
    # --- F: plain filter relaxations on top of v11-B (re-check)
    v["F_m15_q0.57"] = (flt(m15=0.57), "")
    v["F_m10_q0.57"] = (flt(m10=0.57), "")
    v["F_m5_cost0.10"] = (flt(m5_cost=0.10), "")
    v["F_m5_cost0.12"] = (flt(m5_cost=0.12), "")
    v["F_m30h1_q0.55"] = (flt(m30=0.55, h1=0.55), "")
    return v


def cf(filter_text: str) -> str:
    """Encode a confluence filter inside the override string (',' would split the overrides)."""
    return "CF=" + filter_text.replace(",", "@@")


def decode_overrides(over: str) -> tuple[str, str]:
    """-> (plain override text for TraderConfig.override, confluence filter or '')"""
    plain, conf = [], ""
    for pair in over.split(","):
        if pair.startswith("CF="):
            conf = pair[3:].replace("@@", ",")
        elif pair.strip():
            plain.append(pair)
    return ",".join(plain), conf


def run_one(name: str, flt_text: str, over: str, m1, sel, extra_s: str = "", tag: str = "", out: Path = OUT) -> dict:
    key = f"{name}{('__' + tag) if tag else ''}"
    f = out / f"{key}.json"
    if f.exists():
        try:
            return json.load(open(f))
        except Exception:
            pass
    t0 = time.time()
    plain, conf = decode_overrides(over)
    tcfg = TraderConfig().override(",".join(x for x in (REF_T, plain) if x))
    tcfg.trade_filter = flt_text
    tcfg.confluence_filter = conf
    spec = spec_override(SymbolSpec(), extra_s)
    res = PortfolioSimulator(m1, sel, tcfg, spec).run()
    s = res.summary()
    row = {"key": key, "name": name, "tag": tag, "filter": flt_text, "overrides": over, **{k: s.get(k) for k in KEYS}}
    row.update({"pending_placed": s.get("pending_placed"), "cancelled": s.get("cancelled"), "daily_halts": s.get("daily_halts"),
                "halted": s.get("halted"), "reentries_placed": s.get("reentries_placed"), "reentry_trades": s.get("reentry_trades"),
                "confluent_trades": s.get("confluent_trades")})
    tr = res.trades
    if len(tr):
        tr = tr.assign(month=tr.close_time.dt.strftime("%Y-%m"))
        for lab, part in (("IS", tr[tr.close_time < OOS_SPLIT]), ("OOS", tr[tr.close_time >= OOS_SPLIT])):
            row[f"{lab}_n"] = len(part)
            row[f"{lab}_R"] = round(part.r_net.sum(), 2)
            row[f"{lab}_net_$"] = round(part.net.sum(), 2)
            row[f"{lab}_win_%"] = round(100 * (part.net > 0).mean(), 1) if len(part) else np.nan
            row[f"{lab}_PF"] = round(part[part.net > 0].net.sum() / abs(part[part.net < 0].net.sum()), 3) if (part.net < 0).any() else np.inf
            row[f"{lab}_avg_R"] = round(part.r_net.mean(), 4) if len(part) else np.nan
            row[f"{lab}_sl_%"] = round(100 * (part.outcome == "sl").mean(), 1) if len(part) else np.nan
        eq = res.equity.equity
        row["max_dd_%"] = round(100 * (eq / eq.cummax() - 1).min(), 2)
        row["months_pos"] = int((tr.groupby("month").net.sum() > 0).sum())
        row["months"] = int(tr.month.nunique())
        row["worst_month_$"] = round(tr.groupby("month").net.sum().min(), 2)
        row["worst_day_%"] = round(100 * eq.resample("1D").last().dropna().pct_change().min(), 2)
        day_start = eq.groupby(eq.index.date).transform("first")
        row["worst_intraday_%"] = round(100 * (eq / day_start - 1).min(), 2)
        row["by_tf_n"] = tr.groupby("tf").size().to_dict()
        row["by_tf_R"] = tr.groupby("tf").r_net.sum().round(2).to_dict()
        row["outcomes"] = tr.outcome.value_counts().to_dict()
        row["monthly_$"] = tr.groupby("month").net.sum().round(2).to_dict()
        # the EXTRA population (what the lever adds): confluent / re-entry trades
        ex = tr[(tr.confluent) | (tr.reentry > 0)]
        row["extra_n"] = int(len(ex))
        row["extra_R"] = round(ex.r_net.sum(), 2) if len(ex) else 0.0
        row["extra_win_%"] = round(100 * (ex.net > 0).mean(), 1) if len(ex) else np.nan
        row["extra_OOS_R"] = round(ex[ex.close_time >= OOS_SPLIT].r_net.sum(), 2) if len(ex) else 0.0
        l = (tr.net < 0).astype(int).to_numpy()
        best = cur = 0
        for x in l:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        row["max_consec_losses"] = int(best)
        tr.to_csv(out / f"{key}_trades.csv", index=False)
    res.equity.to_csv(out / f"{key}_equity.csv")
    row["secs"] = round(time.time() - t0, 1)
    tmp = out / f"{key}.json.tmp"
    json.dump(row, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f)
    return row


_G: dict = {}


def _init(csv: str, start: str):
    m1 = load_mt5_csv(csv)[start:]
    sel = pd.concat([load_selections(f"study_results/sel_v10_{tf}.pkl") for tf in TFS],
                    ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    _G["m1"], _G["sel"] = m1, sel


def _job(args):
    name, flt_text, over, extra_s, tag = args
    return run_one(name, flt_text, over, _G["m1"], _G["sel"], extra_s=extra_s, tag=tag)


def summarize(rows: list[dict], ref_name: str = "ref", path: str = "study_results/v12_levers.csv") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    ref = df[df.name == ref_name].iloc[0]
    df["d_trades"] = df.trades - ref.trades
    df["d_ret"] = (df["return_%"] - ref["return_%"]).round(1)
    df["d_dd"] = (df["max_dd_%"] - ref["max_dd_%"]).round(2)
    df["d_pf"] = (df.profit_factor - ref.profit_factor).round(3)
    df["d_win"] = (df["win_%"] - ref["win_%"]).round(1)
    # loss profile maintained (v11 band): DD not deeper than ref + 0.5 pt, PF >= ref - 0.05, win >= ref - 3, worst day >= ref - 0.5
    df["hold_loss"] = (df["max_dd_%"] >= ref["max_dd_%"] - 0.5) & (df.profit_factor >= ref.profit_factor - 0.05) & \
                      (df["win_%"] >= ref["win_%"] - 3.0) & (df["worst_day_%"] >= ref["worst_day_%"] - 0.5)
    # the same band judged on the OOS half only (PF / win / sl) - what we actually trust
    df["hold_oos"] = (df["OOS_PF"] >= ref["OOS_PF"] - 0.05) & (df["OOS_win_%"] >= ref["OOS_win_%"] - 3.0) & \
                     (df["OOS_sl_%"] <= ref["OOS_sl_%"] + 2.0) & (df["max_dd_%"] >= ref["max_dd_%"] - 0.5)
    df["ret_dd"] = (df["return_%"] / df["max_dd_%"].abs()).round(2)
    df = df.sort_values("trades", ascending=False)
    df.to_csv(path, index=False)
    return df


STRESS = {"spread_x2": ("spread_multiplier=2.0", ""), "commission_x2": ("", "commission_per_lot=14"),
          "slip_x3": ("sl_slippage=0.30,market_slippage=0.15", ""), "worst_intrabar": ("intrabar=worst", ""),
          "risk0.5": ("risk_pct=0.5", ""), "risk2": ("risk_pct=2.0", "")}

COLS = ["name", "trades", "d_trades", "return_%", "max_dd_%", "profit_factor", "win_%", "sl_%", "worst_day_%", "IS_R", "OOS_R",
        "OOS_PF", "OOS_win_%", "OOS_sl_%", "extra_n", "extra_R", "extra_OOS_R", "months_pos", "hold_loss", "hold_oos"]


def variants_combos(single_df: pd.DataFrame | None) -> dict[str, tuple[str, str]]:
    """Combine the CF / RE / KR / F winners.  Winners = hold_oos and d_trades > 0 in the single grid (fallback: a fixed list)."""
    cf_opts = ["CF_m10m15_q0.52", "CF_m10m15_q0.5", "CF_m15_q0.52", "CF_m10_q0.5", "CF_m10q0.5_m15q0.52"]
    re_opts = ["RE_m10m15_b1", "RE_m10m15_b2", "RE_htf_b1", "RE_htf_b2", "KR_m10m15_b1", "KR_m10m15_b2", "KR_htf_b1", "KR_htf_b2",
               "KR_m10m15m30_b3"]
    f_opts = ["F_m10_q0.57", "F_m5_cost0.12"]
    # (fixed lists: the picks were made by hand from stage A/A2 - see PROGRESS.md; single_df kept for the signature)
    singles = variants_single()
    v: dict[str, tuple[str, str]] = {}
    for c, r in itertools.product(cf_opts, re_opts + [None]):
        parts = [c] + ([r] if r else [])
        overs = ",".join(singles[p][1] for p in parts if singles[p][1])
        v["X_" + "+".join(parts)] = (REF_FLT, overs)
        for fo in f_opts:
            # filter relaxation + confluence filter must both use the relaxed base
            base_f = singles[fo][0]
            cf_text = decode_overrides(singles[c][1])[1]
            # re-derive: the confluence filter keeps its own quality bars, the base filter changes
            v["X_" + "+".join(parts + [fo])] = (base_f, ",".join([cf(cf_text)] + ([singles[r][1]] if r else [])))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/xauusd_m1.csv")
    ap.add_argument("--from", dest="start", default="2025-09-01")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--only", default="", help="comma list of variant names")
    ap.add_argument("--combos", action="store_true", help="add the combination grid (needs the singles for the picks)")
    ap.add_argument("--stress", default="", help="comma list of variant names to stress")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    v = variants_single()
    if a.combos:
        prev = pd.read_csv("study_results/v12_levers.csv") if Path("study_results/v12_levers.csv").exists() else None
        v.update(variants_combos(prev))
    if a.only:
        v = {k: v[k] for k in a.only.split(",")}
        if "ref" not in v:
            v = {"ref": variants_single()["ref"], **v}
    todo = [(k, f, o, "", "") for k, (f, o) in v.items()]
    if a.stress:
        allv = {**variants_single(), **variants_combos(pd.read_csv("study_results/v12_levers.csv"))}
        for n in a.stress.split(","):
            f, o = allv[n]
            for tag, (et, es) in STRESS.items():
                todo.append((n, f, ",".join(x for x in (o, et) if x), es, tag))
    print(f"{len(todo)} runs, {sum(1 for k, _, _, _, tag in todo if not (OUT / (k + ('__' + tag if tag else '') + '.json')).exists())} to run",
          flush=True)
    rows = []

    def show(r):
        print(f"{r['key']:<40} n {r['trades']:4d} ret {r['return_%']:+7.1f}% DD {r['max_dd_%']:6.2f}% PF {r['profit_factor']:5.2f} "
              f"win {r['win_%']:4.1f} sl {r['sl_%']:4.1f} wd {r.get('worst_day_%', 0):5.2f} OOS {r.get('OOS_R', 0):+6.1f}R/{r.get('OOS_PF', 0):4.2f} "
              f"extra {r.get('extra_n', 0):3d}/{r.get('extra_R', 0):+6.1f}R", flush=True)

    if a.workers > 1:
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.csv, a.start)) as ex:
            for r in ex.map(_job, todo):
                rows.append(r)
                show(r)
    else:
        _init(a.csv, a.start)
        for t in todo:
            r = _job(t)
            rows.append(r)
            show(r)
    base = [r for r in rows if not r["tag"]]
    path = "study_results/v12_levers.csv" if not a.only else "study_results/v12_levers_partial.csv"
    if a.combos:
        path = "study_results/v12_combos.csv"
    df = summarize(base, path=path)
    if a.stress:
        pd.DataFrame([r for r in rows if r["tag"]]).to_csv("study_results/v12_stress.csv", index=False)
    pd.set_option("display.width", 260)
    print("\n=== v12 GRID (sorted by trades) ===\n" + df[COLS].to_string(index=False))


if __name__ == "__main__":
    main()
