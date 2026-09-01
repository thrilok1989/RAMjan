"""Stage 72 — the Entry Engine.

The first execution stage. These tests guard the boundary far more than the
arithmetic, because the boundary is the whole value of the bridge:

1. **It consumes `TradingContext` only** — no producer, no engine, no network.
2. **It invents no state** — `decision_v2.STATES` is imported and enforced.
3. **It fabricates no level** — `target2`/`target3` stay UNKNOWN by name.
4. **It sends nothing** — the Telegram payload is prepared and marked unsent.
5. **Every reason traces to a context field**, by owner and by dotted path.
"""

import ast
import json
import pathlib

import pytest

from mios_v5 import entry_engine as EE
from mios_v5 import trading_context as TC
from mios_v5.decision_v2 import STATES


# ── fixtures ────────────────────────────────────────────────────────────

def _fr(**over):
    fr = {
        "market_state": {"state": "TREND"}, "regime": "TRENDING",
        "day_classification": {"day_type": "TREND"},
        "session_intel": {"window": "Morning Trend"},
        "preferred_bias": "BULLISH",
        "transition": {"state": "STRENGTHENING"},
        "stability": "STABLE",
        "reaction": {"state": "BREAK"}, "reaction_level": 118.0,
        "session_conviction": 0.8,
        "htf_alignment": {"bias": "BULL", "score": 78},
        "htf": {"structure": "higher highs"},
        "value_migration": {"direction": "up"},
        "breakout_risk": "MODERATE",
        "validity": {"verdict": "VALID"},
        "flow_shift": {"freeze_entries": False, "detected": False},
        "next_target": 138.0, "invalidation": "a close below 112",
    }
    fr.update(over)
    return fr


def _matrix(**over):
    intel = {"type": "Breakout", "timing": {"timing": "NOW"},
             "quality": {"grade": "A"}, "risk": {"level": "MEDIUM"},
             "lifetime": {"label": "today (shorter)"}}
    intel.update(over.pop("intel", {}))
    best = {"horizon": "intraday", "side": "CALL", "score": 61.5,
            "confidence": 72, "reasons": ["families agree"], "intel": intel}
    best.update(over.pop("best_trade", {}))
    return {"best": "intraday", "best_trade": best}


def _premium(**over):
    p = {"dominance": "CALL Dominant",
         "preferred": {"preferred": "Prefer CALL", "side": "CALL"},
         "bridge": {"energy_score": {"CALL": 78, "PUT": 22},
                    "spike_probability": {"CALL": 71, "PUT": 30},
                    "energy_shift": {"CALL": "Increasing", "PUT": "Decreasing"},
                    "energy_acceleration": {"CALL": 12, "PUT": -9},
                    "rotation": "Stable"}}
    p.update(over)
    return p


def _validation(validation="VALID", liquidity="Agree", agreement="Agree"):
    return {"selected": {"CALL": 24250.0, "PUT": 24250.0},
            "bridge": {"selected_strike": {"CALL": 24250.0, "PUT": 24250.0},
                       "premium_validation": {"CALL": validation,
                                              "PUT": "INVALID"},
                       "premium_liquidity": {"CALL": liquidity, "PUT": "Agree"},
                       "most_traded_agreement": {"CALL": agreement,
                                                 "PUT": "Agree"}}}


def _structure():
    return {"CALL": {"structure_score": 70, "confidence": "HIGH",
                     "support": 112.0, "resistance": 130.0, "ltp": 118.0},
            "PUT": {"structure_score": 34, "confidence": "HIGH",
                    "support": 88.0, "resistance": 95.0, "ltp": 90.0}}


