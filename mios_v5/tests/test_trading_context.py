"""Stage 71.95 — the Unified Trading Context.

The context carries no intelligence of its own, so these tests guard the
contract rather than any arithmetic:

1. **Every field names its owner** — Principle 12. A value with no owner cannot
   be inspected, because nobody knows where to look.
2. **One fact, one owner** — no two fields read the same path.
3. **It calculates nothing** — no producer imported, no arithmetic.
4. **Immutable after creation** — deep-frozen, so two consumers in one cycle
   cannot see different values.
5. **Missing stays UNKNOWN** — never `0`, never a default.
"""

import ast
import json
import pathlib

import pytest

from mios_v5 import trading_context as TC


# ── fixtures: shaped exactly like the real producers ────────────────────

def _fr(**over):
    fr = {
        "market_state": {"state": "TREND", "label": "📈 Trending"},
        "regime": "TRENDING",
        "day_classification": {"day_type": "TREND"},
        "session_intel": {"window": "Morning Trend"},
        "preferred_bias": "BULLISH",
        "transition": {"state": "STRENGTHENING"},
        "stability": "STABLE",
        "htf_alignment": {"bias": "BULL", "score": 78},
        "htf": {"structure": "higher highs"},
        "value_migration": {"direction": "up"},
        "breakout_risk": "MODERATE",
        "validity": {"verdict": "VALID"},
        "flow_shift": {"freeze_entries": False, "detected": False},
    }
    fr.update(over)
    return fr


def _matrix():
    return {"best": "intraday",
            "best_trade": {"horizon": "intraday", "side": "CALL",
                           "score": 61.5, "confidence": 72,
                           "reasons": ["families agree", "reaction at level"]}}


def _premium():
    return {"dominance": "CALL Dominant",
            "preferred": {"preferred": "Prefer CALL", "side": "CALL"},
            "bridge": {"energy_score": {"CALL": 78, "PUT": 22},
                       "spike_probability": {"CALL": 71, "PUT": 30},
                       "energy_shift": {"CALL": "Increasing",
                                        "PUT": "Decreasing"},
                       "energy_acceleration": {"CALL": 12, "PUT": -9},
                       "rotation": "Stable"}}


def _validation():
    return {"selected": {"CALL": 24250.0, "PUT": 24250.0},
            "bridge": {"selected_strike": {"CALL": 24250.0, "PUT": 24250.0},
                       "premium_validation": {"CALL": "VALID", "PUT": "INVALID"},
                       "premium_liquidity": {"CALL": "Agree", "PUT": "Agree"},
                       "most_traded_agreement": {"CALL": "Agree",
                                                 "PUT": "Agree"}}}


def _structure():
    return {"CALL": {"structure_score": 70, "confidence": "HIGH",
                     "support": 112.0, "resistance": None},
            "PUT": {"structure_score": 34, "confidence": "HIGH",
                    "support": None, "resistance": 95.0}}


def _ctx(**over):
    kw = dict(fr=_fr(), matrix=_matrix(), premium=_premium(),
              validation=_validation(), structure=_structure(), cycle=7)
    kw.update(over)
    return TC.build(**kw)


# ══════════════════════════════════════════════════════════════════════
#  1 · every field has an owner
# ══════════════════════════════════════════════════════════════════════

def test_every_field_declares_owner_stage_and_source():
    """Principle 12 in its strictest form: a value that reached a decision must
    be traceable to somewhere a trader can look."""
    ctx = _ctx()
    rows = ctx.owners()
    assert rows
    for row in rows:
        assert row["owner"] and row["owner"] != TC.UNKNOWN, row
        assert row["stage"], row
        assert row["source"] and "." in row["source"], row


def test_no_field_is_anonymous_even_when_unknown():
    """A silent producer still owns its field — otherwise the one value you
    most want to chase is the one with no address."""
    ctx = TC.build()
    for row in ctx.owners():
        assert row["owner"] and row["owner"] != TC.UNKNOWN
        assert row["known"] is False


