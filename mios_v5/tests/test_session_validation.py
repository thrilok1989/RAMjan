"""MIOS V6 — Stage 70 Session Validation tests.

The load-bearing properties: it must **change nothing**, its counterfactual
must state its own limits, and it must refuse to recommend on thin evidence
rather than dressing noise up as a finding.
"""

from mios_v5 import session_validation as sv


def _log(day="2026-07-28"):
    """Three session rows: a WAIT-stanced opening, a WAIT midday, a NORMAL
    afternoon."""
    return [
        {"trading_day": day, "ts": f"{day}T09:30:00+05:30",
         "session": "OPENING_DRIVE", "behaviour": "TRENDING",
         "measures": {"volatility": 80, "dealer": 60, "institutional": 70},
         "modifiers": {"stage52_decision": {"stance": "WAIT"}}},
        {"trading_day": day, "ts": f"{day}T12:00:00+05:30",
         "session": "MIDDAY_BALANCE", "behaviour": "SIDEWAYS",
         "measures": {"volatility": 20, "dealer": 30, "institutional": 20},
         "modifiers": {"stage52_decision": {"stance": "WAIT"}}},
        {"trading_day": day, "ts": f"{day}T14:00:00+05:30",
         "session": "AFTERNOON_TREND", "behaviour": "TRENDING",
         "measures": {"volatility": 55, "dealer": 65, "institutional": 75},
         "modifiers": {"stage52_decision": {"stance": "NORMAL"}}},
    ]


def _res(sid, hhmm, outcome, pnl=20.0, day="2026-07-28", **kw):
    r = {"signal_id": sid, "trading_day": day,
         "exit_at": f"{day}T{hhmm}:00+05:30", "outcome": outcome,
         "pnl_points": pnl if outcome == "win" else -abs(pnl),
         "mfe": 26.0 if outcome == "win" else 3.0, "mae": -8.0,
         "holding_secs": 900}
    r.update(kw)
    return r


def _trade(sid, **kw):
    t = {"signal_id": sid, "trading_day": "2026-07-28", "direction": "CALL",
         "rr": 2.0, "confidence": 72, "market_quality": "GOOD",
         "market_state": "📈 Mark Up"}
    t.update(kw)
    return t


# ── the composite key ───────────────────────────────────────────────────
def test_the_key_is_a_window_times_a_condition():
    """Neither engine is asked to decide anything new — the window is Stage
    69's, the condition is read from Stage 68 / the gap flag."""
    k = sv.session_key({"session": "OPENING_DRIVE", "behaviour": "TRENDING"},
                       {"day_classification": "🧲 Expiry Pin Day"})
    assert k["key"] == "OPENING_DRIVE|EXPIRY"
    assert "Opening Drive" in k["label"] and "Expiry" in k["label"]


def test_conditions_have_a_precedence_order():
    """An expiry gap-up day files under EXPIRY, not both."""
    k = sv.session_key({"session": "MORNING_TREND"},
                       {"day_classification": "🧲 Expiry Pin Day",
                        "gap": "GAP-UP"})
    assert k["condition"] == "EXPIRY"
    k2 = sv.session_key({"session": "MORNING_TREND"},
                        {"day_classification": "💥 News Event Day"})
    assert k2["condition"] == "EVENT"


def test_a_plain_day_is_normal():
    k = sv.session_key({"session": "MIDDAY_BALANCE"}, {})
    assert k["condition"] == "NORMAL"
    assert k["label"].endswith("Balance") or "Balance" in k["label"]


def test_the_behaviour_appears_in_the_label():
    k = sv.session_key({"session": "MORNING_TREND",
                        "behaviour": "TREND_EXHAUSTION"}, {})
    assert "Reversal" in k["label"]


def test_holiday_is_not_a_bucket():
    """The market is closed, no signals exist, and an always-empty bucket is
    clutter."""
    assert "HOLIDAY" not in sv.CONDITIONS


# ── PART 1 · performance ────────────────────────────────────────────────
def test_a_trade_is_attributed_to_the_session_it_was_taken_in():
    perf = sv.performance(
        _log(),
        [_res("A", "09:40", "loss"), _res("B", "14:30", "win")],
        [_trade("A"), _trade("B")])
    by = {p["window"]: p for p in perf}
    assert by["OPENING_DRIVE"]["losses"] == 1
    assert by["AFTERNOON_TREND"]["wins"] == 1


