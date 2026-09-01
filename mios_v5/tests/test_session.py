"""MIOS V6 — Stage 69 Market Session Intelligence tests.

Beyond correctness, two properties are load-bearing: the modifiers must be
**published but not applied** while `SESSION_AWARE` is False, and the engine
must be provably unable to emit a direction.
"""

from datetime import datetime

from mios_v5 import session
from mios_v5.clock import IST


def _at(h, m):
    return IST.localize(datetime(2026, 7, 28, h, m))


def _fr(**kw):
    base = {
        "market_state": {"state": "TREND_UP", "label": "⬆️ TREND UP"},
        "memory_read": {"state_duration_min": 40.0},
        "transition": {"state": "STABLE", "label": "→ Stable", "strength": 72},
        "energy_read": {"state": "BUILDING"},
        "stability": "STABLE",
        "absorption": {"behaviour": "AGGRESSIVE_BUYING"},
        "ltp_behaviour": {"price": {"state": "RISING", "label": "↑ Rising"},
                          "volume": {"state": "HEALTHY", "label": "Healthy"}},
        "families": {"institutions": {"direction": "BULL", "strength": 78,
                                      "reliability": "HIGH"},
                     "dealer": {"direction": "BULL", "strength": 64}},
        "sections": {"orderflow": {"confidence": 70, "headline": "CVD rising"},
                     "options": {"confidence": 55, "headline": "call unwinding"},
                     "liquidity": {"confidence": 60}},
        "is_expiry": False,
    }
    base.update(kw)
    return base


# ── the eight windows ───────────────────────────────────────────────────
def test_every_window_has_a_purpose_and_a_style():
    for key, _, _, label in session.WINDOWS:
        assert label
        assert session.PURPOSE.get(key), key
        rec, avoid = session.STYLE.get(key, ([], []))
        assert rec and avoid, key
    assert session.PURPOSE["CLOSED"] and session.STYLE["CLOSED"]


def test_windows_are_contiguous_and_in_order():
    """A gap between windows would leave a minute of the session unclassified;
    an overlap would make the classification order-dependent."""
    prev_end = None
    for _, start, end, _ in session.WINDOWS:
        assert start < end
        if prev_end is not None:
            assert start == prev_end
        prev_end = end


def test_each_moment_lands_in_the_right_window():
    cases = [((9, 5), "PRE_OPEN"), ((9, 17), "OPENING_AUCTION"),
             ((9, 30), "OPENING_DRIVE"), ((10, 15), "MORNING_TREND"),
             ((12, 0), "MIDDAY_BALANCE"), ((14, 0), "AFTERNOON_TREND"),
             ((15, 10), "CLOSING")]
    for (h, m), expect in cases:
        assert session.classify(_at(h, m))["session"] == expect, (h, m)


def test_boundaries_belong_to_the_window_they_open():
    assert session.classify(_at(9, 20))["session"] == "OPENING_DRIVE"
    assert session.classify(_at(9, 45))["session"] == "MORNING_TREND"
    assert session.classify(_at(11, 30))["session"] == "MIDDAY_BALANCE"
    assert session.classify(_at(15, 0))["session"] == "CLOSING"


def test_outside_hours_is_closed():
    for h, m in ((8, 0), (15, 30), (16, 45), (23, 59), (2, 0)):
        c = session.classify(_at(h, m))
        assert c["session"] == "CLOSED" and c["open"] is False
        assert c["minutes_remaining"] is None


def test_time_remaining_and_progress():
    c = session.classify(_at(10, 15))
    assert c["minutes_elapsed"] == 30
    assert c["minutes_remaining"] == 75
    assert c["minutes_total"] == 105
    assert c["pct_through"] == 29
    assert c["next_session"] == "MIDDAY_BALANCE"


def test_the_last_window_points_at_closed():
    assert session.classify(_at(15, 20))["next_session"] == "CLOSED"


# ── the nine measures ───────────────────────────────────────────────────
def test_every_measure_names_the_engine_that_owns_it():
    m = session.intelligence(_fr(), price={"atr_pct": 0.8})
    assert set(m) == set(session.MEASURES)
    for key, v in m.items():
        assert v["label"] and v["engine"]
        assert v["level"] in ("None", "Low", "Medium", "High", "Very High", "—")


def test_a_silent_engine_is_unavailable_not_defaulted():
    """A panel reading 'Liquidity: Medium' because nothing answered is worse
    than a dash."""
    m = session.intelligence({}, price={})
    for v in m.values():
        assert v["available"] is False
        assert v["value"] is None and v["level"] == "—"


