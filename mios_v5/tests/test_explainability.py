"""MIOS V6.5 — Explainability tests (Stages 61-67).

Two things are under test: that the explanations are *correct*, and that they
are *never generic*. The second matters as much as the first — a layer that
fills in confident prose when the engines are silent is worse than no layer,
because it launders missing evidence into apparent reasoning.
"""

from mios_v5 import (checklist, daily_summary, explain_decision, narrator,
                     risk_explain, trade_review)


def _fr(**kw):
    """A final read with every V6.5 input present unless overridden."""
    base = {
        "preferred_bias": "BULL", "confidence": 74, "stability": "STABLE",
        "decision_v2": {
            "state": "ENTER", "label": "✅ ENTER", "side": "CALL",
            "confidence": 82, "quality": "A", "entry": 23900.0,
            "stop": 23850.0, "reasons": ["Floor proven at 23,900"],
            "warnings": [],
            "proof": {"confirmed": True, "label": "FLOOR CONFIRMED",
                      "zone_price": 23880.0, "n_passed": 8, "n_checks": 8,
                      "refusal": {"proven": True, "price": 23900.0},
                      "reasons": ["Sellers could not push below 23,880"]},
        },
        "reaction": {"state": "REJECTION", "label": "🟢 Rejection",
                     "winner": "Buyers", "confidence": 81, "side": "SUPPORT",
                     "actionable": True},
        "absorption": {"behaviour": "PASSIVE_BUYING", "tone": "bull",
                       "label": "🟢 Passive Buying", "confidence": 74,
                       "expectation": "Accumulation continues"},
        "dealer": {"bias": "NEUTRAL", "label": "🏦 Dealers neutral"},
        "market_state": {"state": "MARK_UP", "label": "📈 Mark Up"},
        "memory_read": {"state": "MARK_UP", "state_duration_min": 32.0,
                        "state_mature": True, "state_fresh": False,
                        "state_transition_risk": 15},
        "htf": {"alignment": {"bias": "BULL", "score": 74, "stars": "★★★★☆",
                              "label": "4/6 Bull", "disagree": []}},
        "validity": {"verdict": "VALID", "valid": True, "pct": 78},
        "transition": {"state": "STRENGTHENING", "label": "↑ Strengthening",
                       "bias": "BULL", "reversal_probability": 12},
        "battle_zone": {"lifecycle": "stable", "health_pct": 72,
                        "support": 23880.0, "resistance": 24050.0},
        "flow_shift": {},
    }
    base.update(kw)
    return base


# ── Stage 63 · Entry Checklist ──────────────────────────────────────────
def test_checklist_covers_every_condition_with_its_engine():
    cl = checklist.build(_fr())
    assert len(cl["rows"]) == len(checklist.CONDITIONS)
    for r in cl["rows"]:
        assert r["engine"] and r["label"]
        # never a bare tick — the engine's actual output is always attached
        assert r["actual"]


def test_checklist_weights_sum_to_100():
    assert sum(w for _, w, _ in checklist.CONDITIONS.values()) == 100


def test_a_clean_setup_reads_fully_ready():
    cl = checklist.build(_fr())
    assert cl["readiness"] == 100 and not cl["failed"]
    assert cl["blocking"] is None
    assert cl["side"] == "CALL"


def test_unknown_is_a_third_state_not_a_guess():
    """A silent engine must not be scored as met OR failed."""
    cl = checklist.build(_fr(absorption=None, htf=None))
    keys = {r["key"] for r in cl["unknown"]}
    assert {"absorption", "htf"} <= keys
    for r in cl["unknown"]:
        assert r["state"] is None and r["icon"] == "⚪"
    # excluded from the denominator, reported as coverage
    assert cl["coverage"] < 100 and cl["readiness"] == 100


def test_readiness_is_weighted_not_counted():
    """Failing the two heaviest conditions must cost more than failing two
    light ones."""
    heavy = checklist.build(_fr(
        validity={"verdict": "INVALID", "valid": False, "pct": 40},
        reaction={"state": "BULL_TRAP", "label": "Bull trap", "confidence": 70,
                  "winner": "Sellers"}))
    light = checklist.build(_fr(
        market_state={"state": "ROTATION", "label": "Rotation"},
        dealer={"bias": "BEAR", "label": "🏦 Dealers bearish"}))
    assert heavy["readiness"] < light["readiness"]


