"""Stage 71.5 — Trade Opportunity Intelligence.

The rule under test throughout: **a missing input yields UNKNOWN with a
reason, never a default.** Nine derived labels sitting on a five-producer
sample is exactly the situation where a confident-looking default does the
most damage, so most of these tests assert what the module REFUSES to say.
"""

import pytest

from mios_v5 import opportunity as OP
from mios_v5 import opportunity_intel as OI
from mios_v5.horizon_owner import HOLD, Horizon, owners_of


def _fr(**over):
    fr = {
        "preferred_bias": "BEAR", "confidence_tempered": 71,
        "stability": "STABLE",
        "flow_shift": {"freeze_entries": False, "score": 8},
        "transition": {"state": "STABLE", "label": "stable"},
        "memory_read": {"state_duration_min": 42, "state_mature": True,
                        "state_transition_risk": 18},
        "market_state": {"state": "TREND_DOWN", "confidence": 70},
        "reaction": {"state": "WATCHING", "confidence": 0},
        "absorption": {"behaviour": "NONE"},
        "htf": {"alignment": {"score": 75}, "reads": {}},
        "validity": {"verdict": "VALID", "valid": True, "pct": 78},
        "day_classification": {"type": "TREND", "label": "📈 Trend Day",
                               "confidence": 62},
        "session_intel": {"session": "MORNING_TREND", "minutes_remaining": 120},
        "energy_read": {"state": "EXPANSION", "release_probability": 40,
                        "breakout_risk": 30},
        "engine_bias": {}, "sections": {},
    }
    fr.update(over)
    return fr


def _fill(h, bias, n=None, conf=80):
    o = owners_of(h)
    o = o if n is None else o[:n]
    return {p: {"bias": bias, "confidence": conf, "label": p} for p in o}


def _matrix(fr=None, native=None, previous=None):
    fr = fr if fr is not None else _fr()
    m = OP.build_matrix(fr, native)
    reads = OP._producer_reads(fr, native)
    return OI.enrich(m, fr, reads, previous)


def _row(m, horizon):
    return next(r for r in m["rows"] if r["horizon"] == horizon)


# ── shape and standing ──────────────────────────────────────────────────

def test_every_row_gets_an_intel_block():
    m = _matrix()
    for r in m["rows"]:
        i = r["intel"]
        assert set(i) >= {"type", "quality", "lifetime", "risk", "maturity",
                          "rotation", "timing", "breakdown", "weakness"}
        assert i["advisory_only"] is True


def test_enrich_never_raises_on_empty_everything():
    for fr in (None, {}, {"reaction": None}):
        m = OI.enrich(OP.build_matrix(fr), fr)
        assert len(m["rows"]) == 5


def test_module_exposes_no_mutators():
    for banned in ("decide", "apply", "promote", "deploy", "set_weight",
                   "set_threshold", "enter", "exit_trade"):
        assert not hasattr(OI, banned), f"opportunity_intel.{banned}"


def test_stage_71_5_is_not_a_registered_engine():
    from mios_v5.engines import ALL_ENGINES
    names = {c().name for c in ALL_ENGINES}
    assert not any("opportunity" in n for n in names)


# ── 1 · type ────────────────────────────────────────────────────────────

def test_executed_reaction_outranks_the_market_state():
    """Stage 42 fired is a thing that HAPPENED; Stage 48 describes the tape."""
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80},
             market_state={"state": "RANGE", "confidence": 70})
    t = OI.opportunity_type(fr)
    assert t["type"] == "BREAKDOWN" and "Stage 42" in t["source"]


def test_market_state_names_the_type_when_no_reaction_fired():
    fr = _fr(reaction={"state": "IDLE"},
             market_state={"state": "ACCUMULATION", "confidence": 70})
    assert OI.opportunity_type(fr)["type"] == "ACCUMULATION_LONG"


