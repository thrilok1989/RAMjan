"""Where the terminal's level labels land, and whether they land at all.

Two defects, both invisible except by looking at the rendered figure.

**Order.** `add_hline`/`add_hrect` with `row=`/`col=` are silently dropped by
Plotly when that subplot holds no trace yet — no error, no warning, the shape
never reaches the figure. The profile overlay ran *before* the candles, so
every panel's POC, VAH and VAL line and every liquidity band was discarded on
the way in. Three profiles computed every cycle, drawn nowhere.

**Side.** `annotation_position="right"` means *outside the panel*: it resolves
to `x=1, xanchor="left"`, so the text starts at the right edge and continues
past it. The two option panels are the rightmost column against an 8px figure
margin, so a right-side label there is cut off.

Neither is catchable by reading the source, so these tests read the figure
Plotly actually produced.
"""

import json

import pandas as pd
import pytest

from mios_v5.ui.terminal_chart import LEG_COL, terminal_chart

#: subplot axis reference → the panel a human calls it
PANEL = {"x domain": "NIFTY", "x2 domain": "CALL", "x3 domain": "PUT"}


def _frame(closes, base):
    return pd.DataFrame({
        "datetime": pd.date_range("2026-08-07 09:15", periods=len(closes),
                                  freq="min"),
        "open": [base] * len(closes), "high": [base * 1.1] * len(closes),
        "low": [base * 0.9] * len(closes), "close": closes,
        "volume": [100] * len(closes)})


def _profile(poc, vah, val, lo, hi):
    return {"poc_price": poc, "value_area_high": vah, "value_area_low": val,
            "rows": [{"bin_low": lo, "bin_high": hi, "ratio": 1.0,
                      "node_type": "HIGH", "sentiment": "BULL"}]}


@pytest.fixture
def figure():
    nifty = _frame([24500, 24520, 24533, 24540, 24533, 24545], 24500)
    call = _frame([60, 70, 76, 80, 76, 82], 70)
    put = _frame([140, 130, 119, 110, 119, 108], 125)
    fig, _ = terminal_chart(
        nifty, call, put,
        {"war_zone": 24533},
        call_levels={"support": 70.0, "vwap": 74.0},
        put_levels={"resistance": 130.0},
        nifty_profile=_profile(24533, 24545, 24500, 24500, 24545),
        call_profile=_profile(76.0, 82.0, 60.0, 60.0, 82.0),
        put_profile=_profile(119.5, 140.0, 108.0, 108.0, 140.0))
    return json.loads(fig.to_json())


def _labels(figure, panel):
    ref = next(k for k, v in PANEL.items() if v == panel)
    return {a["text"]: a for a in figure["layout"].get("annotations", [])
            if a.get("xref") == ref and a.get("text")}


def _side(annotation):
    """Where this label actually sits, in the terms the reader sees."""
    x, anchor = annotation.get("x"), annotation.get("xanchor")
    if x == 1:
        return "right-inside" if anchor == "right" else "right-overhang"
    return "left" if x == 0 else f"x={x}"


# ══════════════════════════════════════════════════════════════════════
#  the profile is drawn at all
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("panel", ["NIFTY", "CALL", "PUT"])
def test_every_panel_draws_its_own_poc_vah_and_val(figure, panel):
    """⭐ These were computed every cycle and reached the figure on none.

    Plotly drops a `row=`/`col=` shape added before that subplot has a trace,
    so drawing the profile first — which the comment said was for layering —
    discarded it instead.
    """
    got = _labels(figure, panel)
    for name in ("POC", "VAH", "VAL"):
        assert name in got, f"{panel} lost its {name} line"


def test_the_liquidity_bands_reach_the_figure(figure):
    """The other half of the same defect: `add_hrect` is dropped identically."""
    below = [s for s in figure["layout"].get("shapes", [])
             if s.get("layer") == "below"]
    assert below, "no liquidity bands were drawn on any panel"
    assert {s.get("xref") for s in below} >= {"x domain", "x2 domain",
                                              "x3 domain"}


def test_the_bands_still_sit_under_the_candles(figure):
    """Moving the profile after `_add_series` must not put the bands on top of
    the price. `layer="below"` is what controls that — not call order."""
    for shape in figure["layout"].get("shapes", []):
        if shape.get("type") == "rect" and shape.get("fillcolor"):
            assert shape.get("layer") == "below"


# ══════════════════════════════════════════════════════════════════════
#  which side the labels land on
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("panel,label", [
    ("CALL", "Support ₹70.00"), ("CALL", "VWAP ₹74.00"),
    ("PUT", "Resistance ₹130.00"),
])
def test_a_legs_own_levels_are_labelled_on_the_right(figure, panel, label):
    """Requested. The right edge is *now*, so the price a line marks sits next
    to the candle testing it; the left edge is the oldest bar on the panel."""
    assert _side(_labels(figure, panel)[label]) == "right-inside"


@pytest.mark.parametrize("panel", ["CALL", "PUT"])
@pytest.mark.parametrize("name", ["POC", "VAH", "VAL"])
def test_nothing_on_an_option_panel_overhangs_the_figure_edge(figure, panel,
                                                              name):
    """⭐ Why `xanchor` is set explicitly.

    These two panels are the rightmost column, against an 8px right margin. A
    label anchored `left` at `x=1` runs off the figure and is cut — a level
    drawn with its price invisible is worse than one drawn on the wrong side.
    """
    assert _side(_labels(figure, panel)[name]) == "right-inside"


def test_every_option_panel_label_is_on_the_same_side(figure):
    """Labels split across both edges make a panel read as two charts."""
    for panel in ("CALL", "PUT"):
        sides = {_side(a) for a in _labels(figure, panel).values()}
        assert sides == {"right-inside"}, f"{panel} labels are split: {sides}"


def test_the_index_panel_keeps_the_wider_placement(figure):
    """NIFTY has the column gap to spill into, so it is left alone. The fix is
    scoped to the panels that were actually being clipped."""
    assert _side(_labels(figure, "NIFTY")["POC"]) == "right-overhang"


def test_the_leg_column_is_named_not_guessed():
    """`col == 2` appearing bare in the overlay would be the kind of constant
    that survives a layout change and stops matching anything."""
    assert LEG_COL == 2


# ══════════════════════════════════════════════════════════════════════
#  it still tolerates a warming-up terminal
# ══════════════════════════════════════════════════════════════════════

def test_a_panel_with_no_series_does_not_take_the_chart_down():
    nifty = _frame([24500, 24520, 24533], 24500)
    fig, notes = terminal_chart(nifty, None, None, {"war_zone": 24533},
                                call_profile=_profile(76, 82, 60, 60, 82))
    assert fig is not None
    assert notes                      # the missing legs are reported, not hidden


def test_no_profile_is_not_an_error():
    nifty = _frame([24500, 24520, 24533], 24500)
    fig, _ = terminal_chart(nifty, None, None, {})
    assert fig is not None