def test_blocking_is_the_heaviest_unmet_condition():
    cl = checklist.build(_fr(
        validity={"verdict": "INVALID", "valid": False, "pct": 40},
        dealer={"bias": "BEAR", "label": "🏦 Dealers bearish"}))
    assert cl["blocking"]["key"] == "validity"       # weight 13 > 10


def test_a_trap_fails_acceptance_whichever_way_you_face():
    for side in ("CALL", "PUT"):
        cl = checklist.build(_fr(reaction={
            "state": "BULL_TRAP", "label": "Bull trap", "confidence": 70,
            "winner": "Sellers"}), side=side)
        row = next(r for r in cl["rows"] if r["key"] == "acceptance")
        assert row["state"] is False


def test_a_neutral_dealer_does_not_block_the_trade():
    cl = checklist.build(_fr())
    row = next(r for r in cl["rows"] if r["key"] == "dealer")
    assert row["state"] is True and "not opposing" in row["actual"]


def test_a_fresh_state_fails_market_state():
    cl = checklist.build(_fr(memory_read={"state": "MARK_UP",
                                          "state_duration_min": 2.0,
                                          "state_fresh": True}))
    row = next(r for r in cl["rows"] if r["key"] == "market_state")
    assert row["state"] is False and "too young" in row["actual"]


def test_decaying_bias_fails_even_when_it_agrees():
    cl = checklist.build(_fr(transition={"state": "WEAKENING",
                                         "label": "↓ Weakening",
                                         "bias": "BULL"}))
    row = next(r for r in cl["rows"] if r["key"] == "bias")
    assert row["state"] is False and "decaying" in row["actual"]


def test_checklist_with_nothing_never_raises():
    cl = checklist.build(None)
    assert cl["readiness"] == 0 and cl["coverage"] == 0
    assert all(r["state"] is None for r in cl["rows"])
    assert checklist.missing(None) == []


# ── Stage 61 · Decision Explainability ──────────────────────────────────
def test_enter_call_explains_as_buy():
    e = explain_decision.explain(_fr())
    assert e["action"] == "BUY" and e["side"] == "CALL"
    assert e["confidence"] == 82


def test_enter_put_explains_as_sell():
    fr = _fr()
    fr["decision_v2"]["side"] = "PUT"
    assert explain_decision.explain(fr)["action"] == "SELL"


def test_every_state_maps_to_a_recognisable_action():
    for state in ("WAIT", "ENTRY_READY", "HOLD", "TRAIL", "EXIT", "ABORT",
                  "SCALE_IN", "SCALE_OUT", "COMPLETE"):
        fr = _fr()
        fr["decision_v2"]["state"] = state
        e = explain_decision.explain(fr)
        assert e["action"] and e["emoji"] and e["colour"]


def test_no_reason_is_ever_generic():
    """Every line carries the engine that produced it and that engine's own
    output — there is no template prose anywhere in the layer."""
    e = explain_decision.explain(_fr())
    assert e["reasons"]
    for r in e["reasons"]:
        assert r["actual"], r
        assert r["engine"], r
        assert r["actual"] in r["text"]


def test_thin_evidence_produces_a_short_explanation_not_invented_prose():
    e = explain_decision.explain({"decision_v2": {"state": "WAIT"}})
    assert e["reasons"] == []
    assert "no engine evidence" in e["sentence"] or e["action"] == "WAIT"
    # nothing fabricated to fill the gap
    assert e["what_happened"] is None


def test_opposing_engines_are_shown_not_suppressed():
    e = explain_decision.explain(_fr(
        dealer={"bias": "BEAR", "label": "🏦 Dealers bearish"},
        htf={"alignment": {"bias": "BEAR", "score": 70, "label": "4/6 Bear",
                           "stars": "", "disagree": []}}))
    labels = {o["label"] for o in e["opposed"]}
    assert "Dealer" in labels and "HTF Alignment" in labels