def test_performance_reports_every_requested_metric():
    perf = sv.performance(_log(), [_res("A", "14:30", "win")], [_trade("A")])
    row = perf[0]
    for k in ("signals", "valid", "win_rate", "loss_rate", "avg_rr",
              "avg_holding_min", "avg_mfe", "avg_mae", "avg_confidence",
              "avg_market_quality", "avg_market_state"):
        assert k in row, k
    assert row["avg_rr"] == 2.0
    assert row["avg_confidence"] == 72.0
    assert row["avg_market_quality"] == "GOOD"


def test_thin_buckets_are_marked_not_dropped():
    perf = sv.performance(_log(), [_res("A", "14:30", "win")], [_trade("A")])
    assert perf[0]["thin"] is True and perf[0]["valid"] == 1
    assert perf[0]["interval"]


def test_ungraded_trades_count_as_signals_but_not_as_valid():
    perf = sv.performance(_log(), [_res("A", "14:30", "open")], [_trade("A")])
    assert perf[0]["signals"] == 1 and perf[0]["valid"] == 0
    assert perf[0]["win_rate"] is None


def test_performance_is_ordered_chronologically():
    """Reading the session in order is what makes a bad hour visible; sorting
    by win rate hides the shape of the day."""
    perf = sv.performance(
        _log(),
        [_res("A", "09:40", "loss"), _res("B", "12:30", "loss"),
         _res("C", "14:30", "win")],
        [_trade("A"), _trade("B"), _trade("C")])
    assert [p["window"] for p in perf] == [
        "OPENING_DRIVE", "MIDDAY_BALANCE", "AFTERNOON_TREND"]


def test_performance_on_nothing():
    assert sv.performance(None, None, None) == []


# ── PART 2 · the counterfactual ─────────────────────────────────────────
def _mixed(n_bad=12, n_good=12):
    """Losers in the WAIT-stanced sessions, winners in the NORMAL one."""
    res, tr = [], []
    for i in range(n_bad):
        res.append(_res(f"L{i}", "09:40", "loss", 12.0))
        tr.append(_trade(f"L{i}"))
    for i in range(n_good):
        res.append(_res(f"W{i}", "14:30", "win", 24.0))
        tr.append(_trade(f"W{i}"))
    return res, tr


def test_the_counterfactual_removes_trades_the_modifiers_would_have_blocked():
    res, tr = _mixed()
    c = sv.counterfactual(_log(), res, tr)
    assert c["without"]["n"] == 24 and c["without"]["win_rate"] == 50.0
    # the WAIT-stanced opening losers are removed
    assert c["with"]["n"] == 12 and c["with"]["win_rate"] == 100.0
    assert c["blocked"] == 12
    assert c["false_signal_reduction"] == 12
    assert c["winners_lost"] == 0
    assert c["improvement_pct"] == 50.0


def test_a_high_confidence_gate_removes_only_low_confidence_trades():
    log = _log()
    log[2]["modifiers"] = {"stage52_decision": {"stance": "HIGH_CONFIDENCE_ONLY"}}
    res = [_res("A", "14:30", "win"), _res("B", "14:35", "loss")]
    tr = [_trade("A", confidence=90), _trade("B", confidence=60)]
    c = sv.counterfactual(log, res, tr)
    assert c["gated"] == 1 and c["with"]["n"] == 1
    assert c["with"]["wins"] == 1


def test_the_counterfactual_states_that_it_can_only_remove_trades():
    """A modifier that would have PERMITTED a declined entry leaves no
    outcome, so opportunity missed is unmeasured."""
    c = sv.counterfactual(_log(), *_mixed())
    assert any("Removal-only" in x for x in c["caveats"])
    assert any("opportunity missed" in x for x in c["caveats"])


def test_the_counterfactual_admits_it_is_in_sample():
    c = sv.counterfactual(_log(), *_mixed())
    assert c["in_sample"] is True
    assert any("In-sample" in x for x in c["caveats"])


def test_thin_history_is_not_promotable():
    res, tr = _mixed(3, 3)
    c = sv.counterfactual(_log(), res, tr)
    assert c["significant"] is False and c["promotable"] is False
    assert "needed before the comparison means anything" in c["verdict"]


def test_a_noise_level_improvement_is_not_promotable():
    res, tr = [], []
    for i in range(25):
        res.append(_res(f"A{i}", "09:40", "win" if i % 2 else "loss"))
        tr.append(_trade(f"A{i}"))
    for i in range(25):
        res.append(_res(f"B{i}", "14:30", "win" if i % 2 else "loss"))
        tr.append(_trade(f"B{i}"))
    c = sv.counterfactual(_log(), res, tr)
    assert c["significant"] is True
    assert c["promotable"] is False
    assert "noise floor" in c["verdict"]


