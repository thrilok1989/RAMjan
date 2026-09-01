"""Priority 1 — premium behaviour visible on the CALL/PUT charts.

The trader should be able to glance at an option panel and know whether the
premium is still being accumulated, without reading a badge. Two renderings
carry that, and both are drawings of `indicators/order_flow.py` — the single
owner — never a second computation of the split.

What these tests mostly guard is the line between rendering and computing.
"""

import pandas as pd
import pytest

from mios_v5.ui import terminal_chart as TC


def _frame(closes, volumes=None, highs=None, lows=None):
    n = len(closes)
    vol = volumes if volumes is not None else [1000] * n
    hi = highs if highs is not None else [c + 2 for c in closes]
    lo = lows if lows is not None else [c - 2 for c in closes]
    return pd.DataFrame({
        "datetime": pd.date_range("2026-07-29 09:15", periods=n, freq="1min"),
        "open": closes, "high": hi, "low": lo, "close": closes, "volume": vol})


def _buying(n=20):
    """Closes pinned near each bar's high — CLV buy fraction near 1."""
    closes = [100 + i for i in range(n)]
    return _frame(closes, highs=[c + 0.2 for c in closes],
                  lows=[c - 5 for c in closes])


def _selling(n=20):
    closes = [100 - i for i in range(n)]
    return _frame(closes, highs=[c + 5 for c in closes],
                  lows=[c - 0.2 for c in closes])


# ── the parse reads the owner, and only the owner ───────────────────────

def test_ohlc_carries_the_owners_delta_and_cvd():
    p = TC._ohlc(_buying())
    assert p["delta"] is not None and p["cvd"] is not None
    assert len(list(p["delta"])) == 20


def test_the_flow_views_match_the_owner_exactly():
    """Not 'close enough' — the panel must render the owner's own numbers."""
    from indicators import order_flow as _of
    df = _buying()
    theirs = _of.all_views(df)
    ours = TC._flow_views(df)
    assert list(ours["delta"]) == list(theirs["delta"])
    assert list(ours["cvd"]) == list(theirs["cum_delta"])


def test_a_frame_without_volume_yields_no_flow_at_all():
    """UNKNOWN, not balanced. Colouring an unmeasured bar green would assert
    a split nobody took (principle 9)."""
    df = _buying().drop(columns=["volume"])
    assert TC._flow_views(df) == {}
    assert TC._ohlc(df).get("delta") is None


def test_flow_views_never_raise_on_junk():
    for bad in (None, pd.DataFrame(), _buying().drop(columns=["high"])):
        assert isinstance(TC._flow_views(bad), dict)


def test_the_chart_module_never_computes_a_buy_fraction():
    """Principle 2: the split has exactly one implementation, and it is not
    in a render module."""
    import inspect
    src = inspect.getsource(TC)
    for banned in ("clip(0, 1)", "fillna(0.5)", "(c - l) / rng"):
        assert banned not in src, banned


# ── bar colours ─────────────────────────────────────────────────────────

def test_buy_dominant_bars_are_green_and_sell_dominant_red():
    buy = TC.flow_colours(TC._ohlc(_buying())["delta"], 20)
    sell = TC.flow_colours(TC._ohlc(_selling())["delta"], 20)
    assert buy.count(TC.FLOW_BUY) > 15
    assert sell.count(TC.FLOW_SELL) > 15


def test_colours_are_one_per_bar_even_when_the_series_is_short():
    cols = TC.flow_colours([1.0, -1.0], 5)
    assert len(cols) == 5
    assert cols[2:] == [TC.FLOW_FLAT] * 3      # unmeasured, not assumed


def test_no_delta_means_no_colours_rather_than_all_grey():
    """`None` lets the caller fall back to the plain overlay; an all-grey list
    would be a flow read that was never taken."""
    assert TC.flow_colours(None, 5) is None
    assert TC.flow_colours([], 5) is None


def test_a_zero_delta_bar_is_grey_not_green():
    assert TC.flow_colours([0.0], 1) == [TC.FLOW_FLAT]


def test_flow_tints_are_softer_than_the_candle_colours():
    """The candles answer where price went; the bars answer who was buying.
    The first question must stay the louder one."""
    for tint in (TC.FLOW_BUY, TC.FLOW_SELL):
        assert tint.startswith("rgba(")
        assert float(tint.rsplit(",", 1)[1].rstrip(")")) <= 0.5


# ── the CVD line ────────────────────────────────────────────────────────

def test_cvd_line_rises_while_buyers_are_adding():
    p = TC._ohlc(_buying())
    y = TC.cvd_line(p["cvd"], p["low"], p["high"])
    assert y is not None and y[-1] > y[0]


def test_cvd_line_falls_when_buyers_have_stopped():
    p = TC._ohlc(_selling())
    y = TC.cvd_line(p["cvd"], p["low"], p["high"])
    assert y is not None and y[-1] < y[0]


def test_cvd_line_stays_inside_the_candle_extent():
    """It must not touch autorange — the same discipline volume_bars uses, and
    the reason a mis-scaled overlay once flattened every panel."""
    p = TC._ohlc(_buying())
    y = [v for v in TC.cvd_line(p["cvd"], p["low"], p["high"]) if v is not None]
    lo = min(float(v) for v in p["low"])
    hi = max(float(v) for v in p["high"])
    assert min(y) >= lo - 1e-9
    assert max(y) <= hi + 1e-9


def test_cvd_line_is_none_when_it_cannot_be_drawn():
    for cvd in (None, [], [1.0], [5.0, 5.0, 5.0]):     # flat span → no shape
        assert TC.cvd_line(cvd, [1, 2], [3, 4]) is None


def test_cvd_line_survives_gaps_from_the_master_timeline():
    """A minute the leg did not trade is NaN after `align`; it must stay a gap
    rather than collapsing the line to the floor."""
    p = TC._ohlc(_buying())
    cvd = list(p["cvd"])
    cvd[5] = float("nan")
    y = TC.cvd_line(cvd, p["low"], p["high"])
    assert y is not None and y[5] is None


# ── it survives the whole figure build ──────────────────────────────────

def test_the_terminal_chart_draws_with_flow_on_the_option_panels():
    fig, notes = TC.terminal_chart(_buying(), _buying(), _selling())
    assert not notes
    colours = [t.marker.color for t in fig.data if t.type == "bar"]
    assert any(isinstance(c, (list, tuple)) for c in colours), \
        "at least one panel's volume bars are flow-coloured"
    assert any(getattr(t, "name", "") == "CVD" for t in fig.data)


def test_a_panel_without_volume_still_draws():
    fig, notes = TC.terminal_chart(_buying(),
                                   _buying().drop(columns=["volume"]),
                                   _selling())
    assert not notes


def test_align_carries_delta_and_cvd_onto_the_master_timeline():
    p = TC._ohlc(_buying())
    timeline = list(p["x"])[:10]
    out = TC.align(p, timeline)
    assert len(list(out["delta"])) == 10
    assert len(list(out["cvd"])) == 10


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"premium flow tests passed ({len(fns)})")
