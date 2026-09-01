"""Stage 71 — the panel, and the native-read bridge that feeds it.

Presentation is still testable: the panel must never invent a value, must
render every state without raising, and must not display a producer the
horizon does not own. It also has a layout budget — the charts underneath it
have to stay above the fold — so the always-visible portion is size-checked.
"""

import re

import pytest

from mios_v5 import opportunity as OP
from mios_v5 import opportunity_intel as OI
from mios_v5.horizon_owner import (AGGREGATE, EXCLUDED, NATIVE_LABEL, OWNED,
                                   Horizon, owners_of)
from mios_v5.ui import opportunity_panel as PANEL


# ── fixtures ────────────────────────────────────────────────────────────

def _fr(**over):
    fr = {
        "preferred_bias": "BEAR", "confidence_tempered": 71,
        "stability": "STABLE",
        "flow_shift": {"freeze_entries": False},
        "transition": {"state": "STABLE", "label": "stable"},
        "memory_read": {"state_duration_min": 22},
        "market_state": {"state": "TREND_DOWN", "confidence": 74},
        "reaction": {"state": "CONFIRMED_BREAKDOWN", "confidence": 81},
        "absorption": {"behaviour": "SELLER_ABSORPTION", "confidence": 66},
        "htf": {"alignment": {"score": 78}, "reads": {}},
        "validity": {"verdict": "VALID", "valid": True, "pct": 80},
        "day_classification": {"type": "TREND", "label": "Trend",
                               "confidence": 66},
        "session_intel": {"session": "MORNING_TREND",
                          "minutes_remaining": 95},
        "energy_read": {"state": "EXPANSION", "release_probability": 55},
        "engine_bias": {}, "sections": {},
    }
    fr.update(over)
    return fr


def _fill(h, bias, n=None):
    o = owners_of(h)
    o = o if n is None else o[:n]
    return {p: {"bias": bias, "confidence": 80, "label": p} for p in o}


def _matrix(fr=None, native=None, previous=None):
    fr = fr if fr is not None else _fr()
    m = OP.build_matrix(fr, native)
    return OI.enrich(m, fr, OP._producer_reads(fr, native), previous)


def _loaded():
    n = {}
    n.update(_fill(Horizon.SCALP, "BEAR"))
    n.update(_fill(Horizon.INTRADAY, "BULL"))
    n.update(_fill(Horizon.SWING, "BEAR"))
    return _matrix(native=n)


def _text(html):
    return re.sub(r"<[^>]+>", " ", html)


# ══════════════════════════════════════════════════════════════════
#  the native-read bridge
# ══════════════════════════════════════════════════════════════════

def test_all_bias_rows_translate_to_producer_ids():
    rows = [{"Engine": "VWAP relation", "_dir": "bull", "Detail": "above"},
            {"Engine": "S/R Behavior", "_dir": "bear", "Detail": "rejected"}]
    out = OP.native_reads_from_rows(rows)
    assert out["native_vwap_relation"]["bias"] == "BULL"
    assert out["native_sr_behavior"]["bias"] == "BEAR"


def test_an_unregistered_label_is_skipped_not_guessed():
    out = OP.native_reads_from_rows(
        [{"Engine": "Some Brand New Signal", "_dir": "bull"}])
    assert out == {}


def test_aggregate_and_excluded_labels_never_become_reads():
    rows = [{"Engine": NATIVE_LABEL["native_master_signal"], "_dir": "bull"},
            {"Engine": NATIVE_LABEL["native_news_bias"], "_dir": "bull"},
            {"Engine": NATIVE_LABEL["native_atm_pcr"], "_dir": "bull"}]
    assert OP.native_reads_from_rows(rows) == {}


def test_neutral_rows_are_carried_not_dropped():
    out = OP.native_reads_from_rows(
        [{"Engine": "VWAP relation", "_dir": "neutral"}])
    assert out["native_vwap_relation"]["bias"] == "NEUTRAL"


def test_bridge_never_fabricates_a_confidence():
    """The all-bias table has no per-signal confidence. Inventing one would
    flow straight into the star display."""
    out = OP.native_reads_from_rows([{"Engine": "VWAP relation",
                                      "_dir": "bull"}])
    assert out["native_vwap_relation"]["confidence"] is None


def test_bridge_tolerates_garbage():
    for bad in (None, [], [None], [{}], [{"Engine": None, "_dir": None}],
                ["not a dict"]):
        assert OP.native_reads_from_rows(bad) == {}


def test_every_registered_native_label_round_trips():
    """Any OWNED native id must be reachable from its display label."""
    rows = [{"Engine": lbl, "_dir": "bull"}
            for pid, lbl in NATIVE_LABEL.items() if pid in OWNED]
    out = OP.native_reads_from_rows(rows)
    assert len(out) == sum(1 for p in NATIVE_LABEL if p in OWNED)


