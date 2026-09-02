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
        # the real shape: Stage 71.7 publishes its downstream contract under
        # ["bridge"] (premium_energy.BRIDGE_KEYS), not at the top level
        "_premium_energy": {"bridge": {"energy_score": {"CALL": 42.0, "PUT": 78.0},
                                       "preferred_premium": "Prefer PUT"}},
        "_cached_option_data": {"max_pain_strike": 24400.0},
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


def test_a_far_barrier_reads_as_room_not_as_a_hold_or_a_break():
    """A resistance 300 points away is neither respected nor broken — but it is
    not silent either. It is not in the way, and that is the read: room above.
    The hold/break rule must not be what answers here."""
    read = A.build(_ss(_nifty_spot_live=24000.0, _la_zones_latest=[]))
    row = _by_check(read, "NIFTY Resistance")
    assert row["align"] == BB.BULL
    assert "Clear of" in row["position"]


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
    assert s["groups"]["STRUCTURE"] == BB.BEAR
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
    """The same ₹12 gap is most of a ₹20 leg and a rounding error on a ₹300
    one, so the bands are a fraction of the premium, not a number of rupees."""
    def _call_hvp(ltp, pivot):
        return _by_check(A.build(_ss(
            _atm_leg_ltp={"ATM CE 24400": ltp, "ATM PE 24400": 110.0},
            _leg_profiles=dict(_ss()["_leg_profiles"],
                               CALL={"hv_points": [{"price": pivot,
                                                    "side": "HIGH"}]}))),
            "CALL HVP HIGH")

    cheap = _call_hvp(20.0, 32.0)      # ₹12 away — 60% of the premium
    rich = _call_hvp(300.0, 312.0)     # ₹12 away — 4% of the premium
    # the cheap leg is CLEAR of its pivot (room to run); the rich one is still
    # underneath it and reads as a hold/break
    assert "Clear of" in cheap["position"]
    assert "Clear of" not in rich["position"]
    assert "Below" in rich["position"]

    # And it is proportional at the tight end too: on the ₹300 leg a ₹1 gap is
    # inside the "at the line" band.
    assert "At" in _call_hvp(300.0, 301.0)["position"]


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

def test_the_trade_card_is_drawn_first(source: str):
    """The order of the page is the order a trader asks the questions: what do
    I do → why → at which levels → what are the premiums doing → every check.
    Analysis above the decision makes the decision something you scroll to."""
    assert source.index("_card_container = st.container()") < \
        source.index("_alignment_container = st.container()")


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


# ── 7 · the four key-path bugs that emptied the OPTION PREMIUM section ───────
#
# Every one of these shipped green: the rows rendered, said "not published",
# and were wrong. A test that only asserts "a row exists" cannot catch a lookup
# into a key nobody writes — so each of these pins the path to its real owner.

def test_premium_energy_is_read_off_the_bridge():
    """Stage 71.7 publishes `energy_score` under ["bridge"], its declared
    downstream contract. Reading it at the top level finds nothing on every
    cycle, which is what made this row say "not published" beside a panel
    drawing the same numbers."""
    from mios_v5 import premium_energy as PE
    assert "energy_score" in PE.BRIDGE_KEYS
    row = _by_check(A.build(_ss()), "Premium Energy")
    assert row["align"] != A.NA
    assert "42" in row["value"] and "78" in row["value"]


def test_premium_energy_falls_back_to_the_side_scores():
    """If the bridge is ever reshaped, the row degrades to the internal shape
    rather than blanking."""
    read = A.build(_ss(_premium_energy={
        "sides": {"CALL": {"energy": 60.0}, "PUT": {"energy": 20.0}}}))
    row = _by_check(read, "Premium Energy")
    assert row["align"] == BB.BULL


@pytest.mark.parametrize("preferred,expected", [
    ("Prefer CALL", BB.BULL),
    ("Prefer PUT", BB.BEAR),
    # the engine declining to call it is an answer, not a gap to fill from the
    # raw scores — which would overrule the stage that just abstained
    ("No Edge", BB.NEUTRAL),
    ("Avoid Both", BB.NEUTRAL),
    (None, BB.BEAR),          # no verdict → the scores decide (PUT 78 > CE 42)
])
def test_the_premium_preference_maps_to_a_nifty_direction(preferred, expected):
    assert A._prefer_align(preferred, 42.0, 78.0) == expected


def test_direction_bias_would_not_have_understood_the_preference():
    """Guards the reason `_prefer_align` exists: bias_ball reads BULL/BEAR/UP/
    DOWN words and has never seen "Prefer CALL", so routing the preference
    through it returned neutral for every cycle."""
    assert BB.direction_bias("Prefer CALL") == BB.NEUTRAL
    assert A._prefer_align("Prefer CALL", None, None) == BB.BULL


def test_the_leg_name_comes_from_the_store_that_holds_the_data():
    """The cascade: `_atm_leg_ltp` / `_atm_leg_vob_volume` are filled at step 7,
    `_leg_profiles` (and its labels) only later by the charts tab. Taking the
    name from the late producer emptied every option row whenever it had not
    published — while the premiums sat in session state throughout."""
    ss = _ss()
    ss.pop("_leg_profiles")
    read = A.build(ss)
    assert _by_check(read, "CALL LTP Price")["value"] == "₹95.00"
    assert _by_check(read, "PUT LTP Support")["align"] == BB.BEAR


def test_a_stale_published_label_is_not_preferred_over_a_live_leg():
    """The ATM strike drifts and the stores are rebuilt around the new one, so
    a label held over from an earlier cycle can name a strike no longer loaded.
    Preferring it blindly reproduces the empty section around the drift."""
    read = A.build(_ss(_leg_profiles={"call_label": "ATM CE 24300",
                                      "put_label": "ATM PE 24300"}))
    assert _by_check(read, "CALL LTP Price")["value"] == "₹95.00"


def test_the_published_label_wins_when_it_names_a_live_leg():
    """When the charts did resolve a leg, this table must describe that leg —
    not a different one it picked itself."""
    ss = _ss()
    ss["_atm_leg_ltp"] = {"ATM CE 24400": 95.0, "ATM+1 CE 24450": 60.0,
                          "ATM PE 24400": 110.0}
    ss["_leg_profiles"] = dict(ss["_leg_profiles"],
                               call_label="ATM+1 CE 24450")
    assert _by_check(A.build(ss), "CALL LTP Price")["value"] == "₹60.00"


def test_the_leg_key_rule_has_one_owner():
    """`terminal_chart.atm_legs` and this module must pick the same leg. The
    rule is about key names, so it lives in `leg_keys` and both call it."""
    from mios_v5 import leg_keys as LK
    from mios_v5.ui import terminal_chart as TC
    keys = ["ATM+1 CE 24450", "ATM CE 24400", "ATM PE 24400", "sid_9999"]
    assert LK.call_put(keys) == ("ATM CE 24400", "ATM PE 24400")
    # the chart helper delegates rather than keeping a second copy
    assert "_call_put" in pathlib.Path(TC.__file__).read_text()
    _, _, ce, pe = TC.atm_legs({k: object() for k in keys})
    assert (ce, pe) == LK.call_put(keys)


