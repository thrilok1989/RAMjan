"""MIOS V6 — Phase 6 tests (Stages 55-60).

The rules under test are as much governance as arithmetic: the Learning Engine
must never influence a live decision, never move a threshold on its own, never
move a weight on its own, and never hide a poor result. Those are asserted here
rather than only documented.
"""

from mios_v5 import (attribution, calibration, contribution, engine_accuracy,
                     false_signal, threshold_opt)


# ── Stage 55 · Trade Attribution ────────────────────────────────────────
def test_bias_sign_treats_neutral_as_abstention():
    assert attribution.bias_sign("STRONG_BULL") == 1
    assert attribution.bias_sign("BEAR") == -1
    for b in ("NEUTRAL", "NONE", None, "", "banana"):
        assert attribution.bias_sign(b) == 0


def test_engine_rows_mark_agreement_and_conflict():
    reads = {
        "stage42_acceptance": {"bias": "BULL", "confidence": 80, "status": "OK"},
        "stage45_htf_vpfr": {"bias": "BEAR", "confidence": 60, "status": "OK"},
        "stage44_flow_shift": {"bias": "NONE", "confidence": 0, "status": "OK"},
    }
    rows = {r["engine"]: r for r in attribution.engine_rows(reads, "CALL")}
    assert rows["stage42_acceptance"]["agreement"] is True
    assert rows["stage42_acceptance"]["conflict"] is False
    assert rows["stage45_htf_vpfr"]["conflict"] is True
    # a non-directional engine neither agrees nor conflicts
    assert rows["stage44_flow_shift"]["agreement"] is False
    assert rows["stage44_flow_shift"]["conflict"] is False


def test_engine_rows_keep_a_broken_engine():
    """'It was degraded that day' is itself an attributable cause of a loss."""
    reads = {"stage42_acceptance": {"bias": "NONE", "confidence": 0,
                                    "status": "DEGRADED"}}
    rows = attribution.engine_rows(reads, "CALL")
    assert len(rows) == 1 and rows[0]["status"] == "DEGRADED"


def test_reliability_is_not_faked_when_absent():
    reads = {"stage42_acceptance": {"bias": "BULL", "confidence": 80}}
    r = attribution.engine_rows(reads, "CALL")[0]
    assert r["reliability"] is None      # not defaulted to 50


def test_strength_is_direction_signed():
    reads = {"stage45_htf_vpfr": {"bias": "BEAR", "confidence": 70}}
    assert attribution.engine_rows(reads, "PUT")[0]["strength"] == -70.0


def test_excursion_tracks_mfe_mae_and_drawdown():
    st = None
    for spot in (100, 110, 140, 120, 95):
        st = attribution.track_excursion(st, "CALL", 100, spot)
    assert st["mfe"] == 40.0
    assert st["mae"] == -5.0
    assert st["max_drawdown"] == 45.0     # +40 peak down to -5
    assert st["samples"] == 5


def test_excursion_is_side_aware():
    st = attribution.track_excursion(None, "PUT", 100, 90)
    assert st["mfe"] == 10.0


def test_trade_quality_separates_bad_signal_from_bad_exit():
    assert attribution.trade_quality(-20, 2, -25) == "BAD"      # never worked
    assert attribution.trade_quality(-20, 40, -25) == "POOR"    # gave it back
    assert attribution.trade_quality(50, 55, -5) == "EXCELLENT"
    assert attribution.trade_quality(50, 200, -5) == "POOR"     # captured 25%


def test_exit_attribution_computes_the_outcome():
    a = {"signal_id": "SIG-1", "direction": "CALL", "entry_price": 100,
         "target": 140, "stop": 90}
    ex = {"mfe": 45.0, "mae": -6.0, "max_drawdown": 12.0}
    r = attribution.exit_attribution(a, 135, "TARGET_HIT", ex,
                                     entered_price=100, holding_secs=900)
    assert r["outcome"] == "win" and r["pnl_points"] == 35.0
    assert r["expected_move"] == 40.0 and r["actual_move"] == 35.0
    assert r["efficiency"] == round(35 / 45, 3)
    assert r["exit_reason"] == "TARGET_HIT"


