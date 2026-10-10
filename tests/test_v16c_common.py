"""v16c - the frozen v16b-A strings in v16c_common equal the bat (the reference of the drawdown study), the reference numbers equal
final_v16b/v16bA_summary.json, and judge16c asks the four v16c questions correctly.  No CSV needed."""
import dataclasses
import json

import pandas as pd

from lubot.execution import TraderConfig
from tests.test_bat_v16 import _bat_config
from v16c_common import DD_IMPROVE_PT, EXPECT_V16B, REF16C, dd_episodes, judge16c, v16b_config


def test_v16b_config_equals_the_bat():
    t, tfs = _bat_config()
    s = v16b_config()
    diffs = {f.name: (getattr(t, f.name), getattr(s, f.name)) for f in dataclasses.fields(TraderConfig)
             if getattr(t, f.name) != getattr(s, f.name)}
    assert set(diffs) <= {"timeframes"}, diffs        # the live bot takes --timeframes separately
    assert tuple(s.timeframes) == tfs == ("M5", "M10", "M15", "M20", "M30", "H1")
    assert s.min_fill_age_min == 2 and s.regime_side_scale == "range:sell:0.5"


def test_reference_equals_final_v16b_summary():
    s = json.load(open("study_results/final_v16b/v16bA_summary.json"))
    for k, v in REF16C.items():
        assert abs(float(s[k]) - float(v)) < 1e-6, (k, s[k], v)
    assert (s["trades"], s["return_%"], s["max_dd_%"]) == EXPECT_V16B


def test_dd_episodes_finds_the_deepest_first():
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    eq = pd.Series([100, 110, 100, 120, 90, 130, 125, 140], index=idx, dtype=float)
    eps = dd_episodes(eq, 3)
    assert len(eps) == 3
    assert eps[0]["depth_%"] == -25.0 and eps[0]["start"] == idx[4] and eps[0]["end"] == idx[5] and eps[0]["days"] == 1.0
    assert eps[1]["depth_%"] == round(100 * (100 / 110 - 1), 2)
    assert eps[2]["depth_%"] == round(100 * (125 / 130 - 1), 2)


class _Res:
    """a fake simulator result built from the shipped v16b-A trade list + equity (so judge16c runs without a sim)."""
    def __init__(self, scale_eq=1.0):
        self.trades = pd.read_csv("study_results/final_v16b/v16bA_trades.csv", parse_dates=["selected_time", "entry_time", "close_time"])
        eq = pd.read_csv("study_results/final_v16b/v16bA_equity.csv", index_col=0, parse_dates=True)
        self.equity = eq
        self._s = json.load(open("study_results/final_v16b/v16bA_summary.json"))

    def summary(self):
        return dict(self._s)


def test_judge16c_on_the_reference_itself():
    j = judge16c(_Res())
    # the reference against itself: DD not better by the band -> less_dd False; everything else held -> score 3
    assert j["trades"] == 446 and abs(j["net_$"] - 33831.3) < 0.01 and j["max_dd_%"] == -5.55
    assert j["less_dd"] is False and j["hold_profit"] and j["hold_loss"] and j["hold_oos"] and j["score"] == 3
    assert j["d_dd_pt"] == 0.0 and j["dd1_%"] == -5.55 and j["dd1_start"] == "2026-08-06" and j["dd2_%"] == -5.09 and j["dd3_%"] == -4.68
    assert DD_IMPROVE_PT == 0.25