# ══════════════════════════════════════════════════════════════════
#  the panel renders every state
# ══════════════════════════════════════════════════════════════════

def test_header_renders_the_best_opportunity():
    h = PANEL.header_html(_loaded())
    t = _text(h)
    assert "Best opportunity" in t
    for field in ("Quality", "Confidence", "Risk", "Timing", "Lifetime",
                  "Energy", "Stability"):
        assert field in t, f"header is missing {field}"


def test_header_always_shows_a_second_opportunity_block():
    """Never hidden — the market always has another possibility."""
    assert "Second best" in _text(PANEL.header_html(_loaded()))


def test_second_block_says_so_when_only_one_horizon_qualified():
    m = _matrix(native=_fill(Horizon.SCALP, "BEAR"))
    assert "Only one horizon qualified" in _text(PANEL.header_html(m))


def test_a_no_trade_header_explains_instead_of_saying_wait():
    t = _text(PANEL.header_html(_matrix()))
    assert "No high-quality opportunity" in t
    assert "Stay flat" in t


def test_every_html_entry_point_survives_empty_input():
    for fn in (PANEL.header_html, PANEL.matrix_html, PANEL.reference_html):
        for arg in (None, {}, {"rows": []}):
            assert isinstance(fn(arg), str)
    assert isinstance(PANEL.detail_html(None), str)


def test_matrix_has_one_row_per_horizon():
    html = PANEL.matrix_html(_loaded())
    for h in ("scalp", "midday", "intraday", "positional", "swing"):
        assert h in html


def test_matrix_rows_follow_display_order():
    m = _loaded()
    html = PANEL.matrix_html(m)
    seen = [h for h in m["display_order"] if h in html]
    positions = [html.index(h) for h in seen]
    assert positions == sorted(positions), "rows must render in display order"


def test_swing_renders_as_bias_only_never_as_a_side():
    m = _matrix(native=_fill(Horizon.SWING, "BEAR"))
    html = PANEL.matrix_html(m)
    swing_row = html[html.index("swing"):]
    assert "Structure" in swing_row
    assert PANEL._SIDE_COLOUR["BIAS"][0] in swing_row, "bias-only is blue"


# ── colour coding ───────────────────────────────────────────────────────

def test_call_is_green_and_put_is_red():
    """Asserted against the palette, not against hex — a literal here is how
    the panel drifted onto a retired grey in the first place."""
    from mios_v5.ui.theme import BULL, BEAR, INFO, MICRO
    assert PANEL._SIDE_COLOUR["CALL"][0] == BULL
    assert PANEL._SIDE_COLOUR["PUT"][0] == BEAR
    assert PANEL._SIDE_COLOUR["WAIT"][0] == MICRO
    assert PANEL._SIDE_COLOUR["BIAS"][0] == INFO


def test_the_panel_uses_no_retired_grey():
    """The workstation guard covers ui/*.py; this one fails closer to home."""
    import pathlib
    from mios_v5.ui.theme import RETIRED
    src = (pathlib.Path(PANEL.__file__)).read_text().lower()
    assert not [g for g in RETIRED if g in src]


def test_verdict_kind_classifies_all_four_cases():
    assert PANEL._verdict_kind({"side": "CALL"}) == "CALL"
    assert PANEL._verdict_kind({"side": "PUT"}) == "PUT"
    assert PANEL._verdict_kind({"bias": "BEAR"}) == "BIAS"
    assert PANEL._verdict_kind({}) == "WAIT"


def test_every_quality_grade_has_a_colour():
    for g in ("A+", "A", "B", "C", "AVOID", "UNKNOWN"):
        assert g in PANEL._QUALITY_COLOUR


def test_every_timing_and_risk_value_has_a_colour():
    for t in OI.TIMING:
        assert t in PANEL._TIMING_COLOUR
    for r in ("LOW", "MEDIUM", "HIGH", "EXTREME", "UNKNOWN"):
        assert r in PANEL._RISK_COLOUR


# ── stability vocabulary is a MAPPING, not a computation ────────────────

def test_stability_word_maps_from_the_published_parts():
    word, _ = PANEL._stability_word(
        {"parts": [{"label": "Bias", "value": "strengthening"}]})
    assert word == "Increasing"
    word, _ = PANEL._stability_word(
        {"parts": [{"label": "Bias", "value": "reversing"}]})
    assert word == "Collapsing"


def test_a_shifted_flow_overrides_the_bias_word():
    """A repriced tape outranks whatever the bias was doing."""
    word, _ = PANEL._stability_word(
        {"parts": [{"label": "Flow", "value": "shifted"},
                   {"label": "Bias", "value": "strengthening"}]})
    assert word == "Explosive"


def test_stability_word_defaults_to_stable_on_nothing():
    assert PANEL._stability_word(None)[0] == "Stable"
    assert PANEL._stability_word({})[0] == "Stable"