def test_unknown_exit_reason_falls_back_rather_than_inventing():
    a = {"signal_id": "S", "direction": "CALL", "entry_price": 100}
    r = attribution.exit_attribution(a, 90, "because I felt like it", {})
    assert r["exit_reason"] == "MANUAL"
    assert r["outcome"] == "loss"


def test_join_drops_ungraded_trades_rather_than_counting_them_as_losses():
    rows = [{"signal_id": "A", "engine": "e"}, {"signal_id": "B", "engine": "e"}]
    results = [{"signal_id": "A", "outcome": "win", "pnl_points": 10},
               {"signal_id": "B", "outcome": "open"}]
    j = attribution.join_outcomes(rows, results)
    assert len(j) == 1 and j[0]["signal_id"] == "A" and j[0]["won"] is True


# ── Stage 56 · Engine Accuracy ──────────────────────────────────────────
def _rows(engine, spec):
    """spec: list of (agreement, conflict, won)."""
    return [{"engine": engine, "signal_id": f"S{i}", "agreement": a,
             "conflict": c, "won": w, "confidence": 80}
            for i, (a, c, w) in enumerate(spec)]


def test_confusion_matrix_maps_to_trading_terms():
    m = engine_accuracy.engine_metrics(_rows("e", [
        (True, False, True),    # TP — agreed, won
        (True, False, False),   # FP — agreed, lost
        (False, True, True),    # FN — opposed, won
        (False, True, False),   # TN — opposed, lost
    ]))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 50.0 and m["recall"] == 50.0
    assert m["accuracy"] == 50.0


def test_abstentions_are_excluded_from_the_matrix():
    """A permanently-neutral engine must not be able to post a good record."""
    m = engine_accuracy.engine_metrics(_rows("e", [(False, False, True)] * 10))
    assert m["voted"] == 0 and m["abstained"] == 10
    assert m["accuracy"] is None and m["precision"] is None
    assert m["voted_share"] == 0.0


def test_wilson_widens_on_small_samples():
    small = engine_accuracy.wilson(7, 10)
    big = engine_accuracy.wilson(70, 100)
    assert (small["high"] - small["low"]) > (big["high"] - big["low"])
    assert small["low"] < 50 < small["high"]


def test_small_samples_are_labelled_not_hidden():
    m = engine_accuracy.engine_metrics(_rows("e", [(True, False, True)] * 5))
    assert m["sample"] == 5
    assert m["significant"] is False
    assert m["win_rate"] == 100.0            # still reported
    assert "not enough" in engine_accuracy.verdict(m)


def test_verdict_calls_out_an_underperformer():
    spec = [(True, False, i % 4 == 0) for i in range(40)]   # 25% precision
    m = engine_accuracy.engine_metrics(_rows("e", spec))
    v = engine_accuracy.verdict(m)
    assert "Underperforming" in v and m["significant"] is True


def test_rank_puts_untested_engines_last_not_bottom_of_the_class():
    joined = _rows("good", [(True, False, True)] * 30) + \
             _rows("new", [(True, False, True)] * 3)
    rep = engine_accuracy.by_engine(joined)
    order = engine_accuracy.rank(rep, window="lifetime")
    assert order[0]["engine"] == "good" and order[0]["ranked"] is True
    assert order[-1]["engine"] == "new" and order[-1]["ranked"] is False


def test_windows_slice_newest_first():
    joined = _rows("e", [(True, False, False)] * 30 + [(True, False, True)] * 90)
    rep = engine_accuracy.by_engine(joined)["e"]
    assert rep["last30"]["win_rate"] == 0.0        # the newest 30 all lost
    assert rep["lifetime"]["sample"] == 120


# ── Stage 57 · Confidence Calibration ───────────────────────────────────
def _conf_rows(conf, n, wins):
    return [{"engine": "e", "agreement": True, "conflict": False,
             "confidence": conf, "won": i < wins} for i in range(n)]


def test_overconfidence_is_detected_and_suggestion_is_a_half_step():
    rows = _conf_rows(90, 100, 50)
    c = calibration.calibrate(rows)
    assert c["claimed_confidence"] == 90.0 and c["historical_accuracy"] == 50.0
    assert c["proven"] is True
    # blended, not replaced — one unlucky window must not rewrite the engine
    assert 65.0 < c["suggested_confidence"] < 90.0
    assert "Overconfident" in c["verdict"]