def test_the_owners_table_covers_every_group_and_field():
    ctx = _ctx()
    named = {r["field"] for r in ctx.owners()}
    for grp, fields in TC.SPEC.items():
        for name in fields:
            assert f"{grp}.{name}" in named
    for grp, aliases in TC.ALIAS.items():
        for name in aliases:
            assert f"{grp}.{name}" in named


def test_the_source_path_is_live_not_a_comment():
    """`_get` reads it. A path that goes stale yields UNKNOWN, not a wrong
    number read from somewhere else."""
    good = _ctx()
    assert good.value("market.stability") == "STABLE"
    moved = _ctx(fr=_fr(stability=None))
    assert not moved.known("market.stability")


# ══════════════════════════════════════════════════════════════════════
#  2 · one fact, one owner
# ══════════════════════════════════════════════════════════════════════

def test_no_two_fields_read_the_same_path():
    """The duplication rule. Two names for one fact drift."""
    seen = {}
    for row in TC.spec_rows():
        src = row["source"]
        assert src not in seen, (
            f"{row['field']} and {seen[src]} both read {src} — one fact, "
            f"one owner")
        seen[src] = row["field"]


def test_no_two_fields_share_a_name_across_groups():
    names = [f"{g}.{n}" for g, fs in TC.SPEC.items() for n in fs]
    assert len(names) == len(set(names))


def test_a_field_that_is_another_fields_value_is_an_alias_not_a_copy():
    """`RECOVERY` is one of the four values Stage 44's stability takes. Reading
    it separately would give one fact two owners."""
    ctx = _ctx()
    rec = ctx.get("risk.recovery")
    assert not rec.known
    assert "market.stability" in rec.source
    assert "two owners" in rec.note
    # and the fact itself is reachable, exactly once
    assert ctx.value("market.stability") == "STABLE"


def test_two_fields_may_share_a_stage_for_different_facts():
    """Stage 44 legitimately owns both the stability word and the freeze flag —
    same owner, different facts, different paths."""
    ctx = _ctx()
    assert ctx.get("market.stability").stage == "44"
    assert ctx.get("risk.freeze").stage == "44"
    assert (ctx.get("market.stability").source
            != ctx.get("risk.freeze").source)