def test_measures_read_the_real_values():
    m = session.intelligence(_fr(), price={"atr_pct": 1.2})
    assert m["strength"]["value"] == 72
    assert m["institutional"]["value"] == 78
    assert m["dealer"]["value"] == 64
    assert m["volatility"]["available"] is True
    assert "ATR" in m["volatility"]["engine"]


def test_a_dry_tape_reads_as_low_liquidity():
    fr = _fr(ltp_behaviour={"price": {"state": "FLAT"},
                            "volume": {"state": "DRY", "label": "Dry"}})
    m = session.intelligence(fr)
    assert m["liquidity"]["level"] in ("None", "Low")
    assert m["momentum"]["level"] in ("None", "Low")


# ── session behaviour ───────────────────────────────────────────────────
def test_behaviour_reads_the_engines_and_says_why():
    b = session.behaviour(_fr())
    assert b["behaviour"] in session.BEHAVIOURS
    assert b["label"] and b["reasons"]


def test_expiry_outranks_everything():
    assert session.behaviour(_fr(is_expiry=True))["behaviour"] == "EXPIRY"


def test_a_shocked_tape_is_choppy():
    assert session.behaviour(_fr(stability="SHOCK"))["behaviour"] == "CHOPPY"


def test_exhaustion_is_named():
    b = session.behaviour(_fr(absorption={"behaviour": "BUYER_EXHAUSTION"}))
    assert b["behaviour"] == "TREND_EXHAUSTION"


def test_compression_and_expansion():
    assert session.behaviour(
        _fr(energy_read={"state": "COMPRESSION"}))["behaviour"] == "COMPRESSING"
    assert session.behaviour(
        _fr(energy_read={"state": "EXPANSION"}))["behaviour"] == "EXPANDING"


def test_a_young_trend_is_building_not_trending():
    b = session.behaviour(_fr(transition={"state": "STRENGTHENING"},
                              energy_read={"state": "BUILDING"}))
    assert b["behaviour"] == "TREND_BUILDING"


def test_no_market_state_is_unknown_not_sideways():
    assert session.behaviour({})["behaviour"] == "UNKNOWN"


# ── the modifiers: published, NOT applied ───────────────────────────────
def test_the_master_switch_is_off():
    """Changing what Stage 51 demands is a real intervention in what MIOS
    trades. The standing rule outranks the feature."""
    assert session.SESSION_AWARE is False


def test_modifiers_are_published_for_every_session():
    for key, _, _, _ in session.WINDOWS:
        m = session.modifiers(key)
        assert "applies_to" in m and "note" in m
        assert m["applied"] is False


def test_a_consumer_gets_nothing_while_the_switch_is_off():
    """`modifier_for` is the only accessor consumers use, so the gate cannot be
    bypassed by reading `applies_to` directly."""
    m = session.modifiers("MIDDAY_BALANCE")
    assert m["applies_to"]["stage51_validity"]["threshold_delta"] == 12
    assert session.modifier_for(m, "stage51_validity") == {}
    assert session.modifier_for(m, "stage52_decision") == {}


def test_the_note_says_plainly_that_nothing_is_applied():
    note = session.modifiers("OPENING_DRIVE")["note"]
    assert "NOT APPLIED" in note and "SESSION_AWARE" in note


def test_the_opening_drive_demands_more_confirmation():
    m = session.modifiers("OPENING_DRIVE")["applies_to"]
    assert m["stage42_acceptance"]["breakout_confidence"] == -15
    assert m["stage42_acceptance"]["require_extra_confirmation"] is True
    assert m["stage51_validity"]["threshold_delta"] == 10
    assert m["stage52_decision"]["stance"] == "WAIT"
    assert m["stage44_flow_shift"]["sensitivity"] < 1.0   # ignore small spikes


def test_midday_inverts_the_flow_shift_sensitivity():
    """A small spike in a quiet tape is meaningful; the same spike at the open
    is noise. The two sessions must move this in OPPOSITE directions."""
    opening = session.modifiers("OPENING_DRIVE")["applies_to"]
    midday = session.modifiers("MIDDAY_BALANCE")["applies_to"]
    assert opening["stage44_flow_shift"]["sensitivity"] < 1.0
    assert midday["stage44_flow_shift"]["sensitivity"] > 1.0


def test_midday_makes_ltp_behaviour_more_significant():
    m = session.modifiers("MIDDAY_BALANCE")["applies_to"]
    assert m["stage50_ltp_behaviour"]["significance"] > 1.0


