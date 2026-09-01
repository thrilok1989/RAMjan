"""The instrument selection has to reach the chart — and say so on it.

Three separate attempts at "switch the chart to SENSEX" looked correct in the
diff and did nothing on screen, because nothing here tested the wiring from
the selected instrument through to what the trader actually sees. Each test
below pins one link in that chain:

  sidebar selection → `_chart_instrument` → the index panel's title

plus the default the app lands on. A wrong instrument is invisible at runtime
— the candles are just numbers — so the panel title is the only thing that
tells a trader which index they are looking at.
"""

from __future__ import annotations

import pandas as pd

from mios_v5.instrument_cache_manager import (
    DEFAULT_INSTRUMENT,
    get_current_instrument,
)
from mios_v5.ui.dashboard_v6 import _index_label
from mios_v5.ui.terminal_chart import SPLIT_KEYS, terminal_charts_split


class _FakeSt:
    """Just the session_state surface `_index_label` touches."""

    def __init__(self, **state):
        self.session_state = dict(state)


def _frame(base: float, day: str = "2026-07-29", n: int = 40):
    idx = pd.date_range(f"{day} 09:15", periods=n, freq="1min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({
        "datetime": idx, "open": base, "high": base + 5.0,
        "low": base - 5.0, "close": base + 1.0, "volume": 1000})


def _index_title(fig):
    """The subplot title Plotly rendered for the index panel."""
    return fig.layout.to_plotly_json()["annotations"][0]["text"]


# ── the app lands on SENSEX ────────────────────────────────────────────

def test_default_instrument_is_nifty():
    """A fresh session opens on NIFTY — the index every existing alert and
    engine refers to. SENSEX is a click away on the sidebar toggle."""
    assert DEFAULT_INSTRUMENT == "NIFTY"
    assert get_current_instrument({}) == "NIFTY"


def test_an_explicit_selection_still_wins():
    assert get_current_instrument({"_selected_instrument": "SENSEX"}) == "SENSEX"


# ── the frame's instrument reaches the label ───────────────────────────

def test_index_label_follows_the_loaded_frame():
    """`_chart_instrument` is stamped by the fetch that publishes the frame,
    so the label names what is actually drawn, not what is merely selected."""
    assert _index_label(_FakeSt(_chart_instrument="SENSEX")) == "SENSEX"
    assert _index_label(_FakeSt(_chart_instrument="NIFTY")) == "NIFTY"


def test_index_label_falls_back_to_nifty_when_unstamped():
    assert _index_label(_FakeSt()) == "NIFTY"


# ── the label reaches the chart ────────────────────────────────────────

def test_index_panel_is_titled_with_the_instrument():
    """Regression: the panel was captioned "NIFTY" unconditionally, so a
    switched chart drew SENSEX candles under a NIFTY title and read as though
    the toggle had done nothing."""
    figs, _ = terminal_charts_split(_frame(81000), _frame(120), _frame(90),
                                    index_label="SENSEX")
    assert _index_title(figs["NIFTY"]) == "SENSEX"


def test_index_panel_still_says_nifty_by_default():
    figs, _ = terminal_charts_split(_frame(24000), _frame(120), _frame(90))
    assert _index_title(figs["NIFTY"]) == "NIFTY"


def test_relabelling_does_not_disturb_the_figure_keys():
    """The panel is renamed for display only — SPLIT_KEYS still keys it
    "NIFTY", so every profile/height/figure lookup keeps working."""
    figs, notes = terminal_charts_split(_frame(81000), _frame(120), _frame(90),
                                        index_label="SENSEX")
    assert set(figs) == set(SPLIT_KEYS)
    assert not notes
    assert all(figs[k] is not None for k in SPLIT_KEYS)


# ── one toggle, not two ────────────────────────────────────────────────

def test_only_one_instrument_selectbox_is_rendered():
    """Regression: the sidebar carried TWO "🎯 Instrument" selectboxes.

    Streamlit keys a widget by its parameters, and the two differed in `help`
    text — so they got separate ids and both rendered instead of colliding.
    The lower one then assigned `_selected_instrument` unconditionally on every
    run, overwriting whatever the upper one had just set, which left the upper
    dropdown inert. Two controls for one setting is the bug whether or not they
    fight; pin it to one.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py").read_text()

    found = 0
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "selectbox"):
            continue
        label = node.args[0] if node.args else None
        if isinstance(label, ast.Constant) and "Instrument" in str(label.value):
            found += 1

    assert found == 1, f"expected exactly one Instrument selectbox, found {found}"