def test_the_cost_in_winners_is_reported_as_prominently_as_the_benefit():
    res, tr = [], []
    for i in range(30):
        res.append(_res(f"L{i}", "09:40", "loss" if i < 24 else "win"))
        tr.append(_trade(f"L{i}"))
    for i in range(20):
        res.append(_res(f"W{i}", "14:30", "win"))
        tr.append(_trade(f"W{i}"))
    c = sv.counterfactual(_log(), res, tr)
    assert c["winners_lost"] == 6
    assert "cost" in c["verdict"] and "winner" in c["verdict"]


def test_the_counterfactual_on_nothing():
    c = sv.counterfactual(None, None, None)
    assert c["sample"] == 0 and "nothing to validate" in c["verdict"]


# ── PART 3 · profiles ───────────────────────────────────────────────────
def test_a_thin_profile_falls_back_to_the_a_priori_table_and_says_so():
    """A profile built from six trades presented in the same voice as one
    built from two hundred is how a system talks itself into a bad habit."""
    perf = sv.performance(_log(), [_res("A", "14:30", "win")], [_trade("A")])
    p = sv.profile(perf[0], _log())
    assert p["source"] == "a-priori"
    assert "a-priori profile" in p["note"]
    assert p["best_strategy"]


def test_a_measured_profile_is_labelled_measured():
    res, tr = [], []
    for i in range(16):
        res.append(_res(f"W{i}", "14:30", "win" if i < 12 else "loss"))
        tr.append(_trade(f"W{i}"))
    perf = sv.performance(_log(), res, tr)
    p = sv.profile(perf[0], _log())
    assert p["source"] == "measured"
    assert p["historical_win_rate"] == 75.0
    assert p["best_strategy"] and p["avoid"]


def test_a_losing_session_is_told_to_stand_aside():
    res, tr = [], []
    for i in range(16):
        res.append(_res(f"L{i}", "12:30", "loss" if i < 13 else "win"))
        tr.append(_trade(f"L{i}"))
    perf = sv.performance(_log(), res, tr)
    p = sv.profile(perf[0], _log())
    assert p["best_strategy"] == "Stand aside"


def test_false_breakouts_are_labelled_as_a_proxy():
    """MIOS does not tag a loss as a false breakout — this must not pretend
    otherwise."""
    import inspect
    src = inspect.getsource(sv._false_breakout_rate)
    assert "proxy" in src.lower()
    assert sv._false_breakout_rate({"loss_rate": 60, "valid": 3}) is None


# ── PART 4 · recommendations ────────────────────────────────────────────
def test_a_thin_session_refuses_to_recommend():
    perf = sv.performance(_log(), [_res("A", "14:30", "win")], [_trade("A")])
    rec = sv.recommendations(perf, sv.profiles(perf, _log()))[0]
    assert rec["significant"] is False
    assert "Not enough graded trades" in rec["do"][0]
    assert "handful" in rec["avoid"][0]


def test_a_strong_session_is_recommended_with_its_sample():
    res, tr = [], []
    for i in range(20):
        res.append(_res(f"W{i}", "14:30", "win" if i < 14 else "loss"))
        tr.append(_trade(f"W{i}"))
    perf = sv.performance(_log(), res, tr)
    rec = sv.recommendations(perf, sv.profiles(perf, _log()))[0]
    assert rec["significant"] is True
    assert "70.0%" in rec["do"][0] or "70%" in rec["do"][0]
    assert rec["interval"]
    assert rec["auto_applied"] is False
    assert "human" in rec["action"].lower()


def test_a_weak_session_is_told_not_to_trade():
    res, tr = [], []
    for i in range(20):
        res.append(_res(f"L{i}", "12:30", "loss" if i < 14 else "win"))
        tr.append(_trade(f"L{i}"))
    perf = sv.performance(_log(), res, tr)
    rec = sv.recommendations(perf, sv.profiles(perf, _log()))[0]
    assert any("Trading this session" in x for x in rec["avoid"])
    assert any("Stand aside" in x for x in rec["do"])


def test_a_thin_reward_risk_is_called_out():
    res, tr = [], []
    for i in range(20):
        res.append(_res(f"W{i}", "14:30", "win" if i < 12 else "loss"))
        tr.append(_trade(f"W{i}", rr=1.1))
    perf = sv.performance(_log(), res, tr)
    rec = sv.recommendations(perf, sv.profiles(perf, _log()))[0]
    assert any("R:R" in x for x in rec["avoid"])