def test_the_close_requires_dealer_agreement():
    m = session.modifiers("CLOSING")["applies_to"]
    assert m["stage51_validity"]["require_dealer"] is True
    assert m["stage52_decision"]["stance"] == "HIGH_CONFIDENCE_ONLY"


def test_the_trend_sessions_are_normal():
    for key in ("MORNING_TREND", "AFTERNOON_TREND"):
        m = session.modifiers(key)["applies_to"]
        assert m["stage52_decision"]["stance"] == "NORMAL"


def test_behaviour_layers_on_top_of_the_session():
    plain = session.modifiers("MIDDAY_BALANCE")["applies_to"]
    choppy = session.modifiers("MIDDAY_BALANCE", "CHOPPY")["applies_to"]
    assert choppy["stage51_validity"]["threshold_delta"] >= \
        plain["stage51_validity"]["threshold_delta"]
    assert "choppy" in choppy["stage51_validity"]["reason"]


def test_the_more_conservative_stance_always_wins():
    """A session that says WAIT and a behaviour that says NORMAL must not
    resolve to NORMAL."""
    m = session.modifiers("MORNING_TREND", "CHOPPY")["applies_to"]
    assert m["stage52_decision"]["stance"] == "WAIT"
    m2 = session.modifiers("CLOSING", "CHOPPY")["applies_to"]
    assert m2["stage52_decision"]["stance"] == "HIGH_CONFIDENCE_ONLY"


def test_closed_is_no_trade():
    assert session.modifiers("CLOSED")["applies_to"][
        "stage52_decision"]["stance"] == "NO_TRADE"


def test_every_modifier_carries_a_reason():
    for key in [k for k, _, _, _ in session.WINDOWS] + ["CLOSED"]:
        for engine, mod in session.modifiers(key)["applies_to"].items():
            assert mod.get("reason"), (key, engine)


# ── the whole read ──────────────────────────────────────────────────────
def test_read_assembles_everything():
    r = session.read(_fr(), price={"atr_pct": 0.9}, now=_at(10, 15),
                     conviction=80)
    assert r["session"] == "MORNING_TREND"
    assert r["measures_available"] == len(session.MEASURES)
    assert r["behaviour"] in session.BEHAVIOURS
    assert r["conviction"] == 80.0
    assert r["conviction_source"] == "Stage 6 Time Cycle"
    assert r["modifiers"]["applied"] is False
    assert r["advisory_only"] is True
    assert "min left" in r["sentence"]


def test_the_conviction_is_carried_not_recomputed():
    """Stage 6 owns the weight `confidence_tempered` depends on — two engines
    computing it would give the system two answers."""
    import inspect
    src = inspect.getsource(session)
    assert "conviction_source" in src
    for banned in ("_CONVICTION", "conviction =  ", "def conviction"):
        assert banned not in src


def test_read_on_a_closed_market():
    r = session.read({}, now=_at(18, 0))
    assert r["open"] is False
    assert "closed" in r["sentence"].lower()


def test_log_row_captures_what_would_have_been_applied():
    r = session.read(_fr(), now=_at(12, 0), conviction=35)
    row = session.log_row(r, trading_day="2026-07-28")
    assert row["session"] == "MIDDAY_BALANCE"
    assert row["trading_day"] == "2026-07-28"
    assert row["modifiers_applied"] is False
    assert row["modifiers"]["stage51_validity"]["threshold_delta"] == 12
    assert set(row["measures"]) == set(session.MEASURES)


# ── the Learning Engine's payoff ────────────────────────────────────────
def _log():
    return [
        {"trading_day": "2026-07-28", "ts": "2026-07-28T09:30:00+05:30",
         "session": "OPENING_DRIVE"},
        {"trading_day": "2026-07-28", "ts": "2026-07-28T12:00:00+05:30",
         "session": "MIDDAY_BALANCE"},
        {"trading_day": "2026-07-28", "ts": "2026-07-28T14:00:00+05:30",
         "session": "AFTERNOON_TREND"},
    ]


def test_a_trade_is_attributed_to_the_session_it_was_taken_in():
    """Attributing by the day's final session would credit every morning trade
    to the close."""
    results = [
        {"signal_id": "A", "trading_day": "2026-07-28",
         "exit_at": "2026-07-28T09:40:00+05:30", "outcome": "loss",
         "pnl_points": -12},
        {"signal_id": "B", "trading_day": "2026-07-28",
         "exit_at": "2026-07-28T14:30:00+05:30", "outcome": "win",
         "pnl_points": 30},
    ]
    perf = {p["session"]: p for p in
            session.performance_by_session(_log(), results)}
    assert perf["OPENING_DRIVE"]["wins"] == 0
    assert perf["AFTERNOON_TREND"]["wins"] == 1


