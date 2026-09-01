"""The slim Trade Card on Dashboard 2, and the ownership split it implements.

The full Trade Card lives in `vob_minimal.py` and owns the main analyser page.
This one carries ONLY what Dashboard 2 does not already own, so the two never
answer the same question twice.

Most of these tests are about what it does not show. An overlap here does not
break anything — it just gives a trader two answers to "what is the timing"
and no way to tell which is authoritative, which is how the Trade Card and the
Matrix drifted together in the first place.
"""

import pathlib
import re

import pytest

from mios_v5.ui import trade_card_panel as TCP


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _fr(**over):
    fr = {
        "preferred_bias": "BEAR", "confidence_tempered": 71,
        "families_read": {"dominant": "BEAR", "agreement_pct": 72,
                          "severity": "low"},
        "htf": {"alignment": {"bias": "BEAR", "score": 78, "label": "aligned",
                              "stars": "★★★★"}},
        "reaction": {"winner": "Sellers", "state": "REJECTION",
                     "confidence": 70},
        "absorption": {"behaviour": "NONE"}, "transition": {"state": "STABLE"},
        "memory_read": {}, "flow_shift": {}, "validity_both": {},
    }
    fr.update(over)
    return fr


_MF = {"poc_price": 24234, "value_area_high": 24278, "value_area_low": 24213}


# ── the architectural constraint ────────────────────────────────────────

def test_the_panel_never_imports_the_app():
    """`mios_v5` never imports `vob_minimal` — the dependency runs one way.
    That is exactly why the full Trade Card could not simply be called here."""
    src = pathlib.Path(TCP.__file__).read_text()
    for banned in ("import vob_minimal", "from vob_minimal"):
        assert banned not in src


def test_it_computes_nothing():
    src = pathlib.Path(TCP.__file__).read_text()
    for banned in ("cumsum", "rolling(", "ewm(", "clip(0, 1)"):
        assert banned not in src, banned


def test_it_never_raises():
    for args in ((None, None, None, None), ({}, 0, {}, {}),
                 (_fr(), "abc", None, None)):
        assert isinstance(TCP.slim_card_html(*args), str)


# ── the ownership split ─────────────────────────────────────────────────

def test_it_does_not_show_what_the_matrix_owns():
    """Quality, timing, risk and the horizon ranking belong to the Opportunity
    Matrix — per horizon, which is strictly more than one blended verdict."""
    t = _text(TCP.slim_card_html(_fr(), 24250.2, _MF, None)).lower()
    for owned_elsewhere in ("quality", "timing", "scalp", "midday",
                            "intraday", "positional", "swing"):
        assert owned_elsewhere not in t, f"{owned_elsewhere} is the Matrix's"


def test_it_does_not_render_sr_zone_cards():
    """`_sr_intelligence` already renders every level, ranked, on this tab."""
    src = pathlib.Path(TCP.__file__).read_text()
    for banned in ("zone_card", "render_sr_panel", "reaction_sr"):
        assert banned not in src, banned


def test_it_does_not_render_the_stage_52_ladder():
    """The Cockpit owns it. Naming the Cockpit in the docstring that explains
    the split is the point; RENDERING its ladder is what must not happen."""
    src = pathlib.Path(TCP.__file__).read_text()
    assert "decision_v2" not in src
    assert "cockpit_html" not in src and "render_cockpit" not in src


def test_the_bias_strip_is_reused_not_reimplemented():
    """Two cards rendering V6 differently would eventually disagree about what
    V6 said — the exact failure Stage 53 exists to prevent, one level up."""
    src = pathlib.Path(TCP.__file__).read_text()
    assert "from .bias_compare import bias_compare_html" in src
    assert "def bias_compare_html" not in src


# ── market facts ────────────────────────────────────────────────────────