def test_security_id_mirrors_are_never_mistaken_for_a_leg():
    """Several stores hold each leg twice — once by name, once by `sid_…`. A
    security id is not a leg name."""
    from mios_v5 import leg_keys as LK
    assert LK.pick(["sid_54321"], "CE") is None


def test_the_magnet_reports_on_a_non_expiry_day():
    """`charm_pin` returns {"active": False, "reason": "not expiry day"} by
    design — it is the expiry-day charm read. `dealer_magnet` exists because
    the magnet itself matters on the other four days, and calling the wrong one
    made this row ❓ for most of every week."""
    from mios_v5 import charm_pin as CP
    assert CP.read(False, 24380.0, 24400.0).get("active") is False
    row = _by_check(A.build(_ss(_is_expiry_today=False)), "Charm Pin / Magnet")
    assert row["align"] != A.NA
    assert "24,400" in row["position"]


def test_max_pain_is_read_from_the_option_chain():
    """`_market_picture` has no `max_pain` key — `analyze_option_chain`
    publishes `max_pain_strike`. Passing mp.get("max_pain") handed the pin
    chooser None and left it one candidate instead of two."""
    ss = _ss()
    ss["_market_picture"] = dict(ss["_market_picture"], oi_pin=None)
    row = _by_check(A.build(ss), "Charm Pin / Magnet")
    assert row["align"] != A.NA, "max pain should still supply the magnet"
    assert "24,400" in row["value"]


def test_a_missing_leg_premium_does_not_blame_the_pivots():
    """The HVP row used to report "no high-volume pivots on this leg" when the
    premium was the missing half — sending a reader to `volume_points` for a
    fault one store away."""
    ss = _ss()
    ss["_atm_leg_ltp"] = {}
    row = _by_check(A.build(ss), "PUT HVP HIGH")
    assert "premium" in row["remark"]
    assert "no high-volume pivots" not in row["remark"]


# ── 8 · precision and reach, from a live expiry afternoon ────────────────────
#
# Both of these shipped rendering plausible-looking rows. The first displayed
# three different prices as the same number; the second cast a real vote from a
# level the premium could not reach.

def _expiry_ss(**over):
    """A near-expiry leg pair: the CALL at ₹5.75, the PUT at 5 paise, and both
    carrying VOB zones from earlier in the session when they were worth more."""
    ss = {
        "_nifty_spot_live": 24055.0,
        "_market_picture": {"regime": "SIDEWAYS"},
        "_atm_leg_ltp": {"ATM CE 24050": 5.75, "ATM PE 24050": 0.05},
        "_atm_leg_vob_volume": {
            "ATM CE 24050": [{"zone_type": "bearish", "mid": 84.0,
                              "status": "INTACT", "dominant": "balanced",
                              "bull_pct": 50}],
            "ATM PE 24050": [{"zone_type": "bearish", "mid": 34.0,
                              "status": "FADING", "dominant": "balanced",
                              "bull_pct": 58}]},
        "_leg_profiles": {
            "CALL": {"hv_points": [{"price": 15.60, "side": "HIGH"},
                                   {"price": 7.50, "side": "LOW"}]},
            "PUT": {"hv_points": [{"price": 30.90, "side": "HIGH"},
                                  {"price": 0.03, "side": "LOW"},
                                  {"price": 0.04, "side": "LOW"}]},
            "call_label": "ATM CE 24050", "put_label": "ATM PE 24050"},
    }
    ss.update(over)
    return ss


def test_a_premium_keeps_its_paise():
    """"₹0 · ₹0" was three different prices — a 5-paise leg and its pivots at
    ₹0.03 and ₹0.04 — all rounded to zero, on the afternoon those are exactly
    the prices being decided."""
    row = _by_check(A.build(_expiry_ss()), "PUT HVP LOW")
    assert row["value"] == "₹0.04 · ₹0.03"
    assert "₹0.04" in row["position"]


def test_an_index_level_keeps_whole_rupees():
    """The same formatter must not put paise on a 24,000-point index level."""
    assert _by_check(A.build(_ss()), "NIFTY Support")["value"] == "₹24,350"
    assert A._rupees(24350.0) == "₹24,350"
    assert A._rupees(0.05) == "₹0.05"
    assert A._rupees(84.0) == "₹84.00"


def test_both_columns_round_a_price_the_same_way():
    """The value column said "₹31" while the position column beside it called
    the same pivot "₹30.90", because two call sites rounded it differently."""
    row = _by_check(A.build(_expiry_ss()), "PUT HVP HIGH")
    assert "₹30.90" in row["value"]
    assert "₹30.90" in row["position"]


def test_an_out_of_reach_zone_is_read_as_room_not_by_its_stale_status():
    """The guard that still matters. `analyze_vob_volume`'s status describes
    what the flow did INSIDE the zone — it is not a claim about a premium that
    has since left it. A CALL at ₹5.75 carried a zone at ₹84 marked INTACT, and
    quoting that as a live verdict voted BEAR from fifteen times away.

    Under the room rule it votes BULL, for the opposite reason: the premium is
    clear of that resistance. The status is not consulted at all, which is the
    thing being asserted — the direction now comes from distance, not from a
    reading of a zone price has left."""
    row = _by_check(A.build(_expiry_ss()), "CALL LTP Resistance")
    assert row["align"] == BB.BULL
    assert "Clear of" in row["position"]
    assert "intact" not in row["remark"].lower(), "stale status must not be quoted"
    assert "₹84.00" in row["value"]


def test_a_leg_zone_in_reach_still_votes():
    """The gate must not silence a zone the premium is actually at."""
    ss = _expiry_ss(_atm_leg_ltp={"ATM CE 24050": 83.0, "ATM PE 24050": 0.05})
    row = _by_check(A.build(ss), "CALL LTP Resistance")
    assert row["align"] == BB.BEAR       # CALL resistance holding = bearish
    assert "Intact" in row["position"]


def test_the_leg_bands_are_shared_by_the_zone_and_pivot_rows():
    """Two definitions of 'near' would let one row call a level in play while
    the row beneath it calls the same distance far away."""
    at, near = A._leg_bands(100.0)
    assert (at, near) == (0.5, 50.0)
    # and the floors keep a near-worthless expiry leg from having no band
    assert A._leg_bands(0.05) == (0.25, 0.5)


@pytest.mark.parametrize("price,level,expected", [
    (100.0, 99.9, (None, None)),        # inside the at-band — unsettled
    (100.0, 99.0, (A.ABOVE, True)),     # near and above
    (100.0, 101.0, (A.ABOVE, False)),   # near and below
    (100.0, 20.0, (A.FAR, None)),       # 80% away — not in the way
])
def test_distance_reports_which_side_and_whether_it_counts(price, level, expected):
    """The verdict is a side, not a direction — `_holding` turns it into one
    once it knows the role."""
    at, near = A._leg_bands(price)
    assert A._distance_word(price, level, at, near)[2] == expected