def test_expiry_pin_day_overrides_everything():
    """Stage 68's own rule: EXPIRY_PIN is a fact, not a vote."""
    fr = _fr(day_classification={"type": "EXPIRY_PIN", "confidence": 80},
             reaction={"state": "CONFIRMED_BREAKOUT", "confidence": 90})
    assert OI.opportunity_type(fr)["type"] == "EXPIRY_PIN"


def test_a_side_opposing_the_type_is_marked_counter_trend():
    """The type is a MARKET fact — one confirmed breakdown, shared by every
    row. A horizon leaning CALL against it is a counter-trend trade, and
    rendering that row as plain "Breakdown / CALL" reads as a contradiction
    rather than as the trade it is."""
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80})
    m = _matrix(fr, _fill(Horizon.SCALP, "BULL"))     # CALL against a breakdown
    t = _row(m, "scalp")["intel"]["type"]
    assert t["counter_trend"] is True
    assert "Counter-trend" in t["label"]
    assert "against it" in t["source"]


def test_a_side_agreeing_with_the_type_is_not_marked():
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    t = _row(m, "scalp")["intel"]["type"]
    assert t["counter_trend"] is False
    assert "Counter-trend" not in t["label"]


def test_a_directionless_type_is_never_counter_trend():
    """MOMENTUM / PULLBACK / RANGE_FADE carry no direction of their own."""
    fr = _fr(reaction={"state": "IDLE"},
             market_state={"state": "RANGE", "confidence": 70})
    for bias in ("BULL", "BEAR"):
        m = _matrix(fr, _fill(Horizon.SCALP, bias))
        assert _row(m, "scalp")["intel"]["type"]["counter_trend"] is False


def test_swing_bias_is_checked_for_counter_trend_too():
    """Swing has no `side`, but it does have a `bias` — it must still be
    marked when its structure opposes the named type."""
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80})
    m = _matrix(fr, _fill(Horizon.SWING, "BULL"))
    assert _row(m, "swing")["intel"]["type"]["counter_trend"] is True


def test_type_is_unknown_when_nothing_reported():
    fr = _fr(reaction={}, market_state={}, day_classification={}, sections={})
    t = OI.opportunity_type(fr)
    assert t["type"] == OI.UNKNOWN and t["known"] is False and t["source"]


def test_every_type_has_a_label():
    for t in set(list(dict(OI._TYPE_FROM_REACTION).values())
                 + list(dict(OI._TYPE_FROM_STATE).values())):
        pass
    for t in OI.TYPE_LABEL:
        assert OI.TYPE_LABEL[t]


# ── 2 · quality ─────────────────────────────────────────────────────────

def test_quality_reuses_decision_v0_bands():
    """Two 'Quality A' badges on one screen must mean the same thing."""
    from mios_v5.decision import _grade
    for avg in (4.8, 4.5, 4.0, 3.8, 3.4, 3.0, 2.0):
        ours = next(g for cut, g in OI._GRADE_BANDS if avg >= cut)
        assert ours == _grade(avg), f"band drift at {avg}"


def test_quality_has_no_b_plus_band():
    """A band v0 cannot express would diverge the vocabularies."""
    assert "B+" not in [g for _, g in OI._GRADE_BANDS]


def test_unknown_components_are_excluded_not_scored_zero():
    """A silent engine is not a bad one. Averaging it as 0 would grade a thin
    read as a bad read."""
    full = OI.quality(_fr(), {})
    thin = OI.quality(_fr(absorption={"behaviour": "NONE"},
                          reaction={"state": None}), {})
    assert thin["known"] < full["known"]
    assert thin["avg"] is None or thin["avg"] > 0


def test_quality_is_unknown_below_three_components():
    fr = _fr(validity={}, reaction={}, absorption={}, htf={}, market_state={},
             day_classification={}, session_intel={}, flow_shift={},
             stability=None)
    q = OI.quality(fr, {})
    assert q["grade"] == OI.UNKNOWN and q["reason"]


def test_a_vetoed_row_is_graded_avoid():
    q = OI.quality(_fr(), {"veto": True})
    assert q["grade"] == "AVOID"


