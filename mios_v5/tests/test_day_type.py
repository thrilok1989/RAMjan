"""MIOS V6.5 — Stage 68 Market Day Classification tests.

Two properties matter beyond correctness: the classification must be driven by
**cross-group agreement** rather than signal count, and the engine must be
provably unable to influence a decision.
"""

from mios_v5 import day_type


def _fr(**kw):
    base = {
        "preferred_bias": "BULL", "stability": "STABLE",
        "market_state": {"state": "TREND_UP", "label": "⬆️ TREND UP"},
        "memory_read": {"state": "TREND_UP", "state_duration_min": 42.0},
        "transition": {"state": "STRENGTHENING", "bias": "BULL"},
        "reaction": {"state": "CONFIRMED_BREAKOUT", "label": "🚀 Breakout",
                     "winner": "Buyers", "confidence": 80},
        "battle_zone": {"lifecycle": "broken", "type": "RESISTANCE",
                        "price": 24000},
        "absorption": {"behaviour": "AGGRESSIVE_BUYING", "tone": "bull",
                       "label": "🟢 Aggressive Buying", "confidence": 72},
        "energy_read": {"state": "EXPANSION"},
        "htf": {"alignment": {"bias": "BULL", "score": 78, "label": "5/6 Bull"}},
        "families": {"institutions": {"direction": "BULL", "strength": 76,
                                      "reliability": "HIGH"}},
        "sections": {"flows": {"bias": "BULL", "headline": "FII buying"},
                     "sector": {"bias": "BULL", "headline": "breadth positive"},
                     "orderflow": {"headline": "CVD rising"},
                     "dealer": {"headline": "gamma flip below"},
                     "options": {"headline": "call unwinding"}},
    }
    base.update(kw)
    return base


_TRENDY_PRICE = {"higher_highs": True, "higher_lows": True,
                 "atr_state": "EXPANDING", "atr_pct": 0.7,
                 "day_range_pct": 1.6, "vwap_distance_pct": 0.8,
                 "breakouts": 4, "failed_breakouts": 0,
                 "opening_range": "BROKEN"}

_RANGEY_PRICE = {"higher_highs": False, "higher_lows": False,
                 "atr_state": "COMPRESSING", "atr_pct": 0.3,
                 "day_range_pct": 0.5, "vwap_distance_pct": 0.05,
                 "poc_distance_pct": 0.02, "breakouts": 0,
                 "failed_breakouts": 4, "opening_range": "HELD"}


def _rangey_fr():
    return _fr(market_state={"state": "ROTATION", "label": "🔁 ROTATION"},
               transition={"state": "STABLE", "bias": "NEUTRAL"},
               reaction={"state": "REJECTION", "label": "🟢 Rejection",
                         "winner": "Buyers", "confidence": 70},
               battle_zone={"lifecycle": "stable", "tests": 4},
               absorption={"behaviour": "PASSIVE_BUYING", "tone": "bull",
                           "label": "🟢 Passive Buying", "confidence": 65},
               energy_read={"state": "COMPRESSION"},
               htf={"alignment": {"bias": "NEUTRAL", "score": 40}},
               families={})


# ── the eight types ─────────────────────────────────────────────────────
def test_every_type_has_a_label_expectation_and_style():
    for t in day_type.TYPES:
        assert t in day_type.LABEL
        assert t in day_type.COLOUR
        assert day_type.EXPECTED.get(t), t
        rec, avoid = day_type.STYLE.get(t, ([], []))
        assert rec and avoid, t


def test_a_trending_tape_classifies_as_a_trend_day():
    c = day_type.classify(_fr(), price=_TRENDY_PRICE)
    assert c["type"] == "TREND"
    assert c["confidence"] > 30
    assert c["recommended"] and c["avoid"]


def test_a_rotating_tape_classifies_as_a_range_day():
    c = day_type.classify(_rangey_fr(), price=_RANGEY_PRICE)
    assert c["type"] == "RANGE", c["tally"]


def test_a_dead_tape_classifies_as_low_participation():
    c = day_type.classify(
        _fr(market_state={"state": "WAIT", "label": "⏳ WAIT"},
            transition={"state": "STABLE"}, reaction={"state": "IDLE"},
            absorption={"behaviour": "NONE"}, energy_read={"state": "DEAD"},
            battle_zone={}, htf={}, families={}, sections={}),
        price={"atr_pct": 0.15, "day_range_pct": 0.2,
               "atr_state": "COMPRESSING"},
        flow={"cvd_state": "FLAT", "volume_state": "DRY",
              "money_flow_state": "FLAT"})
    assert c["type"] == "LOW_PARTICIPATION", c["tally"]