def test_a_working_engine_that_found_nothing_is_not_called_unpublished():
    """"not published" is a plumbing claim. `analyze_vob_volume` returning only
    bearish zones is a real market state — common near expiry, when nothing has
    built below the premium — and reporting it as a missing producer sends the
    reader to the store instead of the chart."""
    row = _by_check(A.build(_expiry_ss()), "CALL LTP Support")
    assert "found no support zone" in row["remark"]
    assert "not published" not in row["remark"]
    # a leg with no zones at all still says so plainly
    ss = _expiry_ss(_atm_leg_vob_volume={"ATM CE 24050": []})
    assert "no VOB zones published" in _by_check(
        A.build(ss), "CALL LTP Support")["remark"]


def test_the_energy_row_distinguishes_absent_from_empty():
    """Two faults needing two different people: the stage never ran, or it ran
    and scored nothing."""
    absent = _by_check(A.build(_expiry_ss()), "Premium Energy")
    assert "has not published" in absent["remark"]
    empty = _by_check(A.build(_expiry_ss(_premium_energy={"bridge": {}})),
                      "Premium Energy")
    assert "no energy score" in empty["remark"]


# ── 9 · every resistance row was voting backwards ───────────────────────────
#
# Reported from a live summary: "War Zone Resistance — 🟢 Above ₹24,046 (+10)"
# appeared under WHY, supporting a BEARISH net read. Price ten points ABOVE a
# resistance means that resistance broke, which is bullish. Both sources of the
# interaction column report which SIDE of the level price is on, and every call
# site was reading that as "the level held" — right for a support, exactly
# inverted for a resistance.

@pytest.mark.parametrize("role,above,expected", [
    # a support holds while price is above it …
    ("support", True, True),
    ("support", False, False),
    # … a resistance is the mirror: it holds while price is BELOW
    ("resistance", True, False),
    ("resistance", False, True),
    # the VOB spellings normalise the same way bias_ball accepts them
    ("bullish", True, True),
    ("bearish", True, False),
])
def test_which_side_price_is_on_resolves_against_the_role(role, above, expected):
    assert A._holding(role, (A.ABOVE, above)) is expected


@pytest.mark.parametrize("role", ["support", "resistance"])
def test_a_rejection_reads_the_same_whatever_the_role(role):
    """REJECTED and BREAK_ATTEMPT are statements about the LEVEL — it did or did
    not do its job — so they must not be flipped by the role the way a
    side-of-the-level verdict is."""
    assert A._holding(role, (A.HELD, True)) is True
    assert A._holding(role, (A.HELD, False)) is False


def test_an_unsettled_verdict_stays_unsettled():
    assert A._holding("resistance", (None, None)) is None


def test_price_above_a_resistance_is_bullish():
    """The reported bug, end to end: spot ₹24,056 against a resistance at
    ₹24,046 is a broken resistance, and broken resistance is bullish."""
    ss = {"_nifty_spot_live": 24056.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"support": {"price": 24000.0},
                           "resistance": {"price": 24046.0}}}
    assert _by_check(A.build(ss), "NIFTY Resistance")["align"] == BB.BULL


def test_price_below_a_resistance_is_bearish():
    """And the mirror still works — a resistance price is sitting under is
    capping it."""
    ss = {"_nifty_spot_live": 24036.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"support": {"price": 24000.0},
                           "resistance": {"price": 24046.0}}}
    assert _by_check(A.build(ss), "NIFTY Resistance")["align"] == BB.BEAR


def test_a_support_is_unaffected_by_the_fix():
    """Supports were always right; the fix must not move them."""
    ss = {"_nifty_spot_live": 24056.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"support": {"price": 24050.0},
                           "resistance": {"price": 24200.0}}}
    assert _by_check(A.build(ss), "NIFTY Support")["align"] == BB.BULL


def test_an_accepted_above_on_a_resistance_is_a_break_not_a_hold():
    """`level_acceptance.ACCEPTED_ABOVE` means price settled above the level —
    on a resistance that is the break, not the hold."""
    ss = {"_nifty_spot_live": 24056.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"support": {"price": 24000.0},
                           "resistance": {"price": 24054.0}},
          "_la_zones_latest": [{"price": 24054.0,
                                "observed": LA.ACCEPTED_ABOVE}]}
    row = _by_check(A.build(ss), "NIFTY Resistance")
    assert row["observed"] is True
    assert row["align"] == BB.BULL


def test_an_index_high_pivot_above_spot_caps_and_below_spot_is_broken():
    """HVP HIGH is a resistance line — `bias_ball.hvp_bias` says so — and had
    the same inversion."""
    def _hvp(spot, pivot):
        ss = {"_nifty_spot_live": spot, "_market_picture": {"regime": "SIDEWAYS"},
              "_leg_profiles": {"NIFTY": {"hv_points": [{"price": pivot,
                                                         "side": "HIGH"}]}}}
        return _by_check(A.build(ss), "NIFTY HVP HIGH")["align"]
    assert _hvp(24056.0, 24040.0) == BB.BULL     # cleared it
    assert _hvp(24036.0, 24050.0) == BB.BEAR     # still under it


def test_a_call_leg_above_its_high_pivot_is_bullish_for_nifty():
    """The leg rows share `_distance_word`, so they carried the same bug — and
    then the PUT inversion sits on top of it."""
    ss = _expiry_ss(_atm_leg_ltp={"ATM CE 24050": 20.0, "ATM PE 24050": 0.05},
                    _leg_profiles={"CALL": {"hv_points": [{"price": 19.50,
                                                           "side": "HIGH"}]},
                                   "call_label": "ATM CE 24050",
                                   "put_label": "ATM PE 24050"})
    # CALL premium above its high pivot = broken resistance on the call =
    # call strengthening = NIFTY bullish
    assert _by_check(A.build(ss), "CALL HVP HIGH")["align"] == BB.BULL


# ── 10 · no general context ─────────────────────────────────────────────────
#
# News, FII/DII, sector rotation, global indices and the commodity regime were
# on this table and are gone — from the rows AND from the tally. Every row is
# one equal vote, so five slow once-a-day context reads could outvote the level
# interactions the table exists to show: a summary read BEARISH on FII/DII and
# commodities while STRUCTURE, the levels themselves, read BULLISH.

def test_the_table_carries_only_levels_and_what_price_does_at_them():
    sections = {r["group"] for r in A.build(_ss())["rows"]}
    assert sections == {A.STRUCTURE, A.PREMIUM, A.FINAL}
    assert "GENERAL CONTEXT" not in sections


@pytest.mark.parametrize("gone", ["News", "FII / DII", "Sector", "Global",
                                  "Commodity", "Regime"])
def test_a_context_check_no_longer_appears(gone):
    assert gone not in {r["check"] for r in A.build(_ss())["rows"]}


def test_context_cannot_reach_the_tally():
    """The point of the removal. A session rich in context and empty of levels
    must produce no vote at all — previously it produced a confident one."""
    read = A.build({
        "_market_picture": {
            "regime": "DOWN",
            "news_bias": {"label": "BEARISH", "net": -3, "n": 11},
            "sector_bias": {"rotation": "RISK-OFF", "breadth": 38},
            "global_bias": {"label": "BEARISH", "score": -1.4},
            "commodity_bias": {"regime": "RISK-OFF"}},
        "_fii_dii_cash": {"FII": {"net": -7986.0}, "DII": {"net": 4589.0}}})
    s = read["summary"]
    assert (s["bull"], s["bear"]) == (0, 0)
    assert s["active"] == 0