def test_decision_engine_warnings_surface_as_opposition():
    fr = _fr()
    fr["decision_v2"]["warnings"] = ["Thin liquidity above"]
    e = explain_decision.explain(fr)
    assert any("Thin liquidity" in o["actual"] for o in e["opposed"])


def test_what_happened_prefers_the_thing_that_already_occurred():
    e = explain_decision.explain(_fr())
    assert "Rejection" in e["what_happened"]
    assert "Buyers won" in e["what_happened"]


def test_explanation_always_answers_the_four_questions():
    e = explain_decision.explain(_fr())
    for k in ("what_happened", "why", "expect", "invalidates"):
        assert k in e
    assert e["expect"] and e["invalidates"]


def test_risk_escalates_on_named_engine_conditions():
    calm = explain_decision.explain(_fr())
    hot = explain_decision.explain(_fr(
        flow_shift={"freeze_entries": True, "score": 78, "reason": "CVD swing"},
        transition={"state": "REVERSING", "bias": "BEAR", "label": "🔄",
                    "reversal_probability": 71}))
    assert hot["risk_score"] > calm["risk_score"]
    assert any("Stage 44" in r for r in hot["risk_reasons"])
    assert hot["risk"] in explain_decision.RISK_LEVELS


def test_risk_reasons_always_name_an_engine():
    e = explain_decision.explain(_fr(
        flow_shift={"freeze_entries": True, "score": 78, "reason": "x"}))
    for r in e["risk_reasons"]:
        assert "Stage" in r or "conditions unmet" in r


def test_market_quality_is_derived_not_a_46th_engine():
    """Evidence agreement × tape stability × energy × conflict — all engines
    that already exist."""
    good = explain_decision.market_quality(_fr(
        families_read={"dominant": "BULL", "agreement_pct": 88,
                       "severity": "LOW"},
        conflict_severity="LOW"))
    assert good["grade"] in ("EXCELLENT", "GOOD")
    assert any("Stage 53" in r for r in good["reasons"])


def test_a_shocked_tape_is_untradeable_not_merely_poor():
    """Some tapes should not be traded at all — 'poor' invites a smaller
    position where the correct answer is no position."""
    q = explain_decision.market_quality(_fr(
        families_read={"dominant": "BULL", "agreement_pct": 60,
                       "severity": "HIGH"},
        stability="SHOCK", conflict_severity="HIGH"))
    assert q["grade"] == "UNTRADEABLE"
    assert any("SHOCK" in r for r in q["reasons"])


def test_market_quality_is_honest_when_it_cannot_judge():
    q = explain_decision.market_quality({})
    assert q["grade"] == "—" and q["score"] is None


# ── Stage 62 · WAIT Analysis ────────────────────────────────────────────
def _waiting():
    fr = _fr(reaction={"state": "IDLE"},
             dealer={"bias": "BEAR", "label": "🏦 Dealers bearish"},
             flow_shift={"freeze_entries": True, "score": 66,
                         "reason": "OI velocity"},
             memory_read={"state": "RANGE", "state_duration_min": 3.0,
                          "state_fresh": True})
    fr["decision_v2"] = {"state": "WAIT", "label": "⏳ WAIT", "side": "CALL",
                         "blocked_by": "acceptance not confirmed"}
    return fr


def test_wait_says_exactly_what_is_missing():
    e = explain_decision.explain(_waiting())
    assert e["action"] == "WAIT"
    labels = {n["label"] for n in e["needs"]}
    assert "Dealer" in labels and "Flow Shift" in labels
    for n in e["needs"]:
        assert n["have"] and n["engine"]     # what you have, not just what you need


def test_wait_reports_a_readiness_percentage():
    e = explain_decision.explain(_waiting())
    assert 0 <= e["readiness"] < 100
    assert e["readiness_label"]


def test_needs_are_ordered_heaviest_first():
    e = explain_decision.explain(_waiting())
    weights = [n["weight"] for n in e["needs"]]
    assert weights == sorted(weights, reverse=True)


def test_blocked_by_prefers_the_decision_engines_own_reason():
    e = explain_decision.explain(_waiting())
    assert e["blocked_by"] == "acceptance not confirmed"