def _behaviour(**over):
    """Stage 71.85's shape. Written out rather than produced by calling the
    stage, so a change in 71.85's *logic* cannot silently change what Stage 72
    is tested against — the bridge is what these tests guard."""
    b = {"CALL": {"behaviour": "Support Building", "strength": "★★★★☆",
                  "confidence": "A", "momentum": "Building",
                  "acceptance": "Inside Value",
                  "top_reasons": ({"label": "Buyer Absorption"},)},
         "PUT": {"behaviour": "Neutral", "strength": TC.UNKNOWN,
                 "confidence": TC.UNKNOWN, "momentum": TC.UNKNOWN,
                 "acceptance": TC.UNKNOWN, "top_reasons": ()}}
    b.update(over)
    return b


def _ctx(**over):
    kw = dict(fr=_fr(), matrix=_matrix(), premium=_premium(),
              validation=_validation(), structure=_structure(),
              behaviour=_behaviour(), cycle=7)
    kw.update(over)
    return TC.build(**kw)


def _run(**over):
    return EE.EntryEngine(_ctx(**over)).run()


# ══════════════════════════════════════════════════════════════════════
#  1 · it consumes TradingContext only
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_nothing_but_the_context_and_the_state_machine():
    """The success criterion. Stage 72 must not reach past the bridge."""
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    # a relative import carries the dot in `level`, not in `module`
    local = {node.module for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.level}
    assert local == {"decision_v2", "trading_context"}, local


def test_it_imports_no_producer_and_no_network():
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"numpy", "pandas", "indicators", "streamlit", "requests",
              "httpx", "urllib", "socket", "supabase", "plotly", "telegram"}
    assert not (imported & banned), imported & banned


def test_it_never_touches_session_state():
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "session_state"


def test_it_reads_no_engine_directly():
    """Named individually, because these are the exact reaches the bridge
    exists to prevent.

    Checked on the call graph and the import graph, never on the text: the
    context's own field names contain `opportunity` and `premium`, and a grep
    cannot tell `ctx.value("opportunity.confidence")` — which is the bridge
    working — from an import of the Opportunity Matrix, which is the bridge
    being bypassed."""
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    for banned in ("final_read", "opportunity", "opportunity_intel",
                   "premium_energy", "strike_validation", "premium_structure",
                   "runner", "engines"):
        assert banned not in imported, banned
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for banned in ("build_matrix", "enrich", "analyse", "run_mios_pass"):
        assert banned not in called, banned


def test_it_runs_from_a_context_alone():
    decision = EE.EntryEngine(_ctx()).run()
    assert isinstance(decision, EE.EntryDecision)
    assert EE.run(_ctx()).state == decision.state


def test_every_weighted_input_is_a_real_context_field():
    """A weight pointing at a field that does not exist is a silent zero."""
    ctx = _ctx()
    for name in EE.WEIGHTS:
        grp, _, fld = name.partition(".")
        assert fld in ctx.group(grp), f"{name} is not a context field"


def test_no_weight_reads_the_same_field_twice():
    assert len(EE.WEIGHTS) == len(set(EE.WEIGHTS))


# ══════════════════════════════════════════════════════════════════════
#  2 · the state machine is Stage 52's
# ══════════════════════════════════════════════════════════════════════

def test_the_state_is_always_a_stage_52_state():
    for over in ({}, {"fr": _fr(stability="SHOCK")},
                 {"fr": _fr(flow_shift={"freeze_entries": True})},
                 {"validation": _validation(validation="INVALID")},
                 {"matrix": {}}, {"premium": {}}, {"structure": {}}):
        assert _run(**over).state in STATES


def test_inventing_a_state_raises_rather_than_leaking():
    """The import is enforcement, not decoration."""
    with pytest.raises(ValueError, match="not a Stage 52 state"):
        EE.EntryEngine._checked("WATCH", "spec vocabulary")
    with pytest.raises(ValueError):
        EE.EntryEngine._checked("FULL_EXIT", "spec vocabulary")


def test_the_specs_missing_states_are_aliased_not_invented():
    """`WATCH`, `PARTIAL_EXIT` and `FULL_EXIT` are not Stage 52 states. The
    alias map means a reader finds the real one rather than nothing."""
    assert set(EE.SPEC_ALIAS) == {"WATCH", "PARTIAL_EXIT", "FULL_EXIT"}
    for spec_name, real in EE.SPEC_ALIAS.items():
        assert spec_name not in STATES
        assert real in STATES