def test_the_buckets_that_only_context_fed_are_gone():
    """A bucket with no possible producer renders as a permanent 'not
    reporting' chip — it says nothing and reads like a fault."""
    assert A.BUCKETS == (A.B_STRUCTURE, A.B_OPTIONS, A.B_DEALERS)
    groups = A.build(_ss())["summary"]["groups"]
    assert "FLOW" not in groups and "GLOBAL" not in groups
    assert set(groups) == set(A.BUCKETS)


def test_no_row_claims_a_bucket_that_does_not_exist():
    """Guards the reverse mistake: a row bucketed FLOW would vanish from every
    per-group verdict while still counting in the totals."""
    for r in A.build(_ss())["rows"]:
        assert r["bucket"] in A.BUCKETS, f"{r['check']} → {r['bucket']}"


# ── 11 · a leg's band is a percentage of a LEVERAGED price ──────────────────
#
# Reported: a call at ₹5.75 with its high-volume pivots at ₹7.50 and ₹8.35 read
# "⚪ Far from ₹7.50". Those are ₹1.75 and ₹2.60 from the premium — thirty and
# forty-five per cent — which is an ordinary morning for an option and plainly
# in front of the price.

@pytest.mark.parametrize("ltp,level,expect_in_play,pct", [
    (5.75, 7.50, True, 30),         # the reported case
    (5.75, 8.35, True, 45),
    (5.75, 15.60, False, 171),      # a 171% move is not "near"
    (5.75, 84.00, False, 1361),     # the stale zone the gate exists for
    (110.0, 132.0, True, 20),
    (0.05, 30.90, False, 61700),
])
def test_a_leg_level_is_in_play_by_percentage_of_its_own_premium(
        ltp, level, expect_in_play, pct):
    at, near = A._leg_bands(ltp)
    gap = abs(level - ltp)
    assert round(gap / ltp * 100) == pct, "fixture drifted"
    assert (gap <= near) is expect_in_play


def test_the_reported_call_pivot_now_votes():
    """End to end on the reported values: ₹5.75 call, pivots at ₹7.50/₹8.35."""
    ss = _expiry_ss(_atm_leg_ltp={"ATM CE 24050": 5.75, "ATM PE 24050": 0.05},
                    _leg_profiles={"CALL": {"hv_points": [
                        {"price": 7.50, "side": "LOW"},
                        {"price": 8.35, "side": "LOW"},
                        {"price": 15.60, "side": "HIGH"}]},
                        "call_label": "ATM CE 24050",
                        "put_label": "ATM PE 24050"})
    low = _by_check(A.build(ss), "CALL HVP LOW")
    assert "Clear of" not in low["position"]      # in play — read as a level
    assert low["align"] == BB.BEAR                # premium under its own support
    # the line 171% away is out of reach, and that is now its own read: the
    # premium is clear of that resistance, so it has room above
    high = _by_check(A.build(ss), "CALL HVP HIGH")
    assert high["align"] == BB.BULL
    assert "Clear of" in high["position"]


def test_a_zone_in_reach_is_read_by_its_status_and_one_out_of_reach_is_not():
    """The band still decides WHICH rule answers, even though both now vote."""
    near = _by_check(A.build(_expiry_ss(
        _atm_leg_ltp={"ATM CE 24050": 83.0, "ATM PE 24050": 0.05})),
        "CALL LTP Resistance")
    far = _by_check(A.build(_expiry_ss()), "CALL LTP Resistance")
    assert "Intact" in near["position"]        # status read
    assert "Clear of" in far["position"]       # room read
    assert near["align"] != far["align"]


# ── 12 · an OI wall is ROOM, not a level price is holding or breaking ───────
#
# Every other row asks "did this level hold or break". A wall asks how much
# room there is before the writers are in the way — the strike barely moves, so
# what changes through the day is the distance to it, and that distance is the
# read. Both directions invert against the naive reading, which is exactly why
# the position-based rule got the near cases backwards.

@pytest.mark.parametrize("check,wall,spot,expected,why", [
    # the CAP: close overhead is the thing stopping the move …
    ("CALL Wall OI", 24400, 24400, BB.BEAR, "sitting on the cap"),
    ("CALL Wall OI", 24400, 24380, BB.BEAR, "20 pts under the cap"),
    ("CALL Wall OI", 24400, 24420, BB.BEAR, "20 pts over, still in its shadow"),
    # … and far away is headroom
    ("CALL Wall OI", 24400, 24200, BB.BULL, "200 pts of room to run"),
    # the FLOOR: close underfoot is writers defending …
    ("PUT Wall OI", 24300, 24300, BB.BULL, "sitting on the floor"),
    ("PUT Wall OI", 24300, 24320, BB.BULL, "20 pts above the floor"),
    ("PUT Wall OI", 24300, 24280, BB.BULL, "20 pts under, still supported"),
    # … and far away is air beneath the market
    ("PUT Wall OI", 24300, 24500, BB.BEAR, "200 pts of nothing below"),
])
def test_a_wall_is_scored_by_how_much_room_it_leaves(check, wall, spot,
                                                     expected, why):
    is_pe = check.startswith("PUT")
    ss = {"_nifty_spot_live": float(spot),
          "_market_picture": {"regime": "SIDEWAYS",
                              "oi_floor": (wall, 9e4) if is_pe else None,
                              "oi_ceiling": (wall, 9e4) if not is_pe else None}}
    assert _by_check(A.build(ss), check)["align"] == expected, why


def test_at_and_near_a_wall_are_the_same_answer():
    """Price sitting on a cap and price twenty points under it are the same
    trading fact — the cap is in the way. Splitting them would produce a
    neutral row at the one distance the wall matters most."""
    def _wall(spot):
        ss = {"_nifty_spot_live": float(spot),
              "_market_picture": {"regime": "SIDEWAYS",
                                  "oi_ceiling": (24400, 9e4)}}
        return _by_check(A.build(ss), "CALL Wall OI")["align"]
    assert _wall(24400) == _wall(24380) == _wall(24399) == BB.BEAR


def test_a_wall_never_abstains():
    """A wall always has a reading — it is either in the way or it is not.
    There is no distance at which it says nothing."""
    for spot in (24000, 24395, 24400, 24405, 25000):
        ss = {"_nifty_spot_live": float(spot),
              "_market_picture": {"regime": "SIDEWAYS",
                                  "oi_ceiling": (24400, 9e4)}}
        row = _by_check(A.build(ss), "CALL Wall OI")
        assert row["align"] in (BB.BULL, BB.BEAR), spot


def test_the_wall_wording_matches_its_score():
    """"Far from ₹24,400" beside 🟢 Bull was a contradiction on one line. The
    text now names what the wall IS from here, which is the thing that votes."""
    def _pos(spot, key, wall):
        ss = {"_nifty_spot_live": float(spot),
              "_market_picture": {"regime": "SIDEWAYS", key: (wall, 9e4)}}
        check = "CALL Wall OI" if key == "oi_ceiling" else "PUT Wall OI"
        return _by_check(A.build(ss), check)["position"]
    assert "Cap in the way" in _pos(24380, "oi_ceiling", 24400)
    assert "Cap clear" in _pos(24200, "oi_ceiling", 24400)
    assert "Floor underfoot" in _pos(24320, "oi_floor", 24300)
    assert "Floor distant" in _pos(24500, "oi_floor", 24300)
    assert "Far from" not in _pos(24200, "oi_ceiling", 24400)