def test_underconfidence_is_reported_just_as_loudly():
    c = calibration.calibrate(_conf_rows(55, 100, 85))
    assert c["proven"] is True and c["gap"] > 0
    assert "Underconfident" in c["verdict"]
    assert c["suggested_confidence"] > 55


def test_small_sample_is_never_promotable():
    c = calibration.calibrate(_conf_rows(90, 12, 4))
    assert c["significant"] is False and c["promotable"] is False
    assert c["suggested_confidence"] == c["claimed_confidence"]


def test_calibrated_engine_gets_no_suggestion():
    c = calibration.calibrate(_conf_rows(70, 100, 70))
    assert c["proven"] is False and c["promotable"] is False
    assert "No change recommended" in c["verdict"]


def test_brier_beats_the_coin_flip_baseline_when_calibrated():
    good = calibration.brier(_conf_rows(90, 100, 90))
    bad = calibration.brier(_conf_rows(90, 100, 20))
    assert good < 0.25 < bad


def test_calibration_never_applies_anything():
    c = calibration.calibrate(_conf_rows(90, 100, 50))
    assert c["applied"] is False
    assert not hasattr(calibration, "apply")
    for s in calibration.suggestions({"e": {"last100": c}}):
        assert s["auto_applied"] is False
        assert "human" in s["action"].lower()


def test_neutral_reads_carry_no_claim_to_miscalibrate():
    rows = [{"engine": "e", "agreement": False, "conflict": False,
             "confidence": 95, "won": False} for _ in range(50)]
    c = calibration.calibrate(rows)
    assert c["sample"] == 0 and c["buckets"] == []


# ── Stage 58 · Threshold Optimisation ───────────────────────────────────
def _trades(n, field, split, pct_above, pct_below):
    """`split` trades at value 50, the rest at 80, with exact win percentages
    on each side so an uplift can be dialled to either side of the noise floor."""
    out, hi, lo = [], 0, 0
    for i in range(n):
        above = i >= split
        if above:
            won = (hi * 100) // max(1, n - split) < pct_above
            hi += 1
        else:
            won = (lo * 100) // max(1, split) < pct_below
            lo += 1
        out.append({"signal_id": f"S{i}", field: 80.0 if above else 50.0,
                    "outcome": "win" if won else "loss",
                    "won": won, "pnl_points": 20.0 if won else -10.0})
    return out


def test_sweep_finds_a_real_cut_point():
    trades = _trades(100, "confidence", 50, pct_above=90, pct_below=20)
    r = threshold_opt.sweep(trades, "confidence", current=40, direction="min")
    assert r["suggestion"] is not None
    s = r["suggestion"]
    assert 50.0 < s["to"] < 80.0
    assert s["expected_improvement"] >= threshold_opt.MIN_UPLIFT
    # the cost is reported as prominently as the benefit
    assert "winners_lost" in s and "losers_avoided" in s


def test_sweep_refuses_a_noise_level_improvement():
    trades = _trades(100, "confidence", 50, pct_above=54, pct_below=50)
    r = threshold_opt.sweep(trades, "confidence", current=40)
    assert r["suggestion"] is None
    assert "noise floor" in r["reason"]


def test_sweep_refuses_thin_samples_outright():
    trades = _trades(20, "confidence", 10, pct_above=90, pct_below=10)
    r = threshold_opt.sweep(trades, "confidence", current=40)
    assert r["suggestion"] is None
    assert "Not enough data" in r["reason"]


def test_sweep_handles_a_missing_field():
    r = threshold_opt.sweep([{"signal_id": "S", "outcome": "win"}], "nope")
    assert r["sample"] == 0 and r["suggestion"] is None


def test_optimise_never_deploys():
    trades = _trades(100, "confidence", 50, pct_above=90, pct_below=20)
    o = threshold_opt.optimise(trades)
    assert o["auto_deployed"] is False
    assert "human" in o["note"]
    for s in o["suggestions"]:
        assert s["auto_applied"] is False
    assert not hasattr(threshold_opt, "apply")
    assert not hasattr(threshold_opt, "deploy")


def test_every_tracked_threshold_names_its_owner():
    for spec in threshold_opt.TRACKED_THRESHOLDS:
        assert spec["owner"] and spec["label"] and spec["field"]