def test_a_frozen_tape_aborts_before_anything_is_scored():
    """ABORT is checked first and unconditionally, exactly as Stage 52 does."""
    d = _run(fr=_fr(flow_shift={"freeze_entries": True, "detected": True}))
    assert d.state == "ABORT"
    assert d.readiness == EE.NOT_READY
    assert any("froze" in w for w in d.warnings)


def test_a_shocked_tape_aborts():
    assert _run(fr=_fr(stability="SHOCK")).state == "ABORT"


def test_an_invalid_strike_waits_rather_than_entering():
    d = _run(validation=_validation(validation="INVALID"))
    assert d.state == "WAIT"
    assert d.readiness == EE.NOT_READY
    assert any("validate" in w for w in d.warnings)


def test_an_illiquid_strike_is_not_ready():
    d = _run(validation=_validation(liquidity="Disagree"))
    assert d.readiness == EE.NOT_READY
    assert any("illiquid" in w for w in d.warnings)


def test_a_strong_setup_in_the_window_enters():
    d = _run()
    assert d.state in ("ENTER", "ENTRY_READY")
    assert d.readiness == EE.READY
    assert d.score >= 60


def test_a_missed_move_waits_however_good_the_score():
    d = _run(matrix=_matrix(intel={"timing": {"timing": "MISSED"}}))
    assert d.entry_zone == EE.MISSED
    assert d.state == "WAIT"


def test_only_pre_entry_states_are_emitted():
    """The rest describe an open position, which this stage cannot see."""
    seen = set()
    for over in ({}, {"fr": _fr(stability="SHOCK")}, {"matrix": {}},
                 {"validation": _validation(validation="INVALID")},
                 {"matrix": _matrix(intel={"timing": {"timing": "MISSED"}})}):
        seen.add(_run(**over).state)
    assert seen <= {"WAIT", "ENTRY_READY", "ENTER", "ABORT"}


# ══════════════════════════════════════════════════════════════════════
#  3 · UNKNOWN propagates, and nothing is fabricated
# ══════════════════════════════════════════════════════════════════════

def test_an_empty_context_yields_unknowns_not_zeros():
    d = EE.EntryEngine(TC.build()).run()
    assert d.state == "WAIT"
    assert d.score == TC.UNKNOWN
    assert d.risk == TC.UNKNOWN and d.reward == TC.UNKNOWN
    assert d.entry_type == TC.UNKNOWN and d.entry_zone == TC.UNKNOWN
    for v in (d.score, d.risk, d.reward, d.entry, d.stop, d.risk_reward):
        assert v != 0 and v is not None


def test_no_engine_at_all_still_returns_a_decision():
    d = EE.EntryEngine(None).run()
    assert d.state in STATES
    assert d.advisory_only is True


def test_target2_and_target3_are_unknown_by_name():
    """Stage 35 publishes one target. A ladder would be inventing levels."""
    d = _run()
    assert d.targets["target2"] == TC.UNKNOWN
    assert d.targets["target3"] == TC.UNKNOWN
    assert set(EE.MISSING_PRODUCERS) == {"target2", "target3"}
    assert set(d.metadata["missing_producers"]) == {"target2", "target3"}


def test_target1_is_stage_35s_and_not_derived():
    assert _run().targets["target1"] == 138.0


def test_risk_reward_is_unknown_unless_all_three_legs_are_known():
    assert _run().risk_reward != TC.UNKNOWN
    thin = _run(fr=_fr(next_target=None), structure={
        "CALL": {"structure_score": 70, "confidence": "HIGH", "ltp": 118.0}})
    assert thin.risk_reward == TC.UNKNOWN