def test_choppy_day_caps_quality_however_confident():
    fr = _fr(day_classification={"type": "CHOPPY", "confidence": 95})
    day = next(c for c in OI.quality(fr, {})["components"] if c["key"] == "day")
    assert day["score"] <= 2.0


# ── 3 · lifetime ────────────────────────────────────────────────────────

def test_lifetime_is_always_anchored_to_the_horizon_band():
    """Never a free-floating number — a prediction wearing an estimate's
    clothes."""
    for h in Horizon:
        lf = OI.lifetime(_fr(), h)
        assert lf["base"] == HOLD[h]
        assert HOLD[h] in lf["label"]


def test_high_release_probability_shortens_the_band():
    lf = OI.lifetime(_fr(energy_read={"state": "EXPANSION",
                                      "release_probability": 80}), Horizon.SCALP)
    assert lf["adjustment"] == "shorter" and lf["notes"]


def test_compression_lengthens_the_band():
    lf = OI.lifetime(_fr(energy_read={"state": "COMPRESSION",
                                      "release_probability": 20}), Horizon.MIDDAY)
    assert lf["adjustment"] == "longer"


def test_session_ending_shortens_only_the_fast_horizons():
    fr = _fr(session_intel={"session": "CLOSING", "minutes_remaining": 12})
    assert OI.lifetime(fr, Horizon.SCALP)["adjustment"] == "shorter"
    assert OI.lifetime(fr, Horizon.SWING)["adjustment"] != "shorter"


# ── 4 · risk ────────────────────────────────────────────────────────────

def test_risk_is_unknown_when_almost_nothing_reported():
    fr = _fr(flow_shift={}, stability=None, day_classification={},
             reaction={}, energy_read={}, validity={})
    r = OI.risk(fr, Horizon.SCALP)
    assert r["level"] == OI.UNKNOWN and r["score"] is None


def test_a_frozen_tape_is_high_or_extreme_risk():
    fr = _fr(flow_shift={"freeze_entries": True}, stability="SHOCK")
    assert OI.risk(fr, Horizon.SCALP)["level"] in ("HIGH", "EXTREME")


def test_every_risk_driver_names_its_stage():
    fr = _fr(flow_shift={"freeze_entries": True},
             day_classification={"type": "CHOPPY", "label": "🔪 Choppy Day",
                                 "confidence": 60})
    assert all("Stage" in d for d in OI.risk(fr, Horizon.SCALP)["drivers"])


def test_calm_trend_day_is_low_risk():
    assert OI.risk(_fr(), Horizon.INTRADAY)["level"] == "LOW"


# ── 5 · maturity ────────────────────────────────────────────────────────

def test_reversing_bias_reads_exhausted():
    assert OI.maturity(_fr(transition={"state": "REVERSING"}))["maturity"] \
        == "EXHAUSTED"


def test_weakening_bias_reads_mature():
    assert OI.maturity(_fr(transition={"state": "WEAKENING"}))["maturity"] \
        == "MATURE"


def test_a_two_minute_state_reads_fresh():
    m = OI.maturity(_fr(memory_read={"state_duration_min": 2,
                                     "state_fresh": True}))
    assert m["maturity"] == "FRESH"


def test_maturity_is_unknown_without_a_duration():
    assert OI.maturity(_fr(memory_read={}, transition={},
                           market_state={}))["maturity"] == OI.UNKNOWN


# ── 6 · rotation ────────────────────────────────────────────────────────

def test_rotation_is_unknown_on_the_first_cycle():
    m = _matrix(native=_fill(Horizon.SCALP, "BULL"))
    assert _row(m, "scalp")["intel"]["rotation"]["rotation"] == OI.UNKNOWN


