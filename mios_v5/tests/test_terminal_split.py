"""⛶ The split terminal: NIFTY, ATM Call and ATM Put as THREE figures.

`terminal_chart` draws one figure so Streamlit's single Fullscreen button
enlarges all three locked panels together. A trader asked to enlarge each chart
on its own, and Streamlit injects that button per `st.plotly_chart` call — so
each chart has to be its own figure. `terminal_charts_split` is that split, and
these tests pin the two properties the split must preserve: three independent
figures, and one shared clock + zoom window so they still line up.
"""

from __future__ import annotations

import ast
import pathlib

import pandas as pd

from mios_v5.ui.terminal_chart import SPLIT_KEYS, terminal_charts_split

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _frame(base: float = 100.0, day: str = "2026-07-29", n: int = 40):
    idx = pd.date_range(f"{day} 09:15", periods=n, freq="1min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({
        "datetime": idx, "open": base, "high": base + 5.0,
        "low": base - 5.0, "close": base + 1.0, "volume": 1000})


# ── three figures, one per chart ───────────────────────────────────────

def test_it_returns_one_figure_per_chart():
    figs, notes = terminal_charts_split(_frame(24000), _frame(120), _frame(90))
    assert set(figs) == set(SPLIT_KEYS)
    assert not notes
    for key in SPLIT_KEYS:
        assert figs[key] is not None, key
        # a real Plotly figure, not a subplot grid: exactly one x/y axis, so
        # each chart is its own fullscreen frame rather than three panels.
        layout = figs[key].layout.to_plotly_json()
        assert "xaxis2" not in layout, f"{key} still carries a second panel"
        assert layout["xaxis"], key


def test_a_missing_series_is_a_note_and_a_none_not_a_blank_panel():
    """The same three-state discipline `terminal_chart` uses: a series that could
    not be drawn is named, and its figure is None so the caller can say why
    instead of rendering an empty axis."""
    figs, notes = terminal_charts_split(None, _frame(120), _frame(90))
    assert "NIFTY" in notes
    assert figs["NIFTY"] is None
    assert figs["CALL"] is not None and figs["PUT"] is not None


# ── one clock, one zoom window — so they still line up ─────────────────

def test_all_three_share_one_zoom_window():
    """The split gives up the shared crosshair, not the shared timeline. Every
    panel is reindexed onto one master timeline and pinned to one window, so the
    x-range is identical across the three figures and 10:48 is 10:48 on each."""
    figs, _ = terminal_charts_split(_frame(24000), _frame(120), _frame(90),
                                    window_minutes=15)
    ranges = [tuple(figs[k].layout.xaxis.range) for k in SPLIT_KEYS]
    assert ranges[0] == ranges[1] == ranges[2]
    assert all(r for r in ranges), "no zoom window was applied"


def test_each_panel_keeps_its_own_price_axis():
    """NIFTY's ~24,000 and a ₹120 premium share a time axis, never a price one —
    so the y-ranges must differ even though the x-window is shared."""
    figs, _ = terminal_charts_split(_frame(24000), _frame(120), _frame(90),
                                    window_minutes=15)
    y_nifty = tuple(figs["NIFTY"].layout.yaxis.range)
    y_call = tuple(figs["CALL"].layout.yaxis.range)
    assert y_nifty != y_call
    assert max(y_nifty) > 1000 and max(y_call) < 1000


# ── the wiring in the dashboard ────────────────────────────────────────

def _terminal_chart_src() -> str:
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_terminal_chart")
    return ast.get_source_segment(src, fn) or ""


def test_the_dashboard_draws_three_charts_each_with_its_own_key():
    """Three `plotly_chart` calls, one per panel, each with a distinct key so
    Streamlit renders three separate fullscreen frames rather than collapsing
    them onto one element id."""
    body = _terminal_chart_src()
    tree = ast.parse(body)
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and getattr(c.func, "attr", "") == "plotly_chart"]
    assert len(calls) == 3, f"expected 3 chart calls, found {len(calls)}"
    keys = set()
    for c in calls:
        cfg = next((kw.value for kw in c.keywords if kw.arg == "config"), None)
        assert isinstance(cfg, ast.Name) and cfg.id == "FS_CHART_CONFIG"
        key = next((kw.value for kw in c.keywords if kw.arg == "key"), None)
        assert isinstance(key, ast.Constant), "a split chart has no stable key"
        keys.add(key.value)
    assert keys == {"terminal_nifty", "terminal_call", "terminal_put"}