def test_trap_heavy_levels_classify_as_choppy():
    c = day_type.classify(
        _fr(reaction={"state": "BULL_TRAP", "label": "🪤 Bull trap",
                      "confidence": 70, "winner": "Sellers"},
            market_state={"state": "TRAP_ACTIVE", "label": "🪤 TRAP ACTIVE"},
            transition={"state": "REVERSING", "bias": "BEAR"},
            memory_read={"state": "TRAP_ACTIVE", "state_duration_min": 3.0},
            battle_zone={"lifecycle": "under-attack"},
            absorption={"behaviour": "NONE"}, htf={}, families={}),
        price={"higher_highs": True, "lower_lows": True,
               "breakouts": 1, "failed_breakouts": 5},
        flow={"cvd_state": "CHOPPY"})
    assert c["type"] == "CHOPPY", c["tally"]


def test_a_shocked_whipsawing_tape_classifies_as_high_volatility():
    c = day_type.classify(
        _fr(stability="SHOCK", energy_read={"state": "EXPANSION"},
            market_state={"state": "EXPANSION", "label": "💥 EXPANSION"},
            reaction={"state": "IDLE"}, battle_zone={},
            absorption={"behaviour": "NONE"},
            htf={"alignment": {"bias": "NEUTRAL", "score": 35}},
            families={}, sections={}),
        price={"atr_pct": 1.6, "atr_state": "EXPANDING", "day_range_pct": 2.2},
        dealer={"gex": -450.0, "gamma_flip_near": True},
        flow={"volume_state": "EXPLOSIVE"})
    assert c["type"] == "HIGH_VOLATILITY", c["tally"]


def test_a_trending_tape_that_gets_shocked_keeps_its_type_but_gains_a_caveat():
    """Classification and style are different questions. A strongly trending
    tape is still a trend day when flow shocks — but 'ride winners on a wide
    trail' is dangerous advice at that moment, and the caveat says so."""
    calm = day_type.classify(_fr(), price=_TRENDY_PRICE)
    shocked = day_type.classify(_fr(stability="SHOCK"), price=_TRENDY_PRICE)
    assert shocked["type"] == calm["type"] == "TREND"
    assert calm["style_caveat"] is None
    assert shocked["style_caveat"] and "size" in shocked["style_caveat"].lower()
    assert "Stage 44" in shocked["style_caveat"]


# ── the two precedence types ────────────────────────────────────────────
def test_a_live_event_takes_precedence_over_the_tape():
    """The tape can look like a trend all morning; on a news day the correct
    classification is still 'news day', because that is how it must be traded."""
    c = day_type.classify(
        _fr(event={"event_detected": True, "event_score": 88,
                   "reaction": "spike"}),
        price=_TRENDY_PRICE)
    assert c["type"] == "NEWS_EVENT"
    assert c["forced"] is True
    assert "Stage 28" in c["forced_reason"]
    # the underlying vote is preserved, not discarded
    assert c["voted_type"] == "TREND"
    assert c["voted_label"] == day_type.LABEL["TREND"]


def test_an_expiry_pin_takes_precedence():
    c = day_type.classify(
        _fr(), price=_TRENDY_PRICE, is_expiry=True,
        charm_pin={"active": True, "pin": 24000.0,
                   "drift": "above spot — upward drag"})
    assert c["type"] == "EXPIRY_PIN" and c["forced"] is True
    assert "24,000" in c["forced_reason"]


def test_expiry_without_a_measurable_pin_does_not_force():
    c = day_type.classify(_fr(), price=_TRENDY_PRICE, is_expiry=True,
                          charm_pin={"active": False})
    assert c["forced"] is False and c["type"] == "TREND"


def test_a_forced_type_still_carries_a_floor_confidence():
    c = day_type.classify(_fr(event={"event_detected": True,
                                     "event_score": 90}), price=_TRENDY_PRICE)
    assert c["confidence"] >= 70


# ── confidence is agreement, not signal count ───────────────────────────
def test_confidence_scales_with_how_many_groups_agree():
    """Twelve signals from one group is one opinion repeated twelve times."""
    broad = day_type.classify(_fr(), price=_TRENDY_PRICE)
    narrow = day_type.classify(
        {"market_state": {"state": "TREND_UP", "label": "x"},
         "memory_read": {"state_duration_min": 42.0},
         "transition": {"state": "STRENGTHENING"},
         "stability": "STABLE", "energy_read": {"state": "EXPANSION"}},
        price=_TRENDY_PRICE)
    assert broad["groups_backing"] > narrow["groups_backing"]
    assert broad["confidence"] > narrow["confidence"]