# ── Stage 59 · Engine Contribution ──────────────────────────────────────
def _vote_rows(sid, spec, won):
    return [{"signal_id": sid, "engine": e, "agreement": a, "conflict": c,
             "won": won, "confidence": 80, "weight": w}
            for e, a, c, w in spec]


def test_shapley_credits_a_unanimous_room_equally():
    rows = _vote_rows("S", [("a", True, False, 1.0), ("b", True, False, 1.0),
                            ("c", True, False, 1.0)], won=True)
    cs = {c["engine"]: c["credit"] for c in contribution.per_trade(rows)}
    assert abs(cs["a"] - cs["b"]) < 1e-6 and abs(cs["b"] - cs["c"]) < 1e-6
    assert all(v > 0 for v in cs.values())


def test_wrong_side_gets_negative_credit():
    rows = _vote_rows("S", [("a", True, False, 1.0), ("b", False, True, 1.0)],
                      won=False)
    cs = {c["engine"]: c["credit"] for c in contribution.per_trade(rows)}
    assert cs["a"] < 0 < cs["b"]        # 'a' agreed and it lost; 'b' warned


def test_abstaining_engines_get_no_record_at_all():
    rows = _vote_rows("S", [("a", True, False, 1.0),
                            ("quiet", False, False, 1.0)], won=True)
    engines = {c["engine"] for c in contribution.per_trade(rows)}
    assert "quiet" not in engines


def test_shapley_is_deterministic_across_runs():
    rows = _vote_rows("S", [(f"e{i}", i % 2 == 0, i % 2 == 1, 1.0)
                            for i in range(10)], won=True)
    a = [c["shapley"] for c in contribution.per_trade(rows)]
    b = [c["shapley"] for c in contribution.per_trade(rows)]
    assert a == b


def test_redundant_engine_earns_less_than_a_pivotal_one():
    """Four engines saying the same thing each matter less than the lone voice
    that decides a split room — this is why correlation is the wrong tool."""
    crowd = contribution.per_trade(
        _vote_rows("S", [(f"c{i}", True, False, 1.0) for i in range(5)],
                   won=True))
    solo = contribution.per_trade(
        _vote_rows("T", [("solo", True, False, 1.0)], won=True))
    assert solo[0]["shapley"] > crowd[0]["shapley"]


def test_by_engine_aggregates_and_flags_the_useless():
    joined = []
    for i in range(10):
        joined += _vote_rows(f"S{i}", [("hero", True, False, 3.0),
                                       ("dud", False, True, 0.1)], won=True)
    rep = contribution.by_engine(joined)
    assert rep["trades"] == 10
    assert rep["top"][0]["engine"] == "hero"
    assert rep["most_influential"][0]["engine"] == "hero"
    lines = contribution.explain(rep)
    assert any("hero" in l for l in lines)


def test_contribution_on_empty_history():
    assert contribution.by_engine(None)["trades"] == 0
    assert contribution.explain(None) == ["No graded trades yet — nothing to "
                                          "attribute."]


# ── Stage 60 · False Signal Analysis ────────────────────────────────────
def test_management_failure_outranks_bad_signal():
    """A trade that ran +30 then lost is not evidence against the entry."""
    c = false_signal.primary_cause({"direction": "CALL"},
                                   {"mfe": 30.0, "exit_reason": "STOP_LOSS"})
    assert c["cause"] == "MANAGEMENT_FAILURE"


def test_never_worked_is_a_bad_signal():
    c = false_signal.primary_cause({"direction": "CALL"},
                                   {"mfe": 1.0, "exit_reason": "STOP_LOSS"})
    assert c["cause"] == "BAD_SIGNAL"


def test_flow_shift_outranks_everything():
    c = false_signal.primary_cause(
        {"direction": "CALL"}, {"mfe": 40.0, "exit_reason": "STOP_LOSS"},
        events=[{"kind": "flow_shift"}])
    assert c["cause"] == "FLOW_SHIFT"


def test_exactly_one_primary_cause_is_assigned():
    c = false_signal.primary_cause(
        {"direction": "CALL", "acceptance": "BULL_TRAP",
         "htf_alignment": "BEAR", "snapshot": {"validity_score": 40,
                                               "state_duration_min": 2}},
        {"mfe": 2.0, "exit_reason": "STOP_LOSS"})
    assert c["cause"] == "TRAP"
    assert len(c["all_factors"]) > 1        # the rest are still recorded