def test_an_unknown_input_leaves_the_denominator():
    """Stage 63's rule. Three of ten reporting is barely-informed, not weak."""
    full = _run()
    thin = _run(premium={}, validation={})
    assert full.metadata["components"]
    assert (len(thin.metadata["components"] or {})
            < len(full.metadata["components"]))
    assert str(full.metadata["score_reason"]).startswith(
        f"{len(EE.WEIGHTS)} of {len(EE.WEIGHTS)}")


def test_too_few_inputs_waits_rather_than_grading_confidently():
    d = _run(matrix={}, premium={}, validation={}, structure={})
    assert d.state == "WAIT"
    assert d.readiness in (EE.NOT_READY, TC.UNKNOWN)
    # either honest reason is fine; what must not happen is a confident grade
    assert any(w in str(d.metadata["state_reason"])
               for w in ("reported", "did not carry enough"))


def test_an_entry_type_it_cannot_source_stays_unknown():
    d = _run(matrix=_matrix(intel={"type": "Something Invented"}))
    assert d.entry_type == TC.UNKNOWN
    assert "can express" in d.metadata["type_reason"]


def test_every_entry_type_emitted_is_in_the_declared_set():
    for raw, want in (("Breakout", "Breakout"), ("Bull Trap", "Reversal"),
                      ("Range", "Mean Reversion"), ("Trend", "Momentum"),
                      ("Pullback", "Pullback")):
        d = _run(matrix=_matrix(intel={"type": raw}))
        assert d.entry_type == want
        assert d.entry_type in EE.ENTRY_TYPES


def test_risk_and_reward_only_emit_declared_bands():
    for over in ({}, {"fr": _fr(stability="UNSTABLE")},
                 {"validation": _validation(validation="WEAK")},
                 {"matrix": _matrix(intel={"risk": {"level": "EXTREME"}})}):
        d = _run(**over)
        assert d.risk in EE.RISK_BANDS or d.risk == TC.UNKNOWN
        assert d.reward in EE.REWARD_BANDS or d.reward == TC.UNKNOWN


def test_instability_escalates_risk_rather_than_averaging_it():
    calm = _run()
    rough = _run(fr=_fr(stability="UNSTABLE"))
    assert (EE.RISK_BANDS.index(rough.risk)
            > EE.RISK_BANDS.index(calm.risk))
    assert any("Stage 44" in d for d in rough.metadata["risk_reason"]) or \
        "escalated" in rough.metadata["risk_reason"]


# ══════════════════════════════════════════════════════════════════════
#  4 · every reason is traceable
# ══════════════════════════════════════════════════════════════════════

def test_every_reason_names_a_stage_and_a_path():
    d = _run()
    assert d.reason_codes
    for r in d.reason_codes:
        assert r.owner.startswith("Stage "), r
        assert "." in r.source, r
        assert r.code and " " not in r.code


def test_reason_owners_match_the_context_field_they_came_from():
    """The owner is copied from the context, never written here."""
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    by_source = {ctx.get(n).source: ctx.get(n).owner for n in EE.WEIGHTS}
    for r in d.reason_codes:
        assert by_source.get(r.source) == r.owner


def test_at_most_five_top_reasons():
    assert len(_run().top_reasons) <= 5


def test_the_top_trigger_is_the_strongest_reason():
    d = _run()
    assert d.top_trigger == d.reason_codes[0].label


def test_invalidations_come_from_stages_that_own_them():
    d = _run()
    assert d.invalidations
    assert any("112" in str(i) for i in d.invalidations)


def test_warnings_are_deduplicated():
    d = _run(fr=_fr(stability="UNSTABLE"),
             validation=_validation(validation="WEAK", agreement="Disagree"))
    assert len(d.warnings) == len(set(d.warnings))
    assert d.warnings