def test_blocked_by_falls_back_to_the_heaviest_failure():
    fr = _waiting()
    fr["decision_v2"].pop("blocked_by")
    e = explain_decision.explain(fr)
    assert e["blocked_by"] and "—" in e["blocked_by"]


def test_non_wait_decisions_carry_no_needs_list():
    e = explain_decision.explain(_fr())
    assert e["needs"] == [] and e["blocked_by"] is None


# ── Stage 64 · Risk Analysis ────────────────────────────────────────────
def test_risk_analysis_justifies_every_number():
    ra = risk_explain.analyse(_fr(), spot=23905,
                              levels={"support": 23880, "resistance": 24050})
    assert ra["available"] is True
    for k in ("entry", "stop", "target", "trail", "rr"):
        assert ra[k].get("why"), k


def test_stop_is_justified_against_the_institutional_level():
    ra = risk_explain.analyse(_fr())
    assert "23,880" in ra["stop"]["why"]
    assert ra["stop"]["distance"] == 50.0


def test_derived_values_are_labelled_as_derived():
    ra = risk_explain.analyse(_fr(), levels={"resistance": 24050})
    assert ra["target"]["basis"] == "derived"
    assert ra["entry"]["basis"] == "proven"


def test_reward_risk_is_computed_and_graded():
    ra = risk_explain.analyse(_fr(), levels={"resistance": 24050})
    assert ra["rr"]["value"] == 3.0 and ra["rr"]["acceptable"] is True


def test_a_thin_reward_risk_is_called_out():
    fr = _fr()
    fr["decision_v2"]["stop"] = 23800.0        # 100 pts of risk
    ra = risk_explain.analyse(fr, levels={"resistance": 23950})
    assert ra["rr"]["acceptable"] is False
    assert "floor" in ra["rr"]["why"]


def test_invalidation_is_never_empty_while_a_stop_exists():
    ra = risk_explain.analyse(_fr())
    assert ra["invalidation"]
    assert any("23,850" in i["what"] for i in ra["invalidation"])
    for i in ra["invalidation"]:
        assert i["engine"]


def test_no_trade_means_no_invented_analysis():
    ra = risk_explain.analyse({"decision_v2": {"state": "WAIT"}})
    assert ra["available"] is False and "nothing to analyse" in ra["reason"]


def test_missing_stop_is_stated_not_hidden():
    fr = _fr()
    fr["decision_v2"]["stop"] = None
    ra = risk_explain.analyse(fr)
    assert ra["stop"]["basis"] == "missing"
    assert "not tradable" in ra["stop"]["why"]


# ── Stage 65 · Trade Narrator ───────────────────────────────────────────
def test_the_first_cycle_opens_the_narration():
    out = narrator.observe(None, _fr(), ts="2026-07-28T09:20:00")
    assert out["beats"] and out["signature"]


def test_an_unchanged_cycle_writes_nothing():
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20")
    b = narrator.observe(a["beats"], fr, ts="09:21",
                         last_signature=a["signature"])
    assert b["new"] == []
    assert len(b["beats"]) == len(a["beats"])


def test_a_transition_writes_exactly_one_beat():
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20")
    fr2 = _fr(dealer={"bias": "BEAR", "label": "🏦 Dealers bearish"})
    b = narrator.observe(a["beats"], fr2, ts="09:36",
                         last_signature=a["signature"])
    assert len(b["new"]) == 1
    assert "Dealers" in b["new"][0]["text"]
    assert b["new"][0]["time"] == "09:36"


def test_the_narrator_never_invents_an_action():
    """Observations are the narrator's; actions are quoted from Stage 52."""
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20")
    fr2 = _fr(flow_shift={"freeze_entries": True, "score": 74,
                          "reason": "CVD swing"})
    b = narrator.observe(a["beats"], fr2, ts="09:48",
                         last_signature=a["signature"])
    # a flow shift is observed, but no instruction is issued
    assert any("Flow shift" in x["text"] for x in b["new"])
    assert all(not x["action"] for x in b["new"])


