"""Chart chrome follows the viewer's theme; the leg S/R read reaches the chart.

Two changes the desk asked for, plus the HVP defaults.

**Theme.** The terminal's background, grid, text and spikes were hard-coded to
the dark palette, so a viewer who picked Light in Settings → Theme got near-
black rectangles pasted onto a white page. Only the chrome switches — candles,
levels and zones carry meaning and read on either background.

**Leg S/R.** `classify_leg_sr_behavior` already classified every leg's own VOB
structure as BREAKING / REJECTING / ACCEPTING / BUILDING every cycle, but the
verdict only reached the tables. The chart drew the zones and left the trader
to re-derive the one judgement the engine had already made.
"""

from __future__ import annotations

import pandas as pd
import pytest

from mios_v5.ui.chart_theme import DARK, LIGHT, active_theme, palette
from mios_v5.ui.terminal_chart import SR_STATE_TONE, terminal_charts_split
from mios_v5.volume_points import defaults


def _frame(base: float, n: int = 30):
    idx = pd.date_range("2026-07-29 09:15", periods=n, freq="1min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({
        "datetime": idx, "open": base, "high": base + 5.0,
        "low": base - 5.0, "close": base + 1.0, "volume": 900})


def _chrome(fig) -> dict:
    lay = fig.layout.to_plotly_json()
    return {"paper": lay["paper_bgcolor"], "plot": lay["plot_bgcolor"],
            "font": lay["font"]["color"], "grid": lay["xaxis"]["gridcolor"]}


def _texts(fig):
    return [a.text for a in (fig.layout.annotations or []) if a.text]


class _Theme:
    def __init__(self, kind):
        self.type = kind


class _Ctx:
    def __init__(self, kind):
        self.theme = _Theme(kind)


class _St:
    """Only the surface `active_theme` probes."""

    def __init__(self, kind=None, base=None):
        if kind is not None:
            self.context = _Ctx(kind)
        self._base = base

    def get_option(self, name):
        if name == "theme.base":
            return self._base
        raise KeyError(name)


# ── the palette ────────────────────────────────────────────────────────

def test_light_and_dark_are_actually_different():
    assert palette("light") != palette("dark")
    assert palette("light")["paper"] == "#ffffff"
    assert palette("dark")["paper"] == "#0b0f16"


def test_both_palettes_define_every_key():
    assert set(LIGHT) == set(DARK)
    for key in DARK:
        assert LIGHT[key].startswith("#") and DARK[key].startswith("#"), key


def test_unknown_theme_falls_back_to_dark():
    """A surprise value must degrade to what the app shipped with, not to a
    half-applied theme that is unreadable either way."""
    for junk in (None, "", "solarized", "LIGHTS", 7):
        assert palette(junk) == DARK or junk == "light"
    assert palette("nonsense") == DARK


def test_theme_lookup_is_case_insensitive():
    assert palette("LIGHT") == LIGHT
    assert palette(" Light ") == LIGHT


# ── reading the viewer's theme ─────────────────────────────────────────

def test_viewer_context_wins():
    assert active_theme(_St(kind="light")) == "light"
    assert active_theme(_St(kind="dark")) == "dark"


def test_falls_back_to_configured_base():
    """`config.toml` ships dark, but the Settings menu overrides it per viewer
    — so the context is preferred and the base is only the fallback."""
    assert active_theme(_St(base="light")) == "light"
    assert active_theme(_St(base="dark")) == "dark"


def test_a_probe_that_raises_does_not_break_the_chart():
    class _Boom:
        @property
        def context(self):
            raise RuntimeError("no context here")

        def get_option(self, name):
            raise RuntimeError("nor here")

    assert active_theme(_Boom()) == "dark"


# ── the chrome reaches the figure ──────────────────────────────────────

@pytest.mark.parametrize("kind", ["light", "dark"])
def test_the_figure_takes_the_palette(kind):
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    theme=palette(kind))
    want = palette(kind)
    for key in ("NIFTY", "CALL", "PUT"):
        got = _chrome(figs[key])
        assert got["paper"] == want["paper"], key
        assert got["font"] == want["font"], key
        assert got["grid"] == want["grid"], key


def test_no_theme_still_draws_dark():
    """Existing callers pass nothing and must be unaffected."""
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {})
    assert _chrome(figs["NIFTY"])["paper"] == DARK["paper"]


# ── the leg S/R read ───────────────────────────────────────────────────