def test_the_summary_explains_both_ways():
    """A stage that explains itself only when it acts teaches a trader to read
    silence as permission."""
    acting = _run().summary()
    blocked = _run(fr=_fr(stability="SHOCK")).summary()
    assert acting["trade"] is True and acting["why"]
    assert blocked["trade"] is False and blocked["why_not"]
    for s in (acting, blocked):
        assert set(s) >= {"trade", "state", "why", "why_not", "confidence",
                          "quality", "risk", "reward", "best_horizon", "side",
                          "strike", "timing", "warnings"}


# ══════════════════════════════════════════════════════════════════════
#  5 · Telegram is prepared, never sent
# ══════════════════════════════════════════════════════════════════════

def test_the_payload_is_marked_unsent_and_advisory():
    t = _run().telegram
    assert t["sent"] is False
    assert t["advisory_only"] is True
    assert "sending belongs downstream" in t["note"]


def test_the_payload_invents_no_value_the_decision_did_not_make():
    d = _run()
    t = d.telegram
    for key in ("state", "side", "strike", "horizon", "timing", "entry",
                "stop", "risk", "reward", "confidence", "quality"):
        assert t[key] == getattr(d, key), key
    assert t["targets"] == d.targets
    assert set(t["reasons"]) <= {r.label for r in d.reason_codes}


def test_the_payload_carries_unknowns_through_rather_than_filling_them():
    t = EE.EntryEngine(TC.build()).run().telegram
    assert t["entry"] == TC.UNKNOWN and t["risk"] == TC.UNKNOWN
    assert t["ready"] is False


def test_nothing_in_the_module_can_send():
    src = pathlib.Path(EE.__file__).read_text()
    for banned in ("send_", "post(", "requests", "bot.", "sendMessage",
                   "api.telegram"):
        assert banned not in src, banned


# ══════════════════════════════════════════════════════════════════════
#  6 · immutability and serialisation
# ══════════════════════════════════════════════════════════════════════

def test_the_decision_cannot_be_edited():
    d = _run()
    with pytest.raises(Exception):
        d.state = "ENTER"
    with pytest.raises(Exception):
        d.targets["target2"] = 999
    with pytest.raises(Exception):
        d.reason_codes[0].weight = 1


def test_it_serialises_cleanly():
    blob = json.dumps(_run().to_dict(), default=str)
    back = json.loads(blob)
    assert back["advisory_only"] is True
    assert back["targets"]["target2"] == TC.UNKNOWN
    assert back["reason_codes"][0]["owner"].startswith("Stage ")
    assert json.dumps(EE.EntryEngine(TC.build()).run().to_dict(), default=str)


def test_the_decision_records_which_context_produced_it():
    """A decision made on a thin context must be visibly thin."""
    d = _run()
    assert d.metadata["context_cycle"] == 7
    assert d.metadata["context_version"] == TC.VERSION
    assert d.metadata["context_coverage"]["pct"] > 0
    thin = EE.EntryEngine(TC.build()).run()
    assert thin.metadata["context_coverage"]["pct"] == 0


def test_every_recommendation_can_be_reconstructed_from_the_context():
    """Weights, components and the source paths are all published, so the score
    can be recomputed by hand from the context alone."""
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    comps = d.metadata["components"]
    weights = d.metadata["weights"]
    total = sum(weights[k] for k in comps)
    rebuilt = round(sum(comps[k] * weights[k] for k in comps) / total)
    assert rebuilt == d.score
    for name in comps:
        assert ctx.known(name), f"{name} scored but not known in the context"


def test_it_is_advisory_and_exposes_no_mutator():
    assert EE.ADVISORY_ONLY is True
    assert _run().advisory_only is True
    for name in dir(EE):
        if name.startswith("_"):
            continue
        assert not name.startswith(("apply", "deploy", "promote", "set_",
                                    "update_", "override", "send"))


def test_it_is_not_an_engine():
    from mios_v5.engines import ALL_ENGINES
    names = {c().name for c in ALL_ENGINES} | {c.__name__ for c in ALL_ENGINES}
    assert not any("entry_engine" in str(n).lower() for n in names)