def test_a_wall_does_not_go_through_the_hold_or_break_rule():
    """Guards the confusion this replaced: the walls have their own builder, so
    a future change to the S/R rule cannot silently re-score them."""
    src = pathlib.Path(A.__file__).read_text()
    assert "def _wall_row(" in src
    assert "_wall_row(\"PUT Wall OI\"" in src
    assert "_wall_row(\"CALL Wall OI\"" in src


def test_only_a_value_anchor_abstains_when_far():
    """Barriers — S/R, walls, pivots, VOB zones — are things price can be CLEAR
    of, so distance is a direction. A value anchor is not: being far above the
    POC is bullish and far below it bearish, which is the position rule, and
    running the room rule over it would report "no POC nearby" as a direction."""
    ss = {"_nifty_spot_live": 24380.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"support": {"price": 24000.0},
                           "resistance": {"price": 24800.0}},
          "_money_flow_data": {"poc_price": 24100.0},
          "_gex_data": {"gamma_flip_level": 24900.0}}
    # barriers report
    assert _by_check(A.build(ss), "NIFTY Resistance")["align"] == BB.BULL
    assert _by_check(A.build(ss), "NIFTY Support")["align"] == BB.BEAR
    # value / regime anchors keep the position rule and abstain when far
    for check in ("NIFTY POC", "Gamma Flip"):
        row = _by_check(A.build(ss), check)
        assert row["align"] == BB.NEUTRAL, check
        assert "Far from" in row["position"], check


# ── 13 · there is ONE war zone ──────────────────────────────────────────────
#
# Stage 35 publishes `battle_zone = {"type": "SUPPORT"|"RESISTANCE", "price"}`:
# a single contested price and the side the fight is running from. The type is
# not a property of the price — it flips when the fight does.
#
# The table had a "War Zone Support" row and a "War Zone Resistance" row, built
# from `low`/`high` keys that do not exist on that object. The fallback fired on
# every cycle and put the SAME price on two rows, voting in opposite directions.

def _war(bz=None, winner=None, probs=None, spot=24302.0):
    return A._final({"battle_zone": bz, "expected_winner": winner,
                     "probabilities": probs or {}}, {}, spot, [])[0]


def test_there_is_exactly_one_war_zone_row():
    checks = [r["check"] for r in A.build(_ss())["rows"]]
    assert checks.count("War Zone") == 1
    assert "War Zone Support" not in checks
    assert "War Zone Resistance" not in checks


def test_the_battle_zone_has_no_band_to_split():
    """The producer's own shape is the argument: one price, one type, no edges.
    If Stage 35 ever grows a band this test fails and the split can be
    reconsidered — until then, inventing one is fabricating a level."""
    src = pathlib.Path(
        A.__file__).parent.joinpath("engines/stage35_reaction_zone.py").read_text()
    assert '"battle_zone": {"type": zone_type, "price": zone_price}' in src


@pytest.mark.parametrize("kind,winner,expected", [
    # the SAME support zone, read by who is winning the fight at it
    ("SUPPORT", "Buyers (bounce)", BB.BULL),
    ("SUPPORT", "Sellers (breakdown)", BB.BEAR),
    # and the same resistance zone likewise
    ("RESISTANCE", "Sellers (rejection)", BB.BEAR),
    ("RESISTANCE", "Buyers (breakout)", BB.BULL),
])
def test_one_zone_changes_side_with_the_war(kind, winner, expected):
    assert _war({"type": kind, "price": 24300}, winner)["align"] == expected


def test_contested_is_an_answer_not_a_gap():
    """Stage 35 declining to call the fight is a verdict. Falling through to
    the hold/break rule would overrule the engine that just abstained."""
    row = _war({"type": "SUPPORT", "price": 24300}, "Contested")
    assert row["align"] == BB.NEUTRAL
    assert "Contested" in row["remark"]


def test_with_no_winner_the_zones_own_type_decides():
    """Only when Stage 35 published no winner does the row fall back to what
    price is doing at the level — and then the zone's `type`, not spot's side
    of it, says whether holding is bullish."""
    holding_support = _war({"type": "SUPPORT", "price": 24300}, None, spot=24320.0)
    assert holding_support["align"] == BB.BULL
    assert "fighting as support" in holding_support["remark"]

    under_resistance = _war({"type": "RESISTANCE", "price": 24400}, None,
                            spot=24380.0)
    assert under_resistance["align"] == BB.BEAR
    assert "fighting as resistance" in under_resistance["remark"]


def test_the_row_says_which_side_the_zone_is_fighting_from():
    """The type is the whole point of the row — a reader cannot interpret
    "Buyers winning" without knowing what they are defending."""
    assert "fighting as resistance" in _war(
        {"type": "RESISTANCE", "price": 24400}, "Buyers (breakout)")["remark"]


def test_price_inside_the_zone_is_marked_as_such():
    assert "Inside war zone" in _war({"type": "SUPPORT", "price": 24300},
                                     "Contested", spot=24302.0)["position"]


def test_no_battle_zone_is_a_reported_absence():
    row = _war(None, None)
    assert row["align"] == A.NA
    assert "not at a contested level" in row["remark"]


# ── 14 · a barrier price is clear of is a direction, on every axis ──────────
#
# "if the resistance is far from LTP then that LTP is bull, and if put is bull
# nifty is bear — same for call, and for support, and for hvp."
#
# The same room rule the OI walls use, now on the leg's own premium axis and on
# the index. `bias_ball` still owns the last step, so a PUT inverts on the way
# out: a put with room for its premium to rise is NIFTY falling.

@pytest.mark.parametrize("chart,role,expected", [
    # a resistance the price is clear of → room to rise on that axis
    ("NIFTY", "resistance", BB.BULL),
    ("CALL", "resistance", BB.BULL),    # call premium free to rise → NIFTY up
    ("PUT", "resistance", BB.BEAR),     # put premium free to rise → NIFTY down
    # a support far from price → nothing holding that axis up
    ("NIFTY", "support", BB.BEAR),
    ("CALL", "support", BB.BEAR),
    ("PUT", "support", BB.BULL),        # put premium unsupported → NIFTY up
])
def test_room_is_the_inverse_of_the_level_constraining_price(chart, role, expected):
    assert A._room_align(chart, role) == expected
    # and it is exactly "the level is not holding it in", not a new formula
    assert A._room_align(chart, role) == A._level_align(chart, role, False)


def test_room_is_side_independent():
    """A resistance far ABOVE is headroom; a resistance far BELOW has already
    been broken through. Both say the price is free to go up."""
    def _res(spot):
        ss = {"_nifty_spot_live": float(spot),
              "_market_picture": {"regime": "SIDEWAYS"},
              "_reaction_sr": {"resistance": {"price": 24400.0},
                               "support": {"price": 20000.0}}}
        return _by_check(A.build(ss), "NIFTY Resistance")["align"]
    assert _res(24000) == _res(24800) == BB.BULL


