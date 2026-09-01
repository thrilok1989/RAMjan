"""Stage 73 — the Trade Lifecycle Engine.

Life after entry, and nothing before it. These guard the ownership boundary
above all else:

1. **Two inputs only** — `EntryDecision` and `TradingContext`.
2. **`EntryDecision` is never mutated** — Stage 73 references, never replaces.
3. **Lifecycle states are its own** — entry states are not reused.
4. **`position_known` is always UNKNOWN** — nothing reports a fill, and
   inferring one from `ENTER` would manage a position that may not exist.
5. **It owns no position, PnL, sizing or broker concept.**
"""

import ast
import dataclasses
import json
import pathlib

import pytest

from mios_v5 import entry_engine as EE
from mios_v5 import trade_lifecycle as TL
from mios_v5 import trading_context as TC
from mios_v5.tests.test_entry_engine import (_ctx, _fr, _matrix, _premium,
                                             _structure, _validation)


def _code_only(module) -> str:
    """The module's executable source, with every docstring removed.

    Three tests in this stack have now failed because a module *explains* a
    rule in prose using the words a grep forbids — "they never predict", "no
    second POC", "BUYER ABSORPTION". A guard that cannot tell a comment from
    an implementation fails on the sentence explaining why the implementation
    is correct, which trains people to delete the sentence.
    """
    tree = ast.parse(pathlib.Path(module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def _entry(**over):
    return EE.EntryEngine(_ctx(**over)).run()


def _life(entry_over=None, **ctx_over):
    ctx = _ctx(**ctx_over)
    decision = EE.EntryEngine(_ctx(**(entry_over or ctx_over))).run()
    return TL.TradeLifecycle(decision, ctx).run()


# ══════════════════════════════════════════════════════════════════════
#  1 · two inputs, no producers
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_only_the_entry_decision_and_the_context():
    tree = ast.parse(pathlib.Path(TL.__file__).read_text())
    local = {n.module for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"entry_engine", "trading_context"}, local


def test_it_imports_no_producer_and_no_network():
    tree = ast.parse(pathlib.Path(TL.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"numpy", "pandas", "indicators", "streamlit", "requests",
              "httpx", "urllib", "socket", "supabase", "plotly", "telegram",
              "opportunity", "premium_energy", "strike_validation",
              "premium_structure", "final_read", "engines", "decision_v2"}
    assert not (imported & banned), imported & banned


def test_it_never_touches_session_state():
    tree = ast.parse(pathlib.Path(TL.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "session_state"


def test_every_health_input_is_a_real_context_field():
    ctx = _ctx()
    for name in TL.HEALTH_WEIGHTS:
        grp, _, fld = name.partition(".")
        assert fld in ctx.group(grp), f"{name} is not a context field"


def test_no_health_weight_reads_the_same_field_twice():
    """Two weights on one fact would count the tape twice — the failure Stage 53
    exists to fix, and the one this stack keeps re-learning."""
    assert len(TL.HEALTH_WEIGHTS) == len(set(TL.HEALTH_WEIGHTS))


def test_it_runs_from_the_two_inputs_alone():
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    assert isinstance(TL.TradeLifecycle(d, ctx).run(), TL.TradeLifecycleDecision)
    assert isinstance(TL.run(d, ctx), TL.TradeLifecycleDecision)


# ══════════════════════════════════════════════════════════════════════
#  2 · the EntryDecision is never mutated
# ══════════════════════════════════════════════════════════════════════

def test_the_entry_decision_is_unchanged_by_a_lifecycle_run():
    """A decision is history. Stage 73 builds a new object; it never edits the
    one it was handed."""
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    before, before_hash = d.to_dict(), d.hash
    TL.TradeLifecycle(d, ctx).run()
    assert d.to_dict() == before
    assert d.hash == before_hash
    assert d.verify() is True


def test_the_lifecycle_references_the_decision_rather_than_replacing_it():
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    lc = TL.TradeLifecycle(d, ctx).run()
    assert lc.decision_id == d.id
    assert lc.id != d.id
    assert lc.version == "73.0" and d.version == EE.VERSION


def test_it_carries_the_entry_version_and_state_in_metadata():
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    lc = TL.TradeLifecycle(d, ctx).run()
    assert lc.metadata["entry_version"] == d.version
    assert lc.metadata["entry_state"] == d.state


def test_a_lifecycle_without_a_decision_still_returns_one():
    lc = TL.TradeLifecycle(None, _ctx()).run()
    assert lc.state in TL.STATES
    assert lc.decision_id == ""
    assert lc.intent == TC.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  3 · the lifecycle state machine is its own
# ══════════════════════════════════════════════════════════════════════

def test_the_lifecycle_states_are_the_declared_nine():
    assert TL.STATES == ("WAIT_ENTRY", "ENTERED", "HOLD", "ADD", "SCALE_OUT",
                         "TRAIL", "EXIT", "COMPLETE", "ABORT")
    assert set(TL.LABEL) == set(TL.STATES)


def test_entry_states_are_not_reused_wholesale():
    """Stage 52 describes getting INTO a trade; this describes being IN one.
    Sharing the vocabulary would make WAIT mean two things one stage apart."""
    from mios_v5.decision_v2 import STATES as ENTRY_STATES
    assert "WAIT" in ENTRY_STATES and "WAIT" not in TL.STATES
    assert "ENTRY_READY" in ENTRY_STATES and "ENTRY_READY" not in TL.STATES
    assert "WAIT_ENTRY" in TL.STATES and "WAIT_ENTRY" not in ENTRY_STATES
    assert "ENTERED" in TL.STATES and "ENTERED" not in ENTRY_STATES


def test_the_state_is_always_a_lifecycle_state():
    for over in ({}, {"fr": _fr(stability="SHOCK")},
                 {"fr": _fr(flow_shift={"freeze_entries": True})},
                 {"validation": _validation(validation="INVALID")},
                 {"matrix": {}}, {"premium": {}}, {"structure": {}}):
        lc = _life(**over)
        assert lc.state in TL.STATES
        assert lc.action in TL.ACTIONS


def test_inventing_a_state_or_action_raises():
    with pytest.raises(ValueError, match="not a Stage 73 lifecycle state"):
        TL.TradeLifecycle._checked("ENTRY_READY")
    with pytest.raises(ValueError, match="not a Stage 73 action"):
        TL.TradeLifecycle._checked_action("COMPLETE")


def test_exactly_one_action_is_chosen():
    lc = _life()
    assert isinstance(lc.action, str)
    assert lc.action in TL.ACTIONS


def test_no_entry_intent_waits_for_one():
    lc = _life(matrix=_matrix(intel={"timing": {"timing": "MISSED"}}))
    assert lc.intent == TL.NO_ENTRY
    assert lc.state == "WAIT_ENTRY" and lc.action == "HOLD"


def test_an_aborted_entry_aborts_the_lifecycle():
    lc = _life(fr=_fr(stability="SHOCK"))
    assert lc.state == "ABORT" and lc.action == "ABORT"


def test_a_freeze_aborts_before_anything_else_is_considered():
    ctx = _ctx(fr=_fr(flow_shift={"freeze_entries": True, "detected": True}))
    d = EE.EntryEngine(_ctx()).run()          # a healthy ENTER
    lc = TL.TradeLifecycle(d, ctx).run()
    assert lc.state == "ABORT"
    assert "froze" in lc.metadata["action_reason"]


# ══════════════════════════════════════════════════════════════════════
#  4 · position awareness — the honest UNKNOWN
# ══════════════════════════════════════════════════════════════════════

def test_position_known_is_always_unknown():
    """Nothing in MIOS reports a fill. Inferring one from ENTER would have every
    later phase managing a position that may not exist."""
    for over in ({}, {"fr": _fr(stability="SHOCK")}, {"matrix": {}}):
        assert _life(**over).position_known == TC.UNKNOWN


def test_intent_and_position_are_separate_facts():
    lc = _life()
    assert lc.intent == TL.ENTERED_INTENT
    assert lc.position_known == TC.UNKNOWN


def test_the_missing_producers_are_named():
    assert set(TL.MISSING_PRODUCERS) == {"position_state", "fill_price"}
    lc = _life()
    assert set(lc.metadata["missing_producers"]) == {"position_state",
                                                     "fill_price"}
    assert any("fill" in w for w in lc.warnings)


# ══════════════════════════════════════════════════════════════════════
#  5 · health, trail, scale, exit
# ══════════════════════════════════════════════════════════════════════

def test_health_reports_a_declared_band():
    for over in ({}, {"fr": _fr(stability="UNSTABLE")},
                 {"validation": _validation(liquidity="Disagree")}):
        h = _life(**over).health
        assert h in TL.HEALTH_BANDS or h == TC.UNKNOWN


def test_an_unknown_input_leaves_the_health_denominator():
    """A position graded on two of eight is barely observed, not unhealthy."""
    full, thin = _life(), _life(premium={}, validation={})
    assert full.metadata["components"]
    assert (len(thin.metadata["components"] or {})
            < len(full.metadata["components"]))
    assert "8 of 8" in full.metadata["health_reason"]


def test_no_health_input_at_all_is_unknown_not_critical():
    lc = TL.TradeLifecycle(_entry(), TC.build()).run()
    assert lc.health == TC.UNKNOWN
    assert lc.health != "Critical"


def test_the_trail_is_a_band_and_names_the_stop_it_consumes():
    """`adaptive_trail` belongs to Stage 52. This stage judges HOW to trail; the
    level comes from the decision."""
    lc = _life()
    assert lc.trail in TL.TRAIL_BANDS or lc.trail == TC.UNKNOWN
    assert lc.metadata["stop_consumed"] == _entry().stop
    assert "apply the band to the stop" in lc.metadata["trail_reason"]


def test_it_computes_no_trail_level():
    """Stage 52 owns `adaptive_trail`. This stage may not import it, call it, or
    reimplement it — it returns a band and consumes the published stop."""
    tree = ast.parse(pathlib.Path(TL.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported |= {a.name for a in node.names}
    assert "adaptive_trail" not in imported
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not (called & {"adaptive_trail", "atr", "compute_trail"})
    # and the trail method performs no arithmetic on the stop it consumes
    trail_src = _code_only(TL)
    trail_src = trail_src[trail_src.index("def trail("):
                          trail_src.index("def scale(")]
    assert "stop *" not in trail_src and "stop +" not in trail_src
    assert "stop -" not in trail_src


def test_no_stop_means_no_trail_rather_than_a_guess():
    ctx = _ctx()
    d = dataclasses.replace(EE.EntryEngine(ctx).run(), stop=TC.UNKNOWN)
    lc = TL.TradeLifecycle(d, ctx).run()
    assert lc.trail == TC.UNKNOWN
    assert "nothing to trail" in lc.metadata["trail_reason"]


def test_instability_forces_an_aggressive_trail():
    lc = _life(fr=_fr(stability="UNSTABLE"))
    assert lc.trail == TL.AGGRESSIVE_TRAIL


def test_scale_never_averages_disagreeing_reads():
    """Averaging "energy collapsing" against "structure strong" recommends
    adding to a position that is losing its exit."""
    code = _code_only(TL)
    scale_src = code[code.index("def scale("):code.index("def exit_reason(")]
    for banned in ("sum(", "mean", "/ 2", "avg"):
        assert banned not in scale_src, banned


def test_scale_reduces_on_an_unstable_tape_whatever_else_says():
    lc = _life(fr=_fr(stability="UNSTABLE"))
    assert lc.scale == TL.SCALE_REDUCE
    assert "size down" in lc.metadata["scale_reason"]


def test_scale_reports_neither_when_reads_disagree():
    ctx = _ctx(premium=_premium(bridge={"energy_score": {"CALL": 80},
                                        "spike_probability": {"CALL": 50},
                                        "energy_shift": {"CALL": "Holding"},
                                        "energy_acceleration": {"CALL": 0},
                                        "rotation": "Stable"}),
               structure={"CALL": {"structure_score": 20, "confidence": "HIGH",
                                   "support": 112.0, "ltp": 118.0}})
    lc = TL.TradeLifecycle(EE.EntryEngine(ctx).run(), ctx).run()
    assert lc.scale in (TL.SCALE_NEITHER, TL.SCALE_REDUCE)


def test_exit_reasons_are_from_the_declared_set():
    for over in ({}, {"fr": _fr(stability="SHOCK")},
                 {"validation": _validation(liquidity="Disagree")}):
        r = _life(**over).exit_reason
        assert r in TL.EXIT_REASONS or r in (None, TC.UNKNOWN)


def test_a_stop_hit_outranks_a_shock():
    """A stop hit during a shock is still a stop hit, and a learning row that
    recorded the shock would blame the tape for a level doing its job."""
    ctx = _ctx(fr=_fr(stability="SHOCK"),
               structure={"CALL": {"structure_score": 70, "confidence": "HIGH",
                                   "support": 112.0, "resistance": 130.0,
                                   "ltp": 110.0}})     # below the 112 stop
    d = EE.EntryEngine(_ctx()).run()
    lc = TL.TradeLifecycle(d, ctx).run()
    assert lc.exit_reason == "Stop Hit"
    assert lc.state == "COMPLETE" and lc.action == "EXIT"


def test_a_target_hit_completes_the_trade():
    ctx = _ctx(structure={"CALL": {"structure_score": 70,
                                   "confidence": "HIGH", "support": 112.0,
                                   "resistance": 130.0, "ltp": 140.0}})
    lc = TL.TradeLifecycle(EE.EntryEngine(_ctx()).run(), ctx).run()
    assert lc.exit_reason == "Target Hit"
    assert lc.state == "COMPLETE"


def test_no_live_premium_means_the_price_triggers_are_unknown_not_absent():
    """"Not checked" and "checked, nothing fired" are different facts."""
    ctx = _ctx(structure={"CALL": {"structure_score": 70,
                                   "confidence": "HIGH", "support": 112.0}})
    lc = TL.TradeLifecycle(EE.EntryEngine(_ctx()).run(), ctx).run()
    assert lc.exit_reason == TC.UNKNOWN
    assert "cannot be checked" in lc.metadata["exit_why"]


def test_illiquidity_is_an_exit_reason():
    lc = _life(validation=_validation(liquidity="Disagree"))
    assert lc.exit_reason == "Illiquidity"


def test_exit_reasons_report_rather_than_predict():
    """Checked on the code, not the prose — the module *says* it never predicts,
    and a grep over the whole file trips on its own explanation."""
    code = _code_only(TL).lower()
    for banned in ("predict", "forecast", "will_hit", "probability_of_exit",
                   "expected_exit"):
        assert banned not in code, banned
    # every exit verdict is a comparison, never a projection
    for reason in TL.EXIT_REASONS:
        assert reason in ("Stop Hit", "Target Hit", "Shock", "Illiquidity",
                          "Structure Failure", "Energy Collapse", "Expiry",
                          "Manual")


# ══════════════════════════════════════════════════════════════════════
#  6 · UNKNOWN propagates
# ══════════════════════════════════════════════════════════════════════

def test_an_empty_context_yields_unknowns_not_zeros():
    lc = TL.TradeLifecycle(None, TC.build()).run()
    assert lc.health == TC.UNKNOWN and lc.trail == TC.UNKNOWN
    assert lc.scale == TC.UNKNOWN and lc.position_known == TC.UNKNOWN
    for v in (lc.health, lc.trail, lc.scale):
        assert v != 0 and v is not None
    assert lc.state in TL.STATES


def test_no_inputs_at_all_still_returns_a_decision():
    lc = TL.TradeLifecycle().run()
    assert lc.state in TL.STATES and lc.action in TL.ACTIONS
    assert lc.advisory_only is True


def test_it_never_raises_on_junk():
    for junk in ({}, {"fr": "nonsense"}, {"matrix": []},
                 {"premium": {"bridge": "bad"}}, {"structure": 7}):
        ctx = TC.build(**junk)
        lc = TL.TradeLifecycle(EE.EntryEngine(ctx).run(), ctx).run()
        assert lc.state in TL.STATES
        assert json.dumps(lc.to_dict(), default=str)


# ══════════════════════════════════════════════════════════════════════
#  7 · identity, integrity, immutability
# ══════════════════════════════════════════════════════════════════════

def test_the_lifecycle_decision_is_deeply_immutable():
    lc = _life()
    assert dataclasses.is_dataclass(lc)
    assert lc.__dataclass_params__.frozen is True
    for attr in ("state", "action", "id", "decision_id", "hash", "created_at"):
        with pytest.raises(Exception):
            setattr(lc, attr, "x")
    with pytest.raises(Exception):
        lc.telegram_payload["state"] = "EXIT"
    with pytest.raises(Exception):
        lc.metadata["weights"] = {}
    with pytest.raises(Exception):
        lc.metadata["components"]["market.stability"] = 0
    for seq in (lc.reason_codes, lc.warnings):
        assert isinstance(seq, tuple)


def test_identity_fields_are_present_on_every_decision():
    for over in ({}, {"matrix": {}}, {"fr": _fr(stability="SHOCK")}):
        lc = _life(**over)
        assert lc.id and lc.created_at and lc.hash
        assert lc.version == "73.0"


def test_lifecycle_ids_are_unique():
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    ids = {TL.TradeLifecycle(d, ctx).run().id for _ in range(50)}
    assert len(ids) == 50


def test_the_hash_is_deterministic():
    args = ("lc-1", "d-1", "73.0", "HOLD", "HOLD", "2026-07-30T10:00:00+00:00")
    assert TL.lifecycle_hash(*args) == TL.lifecycle_hash(*args)
    assert len(TL.lifecycle_hash(*args)) == 64


@pytest.mark.parametrize("index", range(6))
def test_changing_any_hashed_field_changes_the_hash(index):
    base = ["lc-1", "d-1", "73.0", "HOLD", "HOLD",
            "2026-07-30T10:00:00+00:00"]
    changed = list(base)
    changed[index] = "different"
    assert TL.lifecycle_hash(*base) != TL.lifecycle_hash(*changed)


def test_a_decision_verifies_and_a_tampered_one_does_not():
    lc = _life()
    assert lc.verify() is True
    tampered = dataclasses.replace(lc, action="EXIT" if lc.action != "EXIT"
                                   else "HOLD")
    assert tampered.verify() is False


def test_identity_carries_the_join_back_to_the_entry():
    lc = _life()
    ident = lc.identity()
    assert set(ident) == {"id", "decision_id", "version", "created_at", "hash"}
    assert ident["decision_id"] == lc.decision_id


def test_created_at_is_utc_iso8601():
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(_life().created_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


# ══════════════════════════════════════════════════════════════════════
#  8 · Telegram prepared, never sent
# ══════════════════════════════════════════════════════════════════════

def test_the_payload_is_marked_unsent():
    t = _life().telegram_payload
    assert t["sent"] is False and t["advisory_only"] is True
    assert "sending belongs downstream" in t["note"]


def test_the_payload_carries_both_identities():
    lc = _life()
    t = lc.telegram_payload
    assert t["id"] == lc.id and t["decision_id"] == lc.decision_id
    assert t["version"] == "73.0" and t["hash"] == lc.hash


def test_the_payload_invents_no_value():
    lc = _life()
    t = lc.telegram_payload
    for key in ("state", "action", "health", "risk", "trail", "scale",
                "exit_reason", "confidence"):
        assert t[key] == getattr(lc, key), key
    assert set(t["reasons"]) <= {r.label for r in lc.reason_codes}


def test_nothing_in_the_module_can_send():
    code = _code_only(TL)
    for banned in ("send_", "post(", "requests", "sendMessage", "api.telegram"):
        assert banned not in code, banned


# ══════════════════════════════════════════════════════════════════════
#  9 · explainability and ownership
# ══════════════════════════════════════════════════════════════════════

def test_every_reason_traces_to_a_context_field():
    lc = _life()
    ctx = _ctx()
    by_source = {ctx.get(n).source: ctx.get(n).owner for n in TL.HEALTH_WEIGHTS}
    assert lc.reason_codes
    for r in lc.reason_codes:
        assert r.owner.startswith("Stage ")
        assert by_source.get(r.source) == r.owner


def test_at_most_five_reasons():
    assert len(_life().top_reasons) <= 5


def test_the_summary_explains_both_ways():
    s = _life().summary()
    assert set(s) >= {"id", "decision_id", "action", "state", "why", "why_not",
                      "confidence", "risk", "health", "warnings",
                      "top_trigger"}
    assert s["why"]


def test_it_owns_no_position_pnl_or_sizing_concept():
    """Kept out deliberately: they need capital, risk-per-trade and fills, and
    their absence would otherwise infect every phase."""
    fields = set(_life().to_dict())
    for banned in ("pnl", "qty", "quantity", "lots", "size", "capital",
                   "realised", "unrealised", "broker", "order_id",
                   "fill_price", "entry_price"):
        assert banned not in fields, banned


def test_it_never_imports_a_later_stage():
    """Stage 74+ consume this stage; it must not know they exist."""
    tree = ast.parse(pathlib.Path(TL.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    for banned in ("stage74", "learning", "analytics", "replay",
                   "trade_review", "attribution"):
        assert not any(banned in m for m in imported), banned


def test_it_is_advisory_and_not_an_engine():
    from mios_v5.engines import ALL_ENGINES
    assert TL.ADVISORY_ONLY is True
    assert _life().advisory_only is True
    names = {c().name for c in ALL_ENGINES} | {c.__name__ for c in ALL_ENGINES}
    assert not any("lifecycle" in str(n).lower() for n in names)


def test_the_lifecycle_is_reconstructable_from_its_metadata():
    lc = _life()
    comps = lc.metadata["components"]
    weights = lc.metadata["weights"]
    total = sum(weights[k] for k in comps)
    rebuilt = round(sum(comps[k] * weights[k] for k in comps) / total)
    band = ("Excellent" if rebuilt >= 80 else "Good" if rebuilt >= 62 else
            "Average" if rebuilt >= 45 else "Poor" if rebuilt >= 25 else
            "Critical")
    assert band == lc.health


def test_it_serialises_cleanly():
    back = json.loads(json.dumps(_life().to_dict(), default=str))
    assert back["version"] == "73.0"
    assert back["decision_id"]
    assert back["reason_codes"][0]["owner"].startswith("Stage ")


def test_the_docs_exist():
    docs = pathlib.Path(TL.__file__).resolve().parents[1] / "docs"
    for name in ("AUDIT_STAGE_73_LIFECYCLE.md", "STAGE73_OUTPUT_CONTRACT.md",
                 "STAGE73_FROZEN_PLAN.md"):
        assert (docs / name).exists(), name