def test_thin_coverage_is_capped_and_says_so():
    c = day_type.classify({"market_state": {"state": "TREND_UP", "label": "x"},
                           "transition": {"state": "STRENGTHENING"}})
    assert c["groups_available"] < day_type._MIN_GROUPS
    assert c["confidence"] <= day_type._THIN_CAP
    assert "Not enough independent evidence" in c["confidence_note"]


def test_the_depth_group_skips_gracefully_and_is_never_faked():
    c = day_type.classify(_fr(), price=_TRENDY_PRICE)
    depth = next(g for g in c["groups"] if g["group"] == "depth")
    assert depth["available"] is False
    assert "Stage 15 DISABLED" in depth["reason"]
    assert depth["votes"] == {}


def test_a_supplied_depth_book_does_participate():
    c = day_type.classify(_fr(), price=_TRENDY_PRICE,
                          depth={"bid_ask_imbalance_pct": 45.0})
    depth = next(g for g in c["groups"] if g["group"] == "depth")
    assert depth["available"] is True and depth["top"] == "TREND"


def test_no_evidence_at_all_is_unclassified():
    c = day_type.classify({})
    assert c["type"] == "UNKNOWN" and c["confidence"] == 0
    assert c["groups_available"] == 0


def test_every_vote_carries_a_visible_signal_and_its_engine():
    """A vote with no signal behind it is exactly the generic output the
    explainability layer exists to prevent."""
    c = day_type.classify(_fr(), price=_TRENDY_PRICE)
    for g in c["groups"]:
        if not g["available"]:
            continue
        assert g["signals"], g["group"]
        for s in g["signals"]:
            assert s["text"] and s["engine"] and s["type"] in day_type.TYPES
    assert c["evidence"] and all(s["engine"] for s in c["evidence"])


def test_runners_up_are_reported():
    c = day_type.classify(_fr(), price=_TRENDY_PRICE)
    assert c["runners_up"]
    assert all(r["type"] != c["type"] for r in c["runners_up"])


# ── live transitions ────────────────────────────────────────────────────
M = 60.0


def test_a_challenger_must_confirm_before_it_replaces_the_incumbent():
    """'Never lock the market type' does not mean 'flip on every tick'."""
    t = day_type.track(None, {"type": "RANGE", "label": "↔ Range Day",
                              "confidence": 70}, now_ts=0.0)
    assert t["type"] == "RANGE"
    t = day_type.track(t, {"type": "TREND", "label": "📈 Trend Day",
                           "confidence": 65}, now_ts=M)
    assert t["type"] == "RANGE" and t["pending"] == "TREND"
    t = day_type.track(t, {"type": "TREND", "label": "📈 Trend Day",
                           "confidence": 68}, now_ts=2 * M)
    assert t["type"] == "TREND" and t["pending"] is None


def test_a_single_noisy_cycle_does_not_flip_the_type():
    t = day_type.track(None, {"type": "RANGE", "label": "x"}, now_ts=0.0)
    t = day_type.track(t, {"type": "CHOPPY", "label": "y"}, now_ts=M)
    t = day_type.track(t, {"type": "RANGE", "label": "x"}, now_ts=2 * M)
    assert t["type"] == "RANGE" and not t["history"]


def test_a_forced_type_switches_immediately():
    """A live event is not something to confirm over two minutes."""
    t = day_type.track(None, {"type": "RANGE", "label": "x"}, now_ts=0.0)
    t = day_type.track(t, {"type": "NEWS_EVENT", "label": "💥 News Event Day",
                           "confidence": 88, "forced": True,
                           "forced_reason": "Stage 28 detected an event"},
                       now_ts=M)
    assert t["type"] == "NEWS_EVENT"
    assert t["history"][-1]["from"] == "RANGE"


def test_duration_accrues_while_the_type_holds():
    t = None
    for i in range(6):
        t = day_type.track(t, {"type": "TREND", "label": "x", "confidence": 70},
                           now_ts=i * M)
    assert t["duration_min"] == 5.0 and t["cycles"] == 6