def test_traded_against_the_higher_timeframe():
    c = false_signal.primary_cause(
        {"direction": "CALL", "htf_alignment": "4/6 BEAR"},
        {"mfe": 8.0, "exit_reason": "STOP_LOSS"})
    assert c["cause"] == "AGAINST_HTF"


def test_investigate_names_the_engine_that_was_outvoted():
    rows = [{"engine": "loud", "agreement": True, "confidence": 90},
            {"engine": "right", "conflict": True, "confidence": 75}]
    inv = false_signal.investigate(
        {"signal_id": "S1", "direction": "CALL"}, rows,
        {"pnl_points": -18.0, "mfe": 2.0, "exit_reason": "STOP_LOSS"})
    assert inv["outvoted"] == "right"
    assert inv["engines_wrong"][0]["engine"] == "loud"
    assert "outvoted" in inv["summary"]


def test_analyse_flags_a_management_problem_over_entry_filters():
    losses = [false_signal.investigate(
        {"signal_id": f"S{i}", "direction": "CALL"}, [],
        {"pnl_points": -10.0, "mfe": 30.0, "exit_reason": "STOP_LOSS"})
        for i in range(10)]
    a = false_signal.analyse(losses)
    assert a["losses"] == 10
    assert a["top_causes"][0]["name"] == "MANAGEMENT_FAILURE"
    assert "fix the exits" in a["summary"]


def test_recurring_needs_a_pattern_not_three_bad_days():
    losses = [false_signal.investigate({"signal_id": "S1", "direction": "CALL"},
                                       [], {"mfe": 1.0, "pnl_points": -5})]
    a = false_signal.analyse(losses)
    assert a["recurring"] == []


def test_analyse_on_no_losses():
    a = false_signal.analyse(None)
    assert a["losses"] == 0 and "No losses" in a["summary"]


# ── governance: the Learning Engine's binding limits ────────────────────
def test_no_learning_module_is_registered_as_an_engine():
    """It observes, measures, explains, recommends and validates. It does not
    vote, so it must never appear in the orchestrator's engine list."""
    from mios_v5.engines import ALL_ENGINES
    names = {str(getattr(e, "name", "")).lower() for e in ALL_ENGINES}
    names |= {e.__name__.lower() for e in ALL_ENGINES}
    # Stage 40 (prediction validation & learning) is a legitimate V5 engine and
    # is not one of these — the ban is on the Phase 6 modules specifically.
    for banned in ("attribution", "engine_accuracy", "calibration",
                   "threshold_opt", "contribution", "false_signal"):
        assert not any(banned in n for n in names), banned


def test_learning_modules_expose_no_mutators():
    for mod in (attribution, engine_accuracy, calibration, threshold_opt,
                contribution, false_signal):
        for banned in ("apply", "deploy", "promote", "set_threshold",
                       "set_weight", "update_engine"):
            assert not hasattr(mod, banned), f"{mod.__name__}.{banned}"


# ── the assembler + Dashboard 5 ─────────────────────────────────────────
def _phase6_fixture(n=40):
    """n graded trades: engine 'sharp' is right most of the time, 'blind' is
    wrong most of the time, 'mute' never takes a side."""
    eng, res, trades = [], [], []
    for i in range(n):
        sid, won = f"SIG-{i:03d}", i % 3 != 0          # ~67% win rate
        for name, agree in (("sharp", won), ("blind", not won)):
            eng.append({"signal_id": sid, "engine": name, "agreement": agree,
                        "conflict": not agree, "confidence": 85,
                        "weight": 2.0, "output": f"{name} read"})
        eng.append({"signal_id": sid, "engine": "mute", "agreement": False,
                    "conflict": False, "confidence": 0})
        res.append({"signal_id": sid, "trading_day": "2026-07-28",
                    "outcome": "win" if won else "loss",
                    "pnl_points": 22.0 if won else -11.0,
                    "mfe": 25.0 if won else 2.0, "mae": -6.0,
                    "holding_secs": 900, "exit_reason":
                        "TARGET_HIT" if won else "STOP_LOSS",
                    "trade_quality": "GOOD" if won else "BAD"})
        trades.append({"signal_id": sid, "trading_day": "2026-07-28",
                       "direction": "CALL", "confidence": 85 if won else 55,
                       "rr": 2.0, "htf_alignment": "4/6 BULL",
                       "snapshot": {"validity_score": 80 if won else 50,
                                    "evidence_families": 6 if won else 3}})
    return eng, res, trades