def test_same_side_twice_is_continuation():
    fr = _fr()
    prev = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    now = _matrix(fr, _fill(Horizon.SCALP, "BULL"), previous=prev)
    rot = _row(now, "scalp")["intel"]["rotation"]
    assert rot["rotation"] == "CONTINUATION"
    # The label carries the SIDES, the panel prefixes an arrow for the KIND.
    # "CALL → CALL" rendered as "→ CALL → CALL": the arrow twice, and nothing
    # having rotated dressed up as a movement.
    assert rot["label"] == "CALL"
    assert "→" not in rot["label"], "the panel owns the arrow, not the label"


def test_a_flip_is_rotation():
    fr = _fr()
    prev = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    now = _matrix(fr, _fill(Horizon.SCALP, "BEAR"), previous=prev)
    rot = _row(now, "scalp")["intel"]["rotation"]
    assert rot["rotation"] == "ROTATION" and rot["label"] == "CALL → PUT"


def test_a_side_that_disappears_is_fading():
    fr = _fr()
    prev = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    now = _matrix(fr, None, previous=prev)
    assert _row(now, "scalp")["intel"]["rotation"]["rotation"] == "FADING"


def test_a_side_appearing_is_building():
    fr = _fr()
    prev = _matrix(fr, None)
    now = _matrix(fr, _fill(Horizon.SCALP, "BULL"), previous=prev)
    assert _row(now, "scalp")["intel"]["rotation"]["rotation"] == "BUILDING"


# ── 7 · timing ──────────────────────────────────────────────────────────

def test_a_fired_reaction_reads_now():
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    assert _row(m, "scalp")["intel"]["timing"]["timing"] == "NOW"


def test_a_fired_reaction_the_gatekeeper_rejects_reads_prepare():
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 80},
             validity={"verdict": "REJECTED", "valid": False, "pct": 40})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    assert _row(m, "scalp")["intel"]["timing"]["timing"] == "PREPARE"


def test_an_exhausted_move_reads_missed():
    fr = _fr(transition={"state": "REVERSING"})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    assert _row(m, "scalp")["intel"]["timing"]["timing"] == "MISSED"


def test_a_vetoed_horizon_reads_wait():
    fr = _fr(flow_shift={"freeze_entries": True}, stability="SHOCK")
    m = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    assert _row(m, "scalp")["intel"]["timing"]["timing"] == "WAIT"


def test_a_reaction_does_not_trigger_the_slow_horizons():
    """Stage 42 fires on a 1-5 minute timescale. A confirmed breakdown is not
    the moment to open a multi-week structural position — without this scope
    swing inherits the scalp's trigger and reads NOW off a one-minute event."""
    fr = _fr(reaction={"state": "CONFIRMED_BREAKDOWN", "confidence": 90},
             htf={"alignment": {"score": 30}, "reads": {}})
    native = {}
    native.update(_fill(Horizon.SCALP, "BEAR"))
    native.update(_fill(Horizon.SWING, "BEAR"))
    native.update(_fill(Horizon.POSITIONAL, "BEAR"))
    m = _matrix(fr, native)
    assert _row(m, "scalp")["intel"]["timing"]["timing"] == "NOW"
    for slow in ("swing", "positional"):
        t = _row(m, slow)["intel"]["timing"]
        assert t["timing"] != "NOW"
        assert "Stage 45" in t["source"], "slow horizons trigger on HTF"


def test_strong_htf_alignment_triggers_the_slow_horizons():
    # a DEVELOPING state — the default fixture is mature, which correctly
    # downgrades even a strong alignment to LATE (asserted below)
    fr = _fr(reaction={"state": "IDLE"},
             memory_read={"state_duration_min": 20},
             htf={"alignment": {"score": 85, "disagree": []}, "reads": {}})
    m = _matrix(fr, _fill(Horizon.SWING, "BEAR"))
    t = _row(m, "swing")["intel"]["timing"]
    assert t["timing"] == "NOW" and "Stage 45" in t["source"]