def test_running_twice_on_one_context_gives_the_same_answer():
    """Same content, different identity — two runs are two decisions.

    `id`, `created_at` and `hash` are deliberately excluded: a decision is a
    record of an instant, so two records of two instants must not be the same
    object even when they conclude the same thing."""
    ctx = _ctx()
    a, b = EE.EntryEngine(ctx).run(), EE.EntryEngine(ctx).run()
    ident = {"id", "created_at", "hash", "telegram"}
    assert {k: v for k, v in a.to_dict().items() if k not in ident} == \
        {k: v for k, v in b.to_dict().items() if k not in ident}
    assert a.id != b.id


def test_it_never_raises_on_junk():
    for junk in ({}, {"fr": "nonsense"}, {"matrix": []},
                 {"premium": {"bridge": "bad"}}, {"structure": 7},
                 {"validation": {"bridge": None}}):
        d = EE.EntryEngine(TC.build(**junk)).run()
        assert d.state in STATES
        assert json.dumps(d.to_dict(), default=str)


# ══════════════════════════════════════════════════════════════════════
#  7 · the frozen contract — identity, integrity, immutability
# ══════════════════════════════════════════════════════════════════════

def test_the_decision_is_deeply_immutable():
    """A decision represents history, and history must never change."""
    import dataclasses
    d = _run()
    assert dataclasses.is_dataclass(d)
    assert d.__dataclass_params__.frozen is True
    for attr, value in (("state", "ENTER"), ("id", "x"), ("hash", "y"),
                        ("created_at", "z"), ("version", "99")):
        with pytest.raises(Exception):
            setattr(d, attr, value)
    with pytest.raises(Exception):
        d.targets["target1"] = 1
    with pytest.raises(Exception):
        d.telegram["state"] = "ENTER"
    with pytest.raises(Exception):
        d.metadata["weights"] = {}
    with pytest.raises(Exception):
        d.metadata["components"]["strike.validation"] = 0
    for seq in (d.reason_codes, d.warnings, d.invalidations):
        assert isinstance(seq, tuple)


def test_the_version_always_exists_and_is_the_frozen_one():
    # 72.1 is the Stage 71.85 amendment: one weight added, philosophy untouched,
    # and the bump is what keeps it from being a quiet edit inside a frozen
    # stage. See the VERSION comment and docs/STAGE72_FROZEN.md.
    assert EE.VERSION == "72.1"
    for over in ({}, {"matrix": {}}, {"fr": _fr(stability="SHOCK")}):
        assert _run(**over).version == "72.1"
    assert EE.EntryEngine(None).run().version == "72.1"
    # the engine's metadata must agree with the decision's own field
    assert _run().metadata["version"] == _run().version


def test_every_decision_carries_a_uuid4():
    import uuid as _uuid
    d = _run()
    assert d.id
    parsed = _uuid.UUID(d.id)
    assert parsed.version == 4
    assert str(parsed) == d.id


def test_decision_ids_are_unique_across_runs():
    ids = {EE.EntryEngine(_ctx()).run().id for _ in range(50)}
    assert len(ids) == 50


def test_an_empty_context_still_gets_an_identity():
    """A WAIT is a decision too, and the record of a refusal is half the
    audit — Stage 67's rule, applied to execution."""
    d = EE.EntryEngine(TC.build()).run()
    assert d.id and d.created_at and d.hash and d.version
    assert d.verify() is True