def test_transition_history_records_what_it_came_from_and_how_long():
    t = None
    for i in range(5):
        t = day_type.track(t, {"type": "RANGE", "label": "↔ Range Day"},
                           now_ts=i * M)
    for i in range(5, 8):
        t = day_type.track(t, {"type": "TREND", "label": "📈 Trend Day",
                               "confidence": 72}, now_ts=i * M)
    h = t["history"][-1]
    assert h["from"] == "RANGE" and h["to"] == "TREND"
    assert h["duration_min"] == 4.0
    assert t["changes_today"] == 1


def test_the_type_is_never_locked():
    t = None
    for name in ("RANGE", "RANGE", "SWING", "SWING", "TREND", "TREND",
                 "EXPIRY_PIN", "EXPIRY_PIN"):
        t = day_type.track(t, {"type": name, "label": name}, now_ts=M)
    assert t["type"] == "EXPIRY_PIN"
    assert len(t["history"]) == 3


def test_timeline_reads_as_the_sessions_story():
    t = None
    for i, name in enumerate(("RANGE", "RANGE", "TREND", "TREND")):
        t = day_type.track(t, {"type": name, "label": day_type.LABEL[name],
                               "confidence": 70}, now_ts=i * M)
    tl = day_type.timeline(t)
    assert tl[-1]["current"] is True
    assert tl[-1]["to"] == day_type.LABEL["TREND"]


def test_track_ignores_an_unclassified_cycle():
    t = day_type.track({"type": "TREND"}, {"type": "UNKNOWN"}, now_ts=M)
    assert t["type"] == "TREND"
    assert day_type.track(None, None, 0.0) == {}


def test_log_row_is_written_only_on_a_change():
    t = day_type.track(None, {"type": "RANGE", "label": "x"}, now_ts=0.0)
    c = {"type": "RANGE", "evidence": [{"text": "a"}], "groups_backing": 3,
         "groups_available": 5}
    assert day_type.log_row(t, c) is None       # first classification, no history
    for i in range(1, 3):
        t = day_type.track(t, {"type": "TREND", "label": "y",
                               "confidence": 70}, now_ts=i * M)
    row = day_type.log_row(t, c, trading_day="2026-07-28")
    assert row["previous_type"] == "RANGE" and row["new_type"] == "TREND"
    assert row["trading_day"] == "2026-07-28"
    assert row["evidence"] == ["a"]


# ── the Learning Engine's payoff ────────────────────────────────────────
def _log():
    return [
        {"trading_day": "2026-07-28", "ts": "2026-07-28T09:20:00",
         "new_type": "RANGE", "previous_duration_min": 0},
        {"trading_day": "2026-07-28", "ts": "2026-07-28T12:00:00",
         "new_type": "TREND", "previous_type": "RANGE",
         "previous_duration_min": 160},
    ]


def test_a_trade_is_attributed_to_the_type_in_force_when_it_was_taken():
    """Attributing by the day's FINAL type would credit a trend morning's wins
    to the pin afternoon that followed it."""
    results = [
        {"signal_id": "A", "trading_day": "2026-07-28",
         "exit_at": "2026-07-28T10:00:00", "outcome": "loss",
         "pnl_points": -10},
        {"signal_id": "B", "trading_day": "2026-07-28",
         "exit_at": "2026-07-28T13:00:00", "outcome": "win", "pnl_points": 30},
    ]
    perf = {p["type"]: p for p in day_type.performance_by_type(_log(), results)}
    assert perf["RANGE"]["trades"] == 1 and perf["RANGE"]["wins"] == 0
    assert perf["TREND"]["trades"] == 1 and perf["TREND"]["wins"] == 1


def test_thin_types_are_dimmed_not_dropped():
    results = [{"signal_id": str(i), "trading_day": "2026-07-28",
                "exit_at": "2026-07-28T13:00:00", "outcome": "win",
                "pnl_points": 10} for i in range(3)]
    perf = day_type.performance_by_type(_log(), results)
    assert perf and perf[0]["thin"] is True and perf[0]["trades"] == 3


def test_ungraded_trades_are_not_counted():
    results = [{"signal_id": "A", "trading_day": "2026-07-28",
                "exit_at": "2026-07-28T13:00:00", "outcome": "open"}]
    assert day_type.performance_by_type(_log(), results) == []


def test_occurrence_reports_frequency_and_typical_hold():
    occ = {o["type"]: o for o in day_type.occurrence(_log())}
    assert occ["TREND"]["count"] == 1
    assert occ["RANGE"]["count"] == 1
    assert occ["TREND"]["avg_hold_min"] == 160.0


def test_learning_helpers_survive_empty_input():
    assert day_type.performance_by_type(None, None) == []
    assert day_type.occurrence(None) == []


