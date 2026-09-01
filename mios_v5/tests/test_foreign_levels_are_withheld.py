"""A bad bar must not define the price axis, and one index's levels must not
be drawn on another's chart.

Two separate faults, both surfaced by the SENSEX panel.

**The axis.** `price_range` fits the y-axis to the bars on screen. It tolerated
NaN but not zero — and a gap in the feed arrives as zero, not NaN. A single
`low = 0` against SENSEX at ~81,000 stretched the range to roughly
[-4,860, 85,865], so the axis read from 0 upward and the candles collapsed into
a thread across the top of the panel. NIFTY never showed it because its feed
does not print those bars.

**The levels.** Support/resistance, VWAP, POC, the dealer levels and the HTF
lines are computed off the NIFTY chain — those engines are deliberately
NIFTY-only — so on another index they mark prices it can never trade. This is
the rule `_panel_profile` already states for premium legs. It is a correctness
fault rather than the cause of the thin line: the axis is fitted to the candles
alone, so the lines were simply drawn off-screen.
"""

from __future__ import annotations

import pandas as pd

from mios_v5.ui.dashboard_v6 import LEVELS_INDEX, levels_apply_to
from mios_v5.ui.terminal_chart import price_range, terminal_charts_split


NIFTY_LEVELS = {
    "support": 24300.0, "resistance": 24600.0, "vwap": 24450.0,
    "poc": 24400.0, "vah": 24550.0, "val": 24350.0,
}


def _frame(base: float, n: int = 40):
    """A tight intraday series — high/low span 10 points around `base`."""
    idx = pd.date_range("2026-07-29 09:15", periods=n, freq="1min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({
        "datetime": idx, "open": base, "high": base + 5.0,
        "low": base - 5.0, "close": base + 1.0, "volume": 1000})


def _y_range(fig):
    return (fig.layout.to_plotly_json().get("yaxis") or {}).get("range")


def _y_span(fig) -> float:
    rng = _y_range(fig)
    assert rng, "the index panel should carry an explicit y range"
    return abs(float(rng[1]) - float(rng[0]))


# ── a zero price is not a trade ────────────────────────────────────────

def test_a_zero_low_does_not_define_the_axis():
    """The reported bug: one dead bar and the whole series goes flat."""
    f = _frame(81000)
    f.loc[5, "low"] = 0.0

    figs, _ = terminal_charts_split(f, _frame(120), _frame(90), {},
                                    index_label="SENSEX")
    lo, hi = _y_range(figs["NIFTY"])
    assert lo > 80_000, f"axis floor dragged to {lo} by the zero bar"
    assert _y_span(figs["NIFTY"]) < 100


def test_a_zero_high_does_not_define_the_axis():
    f = _frame(81000)
    f.loc[7, "high"] = 0.0

    figs, _ = terminal_charts_split(f, _frame(120), _frame(90), {},
                                    index_label="SENSEX")
    assert _y_span(figs["NIFTY"]) < 100


def test_negative_prices_are_ignored_too():
    assert price_range([-5.0, 100.0, 102.0], [-5.0, 101.0, 103.0]) == \
        price_range([None, 100.0, 102.0], [None, 101.0, 103.0])


def test_nan_is_still_tolerated():
    """NaN already worked; the fix must not regress it."""
    f = _frame(81000)
    f.loc[5, ["low", "high"]] = float("nan")

    figs, _ = terminal_charts_split(f, _frame(120), _frame(90), {},
                                    index_label="SENSEX")
    assert _y_span(figs["NIFTY"]) < 100


def test_an_all_zero_series_falls_back_to_autorange():
    """Nothing real to fit, so pin nothing rather than a bogus range."""
    assert price_range([0, 0, 0], [0, 0, 0]) is None


def test_the_window_filter_still_lines_up_with_its_timestamps():
    """Prices are blanked in place, never dropped — the window filter zips
    them against `x` by index, so removing elements would misalign every bar
    with its timestamp."""
    got = price_range([0, 100.0, 102.0], [0, 101.0, 103.0],
                      x=[1, 2, 3], window=[2, 3])
    assert got is not None
    lo, hi = got
    assert 99.0 < lo < 100.5 and 102.5 < hi < 104.0, got


def test_a_clean_series_is_unchanged():
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    index_label="NIFTY")
    lo, hi = _y_range(figs["NIFTY"])
    assert 24_390 < lo < 24_400 and 24_400 < hi < 24_410


# ── levels belong to the index they were computed from ─────────────────

def test_levels_belong_to_nifty_only():
    assert LEVELS_INDEX == "NIFTY"
    assert levels_apply_to("NIFTY")
    assert not levels_apply_to("SENSEX")


def test_predicate_is_case_insensitive_and_defaults_safely():
    assert levels_apply_to("nifty")
    assert levels_apply_to(None)      # an unstamped frame is treated as NIFTY
    assert not levels_apply_to("sensex")


def test_nifty_keeps_its_levels():
    """Withholding them elsewhere must not cost NIFTY the lines it should have."""
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90),
                                    NIFTY_LEVELS, index_label="NIFTY")
    drawn = [s for s in (figs["NIFTY"].layout.shapes or ())
             if getattr(s, "y0", None) is not None]
    assert drawn, "NIFTY should still get its horizontal levels"