# ── PART 6 · did the recommendation hold? ───────────────────────────────
def test_a_recommendation_is_scored_against_what_followed():
    """Comparing a recommendation to what the session did AFTERWARDS is the
    only way to tell a real edge from a run of luck that has since reverted."""
    stored = [{"key": "AFTERNOON_TREND|NORMAL", "window": "AFTERNOON_TREND",
               "label": "Afternoon Trend", "win_rate": 70.0,
               "created_at": "2026-07-28T15:00:00+05:30"}]
    after = [_res(f"X{i}", "14:30", "loss", day="2026-07-29")
             for i in range(12)]
    s = sv.score_recommendations(stored, after, _log("2026-07-29"))
    row = s["rows"][0]
    assert row["claimed_win_rate"] == 70.0
    assert row["since_win_rate"] == 0.0
    assert row["held"] is False
    assert s["tested"] == 1 and s["held"] == 0


def test_a_recommendation_that_held_is_reported_as_holding():
    stored = [{"key": "AFTERNOON_TREND|NORMAL", "window": "AFTERNOON_TREND",
               "label": "Afternoon Trend", "win_rate": 70.0,
               "created_at": "2026-07-28T15:00:00+05:30"}]
    after = [_res(f"X{i}", "14:30", "win" if i < 9 else "loss",
                  day="2026-07-29") for i in range(12)]
    s = sv.score_recommendations(stored, after, _log("2026-07-29"))
    assert s["rows"][0]["held"] is True and s["held"] == 1


def test_scoring_ignores_trades_from_before_the_recommendation():
    stored = [{"key": "AFTERNOON_TREND|NORMAL", "window": "AFTERNOON_TREND",
               "win_rate": 70.0, "label": "x",
               "created_at": "2026-07-29T00:00:00+05:30"}]
    before = [_res("A", "14:30", "win")]      # 2026-07-28, earlier
    s = sv.score_recommendations(stored, before, _log())
    assert s["rows"][0]["trades_since"] == 0


def test_scoring_on_nothing():
    s = sv.score_recommendations(None, None, None)
    assert s["scored"] == 0 and "No stored recommendations" in s["summary"]


# ── the whole report ────────────────────────────────────────────────────
def test_build_assembles_every_part():
    res, tr = _mixed()
    r = sv.build(_log(), res, tr, [])
    for k in ("performance", "profiles", "counterfactual", "recommendations",
              "recommendation_scoring"):
        assert k in r, k
    assert r["advisory_only"] is True and r["applied"] is False


def test_snapshot_rows_store_the_rate_the_recommendation_was_made_on():
    """A recommendation stored without the number it was made on cannot be
    scored later."""
    res, tr = [], []
    for i in range(20):
        res.append(_res(f"W{i}", "14:30", "win" if i < 14 else "loss"))
        tr.append(_trade(f"W{i}"))
    rows = sv.snapshot_rows(sv.build(_log(), res, tr), trading_day="2026-07-28")
    assert rows
    assert rows[0]["win_rate"] == 70.0 and rows[0]["sample"] == 20
    assert rows[0]["applied"] is False
    assert rows[0]["trading_day"] == "2026-07-28"


def test_snapshot_rows_skip_insignificant_recommendations():
    rows = sv.snapshot_rows(
        sv.build(_log(), [_res("A", "14:30", "win")], [_trade("A")]))
    assert rows == []


def test_build_on_nothing():
    r = sv.build()
    assert r["performance"] == [] and r["counterfactual"]["sample"] == 0


# ── the Postgres round trip ─────────────────────────────────────────────
def test_stored_rows_avoid_the_reserved_word():
    """`window` is reserved in Postgres — `window TEXT` will not even parse,
    so the column is `session_window` and the row must match it."""
    res, tr = [], []
    for i in range(20):
        res.append(_res(f"W{i}", "14:30", "win" if i < 14 else "loss"))
        tr.append(_trade(f"W{i}"))
    rows = sv.snapshot_rows(sv.build(_log(), res, tr))
    assert rows
    assert "window" not in rows[0]
    assert rows[0]["session_window"] == "AFTERNOON_TREND"


def test_scoring_matches_rows_that_came_back_from_the_database():
    """Rows read back carry `session_window`, not `window`. Reading only
    `window` would silently match nothing and score every recommendation as
    having zero subsequent trades — a false all-clear, not a visible break."""
    stored = [{"key": "AFTERNOON_TREND|NORMAL",
               "session_window": "AFTERNOON_TREND",
               "label": "Afternoon Trend", "win_rate": 70.0,
               "created_at": "2026-07-28T15:00:00+05:30"}]
    after = [_res(f"X{i}", "14:30", "win" if i < 9 else "loss",
                  day="2026-07-29") for i in range(12)]
    s = sv.score_recommendations(stored, after, _log("2026-07-29"))
    row = s["rows"][0]
    assert row["trades_since"] == 12
    assert row["window"] == "AFTERNOON_TREND"
    assert row["held"] is True