# ── the boundary ────────────────────────────────────────────────────────
def test_the_engine_is_registered_but_non_directional():
    from mios_v5.core.contract import Bias
    from mios_v5.engines import ALL_ENGINES
    from mios_v5.engines.stage68_day_type import MarketDayTypeEngine
    assert MarketDayTypeEngine in ALL_ENGINES
    import inspect
    src = inspect.getsource(MarketDayTypeEngine)
    assert "bias=Bias.NONE" in src
    assert Bias.NONE.value == "NONE"


def test_it_is_excluded_from_evidence_correlation():
    """It reads every family; voting would count each of them a second time."""
    from mios_v5.evidence import EXCLUDED, FAMILIES
    assert "stage68_day_type" in EXCLUDED
    for members in FAMILIES.values():
        assert "stage68_day_type" not in members


def test_it_exposes_no_mutators_and_declares_itself_advisory():
    for banned in ("decide", "apply", "set_confidence", "signal", "enter",
                   "override"):
        assert not hasattr(day_type, banned), banned
    assert day_type.classify(_fr(), price=_TRENDY_PRICE)["advisory_only"] is True


def test_the_key_does_not_collide_with_stage_4s_day_type():
    """Stage 4 already owns `fr["day_type"]` for its expiry/gap frame; a silent
    collision would have shadowed it for every existing reader."""
    import inspect

    from mios_v5 import final_read
    src = inspect.getsource(final_read.build_final_read)
    assert src.count('"day_type":') == 1
    assert '"day_classification":' in src


def test_the_daily_summary_quotes_stage_68_rather_than_reclassifying():
    from mios_v5.daily_summary import market_personality
    p = market_personality(
        {"day_classification": {"type": "TREND", "label": "📈 Trend Day",
                                "confidence": 84,
                                "confidence_note": "5 of 6 groups agree",
                                "memory": {"duration_min": 90.0,
                                           "changes_today": 2}}},
        state_log=["ROTATION"] * 50)
    assert p["source"] == "stage68"
    assert p["type"] == "TREND" and p["confidence"] == 84


def test_the_daily_summary_still_falls_back_without_stage_68():
    from mios_v5.daily_summary import market_personality
    p = market_personality({"stability": "STABLE"}, ["MARK_UP"] * 40)
    assert p["source"] == "fallback" and p["personality"] == "Trending"


# ── panels ──────────────────────────────────────────────────────────────
def test_panels_render_and_stay_quiet_when_empty():
    from mios_v5.ui import day_type_panel as dp
    c = day_type.classify(_fr(), price=_TRENDY_PRICE)
    t = day_type.track(None, c, now_ts=0.0)
    c = {**c, "duration_min": t["duration_min"],
         "changes_today": t["changes_today"], "memory": t}

    badge = dp.day_type_badge(c)
    assert "Trend Day" in badge and "Today's market" in badge

    card = dp.day_type_card(c)
    assert "Recommended" in card and "Avoid" in card
    assert "Expected" in card
    assert "cannot override the Decision Engine" in card
    assert "Flow in SHOCK" in dp.day_type_card(
        day_type.classify(_fr(stability="SHOCK"), price=_TRENDY_PRICE))

    detail = dp.day_type_detail(c)
    assert "evidence groups" in detail
    assert "Stage 15 DISABLED" in detail      # unavailable groups are shown

    tl = dp.day_type_timeline(day_type.timeline(t))
    assert "How today has evolved" in tl

    assert dp.day_type_badge(None) == ""
    assert "not yet classified" in dp.day_type_card(None)
    assert dp.day_type_detail(None) == ""
    assert dp.day_type_timeline(None) == ""


def test_the_forced_card_shows_what_the_tape_voted_underneath():
    from mios_v5.ui.day_type_panel import day_type_card
    c = day_type.classify(_fr(event={"event_detected": True,
                                     "event_score": 90}), price=_TRENDY_PRICE)
    html = day_type_card(c)
    assert "News Event Day" in html
    assert "The tape itself voted" in html and "Trend Day" in html


def test_performance_panel_dims_thin_rows():
    from mios_v5.ui.day_type_panel import performance_by_type
    html = performance_by_type([{"label": "📈 Trend Day", "win_rate": 70.0,
                                 "trades": 4, "sessions": 2, "thin": True}])
    assert "thin" in html and "shown, not trusted" in html
    assert "028_day_type_log" in performance_by_type(None)


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"day type tests passed ({len(fns)})")