def test_created_at_is_utc_iso8601_and_fixed():
    from datetime import datetime, timezone
    d = _run()
    parsed = datetime.fromisoformat(d.created_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
    assert parsed.microsecond == 0
    with pytest.raises(Exception):
        d.created_at = "2020-01-01T00:00:00+00:00"


def test_the_hash_is_deterministic():
    """Same six inputs, same digest — every time, in any process."""
    args = ("id-1", "72.0", "ENTER", 72, 83, "2026-07-30T10:00:00+00:00")
    first = EE.decision_hash(*args)
    assert first == EE.decision_hash(*args)
    assert len(first) == 64 and int(first, 16) >= 0


@pytest.mark.parametrize("index", range(6))
def test_changing_any_hashed_field_changes_the_hash(index):
    base = ["id-1", "72.0", "ENTER", 72, 83, "2026-07-30T10:00:00+00:00"]
    changed = list(base)
    changed[index] = "different"
    assert EE.decision_hash(*base) != EE.decision_hash(*changed)


def test_a_number_and_its_text_form_hash_the_same():
    """A score stored as text and a score stored as a number are the same
    decision, and an integrity check that disagreed would cry wolf."""
    a = EE.decision_hash("i", "72.0", "ENTER", 72, 83, "t")
    b = EE.decision_hash("i", "72.0", "ENTER", "72", "83", "t")
    assert a == b


def test_the_hash_fields_are_declared_and_are_the_ones_used():
    assert EE.HASH_FIELDS == ("id", "version", "state", "confidence",
                              "score", "created_at")
    d = _run()
    for name in EE.HASH_FIELDS:
        assert hasattr(d, name), name


def test_a_decision_verifies_against_its_own_hash():
    for over in ({}, {"fr": _fr(stability="SHOCK")}, {"matrix": {}}):
        assert _run(**over).verify() is True


def test_an_altered_record_fails_verification():
    """The point of the hash: a stored decision whose content no longer matches
    was changed after it was made."""
    import dataclasses
    d = _run()
    tampered = dataclasses.replace(d, state="ENTER" if d.state != "ENTER"
                                   else "WAIT")
    assert tampered.verify() is False
    assert d.verify() is True


def test_identity_is_the_join_key_downstream_stages_carry():
    d = _run()
    ident = d.identity()
    assert set(ident) == {"id", "version", "created_at", "hash"}
    assert all(ident[k] == getattr(d, k) for k in ident)


def test_the_telegram_payload_carries_version_id_and_created_at():
    t = _run().telegram
    for key in ("id", "version", "created_at", "hash"):
        assert t[key], key
    d = _run()
    assert d.telegram["id"] == d.id
    assert d.telegram["hash"] == d.hash
    assert d.telegram["created_at"] == d.created_at


def test_the_summary_carries_the_identity_too():
    d = _run()
    s = d.summary()
    assert s["id"] == d.id and s["version"] == d.version
    assert s["created_at"] == d.created_at


def test_the_serialised_decision_carries_the_identity():
    back = json.loads(json.dumps(_run().to_dict(), default=str))
    for key in ("id", "version", "created_at", "hash"):
        assert back[key]


# ══════════════════════════════════════════════════════════════════════
#  8 · Stage 72 owns the execution decision and nothing after it
# ══════════════════════════════════════════════════════════════════════

def test_it_never_imports_a_later_stage():
    """Stage 73+ extend a decision; Stage 72 must not know they exist."""
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    for banned in ("trade_manager", "stage73", "stage_73", "position",
                   "portfolio", "pnl", "learning", "analytics"):
        assert not any(banned in m for m in imported), banned


def test_it_owns_no_position_concept():
    """Position, PnL, trailing, scaling and exit belong to Stage 73+. A field
    for any of them here would be Stage 72 claiming ground it cannot see."""
    fields = set(_run().to_dict())
    for banned in ("position", "pnl", "qty", "quantity", "lots", "filled",
                   "trail", "exit_price", "realised", "unrealised"):
        assert banned not in fields, banned


def test_the_frozen_doc_exists_and_names_the_contract():
    doc = (pathlib.Path(EE.__file__).resolve().parents[1] / "docs" /
           "STAGE72_FROZEN.md")
    assert doc.exists()
    text = doc.read_text()
    for section in ("Purpose", "Owners", "Inputs", "Outputs", "State Machine",
                    "Scoring", "Telegram Contract", "Decision Contract",
                    "Immutability", "Versioning", "Known limitations",
                    "Future extension points"):
        assert section in text, section