def test_report_builds_every_stage():
    from mios_v5 import learning_report
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [], window="lifetime")
    for k in ("overall", "accuracy", "rankings", "calibration",
              "calibration_suggestions", "thresholds", "contribution",
              "false_signals"):
        assert k in p, k
    assert p["advisory_only"] is True
    assert p["overall"]["graded"] == 40


def test_report_ranks_the_sharp_engine_above_the_blind_one():
    from mios_v5 import learning_report
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [], window="lifetime")
    order = [r["engine"] for r in p["rankings"] if r["ranked"]]
    assert order.index("sharp") < order.index("blind")


def test_report_flags_the_permanently_neutral_engine_as_useless():
    from mios_v5 import learning_report
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [], window="lifetime")
    acc = p["accuracy"]["mute"]["lifetime"]
    assert acc["voted"] == 0 and acc["precision"] is None
    assert "mute" not in {e["engine"] for e in p["contribution"]["engines"]}


def test_report_investigates_every_loss():
    from mios_v5 import learning_report
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [], window="lifetime")
    losses = sum(1 for r in res if r["outcome"] == "loss")
    fs = p["false_signals"]
    assert fs["losses"] == losses
    # a diagnosable cause outranks the catch-all: "the gate was weak" is
    # actionable, "the read was wrong" is not
    assert fs["top_causes"][0]["name"] == "WEAK_VALIDITY"
    assert fs["recurring"]                      # 14 occurrences is a pattern
    # and the most useful line in Phase 6: the engine that called it right
    assert fs["outvoted_leaders"][0]["name"] == "sharp"
    assert fs["worst_engines"][0]["engine"] == "blind"


def test_report_survives_completely_empty_input():
    from mios_v5 import learning_report
    p = learning_report.build(None, None, None, None)
    assert p["overall"]["graded"] == 0
    assert p["rankings"] == [] and p["thresholds"]["auto_deployed"] is False


def test_snapshot_rows_are_append_only_and_unapplied():
    from mios_v5 import learning_report
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [])
    rows = learning_report.snapshot_rows(p, trading_day="2026-07-28")
    assert {r["stage"] for r in rows} == {"accuracy", "calibration",
                                          "thresholds", "contribution",
                                          "false_signal"}
    assert all(r["applied"] is False for r in rows)
    assert all(r["trading_day"] == "2026-07-28" for r in rows)


def test_dashboard_5_renders_every_section():
    from mios_v5 import learning_report
    from mios_v5.ui import learning_panel as lp
    eng, res, trades = _phase6_fixture()
    p = learning_report.build(eng, res, trades, [], window="lifetime")
    assert "Overall accuracy" in lp.overall_html(p["overall"])
    acc = lp.accuracy_html(p["rankings"], "lifetime")
    assert "sharp" in acc and "n=" in acc          # sample size always shown
    assert "Confidence calibration" in lp.calibration_html(
        p["calibration_suggestions"], p["calibration"])
    assert "not deployed" in lp.thresholds_html(p["thresholds"]) or \
           "noise floor" in lp.thresholds_html(p["thresholds"])
    assert "Shapley" in lp.contribution_html(p["contribution"],
                                             p["contribution_lines"])
    assert "False-signal" in lp.false_signal_html(p["false_signals"],
                                                  p["recent_losses"])


def test_dashboard_5_states_the_boundary_on_screen():
    from mios_v5.ui import learning_panel as lp
    g = lp.governance_html()
    for phrase in ("never influences a live decision", "append-only",
                   "requires a human"):
        assert phrase in g


def test_dashboard_5_warns_below_the_significance_floor():
    from mios_v5.ui import learning_panel as lp
    html = lp.overall_html({"graded": 6, "win_rate": 83.3})
    assert "provisional" in html and "6 graded" in html


def test_dashboard_5_handles_empty_payload():
    from mios_v5.ui import learning_panel as lp
    for fn in (lp.overall_html, lp.accuracy_html, lp.calibration_html,
               lp.thresholds_html, lp.contribution_html, lp.false_signal_html):
        assert isinstance(fn(None), str)


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"phase 6 learning tests passed ({len(fns)})")