def test_an_action_beat_is_quoted_from_the_decision_engine():
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20")
    fr2 = _fr()
    fr2["decision_v2"] = {"state": "EXIT", "label": "🚪 EXIT",
                          "reasons": ["Bias reversed"]}
    b = narrator.observe(a["beats"], fr2, ts="10:05",
                         last_signature=a["signature"])
    action = [x for x in b["new"] if x["action"]]
    assert action and "EXIT" in action[0]["text"]
    assert action[0]["engine"] == "Stage 52 Decision Engine"


def test_excursion_milestones_are_narrated_once():
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20", excursion={"mfe": 0, "mae": 0})
    b = narrator.observe(a["beats"], fr, ts="09:30",
                         excursion={"mfe": 24.0, "mae": -3.0},
                         last_signature=a["signature"])
    texts = [x["text"] for x in b["new"]]
    assert "Trade +10 pts in favour" in texts
    assert "Trade +20 pts in favour" in texts
    c = narrator.observe(b["beats"], fr, ts="09:31",
                         excursion={"mfe": 24.0, "mae": -3.0},
                         last_signature=b["signature"])
    assert c["new"] == []                     # not repeated


def test_beats_are_trimmed_to_the_keep_limit():
    beats, sig = None, None
    for i in range(120):
        fr = _fr(market_state={"state": f"S{i}", "label": f"State {i}"})
        out = narrator.observe(beats, fr, ts="09:20", last_signature=sig,
                               keep=10)
        beats, sig = out["beats"], out["signature"]
    assert len(beats) == 10


def test_recap_and_summary():
    fr = _fr()
    a = narrator.observe(None, fr, ts="09:20")
    assert narrator.recap(a["beats"])
    assert "developments" in narrator.summarise(a["beats"])
    assert narrator.summarise(None) == "No narration recorded."


# ── Stage 66 · Post-Trade Review ────────────────────────────────────────
def _trade(**kw):
    t = {"signal_id": "SIG-001", "trading_day": "2026-07-28",
         "direction": "CALL", "acceptance": "🟢 Rejection",
         "absorption": "🟢 Passive Buying", "market_state": "📈 Mark Up",
         "dealer_state": "🏦 Dealers neutral", "htf_alignment": "4/6 BULL",
         "snapshot": {"validity_score": 78, "evidence_families": 7}}
    t.update(kw)
    return t


def _rows(spec):
    return [{"signal_id": "SIG-001", "engine": e, "agreement": a,
             "conflict": c, "confidence": 80, "weight": 2.0,
             "output": f"{e} said so"} for e, a, c in spec]


def test_a_winner_is_reviewed_not_just_congratulated():
    rev = trade_review.review(
        _trade(), {"outcome": "win", "pnl_points": 30.0, "mfe": 78.0,
                   "mae": -5.0, "holding_secs": 1200,
                   "exit_reason": "TRAILING_STOP", "trade_quality": "POOR"},
        _rows([("acceptance", True, False), ("bias", False, True)]))
    assert rev["outcome"] == "Winner"
    assert "gave back" in rev["improvement"]
    assert "48 points" in rev["improvement"]


def test_a_well_managed_winner_is_said_to_be_well_managed():
    rev = trade_review.review(
        _trade(), {"outcome": "win", "pnl_points": 50.0, "mfe": 55.0,
                   "mae": -4.0}, _rows([("acceptance", True, False)]))
    assert "well managed" in rev["improvement"]


def test_best_and_weakest_engine_come_from_marginal_credit():
    rev = trade_review.review(
        _trade(), {"outcome": "win", "pnl_points": 40.0, "mfe": 45.0},
        _rows([("hero", True, False), ("wrong", False, True)]))
    assert rev["best_engine"] == "hero"
    assert rev["weakest_engine"] == "wrong"
    assert rev["best_credit"] > 0 > rev["weakest_credit"]


def test_a_loser_gets_a_full_investigation():
    rev = trade_review.review(
        _trade(htf_alignment="4/6 BEAR"),
        {"outcome": "loss", "pnl_points": -18.0, "mfe": 3.0, "mae": -20.0,
         "exit_reason": "STOP_LOSS"},
        _rows([("loud", True, False), ("right", False, True)]))
    assert rev["outcome"] == "Loser"
    assert rev["primary_cause"]
    assert rev["false_signal_type"]
    assert rev["outvoted"] == "right"
    assert "outvoted" in rev["better_alternative"]
    assert rev["lessons"]