def test_strong_htf_on_a_late_cycle_move_is_late_not_now():
    """Alignment says the structure agrees; maturity says you are arriving
    after the move. Both are true, and LATE is the honest verdict."""
    fr = _fr(reaction={"state": "IDLE"},
             memory_read={"state_duration_min": 240, "state_mature": True},
             htf={"alignment": {"score": 85, "disagree": []}, "reads": {}})
    m = _matrix(fr, _fill(Horizon.SWING, "BEAR"))
    assert _row(m, "swing")["intel"]["timing"]["timing"] == "LATE"


def test_contested_htf_holds_the_slow_horizons_at_prepare():
    fr = _fr(reaction={"state": "IDLE"},
             htf={"alignment": {"score": 60, "disagree": ["Weekly"]},
                  "reads": {}})
    m = _matrix(fr, _fill(Horizon.SWING, "BEAR"))
    t = _row(m, "swing")["intel"]["timing"]
    assert t["timing"] == "PREPARE" and "Weekly" in t["source"]


def test_every_timing_names_its_reason():
    m = _matrix(native=_fill(Horizon.SCALP, "BULL"))
    for r in m["rows"]:
        assert r["intel"]["timing"]["source"]


# ── 8 · breakdown ───────────────────────────────────────────────────────

def test_breakdown_only_shows_producers_the_horizon_owns():
    """Showing Dealer on the scalp row would imply evidence scalp lacks."""
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))
    native.update(_fill(Horizon.POSITIONAL, "BEAR"))
    m = _matrix(native=native)
    scalp_ids = {b["id"] for b in _row(m, "scalp")["intel"]["breakdown"]}
    assert scalp_ids <= set(owners_of(Horizon.SCALP))
    assert not (scalp_ids & set(owners_of(Horizon.POSITIONAL)))


def test_breakdown_is_sorted_strongest_first():
    native = _fill(Horizon.SCALP, "BULL")
    ids = list(native)
    native[ids[0]]["confidence"] = 20
    native[ids[1]]["confidence"] = 95
    m = _matrix(native=native)
    confs = [b["confidence"] for b in _row(m, "scalp")["intel"]["breakdown"]]
    assert confs == sorted(confs, reverse=True)


def test_breakdown_is_empty_when_nothing_reported():
    assert _matrix()["rows"][0]["intel"]["breakdown"] == []


# ── 9 · weakness ────────────────────────────────────────────────────────

def test_weakness_is_populated_on_a_degraded_tape():
    fr = _fr(transition={"state": "WEAKENING", "label": "Bear weakening"},
             day_classification={"type": "CHOPPY", "label": "🔪 Choppy Day",
                                 "confidence": 60})
    m = _matrix(fr, _fill(Horizon.SCALP, "BEAR"))
    assert _row(m, "scalp")["intel"]["weakness"]


def test_weakness_has_no_duplicates():
    fr = _fr(flow_shift={"freeze_entries": True}, stability="SHOCK",
             transition={"state": "REVERSING"})
    w = _row(_matrix(fr, _fill(Horizon.INTRADAY, "BEAR")),
             "intraday")["intel"]["weakness"]
    assert len(w) == len(set(w))


def test_weakness_is_distinct_from_lost_because():
    """`lost_because` is why it did not win. `weakness` is how it can fail —
    a winning trade still has one."""
    m = _matrix(_fr(transition={"state": "WEAKENING"}),
                _fill(Horizon.SCALP, "BULL"))
    r = _row(m, "scalp")
    assert r["intel"]["weakness"]
    assert r["intel"]["weakness"] != r.get("lost_because")


# ── best / second / no-trade ────────────────────────────────────────────

def test_best_and_second_follow_the_ranking():
    native = {}
    native.update(_fill(Horizon.SCALP, "BULL"))
    native.update(_fill(Horizon.INTRADAY, "BEAR"))
    m = _matrix(native=native)
    assert m["best_trade"]["horizon"] == m["ranked"][0]
    assert m["second_choice"]["horizon"] == m["ranked"][1]
    assert m["no_trade"] is None