def test_facts_show_spot_value_area_and_gap():
    t = _text(TCP.market_facts_html(
        24250.2, _MF, {"type": "GAP-DOWN", "pct": -0.42}))
    assert "24,250.2" in t
    assert "VAL ₹24,213" in t and "POC ₹24,234" in t and "VAH ₹24,278" in t
    assert "GAP-DOWN" in t and "-0.42%" in t


def test_an_unmeasured_field_is_omitted_not_zeroed():
    """A `POC ₹0` line is worse than no POC line."""
    t = _text(TCP.market_facts_html(24250.2, {}, {}))
    assert "24,250.2" in t
    assert "POC" not in t and "GAP" not in t


def test_no_spot_and_no_profile_yields_nothing_at_all():
    assert TCP.market_facts_html(None, None, None) == ""


def test_a_flat_open_is_not_shown_as_a_gap():
    t = _text(TCP.market_facts_html(24250, _MF, {"type": "FLAT", "pct": 0.01}))
    assert "GAP" not in t


# ── value position ──────────────────────────────────────────────────────

@pytest.mark.parametrize("spot,expect", [
    (24300, "above VAH"), (24100, "below VAL"), (24240, "inside VA")])
def test_value_position_reads_the_three_cases(spot, expect):
    assert TCP.value_position(spot, 24278, 24213)[0] == expect


def test_value_position_is_none_without_a_value_area():
    """With no value area there is no inside, and defaulting to it would
    assert acceptance nobody measured."""
    assert TCP.value_position(24250, None, None) is None
    assert TCP.value_position(None, 24278, 24213) is None


def test_value_position_works_with_only_one_boundary():
    assert TCP.value_position(24300, 24278, None)[0] == "above VAH"
    assert TCP.value_position(24100, None, 24213)[0] == "below VAL"


# ── the card as a whole ─────────────────────────────────────────────────

def test_the_card_carries_facts_and_the_divergence():
    t = _text(TCP.slim_card_html(_fr(), 24250.2, _MF, None))
    assert "Market facts" in t and "24,250.2" in t
    assert "MIOS V5" in t and "MIOS V6" in t


def test_an_empty_card_renders_nothing_rather_than_a_hollow_box():
    assert TCP.slim_card_html(None, None, None, None) == ""


def test_facts_alone_still_render_when_v6_is_cold():
    html = TCP.slim_card_html({}, 24250.2, _MF, None)
    assert "24,250.2" in _text(html)


def test_the_panel_uses_no_retired_grey():
    from mios_v5.ui.theme import RETIRED
    src = pathlib.Path(TCP.__file__).read_text().lower()
    assert not [g for g in RETIRED if g in src]


def test_the_panel_has_no_hard_pixel_widths():
    src = pathlib.Path(TCP.__file__).read_text()
    bad = [m for m in re.findall(r"(?<!min-)(?<!max-)width:\s*(\d+)px", src)
           if int(m) > 60]
    assert not bad, bad


def test_it_is_wired_into_the_trading_tab():
    src = (pathlib.Path(TCP.__file__).parent / "dashboard_v6.py").read_text()
    assert "render_slim_trade_card" in src


def test_it_sits_below_the_opportunity_read():
    """Dashboard 2's rule, restated once the charts moved to their own tab.

    The rule used to read "nothing above the charts but the opportunity read"
    and was checked as `_terminal_chart(` < `render_slim_trade_card`. The chart
    is now drawn by `_charts_screen` on the first tab, so the surviving half of
    the rule is what it always meant: the slim card comes after the opportunity
    and strike reads, not before them.
    """
    src = (pathlib.Path(TCP.__file__).parent / "dashboard_v6.py").read_text()
    body = src[src.index("def _trading_screen"):src.index("def _command_center")]
    assert "_terminal_chart(" not in body, \
        "the charts moved to _charts_screen — this tab should not redraw them"
    assert body.index("_opportunity(") < body.index("render_slim_trade_card")
    assert body.index("_strike_validation(") < body.index("render_slim_trade_card")


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        if not hasattr(fn, "pytestmark"):
            fn()
    print(f"slim trade card tests passed ({len(fns)})")