# `_leg_levels` publishes the behaviour level under "support"/"resistance",
# so these mirror what the panel really receives: the level AND the read.
def _lv(side, level):
    return {side: level, "vwap": level * 0.95}


@pytest.mark.parametrize("state", sorted(SR_STATE_TONE))
def test_each_state_is_written_onto_the_level(state):
    sr = {"state": state, "side": "resistance", "level": 124.5}
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    call_levels=_lv("resistance", 124.5),
                                    call_sr=sr)
    assert any(state in t for t in _texts(figs["CALL"])), _texts(figs["CALL"])


def test_the_state_does_not_draw_a_second_line_at_the_same_price():
    """Regression: the state was first drawn as its own hline, which put TWO
    lines at the identical price — the `Resistance ₹124.50` that `_leg_levels`
    already publishes, plus a `BREAKING resistance ₹124.50` on top of it. One
    level, one line, one label."""
    sr = {"state": "BREAKING", "side": "resistance", "level": 124.5}
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    call_levels=_lv("resistance", 124.5),
                                    call_sr=sr)
    at_level = [t for t in _texts(figs["CALL"]) if "124.50" in t]
    assert len(at_level) == 1, at_level
    assert "BREAKING" in at_level[0]


def test_the_level_is_shown_with_the_state():
    sr = {"state": "BUILDING", "side": "support", "level": 88.25}
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    put_levels=_lv("support", 88.25), put_sr=sr)
    assert any("88.25" in t and "BUILDING" in t for t in _texts(figs["PUT"]))


def test_the_state_lands_on_the_side_it_belongs_to():
    """A support read must not decorate the resistance line."""
    figs, _ = terminal_charts_split(
        _frame(24400), _frame(120), _frame(90), {},
        call_levels={"support": 90.0, "resistance": 124.5},
        call_sr={"state": "BUILDING", "side": "support", "level": 90.0})
    for t in _texts(figs["CALL"]):
        if "124.50" in t:
            assert "BUILDING" not in t, t
        if "90.00" in t:
            assert "BUILDING" in t, t


def test_state_none_leaves_the_level_undecorated():
    for sr in ({"state": "NONE", "side": None, "level": None}, {}, None):
        figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90),
                                        {}, call_levels=_lv("resistance", 124.5),
                                        call_sr=sr)
        assert any(t == "Resistance ₹124.50" for t in _texts(figs["CALL"])), sr


def test_a_state_whose_level_is_not_on_the_panel_decorates_nothing():
    """The read is only written onto a line at the SAME price — otherwise a
    stale level would relabel whatever line happened to be there."""
    figs, _ = terminal_charts_split(
        _frame(24400), _frame(120), _frame(90), {},
        call_levels={"resistance": 200.0},
        call_sr={"state": "BREAKING", "side": "resistance", "level": 124.5})
    assert not any("BREAKING" in t for t in _texts(figs["CALL"]))


def test_the_index_panel_does_not_take_a_leg_read():
    """These are premium levels on a premium axis — they belong to the leg
    that produced them and nowhere else."""
    sr = {"state": "BREAKING", "side": "resistance", "level": 124.5}
    figs, _ = terminal_charts_split(_frame(24400), _frame(120), _frame(90), {},
                                    call_sr=sr, put_sr=sr)
    assert not any("BREAKING" in t for t in _texts(figs["NIFTY"]))


def test_call_and_put_reads_do_not_bleed_into_each_other():
    figs, _ = terminal_charts_split(
        _frame(24400), _frame(120), _frame(90), {},
        call_levels=_lv("resistance", 124.5), put_levels=_lv("support", 88.0),
        call_sr={"state": "BREAKING", "side": "resistance", "level": 124.5},
        put_sr={"state": "REJECTING", "side": "support", "level": 88.0})
    assert any("BREAKING" in t for t in _texts(figs["CALL"]))
    assert not any("REJECTING" in t for t in _texts(figs["CALL"]))
    assert any("REJECTING" in t for t in _texts(figs["PUT"]))
    assert not any("BREAKING" in t for t in _texts(figs["PUT"]))


# ── HVP defaults ───────────────────────────────────────────────────────

def test_hvp_defaults_are_five_bars_either_side():
    d = defaults()
    assert d["left"] == 5, d
    assert d["right"] == 5, d


def test_hvp_volume_filter_is_unchanged():
    """Only the bar counts were asked for; the filter keeps its value."""
    assert defaults()["filter_vol"] == 2.0