def test_no_migration_uses_a_reserved_word_as_a_bare_column():
    """One reserved word cost a migration that would not run at all. Catch the
    next one here rather than in the Supabase SQL editor."""
    import os
    import re

    # PostgreSQL reserved words that are plausible column names.
    reserved = {"window", "order", "group", "user", "check", "table", "column",
                "limit", "offset", "default", "all", "any", "array", "as",
                "asc", "both", "case", "cast", "collate", "constraint",
                "create", "current_date", "current_time", "current_user",
                "desc", "distinct", "do", "else", "end", "except", "false",
                "for", "foreign", "from", "grant", "having", "in", "initially",
                "intersect", "into", "leading", "only", "or", "and", "not",
                "null", "placing", "primary", "references", "returning",
                "select", "session_user", "some", "symmetric", "then", "to",
                "trailing", "true", "union", "unique", "using", "variadic",
                "when", "where", "with"}
    types = (r"TEXT|INTEGER|BIGINT|SMALLINT|BOOLEAN|JSONB|JSON|DOUBLE|REAL|"
             r"NUMERIC|TIMESTAMPTZ|TIMESTAMP|DATE|BIGSERIAL|SERIAL|UUID")
    col = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(?:" + types + r")\b")

    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "sql")
    bad = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".sql"):
            continue
        with open(os.path.join(root, fn), encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                m = col.match(line.split("--")[0])
                if m and m.group(1).lower() in reserved:
                    bad.append(f"{fn}:{i} {m.group(1)}")
    assert not bad, "reserved word as a bare column name: " + "; ".join(bad)


# ── the boundary ────────────────────────────────────────────────────────
def test_stage_70_is_not_an_engine():
    from mios_v5.engines import ALL_ENGINES
    names = {str(getattr(e, "name", "")).lower() for e in ALL_ENGINES}
    names |= {e.__name__.lower() for e in ALL_ENGINES}
    assert not any("session_validation" in n for n in names)
    assert not any("stage70" in n for n in names)


def test_stage_70_exposes_no_mutators():
    for banned in ("apply", "deploy", "promote", "set_threshold", "set_weight",
                   "set_confidence", "decide", "enable"):
        assert not hasattr(sv, banned), banned


def test_stage_70_cannot_flip_the_session_switch():
    """It validates whether the modifiers should be applied. It must not be
    able to apply them."""
    import ast
    import inspect

    # AST, not text — the docstring legitimately NAMES the switch when
    # explaining what Stage 70 validates. What must not exist is a WRITE.
    tree = ast.parse(inspect.getsource(sv))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            name = (t.id if isinstance(t, ast.Name) else
                    t.attr if isinstance(t, ast.Attribute) else "")
            assert name != "SESSION_AWARE", ast.dump(node)
    # and it must not import the switch into its own namespace
    assert not hasattr(sv, "SESSION_AWARE")


# ── panels ──────────────────────────────────────────────────────────────
def test_panels_render_and_stay_quiet_when_empty():
    from mios_v5.ui import session_validation_panel as vp
    res, tr = _mixed()
    r = sv.build(_log(), res, tr, [])

    perf = vp.performance_html(r["performance"])
    assert "Session performance" in perf
    assert "not trusted" in perf          # the footnote is always present
    # a genuinely thin bucket carries the badge
    thin = vp.performance_html(
        sv.performance(_log(), [_res("A", "14:30", "win")], [_trade("A")]))
    assert "thin" in thin

    cf = vp.counterfactual_html(r["counterfactual"])
    assert "Without Stage 69" in cf and "With Stage 69" in cf
    assert "Winners removed" in cf
    assert "Removal-only" in cf and "In-sample" in cf

    assert "Session profiles" in vp.profiles_html(r["profiles"])
    assert "not applied" in vp.recommendations_html(r["recommendations"])
    assert "Did the recommendations hold" in vp.scoring_html(
        r["recommendation_scoring"])

    assert "sql/029" in vp.performance_html(None)
    assert vp.profiles_html(None) == ""
    assert vp.recommendations_html(None) == ""


def test_the_panel_states_the_boundary_on_screen():
    from mios_v5.ui.session_validation_panel import boundary_html
    b = boundary_html()
    for phrase in ("logs and validates", "cannot change the Decision Engine",
                   "human flipping"):
        assert phrase in b


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"session validation tests passed ({len(fns)})")