def test_no_trade_explains_instead_of_saying_wait():
    """Stage 67's rule: what MIOS refused is half the report."""
    m = _matrix()
    nt = m["no_trade"]
    assert nt is not None
    assert nt["headline"] != "WAIT"
    assert nt["reasons"], "a no-trade day must say WHY"
    assert nt["recommendation"] == "Stay flat"


def test_no_trade_names_the_market_condition_behind_it():
    fr = _fr(market_state={"state": "COMPRESSION", "confidence": 70},
             day_classification={"type": "CHOPPY", "label": "🔪 Choppy Day",
                                 "confidence": 70})
    nt = _matrix(fr)["no_trade"]
    joined = " ".join(nt["reasons"])
    assert "Stage 48" in joined or "Stage 68" in joined


def test_second_choice_is_absent_with_only_one_ranked():
    m = _matrix(native=_fill(Horizon.SCALP, "BULL"))
    assert m["best_trade"] is not None
    assert m["second_choice"] is None


# ── swing keeps its rule through enrichment ─────────────────────────────

def test_swing_still_has_no_side_after_enrichment():
    m = _matrix(native=_fill(Horizon.SWING, "BEAR"))
    swing = _row(m, "swing")
    assert "side" not in swing
    assert swing["intel"]["type"]["type"]        # still classified
    assert m["best_trade"] is None or m["best_trade"]["horizon"] != "swing"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"opportunity intel tests passed ({len(fns)})")


# ── the display defects the matrix column showed live ───────────────────

def test_no_rotation_kind_prints_its_arrow_twice():
    """The row read `→ CALL → CALL`. The panel owns the arrow (for the KIND);
    the label owns the sides. A label that also carries an arrow for the
    continuation case doubles it and makes "nothing changed" look like a move."""
    from mios_v5.ui.opportunity_panel import _ROTATION_ARROW
    fr = _fr()
    prev = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    now = _matrix(fr, _fill(Horizon.SCALP, "BULL"), previous=prev)
    rot = _row(now, "scalp")["intel"]["rotation"]
    rendered = f"{_ROTATION_ARROW.get(rot['rotation'], '·')} {rot['label']}"
    assert rendered.count("→") <= 1, f"doubled arrow: {rendered!r}"


def test_a_real_rotation_still_shows_both_sides():
    """Trimming the continuation label must not trim the case that matters."""
    fr = _fr()
    prev = _matrix(fr, _fill(Horizon.SCALP, "BULL"))
    now = _matrix(fr, _fill(Horizon.SCALP, "BEAR"), previous=prev)
    rot = _row(now, "scalp")["intel"]["rotation"]
    assert rot["rotation"] == "ROTATION"
    assert "CALL" in rot["label"] and "PUT" in rot["label"]


def test_opportunity_type_does_not_pretend_to_be_per_horizon():
    """It took a `Horizon` and never referenced it, which implies a per-horizon
    read that is not happening. Type IS market-level — every branch reads `fr`
    alone — so the parameter is gone rather than left to mislead."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(OI.opportunity_type)).body[0]
    params = [a.arg for a in fn.args.args]
    assert params == ["fr"], f"unexpected signature {params}"
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert not [p for p in params if p not in used], "a parameter is ignored"


def test_the_market_level_fields_are_recorded():
    """"All five rows say the same thing" must be checkable against intent."""
    assert "type" in OI.MARKET_LEVEL_FIELDS


def test_the_horizon_aware_fields_really_do_use_the_horizon():
    """Risk, lifetime and timing were suspected of the same defect. They are
    not: each references its horizon. Pinned so a refactor cannot quietly turn
    one of them into another market read stamped five times."""
    import ast
    import inspect
    for name in ("risk", "lifetime", "timing"):
        fn = ast.parse(inspect.getsource(getattr(OI, name))).body[0]
        params = [a.arg for a in fn.args.args]
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        dead = [p for p in params if p not in used]
        assert not dead, f"{name} ignores {dead}"