# ══════════════════════════════════════════════════════════════════════
#  3 · it calculates nothing
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_calculation_engine():
    tree = ast.parse(pathlib.Path(TC.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"numpy", "pandas", "indicators", "streamlit", "requests",
              "scipy", "plotly"}
    assert not (imported & banned), imported & banned


def test_it_imports_no_mios_engine():
    """It transports what stages produced; it never asks one to produce.

    Checked on the import graph, not the text: the ownership table *names*
    every producer it carries a value from, and a grep cannot tell a label from
    an import — the SPEC entry `("Premium Structure", "71.8", …)` is the
    provenance this module exists to publish."""
    tree = ast.parse(pathlib.Path(TC.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("mios_v5"), mod
            assert not mod.startswith("."), mod
            assert "engines" not in mod, mod
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("mios_v5"), a.name


def test_it_calls_no_producer_function():
    """Beyond imports: no local name that looks like an engine is ever called."""
    tree = ast.parse(pathlib.Path(TC.__file__).read_text())
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    for banned in ("analyse", "build_matrix", "enrich", "compute_vpfr",
                   "run_mios_pass"):
        assert banned not in called, banned


def test_it_contains_no_arithmetic_on_engine_values():
    """`coverage()` counts fields, which is bookkeeping about the context
    itself. Nothing arithmetic touches a transported value."""
    src = pathlib.Path(TC.__file__).read_text()
    for banned in ("sum(", "/ 2", "* 0.", "round(f.value", "avg", "mean"):
        if banned == "sum(":
            # only the two field counters may sum, and they sum lengths
            assert src.count("sum(") <= 2, "sum() used beyond field counting"
            continue
        assert banned not in src, banned


def test_it_never_reaches_into_session_state_or_the_network():
    """`.get(` is an ordinary mapping read, so the check is on the two things
    that would actually make this module impure: a session-state attribute, and
    any network client at all."""
    tree = ast.parse(pathlib.Path(TC.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "session_state"
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "urllib", "socket",
                            "supabase", "streamlit"})


def test_values_are_transported_unchanged():
    ctx = _ctx()
    assert ctx.value("opportunity.opportunity_score") == 61.5
    assert ctx.value("market.market_state") == "TREND"
    assert ctx.value("htf.alignment") == 78
    assert dict(ctx.value("energy.energy")) == {"CALL": 78, "PUT": 22}


# ══════════════════════════════════════════════════════════════════════
#  4 · immutable after creation
# ══════════════════════════════════════════════════════════════════════

def test_the_context_itself_cannot_be_reassigned():
    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.market = {}


def test_a_field_cannot_be_edited():
    f = _ctx().get("market.stability")
    with pytest.raises(Exception):
        f.value = "SHOCK"


def test_a_group_cannot_be_written_to():
    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.market["stability"] = TC.Field("SHOCK")
    with pytest.raises(Exception):
        del ctx.market["stability"]


def test_nested_values_are_frozen_all_the_way_down():
    """Shallow immutability is a promise the object cannot keep: a frozen
    dataclass holding a plain dict lets one consumer edit what another is about
    to read."""
    ctx = _ctx()
    energy = ctx.value("energy.energy")
    with pytest.raises(Exception):
        energy["CALL"] = 0
    reasons = ctx.value("opportunity.top_reason")
    assert isinstance(reasons, str)      # scalar here
    struct = ctx.value("premium.premium_structure")
    with pytest.raises(Exception):
        struct["CALL"] = {}


def test_mutating_the_source_after_build_does_not_change_the_context():
    """Two stages reading one context in one cycle must see one set of values."""
    fr = _fr()
    ctx = TC.build(fr=fr)
    fr["stability"] = "SHOCK"
    assert ctx.value("market.stability") == "STABLE"


# ══════════════════════════════════════════════════════════════════════
#  5 · missing stays UNKNOWN
# ══════════════════════════════════════════════════════════════════════

def test_an_absent_root_yields_unknown_not_zero():
    ctx = TC.build(fr=_fr())          # no matrix, premium, validation
    assert ctx.value("opportunity.best_horizon") == TC.UNKNOWN
    assert ctx.value("energy.energy") == TC.UNKNOWN
    assert ctx.value("strike.validation") == TC.UNKNOWN
    for name in ("opportunity.best_horizon", "energy.energy"):
        assert ctx.get(name).value != 0
        assert ctx.get(name).value is not None


def test_a_missing_root_is_named_rather_than_guessed():
    ctx = TC.build(fr=_fr())
    assert set(ctx.meta["roots_missing"]) == set(TC.ROOTS) - {"fr"}
    assert ctx.meta["roots_supplied"] == ("fr",)


def test_a_none_value_reads_as_unknown_not_as_a_value():
    """Engines publish `None` deliberately; a context must not pass it on as
    though something were measured."""
    ctx = _ctx(fr=_fr(breakout_risk=None))
    assert not ctx.known("risk.risk")


def test_missing_and_coverage_report_the_thin_cycle():
    full, thin = _ctx(), TC.build(fr=_fr())
    assert full.coverage()["known"] > thin.coverage()["known"]
    assert "energy.energy" in thin.missing()
    assert "energy.energy" not in full.missing()


def test_an_unknown_field_name_returns_a_field_not_an_exception():
    got = _ctx().get("market.no_such_thing")
    assert isinstance(got, TC.Field)
    assert not got.known and "no such field" in got.note


def test_a_side_map_with_neither_side_reporting_is_unknown():
    """A field that is present but empty reads as measured."""
    ctx = _ctx(structure={})
    assert ctx.value("premium.premium_score") == TC.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  6 · serialisation
# ══════════════════════════════════════════════════════════════════════

def test_it_serialises_cleanly_with_provenance():
    blob = json.dumps(_ctx().to_dict())
    back = json.loads(blob)
    assert back["market"]["stability"]["value"] == "STABLE"
    assert back["market"]["stability"]["stage"] == "44"
    assert back["market"]["stability"]["source"] == "fr.stability"
    assert back["coverage"]["total"] == back["meta"]["fields"]


def test_values_only_drops_provenance_but_not_values():
    v = _ctx().values_only()
    assert json.dumps(v)
    assert v["market"]["stability"] == "STABLE"
    assert v["energy"]["energy"] == {"CALL": 78, "PUT": 22}


def test_serialisation_survives_an_empty_context():
    assert json.dumps(TC.build().to_dict())


def test_meta_carries_the_cycle_and_the_version():
    ctx = _ctx()
    assert ctx.meta["cycle"] == 7
    assert ctx.meta["version"] == TC.VERSION
    assert ctx.meta["timestamp"] > 0


# ══════════════════════════════════════════════════════════════════════
#  7 · the architectural standing, and what Stage 72 may read
# ══════════════════════════════════════════════════════════════════════

def test_it_is_not_an_engine():
    from mios_v5.engines import ALL_ENGINES
    names = {c().name for c in ALL_ENGINES} | {c.__name__ for c in ALL_ENGINES}
    assert not any("trading_context" in str(n).lower() for n in names)
    assert not any("context" == str(n).lower() for n in names)


def test_it_is_advisory_and_exposes_no_mutator():
    assert TC.ADVISORY_ONLY is True
    assert _ctx().advisory_only is True
    for name in dir(TC):
        if name.startswith("_"):
            continue
        assert not name.startswith(("apply", "deploy", "promote", "set_",
                                    "update_", "override"))


def test_stage_72_can_answer_every_question_from_the_context_alone():
    """The success criterion: a consumer needs no other object.

    If any of these is unreachable, Stage 72 would have to read a stage
    directly and the bridge has failed at the thing it exists for."""
    ctx = _ctx()
    needed = (
        "market.market_state", "market.day_type", "market.session",
        "market.trend", "market.transition", "market.stability",
        "opportunity.best_horizon", "opportunity.best_side",
        "opportunity.opportunity_score", "opportunity.confidence",
        "premium.preferred_premium", "premium.selected_call",
        "premium.selected_put", "premium.premium_score",
        "strike.selected_strike", "strike.validation", "strike.liquidity",
        "strike.agreement",
        "energy.energy", "energy.dominance", "energy.rotation",
        "energy.shift", "energy.energy_acceleration",
        "energy.spike_probability",
        "htf.htf_bias", "htf.alignment",
        "risk.risk", "risk.validity", "risk.freeze",
    )
    for name in needed:
        assert ctx.known(name), f"{name} unreachable — Stage 72 would have to " \
                                f"read a stage directly"


def test_the_context_is_the_only_argument_a_consumer_needs():
    """A consumer written against the context must not need the raw payloads —
    demonstrated by answering a full decision shape from `ctx` alone."""
    ctx = _ctx()

    def _consumer(context):
        return {
            "side": context.value("opportunity.best_side"),
            "strike": (context.value("premium.selected_call")
                       if context.value("opportunity.best_side") == "CALL"
                       else context.value("premium.selected_put")),
            "validated": context.value("strike.validation"),
            "blocked": context.value("risk.freeze"),
            "why": context.value("opportunity.top_reason"),
        }

    got = _consumer(ctx)
    assert got["side"] == "CALL" and got["strike"] == 24250.0
    assert dict(got["validated"])["CALL"] == "VALID"
    assert got["blocked"] is False
    assert got["why"] == "families agree"


def test_building_never_raises_on_junk():
    for junk in ({}, {"fr": "nonsense"}, {"matrix": []},
                 {"premium": {"bridge": "bad"}}, {"structure": 7}):
        ctx = TC.build(**junk)
        assert isinstance(ctx, TC.TradingContext)
        assert json.dumps(ctx.to_dict())