def test_performance_is_ordered_chronologically_not_by_win_rate():
    """Reading the day in order is what makes 'we lose money at midday'
    visible."""
    results = [{"signal_id": str(i), "trading_day": "2026-07-28",
                "exit_at": t, "outcome": o, "pnl_points": p}
               for i, (t, o, p) in enumerate([
                   ("2026-07-28T09:40:00+05:30", "loss", -10),
                   ("2026-07-28T12:30:00+05:30", "loss", -8),
                   ("2026-07-28T14:30:00+05:30", "win", 25)])]
    order = [p["session"] for p in
             session.performance_by_session(_log(), results)]
    assert order == ["OPENING_DRIVE", "MIDDAY_BALANCE", "AFTERNOON_TREND"]


def test_thin_sessions_are_marked_not_dropped():
    results = [{"signal_id": "A", "trading_day": "2026-07-28",
                "exit_at": "2026-07-28T14:30:00+05:30", "outcome": "win",
                "pnl_points": 10}]
    perf = session.performance_by_session(_log(), results)
    assert perf and perf[0]["thin"] is True


def test_ungraded_trades_are_not_counted():
    results = [{"signal_id": "A", "trading_day": "2026-07-28",
                "exit_at": "2026-07-28T14:30:00+05:30", "outcome": "open"}]
    assert session.performance_by_session(_log(), results) == []


def test_learning_helpers_survive_empty_input():
    assert session.performance_by_session(None, None) == []


# ── the boundary ────────────────────────────────────────────────────────
def test_the_engine_is_registered_and_non_directional():
    from mios_v5.core.contract import Bias
    from mios_v5.engines import ALL_ENGINES
    from mios_v5.engines.stage69_session import SessionIntelligenceEngine
    assert SessionIntelligenceEngine in ALL_ENGINES
    import inspect
    assert "bias=Bias.NONE" in inspect.getsource(SessionIntelligenceEngine)
    assert Bias.NONE.value == "NONE"


def test_it_is_excluded_from_evidence_correlation():
    from mios_v5.evidence import EXCLUDED, FAMILIES
    assert "stage69_session" in EXCLUDED
    for members in FAMILIES.values():
        assert "stage69_session" not in members


def test_it_exposes_no_mutators():
    for banned in ("decide", "apply", "set_confidence", "signal", "enter",
                   "override", "set_threshold"):
        assert not hasattr(session, banned), banned


def test_it_reads_stage_6_rather_than_replacing_it():
    """Stage 6 still feeds `confidence_tempered`; Stage 69 must not have taken
    that over."""
    import inspect

    from mios_v5 import final_read
    src = inspect.getsource(final_read.build_final_read)
    assert 'conv = (tc.data.get("conviction")' in src
    from mios_v5.engines.stage69_session import SessionIntelligenceEngine
    assert "stage06_timecycle" in SessionIntelligenceEngine.deps


# ── panels ──────────────────────────────────────────────────────────────
def test_panels_render_and_stay_quiet_when_empty():
    from mios_v5.ui import session_panel as sp
    r = session.read(_fr(), price={"atr_pct": 0.9}, now=_at(10, 15),
                     conviction=80)

    strip = sp.session_strip(r)
    assert "Morning Trend" in strip and "min left" in strip

    card = sp.session_card(r)
    assert "Current session" in card
    assert "Recommended" in card and "Avoid" in card
    assert "Session Strength" in card
    assert "cannot override the Decision Engine" in card

    table = sp.modifier_table(r)
    assert "Session modifiers" in table
    assert "NOT APPLIED" in table

    assert sp.session_strip(None) == ""
    assert "not yet classified" in sp.session_card(None)
    assert "029_session_log" in sp.performance_by_session(None)


def test_the_card_names_the_engines_that_did_not_report():
    from mios_v5.ui.session_panel import session_card
    html = session_card(session.read({}, now=_at(10, 15)))
    assert "not reporting" in html


def test_the_modifier_table_shows_what_it_would_have_done():
    """Showing the adjustment the trader is NOT yet getting is the evidence
    that decides whether to promote it."""
    from mios_v5.ui.session_panel import modifier_table
    html = modifier_table(session.read(_fr(), now=_at(12, 0)))
    assert "stage51_validity" in html
    assert "threshold_delta 12" in html
    assert "multiple confirmations" in html


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"session tests passed ({len(fns)})")