def test_the_five_workstation_words_are_all_reachable():
    produced = {w for w, _ in list(PANEL._FLOW_WORD.values())
                + list(PANEL._TRANSITION_WORD.values())}
    assert {"Stable", "Increasing", "Weakening", "Explosive",
            "Collapsing"} <= produced


# ── the energy bar shows only what exists ───────────────────────────────

def test_energy_bar_uses_the_published_bull_bear_counts():
    html = PANEL._energy_bar({"bull": 15, "bear": 5})
    assert "15/5" in html and "75%" in html


def test_energy_bar_is_a_dash_when_nothing_reported():
    assert "—" in PANEL._energy_bar({"bull": 0, "bear": 0})


# ── detail: reasoning, weakness, why-not ────────────────────────────────

def test_detail_shows_every_intel_field():
    row = _loaded()["best_trade"]
    t = _text(PANEL.detail_html(row))
    for field in ("Type", "Quality", "Risk", "Timing", "Lifetime", "Maturity",
                  "Rotation"):
        assert field in t


def test_detail_shows_weakness_when_present():
    m = _matrix(_fr(transition={"state": "WEAKENING", "label": "weakening"}),
                _fill(Horizon.SCALP, "BEAR"))
    row = next(r for r in m["rows"] if r["horizon"] == "scalp")
    assert "Weakness" in _text(PANEL.detail_html(row))


def test_detail_shows_why_not_ranked_higher():
    n = {}
    n.update(_fill(Horizon.SCALP, "BEAR"))
    n.update(_fill(Horizon.POSITIONAL, "BEAR"))
    m = _matrix(native=n)
    second = next(r for r in m["rows"] if r["horizon"] == m["ranked"][1])
    assert "Why not ranked higher" in _text(PANEL.detail_html(second))


def test_detail_only_shows_producers_the_horizon_owns():
    """The panel must not leak another horizon's evidence into a row."""
    n = {}
    n.update(_fill(Horizon.SCALP, "BEAR"))
    n.update(_fill(Horizon.POSITIONAL, "BULL"))
    m = _matrix(native=n)
    scalp = next(r for r in m["rows"] if r["horizon"] == "scalp")
    html = PANEL.detail_html(scalp)
    for pid in owners_of(Horizon.POSITIONAL):
        assert pid not in html


# ── reference & excluded ────────────────────────────────────────────────

def test_reference_marks_every_aggregate_non_voting():
    html = PANEL.reference_html(_loaded())
    assert "never counted" in _text(html)
    assert "non-voting" in _text(html)


def test_excluded_lists_every_producer_with_its_reason():
    html = PANEL.reference_html(_loaded())
    assert str(len(EXCLUDED) + len(AGGREGATE)) in html
    assert "unstable" in html or "superseded" in html


# ── the layout budget ───────────────────────────────────────────────────

def test_the_always_visible_portion_stays_small():
    """The terminal chart has to survive underneath this. Header + matrix is
    the entire budget; everything else lives behind an expander."""
    m = _loaded()
    always = PANEL.header_html(m) + PANEL.matrix_html(m)
    rows = always.count("<tr")
    assert rows <= 7, "one header row plus five horizons, no more"
    assert "expander" not in always


def test_detail_is_not_rendered_by_the_always_visible_part():
    m = _loaded()
    always = PANEL.header_html(m) + PANEL.matrix_html(m)
    assert "Quality components" not in always
    assert "Why not ranked higher" not in always


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"opportunity panel tests passed ({len(fns)})")


# ── the three things once called "energy" ───────────────────────────────

def test_the_header_shows_stage_37_energy_not_rotation():
    """Rotation and the vote-split bar were both once labelled Energy while
    Stage 37's actual read — computed every cycle — was shown nowhere."""
    m = _loaded()
    t = _text(PANEL.header_html(m))
    assert "Rotation" in t, "the rotation cell is labelled Rotation"
    assert "Energy" in t, "Stage 37 energy has its own cell"


def test_energy_label_reads_stage_37_state_and_release():
    assert PANEL._energy_label({"state": "COMPRESSION",
                                "release_probability": 72}) == "Coiling 72%"
    assert PANEL._energy_label({"state": "EXPANSION",
                                "release_probability": 0}) == "Releasing"


def test_energy_is_a_dash_when_stage_37_is_silent():
    for en in (None, {}, {"state": None}):
        assert PANEL._energy_label(en) == "—"


def test_the_matrix_carries_stage_37_energy():
    fr = _fr(energy_read={"state": "COMPRESSION", "release_probability": 66})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    assert m["energy"]["state"] == "COMPRESSION"
    assert "Coiling" in _text(PANEL.header_html(m))


def test_the_vote_split_column_is_not_called_energy():
    """It is the bull/bear balance of owned producers, not market energy."""
    html = PANEL.matrix_html(_loaded())
    assert "Balance</th>" in html
    assert "Energy</th>" not in html