def test_lessons_are_cause_specific_not_platitudes():
    mismanaged = trade_review.review(
        _trade(), {"outcome": "loss", "pnl_points": -10.0, "mfe": 35.0,
                   "exit_reason": "STOP_LOSS"}, _rows([("e", True, False)]))
    assert "Fix the exit" in mismanaged["lessons"][0]
    bad_read = trade_review.review(
        _trade(), {"outcome": "loss", "pnl_points": -10.0, "mfe": 1.0,
                   "exit_reason": "STOP_LOSS"}, _rows([("e", True, False)]))
    assert mismanaged["lessons"][0] != bad_read["lessons"][0]


def test_an_open_trade_is_not_reviewed():
    rev = trade_review.review(_trade(), {"outcome": "open"})
    assert rev["available"] is False and "not graded" in rev["reason"]


def test_review_many_skips_ungraded_rows():
    out = trade_review.review_many(
        [_trade()],
        [{"signal_id": "SIG-001", "outcome": "win", "pnl_points": 20.0,
          "mfe": 25.0},
         {"signal_id": "SIG-002", "outcome": "open"}],
        _rows([("e", True, False)]))
    assert len(out) == 1 and out[0]["signal_id"] == "SIG-001"


# ── Stage 67 · Daily Summary ────────────────────────────────────────────
def _day(n=6):
    res, trades, eng = [], [], []
    for i in range(n):
        sid, won = f"SIG-{i:03d}", i % 3 != 0
        res.append({"signal_id": sid, "trading_day": "2026-07-28",
                    "outcome": "win" if won else "loss",
                    "pnl_points": 25.0 if won else -12.0,
                    "mfe": 30.0 if won else 2.0, "mae": -8.0,
                    "holding_secs": 1080,
                    "exit_reason": "TARGET_HIT" if won else "STOP_LOSS"})
        trades.append(_trade(signal_id=sid, rr=2.0))
        for e, agree in (("sharp", won), ("blind", not won)):
            eng.append({"signal_id": sid, "engine": e, "agreement": agree,
                        "conflict": not agree, "confidence": 80, "weight": 2.0})
    return res, trades, eng


def test_daily_summary_reports_performance_and_engines():
    res, trades, eng = _day()
    s = daily_summary.summarise(results=res, trades=trades, engine_rows=eng,
                                final_read=_fr(), trading_day="2026-07-28")
    assert s["trades"] == 6 and s["wins"] == 4 and s["losses"] == 2
    assert s["win_rate"] == 66.7
    assert s["avg_rr"] == 2.0
    assert s["best_engine"] == "sharp" and s["weakest_engine"] == "blind"


def test_what_mios_refused_is_half_the_report():
    res, trades, eng = _day()
    s = daily_summary.summarise(
        results=res, trades=trades, engine_rows=eng, final_read=_fr(),
        wait_log=["Acceptance"] * 40 + ["Flow Shift"] * 9)
    assert s["most_common_wait_reason"] == "Acceptance"
    assert s["wait_cycles"] == 49
    assert s["wait_reasons"][0]["pct"] > 80


def test_personality_reads_how_the_day_was_spent_not_how_it_closed():
    """A day that trended for hours and closed in a 20-minute rotation was a
    trending day; reading only the closing state teaches the wrong lesson."""
    log = ["MARK_UP"] * 40 + ["ROTATION"] * 8
    p = daily_summary.market_personality(
        _fr(market_state={"state": "ROTATION", "label": "Rotation"}), log)
    assert p["personality"] == "Trending"


def test_a_shocked_close_overrides_everything():
    p = daily_summary.market_personality(_fr(stability="SHOCK"),
                                         ["MARK_UP"] * 40)
    assert p["personality"] == "Shock"


def test_tomorrow_is_a_watchlist_not_a_forecast():
    s = daily_summary.summarise(final_read=_fr(),
                                levels={"support": 23880,
                                        "resistance": 24050})
    assert s["tomorrow_watch"]
    for w in s["tomorrow_watch"]:
        assert w["means"] and w["level"]
    assert "watch-list, not a position" in s["outlook"]
    # never a directional call
    for word in ("will rise", "will fall", "buy tomorrow", "sell tomorrow"):
        assert word not in s["outlook"].lower()