@pytest.mark.parametrize("check,ltp,level,side,expected", [
    # the reported rows, on the reported numbers
    ("CALL LTP Resistance", 5.75, 84.36, None, BB.BULL),
    ("PUT LTP Resistance", 0.05, 33.80, None, BB.BEAR),
    ("CALL HVP HIGH", 5.75, 15.60, "HIGH", BB.BULL),
    ("PUT HVP HIGH", 0.05, 30.90, "HIGH", BB.BEAR),
])
def test_a_far_leg_level_votes_through_the_leg_inversion(
        check, ltp, level, side, expected):
    is_call = check.startswith("CALL")
    ce, pe = ("ATM CE 24050", "ATM PE 24050")
    zones = {"zone_type": "bearish", "mid": level, "status": "INTACT",
             "dominant": "balanced", "bull_pct": 50}
    ss = {"_nifty_spot_live": 24055.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_atm_leg_ltp": {ce: 5.75, pe: 0.05},
          "_atm_leg_vob_volume": {(ce if is_call else pe): [zones]},
          "_leg_profiles": {
              ("CALL" if is_call else "PUT"): {
                  "hv_points": [{"price": level, "side": side}]} if side else {},
              "call_label": ce, "put_label": pe}}
    assert _by_check(A.build(ss), check)["align"] == expected


def test_a_value_anchor_is_not_a_barrier():
    """POC and the gamma flip keep the position rule. Being far above value is
    bullish and far below it bearish — running the room rule over them would
    report "no POC nearby" as a direction, which is meaningless."""
    ss = {"_nifty_spot_live": 24380.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_money_flow_data": {"poc_price": 24100.0},
          "_gex_data": {"gamma_flip_level": 24900.0}}
    for check in ("NIFTY POC", "Gamma Flip"):
        assert _by_check(A.build(ss), check)["align"] == BB.NEUTRAL, check


def test_at_a_level_is_still_contested():
    """Only FAR gets the room read. Price sitting ON a level is genuinely
    undecided, and turning that into a direction would be the invention this
    module refuses to make."""
    ss = {"_nifty_spot_live": 24398.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"resistance": {"price": 24400.0},
                           "support": {"price": 20000.0}}}
    row = _by_check(A.build(ss), "NIFTY Resistance")
    assert row["align"] == BB.NEUTRAL
    assert "At" in row["position"]


def test_the_far_wording_says_why_it_is_coloured():
    """"🟢 Far from ₹84.36" states the geometry and hides the reason. A reader
    cannot tell why a green ball sits beside "far from"."""
    ss = {"_nifty_spot_live": 24000.0, "_market_picture": {"regime": "SIDEWAYS"},
          "_reaction_sr": {"resistance": {"price": 24400.0},
                           "support": {"price": 23000.0}}}
    assert "Clear of" in _by_check(A.build(ss), "NIFTY Resistance")["position"]
    assert "Unsupported" in _by_check(A.build(ss), "NIFTY Support")["position"]


def test_the_walls_and_the_barriers_agree_on_the_rule():
    """The walls got this rule first and keep their own wording; the shared
    logic must still give the same answer, or two rows describing the same
    geometry would disagree."""
    # a CE wall far away and a resistance far away are the same claim
    ss = {"_nifty_spot_live": 24000.0, "_market_picture":
          {"regime": "SIDEWAYS", "oi_ceiling": (24400, 9e4)},
          "_reaction_sr": {"resistance": {"price": 24400.0},
                           "support": {"price": 20000.0}}}
    read = A.build(ss)
    assert _by_check(read, "CALL Wall OI")["align"] == BB.BULL
    assert _by_check(read, "NIFTY Resistance")["align"] == BB.BULL


# ── 15 · it has to survive a phone ──────────────────────────────────────────
#
# Five columns at eleven pixels is a fine desktop table and unreadable on a
# handset, which is where this gets looked at during a session. Two layouts
# over ONE set of markup — a phone branch that built different HTML would be a
# second renderer to keep in step, and the two would drift the first time a
# column was added.

def _panel():
    from mios_v5.ui import alignment_panel as P
    return P


def test_one_markup_two_layouts():
    """The phone view must be CSS over the same rows, not a second builder."""
    P = _panel()
    src = pathlib.Path(P.__file__).read_text()
    assert "@media" in P._CSS
    # exactly one function emits rows, for both layouts
    assert src.count("def _row_html") == 1
    assert "mobile" not in src.lower().replace("automobile", "")


def test_the_breakpoint_turns_the_table_into_cards():
    P = _panel()
    css = P._CSS
    assert f"@media (max-width:{P._BREAK}px)" in css
    for rule in ("thead", "display:none", "display:flex", "flex-wrap:wrap"):
        assert rule in css, rule


def test_the_verdict_sits_beside_the_name_not_below_it():
    """The cells are emitted in table order and the verdict is the fourth. On a
    phone it belongs beside the NAME, three cells earlier — `order` does that.
    Floating it right made it drop past the value and land beside whatever
    happened to be tall, which put the ball under the wrong line."""
    P = _panel()
    # only the phone half of the sheet — the desktop table has no order at all
    phone = P._CSS.split("@media", 1)[1]
    # the name is ordered first and the verdict second, ahead of the value
    # (third) that comes between them in source order
    for cls, order in ((".c-check", 1), (".c-align", 2), (".c-value", 3)):
        seg = phone.split(cls, 1)[-1][:140]
        assert f"order:{order}" in seg, f"{cls} is not ordered {order}"
    # and the float that caused the drop is gone
    assert "float:right" not in P._CSS


def test_a_label_is_not_set_at_price_size():
    """"Balanced delta positioning" at 22px swamps the card; ₹24,050 at 22px is
    the point of the card."""
    P = _panel()
    long_row = {"check": "Dealer DEX", "value": "Balanced delta positioning",
                "position": "—", "align": A.NEUTRAL, "remark": "", "observed": True}
    short_row = dict(long_row, check="PUT Wall OI", value="₹24,050")
    assert "c-value long" in P._row_html(long_row)
    assert "long" not in P._row_html(short_row).split("c-value")[1][:12]
    assert ".c-value.long" in P._CSS


def test_an_empty_cell_does_not_leave_a_blank_line_on_a_phone():
    """A row with no value or position is a stack of gaps otherwise."""
    P = _panel()
    html = P._row_html({"check": "War Zone", "value": "—", "position": "—",
                        "align": A.NA, "remark": "no battle zone",
                        "observed": False})
    assert "c-value none" in html and "none" in html
    assert ".c-value.none" in P._CSS and "display:none" in P._CSS


def test_the_stylesheet_cannot_restyle_another_panel():
    """Every selector is under the panel's own class. A bare `table {}` here
    would reach the terminal's tables and the option chain."""
    P = _panel()
    body = P._CSS.split("<style>")[1].split("</style>")[0]
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(("/*", "*", "@media", "}", "{")):
            continue
        if "{" in line and not line.startswith("."):
            raise AssertionError(f"unscoped selector: {line}")
        if line.startswith(".") and P._NS not in line:
            raise AssertionError(f"selector outside the namespace: {line}")


