"""The Market Alignment Checklist assembles; it must never compute.

The tests that matter here are not "does it produce rows" — they are the four
ways a view over other people's numbers goes wrong:

1. It invents a value when a producer is quiet (principle 9).
2. It reimplements a rule that already has an owner — here, the option-leg
   inversion in `bias_ball` and the observed vocabulary in `level_acceptance`.
3. It dilutes the vote by counting rows that did not report.
4. It states a behavioural claim ("rejecting") where all it has is arithmetic.

`vob_minimal` boots Streamlit on import, so the wiring checks at the bottom are
source-level, matching the rest of this suite.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import alignment as A
from mios_v5 import bias_ball as BB
from mios_v5 import level_acceptance as LA

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


# ── a spot-and-levels fixture roughly matching a real bearish afternoon ──

def _ss(**over):
    ss = {
        "_nifty_spot_live": 24380.0,
        "_market_picture": {
            "regime": "DOWN", "em": "🔴⬇️", "p_up": 22, "p_down": 58, "p_side": 20,
            "news_bias": {"label": "BEARISH", "net": -3, "n": 11},
            "sector_bias": {"rotation": "RISK-OFF", "breadth": 38},
            "global_bias": {"label": "BEARISH", "score": -1.4},
            "commodity_bias": {"regime": "RISK-OFF"},
            "dex_bias": {"label": "BEARISH"},
            "oi_floor": (24300, 91000), "oi_ceiling": (24400, 120000),
            "oi_pin": (24400, "max OI"),
        },
        "_fii_dii_cash": {"FII": {"net": -2450.0}, "DII": {"net": 1800.0}},
        "_gex_data": {"total_gex": -42.0, "gamma_flip_level": 24420.0},
        "_money_flow_data": {"poc_price": 24360.0},
        "_reaction_sr": {"support": {"price": 24350.0, "strength": 61},
                         "resistance": {"price": 24400.0, "strength": 74}},
        "_la_zones_latest": [
            {"price": 24400.0, "observed": LA.REJECTED, "is_battle_zone": True},
            {"price": 24350.0, "observed": LA.TESTING},
        ],
        "_leg_profiles": {
            "NIFTY": {"hv_points": [{"price": 24310.0, "side": "LOW"},
                                    {"price": 24405.0, "side": "HIGH"}]},
            "CALL": {"hv_points": [{"price": 88.0, "side": "LOW"}]},
            "PUT": {"hv_points": [{"price": 132.0, "side": "HIGH"}]},
            "call_label": "ATM CE 24400", "put_label": "ATM PE 24400"},
        "_atm_leg_ltp": {"ATM CE 24400": 95.0, "ATM PE 24400": 110.0},
        "_atm_leg_vob_volume": {
            "ATM CE 24400": [{"zone_type": "bullish", "mid": 95.0,
                              "status": "BREAKING", "dominant": "sellers",
                              "bull_pct": 31}],
            "ATM PE 24400": [{"zone_type": "bullish", "mid": 110.0,
                              "status": "BUILDING", "dominant": "buyers",
                              "bull_pct": 72}]},
        "_premium_energy": {"energy_score": {"CALL": 42.0, "PUT": 78.0},
                            "premium_bias": "BEARISH"},
    }
    ss.update(over)
    return ss


def _by_check(read, name):
    for r in read["rows"]:
        if r["check"] == name:
            return r
    raise AssertionError(f"no row named {name!r}")


# ── 1 · nothing is invented ──────────────────────────────────────────────────

def test_an_empty_session_reports_every_check_as_not_available():
    """The failure this guards is a checklist that looks confident on a dead
    feed. With no producers at all, every row must be ❓ — not neutral, and
    certainly not a direction."""
    read = A.build({})
    assert read["rows"], "the checklist must still render its rows"
    assert all(r["align"] == A.NA for r in read["rows"])
    s = read["summary"]
    assert (s["bull"], s["bear"], s["neutral"]) == (0, 0, 0)
    assert s["active"] == 0
    assert s["na"] == len(read["rows"])


def test_a_missing_check_says_why_rather_than_disappearing():
    """A dropped row is indistinguishable from a check nobody implemented."""
    for row in A.build({})["rows"]:
        assert row["remark"], f"{row['check']} is ❓ with no reason given"


def test_a_quiet_producer_never_becomes_a_zero():
    """Principle 9: an unmeasured fact is MISSING, never 0. A GEX of exactly
    zero is a real reading (perfectly balanced) and must not look the same as
    a GEX that was never computed."""
    absent = _by_check(A.build(_ss(_gex_data={})), "Dealer GEX")
    assert absent["align"] == A.NA and absent["value"] == "—"
    zero = _by_check(A.build(_ss(_gex_data={"total_gex": 0.0})), "Dealer GEX")
    assert zero["align"] != A.NA
    assert "0" in zero["value"]


def test_nan_is_not_a_reading():
    read = A.build(_ss(_money_flow_data={"poc_price": float("nan")}))
    assert _by_check(read, "NIFTY POC")["align"] == A.NA


# ── 2 · the rules that already have owners are not reimplemented ─────────────

@pytest.mark.parametrize("chart,role,holding,expected", [
    # NIFTY and CALL read straight; PUT inverts. Holding keeps the natural
    # direction, breaking flips it.
    ("NIFTY", "support", True, BB.BULL),
    ("NIFTY", "support", False, BB.BEAR),
    ("NIFTY", "resistance", True, BB.BEAR),
    ("NIFTY", "resistance", False, BB.BULL),
    ("CALL", "support", True, BB.BULL),
    ("CALL", "support", False, BB.BEAR),
    ("PUT", "support", True, BB.BEAR),
    ("PUT", "support", False, BB.BULL),
    ("PUT", "resistance", True, BB.BULL),
])
def test_level_direction_follows_bias_ball_then_flips_on_a_break(
        chart, role, holding, expected):
    assert A._level_align(chart, role, holding) == expected


def test_an_unsettled_level_is_neutral_not_a_weak_direction():
    """TESTING and FAILED_BREAK_WAIT are explicitly 'the market has not decided'
    in `level_acceptance`. Scoring them as a half-vote would put the checklist
    ahead of the engine it is quoting."""
    assert A._level_align("NIFTY", "support", None) == BB.NEUTRAL


def test_the_leg_inversion_is_not_written_here():
    """The PUT flip must come from `bias_ball`, so there is one home for it."""
    src = (pathlib.Path(A.__file__)).read_text()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {getattr(n.func, "attr", "") for n in calls}
    assert "leg_level_bias" in names, "the level rows must funnel through bias_ball"


def test_every_observed_state_in_the_vocabulary_is_handled():
    """If `level_acceptance` grows a seventh word, this fails rather than
    silently rendering it as a blank interaction."""
    vocabulary = {LA.TESTING, LA.BREAK_ATTEMPT, LA.ACCEPTED_ABOVE,
                  LA.ACCEPTED_BELOW, LA.FAILED_BREAK_WAIT, LA.REJECTED}
    assert vocabulary <= set(A._OBSERVED)


def test_the_at_band_matches_the_acceptance_strip():
    """Two definitions of 'at a level' would let the checklist call a level
    tested while the strip beside it calls the same level far away."""
    assert A.AT_BAND == LA.INTERACTION_BAND


# ── 3 · the interaction column is a lookup, with an honest fallback ──────────

def test_an_observed_level_is_quoted_from_the_acceptance_strip():
    read = A.build(_ss())
    res = _by_check(read, "NIFTY Resistance")
    assert "Rejecting" in res["position"]
    assert res["observed"] is True
    assert res["align"] == BB.BEAR       # resistance holding = bearish


def test_a_level_with_no_observation_falls_back_to_geometry_and_says_so():
    """The fallback must be flagged, because 'above a level' is arithmetic and
    'rejecting a level' is a measurement, and the panel dims the difference."""
    read = A.build(_ss(_la_zones_latest=[]))
    res = _by_check(read, "NIFTY Resistance")
    assert res["observed"] is False
    assert "Rejecting" not in res["position"]
    assert "Below" in res["position"] or "Above" in res["position"]


def test_a_far_level_is_neutral_rather_than_held_or_broken():
    """A level 300 points away is neither respected nor broken. Calling it
    either would be the invented claim this module exists to avoid."""
    read = A.build(_ss(_nifty_spot_live=24000.0, _la_zones_latest=[]))
    row = _by_check(read, "NIFTY Resistance")
    assert "Far from" in row["position"]
    assert row["align"] == BB.NEUTRAL


def test_a_battle_zone_level_is_marked_as_one():
    read = A.build(_ss())
    assert "war zone" in _by_check(read, "NIFTY Resistance")["position"]


# ── 4 · the vote is counted honestly ─────────────────────────────────────────

def test_unavailable_checks_are_excluded_from_the_denominator():
    """`active` must count only checks that reported. A cycle where half the
    producers are quiet should read '8 of 11 agree', never '8 of 28' — the
    latter makes a confident read look weak for a reason unrelated to price."""
    read = A.build(_ss())
    s = read["summary"]
    assert s["active"] == s["bull"] + s["bear"] + s["neutral"]
    assert s["na"] > 0
    assert s["active"] + s["na"] + s["info"] == len(read["rows"])


def test_reference_rows_report_a_value_and_still_do_not_vote():
    """Spot and the raw premiums are `info`, not `na`: they reported fine, they
    just have no direction. Folding them into ❓ would make a healthy cycle look
    degraded."""
    read = A.build(_ss())
    spot = _by_check(read, "Spot Price")
    assert spot["align"] == A.INFO
    assert spot["value"] == "₹24,380"
    assert _by_check(read, "CALL LTP Price")["align"] == A.INFO
    assert read["summary"]["info"] >= 3


def test_the_bearish_fixture_reads_bearish_with_its_conflicts_named():
    read = A.build(_ss())
    s = read["summary"]
    assert s["net"] == BB.BEAR
    assert s["bear"] > s["bull"]
    # The dealer magnet pulls up against a bearish tape — exactly the conflict
    # the summary block exists to surface.
    assert any("Charm Pin" in c for c in s["conflicts"])
    assert s["groups"]["GLOBAL"] == BB.BEAR
    assert s["groups"]["OPTIONS"] == BB.BEAR


def test_a_bucket_with_nothing_directional_has_no_verdict():
    """An empty bucket must not report 'mixed', which claims a balance it never
    measured."""
    assert A.build({})["summary"]["groups"]["DEALERS"] == A.NA


def test_a_put_leg_holding_its_support_reads_bearish_for_nifty():
    """The worked example from the request: PUT LTP support at ₹110 holding is
    a BEAR row, because a strong put premium means a falling index."""
    row = _by_check(A.build(_ss()), "PUT LTP Support")
    assert row["align"] == BB.BEAR
    assert "Building" in row["position"]


def test_a_call_leg_losing_its_support_also_reads_bearish():
    row = _by_check(A.build(_ss()), "CALL LTP Support")
    assert row["align"] == BB.BEAR
    assert "Breaking" in row["position"]


def test_leg_hvp_bands_scale_with_the_premium():
    """₹5 is a touch on a ₹300 leg and a different world on a ₹20 one, so the
    leg bands are a fraction of the premium, not index points."""
    cheap = A.build(_ss(_atm_leg_ltp={"ATM CE 24400": 20.0, "ATM PE 24400": 110.0},
                        _leg_profiles=dict(_ss()["_leg_profiles"],
                                           CALL={"hv_points": [{"price": 25.0,
                                                                "side": "HIGH"}]})))
    rich = A.build(_ss(_atm_leg_ltp={"ATM CE 24400": 300.0, "ATM PE 24400": 110.0},
                       _leg_profiles=dict(_ss()["_leg_profiles"],
                                          CALL={"hv_points": [{"price": 305.0,
                                                               "side": "HIGH"}]})))
    # The same ₹5 gap, read twice: a quarter of the way across a ₹20 leg (out
    # of play), and 1.7% of a ₹300 one (still in play, so it votes).
    cheap_row = _by_check(cheap, "CALL HVP HIGH")
    rich_row = _by_check(rich, "CALL HVP HIGH")
    assert "Far from" in cheap_row["position"]
    assert cheap_row["align"] == BB.NEUTRAL
    assert "Far from" not in rich_row["position"]
    assert rich_row["align"] != BB.NEUTRAL

    # And the band really is proportional, not a fixed number of rupees: on the
    # ₹300 leg a ₹1 gap is inside the "at the line" band that ₹5 sat outside.
    at_line = A.build(_ss(_atm_leg_ltp={"ATM CE 24400": 300.0, "ATM PE 24400": 110.0},
                          _leg_profiles=dict(_ss()["_leg_profiles"],
                                             CALL={"hv_points": [{"price": 301.0,
                                                                  "side": "HIGH"}]})))
    assert "At" in _by_check(at_line, "CALL HVP HIGH")["position"]


# ── 5 · it is a view, not an engine ──────────────────────────────────────────

def test_the_module_computes_no_market_data():
    """No pandas, no numpy, no network, no candle maths. If any of these appear,
    the checklist has started being a second engine."""
    src = pathlib.Path(A.__file__).read_text()
    for banned in ("import pandas", "import numpy", "import requests",
                   "import streamlit", "calculate_money_flow_profile",
                   "compute_vpfr", "detect_hvp", "VolumeOrderBlocks"):
        assert banned not in src, f"alignment.py must not reference {banned}"


def test_it_never_imports_the_app():
    """`mios_v5` may not import `vob_minimal` — it boots Streamlit and reads
    secrets. The whole dependency direction rests on this."""
    for mod in (A.__file__,
                pathlib.Path(A.__file__).parent / "ui" / "alignment_panel.py"):
        assert "vob_minimal" not in pathlib.Path(mod).read_text()


def test_build_does_not_mutate_the_state_it_reads():
    ss = _ss()
    before = {k: repr(v) for k, v in ss.items()}
    A.build(ss)
    assert {k: repr(v) for k, v in ss.items()} == before


def test_build_survives_garbage_in_every_slot():
    """Every producer is defensive elsewhere in the app; a malformed publish
    must degrade this table to ❓, not raise inside the render."""
    junk = {k: "not-a-dict" for k in
            ("_market_picture", "_gex_data", "_money_flow_data", "_reaction_sr",
             "_leg_profiles", "_atm_leg_vob_volume", "_atm_leg_ltp",
             "_premium_energy", "_fii_dii_cash", "_la_zones_latest")}
    junk["_nifty_spot_live"] = "nonsense"
    read = A.build(junk)
    assert read["rows"]
    assert all(r["align"] in (A.NA, A.INFO, BB.NEUTRAL) for r in read["rows"])


# ── 6 · the wiring in the app ────────────────────────────────────────────────

def test_the_panel_is_drawn_above_the_trade_card(source: str):
    """Position: the checklist is the 'does everything agree?' read the card's
    verdict rests on, so its container is claimed first."""
    assert source.index("_alignment_container = st.container()") < \
        source.index("_card_container = st.container()")


def test_the_panel_is_filled_after_the_v6_render(source: str):
    """Order of computation, which is the opposite of position and is the whole
    reason the container is claimed early and filled late: the checklist reads
    `_leg_profiles`, and Dashboard V6 publishes it while it draws. Filling it
    with the rest of the card stack would pair last cycle's HVP lines with this
    cycle's spot."""
    render_v6 = source.index("render_dashboard_v6(state=")
    fill = source.index("_render_alignment(")
    assert render_v6 < fill, "the checklist must be built after V6 publishes"
    # and it must be the CONTAINER claimed up top that it draws into, not a
    # fresh one here — otherwise it renders below V6 and the position is lost.
    assert "slot=_alignment_container" in source


def test_the_leg_ltp_is_published_where_it_is_already_computed(source: str):
    """The premium is published as a plain float so a pure module can read it
    without taking a pandas dependency — and from the line that already has the
    number, so nothing is recomputed."""
    assert "st.session_state['_atm_leg_ltp'][name] = ltp" in source
    # and reset with the other per-cycle leg stores, so a drifting ATM strike
    # cannot leave a stale premium behind
    reset = source.index("'_atm_leg_ltf_delta', '_atm_leg_ltp'")
    assert reset < source.index("st.session_state['_atm_leg_ltp'][name] = ltp")


def test_the_why_line_quotes_evidence_not_a_dash():
    """A context row has no level to be at, so its evidence is its value. Taking
    `position` unconditionally printed "News — —" — a dash quoted as a reason."""
    s = A.build(_ss())["summary"]
    assert s["why"], "a directional net read must say what supports it"
    for phrase in s["why"] + s["conflicts"]:
        assert "— —" not in phrase
        assert not phrase.endswith("—")