def test_tomorrow_risks_name_their_engine():
    s = daily_summary.summarise(final_read=_fr(
        transition={"state": "REVERSING", "bias": "BEAR", "label": "🔄",
                    "reversal_probability": 68},
        stability="UNSTABLE"))
    assert any("Stage 47" in r for r in s["tomorrow_risks"])
    assert any("Stage 44" in r for r in s["tomorrow_risks"])


def test_daily_summary_on_a_day_with_no_trades():
    s = daily_summary.summarise(final_read=_fr())
    assert s["trades"] == 0
    assert "No graded trades today" in s["outlook"]
    assert s["tomorrow_risks"]              # never empty


def test_daily_summary_survives_empty_everything():
    s = daily_summary.summarise()
    assert s["trades"] == 0
    assert s["market_personality"] in daily_summary.PERSONALITIES


# ── the boundary, asserted rather than documented ───────────────────────
def test_no_explainability_module_is_registered_as_an_engine():
    from mios_v5.engines import ALL_ENGINES
    names = {str(getattr(e, "name", "")).lower() for e in ALL_ENGINES}
    names |= {e.__name__.lower() for e in ALL_ENGINES}
    for banned in ("checklist", "explain_decision", "risk_explain",
                   "narrator", "trade_review", "daily_summary"):
        assert not any(banned in n for n in names), banned


def test_explainability_exposes_no_mutators():
    for mod in (checklist, explain_decision, risk_explain, narrator,
                trade_review, daily_summary):
        for banned in ("decide", "apply", "set_confidence", "set_threshold",
                       "set_weight", "signal", "enter", "exit_trade"):
            assert not hasattr(mod, banned), f"{mod.__name__}.{banned}"


def test_every_output_declares_itself_advisory():
    assert checklist.build(_fr())["advisory_only"] is True
    assert explain_decision.explain(_fr())["advisory_only"] is True
    assert risk_explain.analyse(_fr())["advisory_only"] is True
    assert trade_review.review(_trade(), {"outcome": "win", "pnl_points": 5,
                                          "mfe": 6})["advisory_only"] is True
    assert daily_summary.summarise()["advisory_only"] is True


# ── panels ──────────────────────────────────────────────────────────────
def test_panels_render_and_stay_empty_when_blank():
    from mios_v5.ui import explain_panel as ep
    from mios_v5.ui import narrator_panel as np_
    from mios_v5.ui import review_panel as rp

    cl = checklist.build(_fr())
    e = explain_decision.explain(_fr(), cl)
    html = ep.decision_explanation_html(e)
    assert "BUY" in html and "Stage 42" in html
    assert "Stage 35" in ep.checklist_html(cl)
    assert "%" in ep.checklist_line(cl)
    assert "Invalidation" in ep.risk_html(risk_explain.analyse(_fr()))
    assert ep.decision_explanation_html(None) == ""
    assert ep.checklist_html(None) == ""

    beats = narrator.observe(None, _fr(), ts="09:20")["beats"]
    assert "09:20" in np_.narrator_html(beats)
    assert "never prescribes" in np_.narrator_html(beats)
    assert "transitions" in np_.narrator_html(None)

    rev = trade_review.review(_trade(), {"outcome": "win", "pnl_points": 30.0,
                                         "mfe": 78.0})
    assert "Trade review" in rp.review_html(rev)
    assert "Daily market summary" in rp.daily_summary_html(
        daily_summary.summarise(final_read=_fr()))


def test_panels_state_the_boundary_on_screen():
    from mios_v5.ui.explain_panel import boundary_html
    b = boundary_html()
    for phrase in ("generates no signal", "never influences the Decision "
                   "Engine", "quoted from an engine"):
        assert phrase in b


def test_wait_panel_shows_need_and_readiness():
    from mios_v5.ui.explain_panel import decision_explanation_html
    html = decision_explanation_html(explain_decision.explain(_waiting()))
    assert "Need" in html and "readiness" in html.lower()


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"explainability tests passed ({len(fns)})")