def test_the_css_ships_with_the_panel_not_separately():
    """It goes out inside the same markdown call as the table. Injected once
    somewhere else, a rerun that skips the panel would leave its rules behind —
    and a rerun that skips the injector would render the table unstyled."""
    P = _panel()
    render_src = pathlib.Path(P.__file__).read_text().split("def render")[1]
    assert "_CSS" in render_src


# ── 16 · the dashboard ──────────────────────────────────────────────────────
#
# Twenty-one rows of five columns is a complete answer and a slow one. The
# dashboard is the same data grouped and sorted — it must never be a second
# read, or the ten-second view and the audit view would tell a trader two
# different things.

def _dash(ss=None):
    return A.dashboard(A.build(ss if ss is not None else _ss()))


def test_the_dashboard_reads_the_built_rows_not_the_session():
    """It takes the READ, not session state, so there is one pass over the
    market per cycle and the two views are provably the same data."""
    import inspect
    sig = inspect.signature(A.dashboard)
    assert list(sig.parameters) == ["read"], "it must take the read, not state"
    body = inspect.getsource(A.dashboard).split('"""', 2)[-1]
    # no session key is reachable from here — the read is the only input
    for key in ("_market_picture", "_reaction_sr", "_gex_data", "_leg_profiles",
                "_atm_leg_ltp", "_premium_energy", "_money_flow_data"):
        assert key not in body, f"dashboard() reaches for {key}"


def test_conviction_separates_a_lean_from_an_alignment():
    """"🔴 BEARISH" over 7 of 21 checks and the same words over 19 of 21 are
    completely different trades, and the old summary printed them identically."""
    assert A.conviction({"agreement": 19, "active": 21})[0] == "HIGH"
    assert A.conviction({"agreement": 13, "active": 21})[0] == "MODERATE"
    assert A.conviction({"agreement": 7, "active": 21}) == ("LOW", 33)
    # nothing reporting is not high conviction
    assert A.conviction({"agreement": 0, "active": 0}) == ("LOW", 0)


def test_the_ladder_is_ordered_high_to_low_with_spot_in_place():
    d = _dash()
    prices = [r["price"] for r in d["ladder"]]
    assert prices == sorted(prices, reverse=True)
    spots = [i for i, r in enumerate(d["ladder"]) if r["spot"]]
    assert len(spots) == 1, "spot appears exactly once"
    i = spots[0]
    assert all(r["price"] >= d["spot"] for r in d["ladder"][:i])
    assert all(r["price"] <= d["spot"] for r in d["ladder"][i + 1:])


def test_levels_on_the_same_strike_collapse_to_one_rung():
    """The magnet and the PUT wall are routinely the same strike. Two lines a
    pixel apart say "two things" where the market has one."""
    ss = _ss()
    ss["_market_picture"] = dict(ss["_market_picture"],
                                 oi_floor=(24300, 9e4), oi_pin=(24302, "max OI"))
    ss["_cached_option_data"] = {"max_pain_strike": 24302.0}
    # the rung is priced at whichever level was met first; what matters is that
    # the wall and the magnet ended up on the SAME one
    rungs = [r for r in _dash(ss)["ladder"] if "PUT Wall OI" in r["labels"]]
    assert len(rungs) == 1
    assert "Charm Pin / Magnet" in rungs[0]["labels"], rungs[0]["labels"]
    assert all(abs(rungs[0]["price"] - p) <= A.RUNG_TOLERANCE
               for p in (24300, 24302))


def test_a_premium_never_lands_on_the_index_ladder():
    """A leg at ₹95 sorted into index prices would place the call below every
    level and above nothing. Only index-axis rows carry a numeric level."""
    for r in A.build(_ss())["rows"]:
        if r["group"] == A.PREMIUM:
            assert r.get("level") is None, r["check"]
    assert all(x["price"] > 1000 for x in _dash()["ladder"])


def test_a_rung_reports_neutral_when_its_rows_disagree_and_na_only_when_silent():
    """Collapsing "they disagree" and "nobody reported" into one glyph loses
    the difference between a contested level and an absent one."""
    mixed = A.ladder([{"check": "A", "level": 100.0, "align": BB.BULL},
                      {"check": "B", "level": 101.0, "align": BB.BEAR}], None)
    assert mixed[0]["align"] == BB.NEUTRAL
    quiet = A.ladder([{"check": "A", "level": 100.0, "align": A.NA}], None)
    assert quiet[0]["align"] == A.NA
    agreed = A.ladder([{"check": "A", "level": 100.0, "align": BB.BULL},
                       {"check": "B", "level": 101.0, "align": BB.BULL}], None)
    assert agreed[0]["align"] == BB.BULL


def test_each_pressure_entry_names_its_bucket():
    """Without it the three columns can only be handed the global bull/bear
    list, and the dealer magnet shows up under OPTIONS."""
    d = _dash()
    for side in (BB.BULL, BB.BEAR):
        for p in d["pressure"][side]:
            assert p["bucket"] in A.BUCKETS, p


def test_a_column_only_names_drivers_it_owns():
    from mios_v5.ui import alignment_panel as P
    d = _dash()
    html = P.groups_html(d)
    # split on the column boundary, not on a guessed closing tag
    cols = html.split("<div class='col'>")[1:]
    options = next(c for c in cols if "OPTIONS" in c)
    for p in d["pressure"][BB.BEAR]:
        if p["bucket"] != A.B_OPTIONS:
            assert p["check"] not in options, (
                f"{p['check']} is a {p['bucket']} row shown under OPTIONS")


def test_the_gate_is_transported_not_recomputed():
    """`compute_market_picture` owns the entry decision. A second verdict here
    would put two answers to "do I take this" on one screen."""
    src = pathlib.Path(A.__file__).read_text()
    for banned in ("def _entry_gate", "def compute_entry", "'ARMED_'"):
        assert banned not in src
    ss = _ss()
    gate = {"state": "ARMED_PUT", "level": 24400.0, "target": 24300.0,
            "rr": 2.1, "why": ["armed at resistance"]}
    ss["_market_picture"] = dict(ss["_market_picture"], entry_gate=gate)
    assert _dash(ss)["gate"]["state"] == "ARMED_PUT"
    assert _dash(ss)["gate"]["rr"] == 2.1


def test_the_energy_read_matches_the_row_it_is_drawn_beside():
    """Two lookups of the same number are two chances to drift."""
    read = A.build(_ss())
    e = read["energy"]
    row = _by_check(read, "Premium Energy")
    assert f"{e['CALL']:.0f}" in row["value"] and f"{e['PUT']:.0f}" in row["value"]
    assert e["winner"] == "PUT"


def test_the_dashboard_survives_an_empty_market():
    d = _dash({})
    assert d["conviction"] == "LOW" and d["conviction_pct"] == 0
    assert d["ladder"] == [] and d["energy"] == {}
    assert d["pressure"][BB.BULL] == [] and d["pressure"][BB.BEAR] == []


def test_the_gate_leads_the_panel():
    """It is the decision; everything under it is the reasoning. Same rule that
    put the Trade Card above this panel — an answer you have to scroll to is an
    answer arriving late."""
    import inspect
    from mios_v5.ui import alignment_panel as P
    body = inspect.getsource(P.render)
    for later in ("verdict_html(d)", "ladder_html(d)", "legs_html(d)",
                  "conflict_html(d)"):
        assert body.index("gate_html(d)") < body.index(later), later


def test_the_detail_table_is_still_reachable():
    """The dashboard is the scan; the table is the audit. A summary you cannot
    check is a summary you have to trust."""
    from mios_v5.ui import alignment_panel as P
    src = pathlib.Path(P.__file__).read_text()
    assert "Detailed alignment" in src
    assert "table_html(rows)" in src


# ── 17 · the CE/PE battle ───────────────────────────────────────────────────
#
# The first dashboard dropped the leg LTP structure, and dropping it was the
# mistake: the index levels say where price is, and only the premiums say
# whether the option market is confirming it.

def _legs_ss():
    return {
        "_nifty_spot_live": 24055.80,
        "_market_picture": {"regime": "SIDEWAYS", "oi_floor": (24000, 9e4),
                            "oi_ceiling": (24100, 1.1e5)},
        "_reaction_sr": {"support": {"price": 24050.0},
                         "resistance": {"price": 24109.0}},
        "_atm_leg_ltp": {"ATM CE 24050": 107.30, "ATM PE 24050": 155.85},
        "_atm_leg_vob_volume": {
            "ATM CE 24050": [{"zone_type": "bullish", "mid": 108.98,
                              "status": "FADING", "dominant": "balanced",
                              "bull_pct": 42}],
            "ATM PE 24050": [{"zone_type": "bullish", "mid": 141.98,
                              "status": "BUILDING", "dominant": "buyers",
                              "bull_pct": 76}]},
        "_leg_profiles": {
            "CALL": {"hv_points": [{"price": 115.85, "side": "HIGH"},
                                   {"price": 107.00, "side": "LOW"}]},
            "PUT": {"hv_points": [{"price": 156.15, "side": "HIGH"},
                                  {"price": 140.10, "side": "LOW"}]},
            "call_label": "ATM CE 24050", "put_label": "ATM PE 24050"},
        "_premium_energy": {"bridge": {"energy_score": {"CALL": 30, "PUT": 56},
                                       "preferred_premium": "Prefer PUT"}},
    }


@pytest.mark.parametrize("chart,nifty,expected", [
    # a CALL reads straight: bullish for NIFTY means the call is strong
    ("CALL", BB.BULL, A.STRONG),
    ("CALL", BB.BEAR, A.WEAK),
    # a PUT inverts, for the same reason bias_ball inverts on the way out
    ("PUT", BB.BEAR, A.STRONG),
    ("PUT", BB.BULL, A.WEAK),
    ("PUT", BB.NEUTRAL, None),
])
def test_a_legs_own_strength_is_the_nifty_read_run_backwards(chart, nifty, expected):
    """Showing "🔴 Bear" in a card headed PUT SIDE would have the trader reading
    it as the put being weak, when a bearish PUT row means the opposite."""
    assert A.leg_strength(chart, nifty) == expected


def test_the_premium_band_comes_from_stage_71_7_not_from_here():
    """The first attempt scored the card by a majority of its own level rows —
    invented here — and read STRONG for a call whose energy was 30, because a
    resistance far overhead outvoted the row that mattered."""
    from mios_v5 import premium_energy as PE
    for score in (10, 30, 56, 75, 95):
        assert A._energy_band(score) == PE.energy_band(score)
    legs = {l["chart"]: l for l in A.dashboard(A.build(_legs_ss()))["legs"]}
    assert legs["CALL"]["state"] == "Weak"       # energy 30
    assert legs["PUT"]["state"] == "Healthy"     # energy 56


def test_each_leg_gets_its_own_ladder_on_its_own_axis():
    """A ₹107 premium and a 24,050 index level share no axis."""
    legs = {l["chart"]: l for l in A.dashboard(A.build(_legs_ss()))["legs"]}
    for chart, ltp in (("CALL", 107.30), ("PUT", 155.85)):
        rungs = legs[chart]["ladder"]
        prices = [r["price"] for r in rungs]
        assert prices == sorted(prices, reverse=True)
        assert all(p < 1000 for p in prices), "an index level reached a leg map"
        marks = [i for i, r in enumerate(rungs) if r["ltp"]]
        assert len(marks) == 1
        assert rungs[marks[0]]["price"] == ltp
        assert all(r["price"] >= ltp for r in rungs[:marks[0]])


def test_the_leg_ladder_and_the_row_name_the_same_prices():
    """Built from the rows' own `levels`, so the map under a premium and the
    text beside it cannot disagree."""
    read = A.build(_legs_ss())
    row = _by_check(read, "CALL HVP HIGH")
    rungs = A.leg_ladder(read["rows"], "CALL")
    for lv in row["levels"]:
        assert any(abs(r["price"] - lv) < 0.001 for r in rungs), lv


def test_the_battle_section_renders_both_sides():
    from mios_v5.ui import alignment_panel as P
    html = P.legs_html(A.dashboard(A.build(_legs_ss())))
    assert "CALL SIDE" in html and "PUT SIDE" in html
    assert "107.30" in html and "155.85" in html
    assert "PREMIUM WEAK" in html and "PREMIUM HEALTHY" in html
    assert "42% buy volume" in html and "76% buy volume" in html


def test_the_chain_shows_spot_then_premium_then_dealers():
    from mios_v5.ui import alignment_panel as P
    html = P.chain_html(A.dashboard(A.build(_legs_ss())))
    # the header names all three too — check the chain BODY for the order
    body = html.split("<div class='chain'>", 1)[1]
    assert body.index("SPOT STRUCTURE") < body.index("OPTION PREMIUM")
    assert body.index("OPTION PREMIUM") < body.index("DEALERS")
    # and the middle link carries the legs' own bands, not a bucket verdict
    assert "CALL WEAK" in body and "PUT HEALTHY" in body


def test_conflicted_is_not_the_same_as_low_conviction():
    """A read can be thin because little reported, or thin because structure
    and options pull opposite ways. Only the second is a conflict."""
    d = A.dashboard(A.build(_ss()))
    assert isinstance(d["conflicted"], bool)
    # buckets all one way → not conflicted, whatever the conviction
    agreed = A.dashboard({"rows": [], "summary": {"groups": {"STRUCTURE": BB.BEAR,
                                                             "OPTIONS": BB.BEAR}}})
    assert agreed["conflicted"] is False
    split = A.dashboard({"rows": [], "summary": {"groups": {"STRUCTURE": BB.BULL,
                                                            "OPTIONS": BB.BEAR}}})
    assert split["conflicted"] is True


def test_every_percentage_flex_basis_is_measured_border_box():
    """Streamlit does not set `box-sizing` for us, and the default content-box
    makes a percentage flex-basis a lie: `flex:1 1 46%` sizes the CONTENT to
    46% and then ADDS the padding and border, so two 46% cards plus a divider
    overflow by a pixel and wrap. The CE/PE battle silently stacked on desktop
    for exactly this — nothing in the markup or the computed flex values showed
    it, only the rendered geometry."""
    P = _panel()
    assert "box-sizing:border-box" in P._CSS
    # it has to cover the CHILDREN too — every card that sets a % basis also
    # sets padding on itself
    rule = next(l for l in P._CSS.splitlines() if "box-sizing" in l)
    assert f".{P._NS} *" in rule, "the reset must reach the flex items"
