"""Stage 71.85 — Premium LTP Behaviour.

The ten properties the specification asks these tests to prove, in order:

1. it imports no producer engine
2. it never recalculates a Stage 71.8 output
3. exactly one behaviour state is emitted
4. at most five reasons
5. no recommendation vocabulary appears
6. `TradingContext` transports every new field
7. Stage 72 still consumes only the context
8. the Telegram payload carries the new fields
9. the behaviour can be reconstructed from the consumed inputs alone
10. every consumed field names exactly one owner

Numbers 1, 2, 5 and 7 are **guards**, and they read the parse tree rather than
the text. Five tests in this stack have failed because a module explained a rule
in prose using the words a grep forbids; a guard that cannot tell a docstring
from an implementation teaches people to delete the docstring.
"""

import ast
import pathlib
import re

import pytest

from mios_v5 import decision as DEC
from mios_v5 import dispatcher as DP
from mios_v5 import entry_engine as EE
from mios_v5 import premium_behaviour as PB
from mios_v5 import trading_context as TC


def _code_only(module) -> str:
    """The module's executable source, every docstring removed."""
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


# ── fixtures ────────────────────────────────────────────────────────────

def _structure(**over):
    """Stage 71.8's shape for one leg, defended at its support."""
    st = {
        "ltp": 100.0, "support": 97.0, "resistance": 130.0,
        "levels": {"state": "REJECTING", "support": 97.0, "resistance": 130.0},
        "acceptance_read": {"state": "REJECTING"},
        "trend": "Up", "trend_read": {"trend": "Up", "momentum": 1.8},
        "flow": {"cbv": 68000.0, "csv": 32000.0, "cvd": 36000.0,
                 "buy_share": 68.0, "volume": 100000.0},
        "absorption": {"buyer": True, "seller": False,
                       "label": "buyer absorption"},
        "break_probability": 40.0, "fakeout_probability": 62.0,
        "hvn": [{"price": 97.2}], "lvn": [],
        "profile": {"vp_poc": 99.0, "vah": 105.0, "val": 95.0},
        "ignition": {"fired": False, "wyckoff": []},
        "rvol": 1.9, "volume_climax": {"climax": False},
        "structure_score": 71, "confidence": "HIGH",
    }
    st.update(over)
    return st


def _energy(**over):
    e = {"sides": {"CALL": {"energy": 78, "spike": 72,
                            "behaviour": {"state": "building",
                                          "label": "Building",
                                          "pressure": "absorbing",
                                          "pressure_label": "Absorbing"}},
                   "PUT": {"energy": 22, "spike": 20,
                           "behaviour": {"state": "distribution",
                                         "pressure": "weakening"}}},
         "shift": {"CALL": {"state": "Increasing", "accelerating": True,
                            "acceleration": 12.0},
                   "PUT": {"state": "Decreasing", "accelerating": False}},
         "rotation": {"rotation": "ROTATION", "label": "PUT → CALL"},
         "dominance": {"side": "CALL"}}
    e.update(over)
    return e


def _fr(**over):
    fr = {"stability": "STABLE", "spot": 24000.0,
          "reaction": {"state": "REJECTION"},
          "dealer_levels": {"gamma_flip": 24300.0},
          "charm_pin": {"active": False}}
    fr.update(over)
    return fr


def _validation():
    return {"sides": {"CALL": {"checks": {"premium_sr_strength": 82}},
                      "PUT": {"checks": {"premium_sr_strength": 40}}}}


def _run(structure=None, energy=None, fr=None, side="CALL"):
    return PB.analyse(_structure() if structure is None else structure,
                      _energy() if energy is None else energy,
                      _fr() if fr is None else fr,
                      side, _validation())


# ══════════════════════════════════════════════════════════════════════
#  1 · it imports no producer engine
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_only_the_grade_it_is_told_to_reuse():
    """The one local import is `decision._grade`, and the specification names
    it: *no second grading system*."""
    tree = ast.parse(pathlib.Path(PB.__file__).read_text())
    local = {node.module for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.level}
    assert local == {"decision"}, local


def test_it_imports_no_producer_no_app_and_no_network():
    tree = ast.parse(pathlib.Path(PB.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"numpy", "pandas", "indicators", "streamlit", "requests",
              "vob_minimal", "db", "supabase", "premium_structure",
              "premium_energy", "strike_validation", "ltp_behaviour"}
    assert not (imported & banned), imported & banned


def test_the_grade_is_stage_zero_s_and_not_a_copy_of_it():
    """`_grade` is imported, so the two ladders cannot drift apart. If someone
    reimplements it here this test is the thing that notices."""
    assert PB._grade is DEC._grade
    for avg, want in ((4.9, "A+"), (4.0, "A"), (3.2, "B"), (1.0, "C")):
        assert PB._grade(avg) == want


# ══════════════════════════════════════════════════════════════════════
#  2 · it never recalculates a Stage 71.8 output
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("owned", ["break_probability", "fakeout_probability",
                                   "structure_score", "rvol", "hvn", "lvn",
                                   "volume_climax", "support", "resistance"])
def test_it_defines_no_producer_for_anything_stage_71_8_owns(owned):
    """A function whose *name* claims one of Stage 71.8's facts would be a
    second owner however carefully it was written."""
    tree = ast.parse(pathlib.Path(PB.__file__).read_text())
    defined = {n.name.lstrip("_") for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    assert owned not in defined, f"{owned} has a producer here"


def test_the_probabilities_are_passed_through_byte_for_byte():
    st = _structure(break_probability=83.0, fakeout_probability=17.0)
    out = _run(structure=st)
    assert out["break_probability"] == 83.0
    assert out["fakeout_probability"] == 17.0


def test_changing_a_stage_71_8_number_changes_only_the_read_of_it():
    """The passthrough is a passthrough: 71.8's numbers arrive unaltered even
    when this stage's own verdict changes around them."""
    a = _run(structure=_structure(structure_score=12))
    b = _run(structure=_structure(structure_score=99))
    assert a["structure_strength"] == b["structure_strength"] == 82  # 71.8's


def test_the_only_things_it_claims_to_compute_are_the_five():
    assert PB.COMPUTED_HERE == ("behaviour", "strength", "confidence",
                                "momentum", "top_reasons")


# ══════════════════════════════════════════════════════════════════════
#  3 · exactly one behaviour state
# ══════════════════════════════════════════════════════════════════════

def test_there_are_exactly_six_states_and_five_momentum_words():
    assert len(PB.BEHAVIOUR_STATES) == 6 == len(set(PB.BEHAVIOUR_STATES))
    assert len(PB.MOMENTUM_STATES) == 5 == len(set(PB.MOMENTUM_STATES))
    assert len(PB.STRENGTH_BANDS) == 5


@pytest.mark.parametrize("case", [
    {},                                                     # the healthy read
    {"structure": {}},                                      # no structure
    {"energy": {}},                                         # no energy
    {"fr": {}},                                             # no market
    {"structure": {}, "energy": {}, "fr": {}},              # nothing at all
    {"structure": _structure(ltp=None)},                    # no premium price
    {"structure": _structure(ltp=100.0, support=10.0, resistance=900.0)},
])
def test_one_behaviour_always_and_it_is_one_of_the_six(case):
    out = _run(**case)
    assert out["behaviour"] in PB.BEHAVIOUR_STATES
    assert isinstance(out["behaviour"], str)
    assert out["momentum"] in PB.MOMENTUM_STATES + (PB.UNKNOWN,)
    assert out["strength"] in PB.STRENGTH_BANDS + (PB.UNKNOWN,)
    assert out["confidence"] in PB.CONFIDENCE_GRADES


def test_it_never_raises_whatever_arrives():
    for junk in (None, "", 0, [], "a string where a dict belongs", {"a": None}):
        out = PB.analyse(junk, junk, junk, "CALL", junk)
        assert out["behaviour"] in PB.BEHAVIOUR_STATES


def test_the_engaged_level_names_the_behaviour():
    """The whole design in one test: the same pressure, at the two levels, is
    two different behaviours — and never a blend of them."""
    at_support = _run(structure=_structure(ltp=100.0, support=98.0,
                                           resistance=180.0))
    at_resistance = _run(structure=_structure(ltp=100.0, support=40.0,
                                              resistance=102.0))
    assert at_support["engagement"]["kind"] == "support"
    assert at_resistance["engagement"]["kind"] == "resistance"
    assert at_support["behaviour"] == PB.SUPPORT_BUILDING
    assert at_resistance["behaviour"] == PB.RESISTANCE_FADING


def test_acceptance_only_when_no_level_is_engaged():
    """The specification's rule, stated as a rule: `Acceptance` requires the
    absence of a fight, not merely evidence that price is accepted."""
    away = _structure(ltp=100.0, support=40.0, resistance=180.0,
                      profile={"vah": 90.0, "val": 80.0})
    out = _run(structure=away)
    assert out["engagement"]["kind"] is None
    assert out["behaviour"] == PB.ACCEPTANCE
    assert out["acceptance"] == "Accepted Above VAH"

    engaged = _run(structure=_structure(ltp=100.0, support=98.0,
                                        resistance=180.0,
                                        profile={"vah": 90.0, "val": 80.0}))
    assert engaged["behaviour"] != PB.ACCEPTANCE


def test_neutral_only_when_the_evidence_is_insufficient():
    out = _run(structure={}, energy={}, fr={})
    assert out["behaviour"] == PB.NEUTRAL
    assert out["evidence"]["reporting"] < PB._MIN_EVIDENCE


def test_neutral_is_never_graded():
    """Five stars and an A+ on "not enough evidence to say" would be the
    opposite of what the words mean."""
    out = _run(structure={}, energy={}, fr={})
    assert out["behaviour"] == PB.NEUTRAL
    assert out["strength"] == PB.UNKNOWN
    assert out["confidence"] == PB.UNKNOWN


def test_a_tie_at_the_level_is_neutral_rather_than_a_coin_toss():
    out = PB._behaviour({"kind": "support"}, 3.0, 3.0, 6, None)
    assert out["behaviour"] == PB.NEUTRAL


# ══════════════════════════════════════════════════════════════════════
#  4 · at most five reasons, and never a plain string
# ══════════════════════════════════════════════════════════════════════

def test_at_most_five_reasons_however_much_reported():
    out = _run()
    assert len(out["evidence"]["all"]) > 5, "the fixture must overflow the cap"
    assert len(out["top_reasons"]) == 5


@pytest.mark.parametrize("case", [{}, {"structure": {}}, {"energy": {}},
                                  {"structure": {}, "energy": {}, "fr": {}}])
def test_every_reason_is_structured_and_names_its_owner(case):
    for r in _run(**case)["top_reasons"]:
        assert set(r) == {"code", "label", "owner", "weight", "source",
                          "direction"}
        assert isinstance(r["code"], str) and r["code"]
        assert isinstance(r["label"], str) and r["label"]
        assert isinstance(r["weight"], float) and 0.0 < r["weight"] <= 1.0
        assert r["owner"].startswith("Stage "), r["owner"]
        assert r["source"] in PB.CONSUMED


def test_the_reasons_are_ranked_and_the_winning_side_leads():
    out = _run()
    agreeing = [r for r in out["top_reasons"] if r["direction"] == PB.UP]
    assert agreeing, "the fixture is one-sided UP"
    weights = [r["weight"] for r in agreeing]
    assert weights == sorted(weights, reverse=True)


def test_the_top_reason_is_the_strongest_one():
    out = _run()
    strongest = max(out["evidence"]["all"], key=lambda r: r["weight"])
    assert out["top_reasons"][0]["weight"] == strongest["weight"]


# ══════════════════════════════════════════════════════════════════════
#  5 · no recommendation vocabulary
# ══════════════════════════════════════════════════════════════════════

_FORBIDDEN = ("BUY", "SELL", "ENTER", "EXIT", "LONG", "SHORT", "ENTRY")


@pytest.mark.parametrize("word", _FORBIDDEN)
def test_the_code_contains_no_recommendation_vocabulary(word):
    """Whole words, on the parse tree. `BUYER_ABSORPTION` is Stage 43's name for
    a measurement and must survive; a bare `BUY` must not."""
    code = _code_only(PB)
    hits = re.findall(rf"\b{word}\b", code)
    assert not hits, f"{word} appears {len(hits)}× in Stage 71.85's code"


def test_no_output_value_reads_as_a_recommendation():
    for case in ({}, {"structure": {}}, {"energy": {}}):
        out = _run(**case)
        printed = " ".join(str(v) for k, v in out.items()
                           if k not in ("consumed", "computed_here"))
        for word in _FORBIDDEN:
            assert not re.search(rf"\b{word}\b", printed.upper()), word


def test_it_defines_nothing_that_decides_or_selects():
    tree = ast.parse(pathlib.Path(PB.__file__).read_text())
    names = {n.name.lstrip("_").lower() for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    for banned in ("decide", "decision", "recommend", "signal", "select",
                   "trade", "order", "position", "dispatch", "send"):
        assert not any(banned in n for n in names), banned


# ══════════════════════════════════════════════════════════════════════
#  6 · the context transports every new field
# ══════════════════════════════════════════════════════════════════════

_NEW_FIELDS = ("behaviour", "behaviour_strength", "behaviour_confidence",
               "momentum", "break_probability", "fakeout_probability",
               "acceptance", "top_reason", "structure_state",
               "structure_strength")


def _ctx():
    beh = PB.build({"CALL": _structure(), "PUT": _structure(ltp=40.0)},
                   _energy(), _fr(), _validation())
    return TC.build(fr=_fr(), premium=_energy(), validation=_validation(),
                    structure={"CALL": _structure(), "PUT": _structure(ltp=40.0)},
                    behaviour=beh, cycle=3)


@pytest.mark.parametrize("name", _NEW_FIELDS)
def test_the_context_carries_the_field_with_its_owner(name):
    f = _ctx().get(f"premium.{name}")
    assert f.known, f"premium.{name} did not reach the context"
    assert f.stage in ("71.8", "71.85")
    assert f.source.split(".")[0] in TC.ROOTS


def test_the_four_computed_fields_name_stage_71_85_and_the_rest_do_not():
    """A field this stage did not measure must not name it as owner. `71.85`
    transporting Stage 71.8's break probability would give that number two
    owners, which is the failure the bridge exists to prevent."""
    ctx = _ctx()
    computed = {"behaviour", "behaviour_strength", "behaviour_confidence",
                "momentum", "top_reason", "acceptance"}
    for name in _NEW_FIELDS:
        stage = ctx.get(f"premium.{name}").stage
        assert stage == ("71.85" if name in computed else "71.8"), name


def test_the_context_still_transports_and_never_computes():
    """The values in the context are the values the stage published — the
    bridge did not round, rescale or reinterpret one of them."""
    beh = PB.build({"CALL": _structure()}, _energy(), _fr(), _validation())
    ctx = TC.build(fr=_fr(), premium=_energy(), validation=_validation(),
                   structure={"CALL": _structure()}, behaviour=beh)
    assert ctx.get("premium.behaviour").value["CALL"] == beh["CALL"]["behaviour"]
    assert ctx.get("premium.momentum").value["CALL"] == beh["CALL"]["momentum"]
    assert (ctx.get("premium.top_reason").value["CALL"]
            == beh["CALL"]["top_reasons"][0]["label"])


def test_no_two_context_fields_read_the_same_path():
    """Stage 71.95's binding rule, re-checked after ten fields were added."""
    seen = {}
    for row in TC.spec_rows():
        assert row["source"] not in seen, (row["field"], seen[row["source"]])
        seen[row["source"]] = row["field"]


def test_a_context_built_without_stage_71_85_says_so():
    ctx = TC.build(fr=_fr(), structure={"CALL": _structure()})
    assert "behaviour" in ctx.meta["roots_missing"]
    assert not ctx.get("premium.behaviour").known
    # the fields 71.8 owns still arrive — one absent producer is not a blackout
    assert ctx.get("premium.break_probability").known


# ══════════════════════════════════════════════════════════════════════
#  7 · Stage 72 still consumes only the context
# ══════════════════════════════════════════════════════════════════════

def test_stage_72_did_not_gain_an_import():
    tree = ast.parse(pathlib.Path(EE.__file__).read_text())
    local = {n.module for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"decision_v2", "trading_context"}, local


def test_stage_72_reads_behaviour_through_the_bridge_only():
    """Every value in the decision's behaviour block came from `self._v`, which
    is a context read. Stage 72 cannot reach Stage 71.85 directly."""
    src = ast.parse(pathlib.Path(EE.__file__).read_text())
    fn = next(n for n in ast.walk(src)
              if isinstance(n, ast.FunctionDef) and n.name == "behaviour")
    reads = {a.value for n in ast.walk(fn) if isinstance(n, ast.Call)
             for a in n.args if isinstance(a, ast.Constant)
             and isinstance(a.value, str) and a.value.startswith("premium.")}
    assert len(reads) == 10, reads
    assert all(r.split(".", 1)[1] in _NEW_FIELDS for r in reads)


def test_the_new_component_is_one_more_weight_and_nothing_else():
    """*Do NOT modify Stage72 scoring philosophy. Simply add one more
    evaluation component.* — same weighted mean, same denominator rule."""
    assert "premium.behaviour" in EE.WEIGHTS
    assert len(EE.WEIGHTS) == 11
    assert len(set(EE.WEIGHTS)) == 11, "a weight would be read twice"
    assert EE.WEIGHTS["premium.premium_score"] == 1.5, "71.8's weight unchanged"


def test_behaviour_can_raise_lower_or_leave_the_entry_score():
    """The specification's three permitted effects — and never a fourth."""
    def _score(word):
        beh = {"CALL": {"behaviour": word, "strength": "★★★★☆",
                        "confidence": "A", "momentum": "Building",
                        "acceptance": "Inside Value", "top_reasons": ()}}
        ctx = TC.build(fr=_fr(), premium=_energy(), validation=_validation(),
                       structure={"CALL": _structure()}, behaviour=beh)
        return EE.EntryEngine(ctx).score("CALL")

    good, bad = _score(PB.SUPPORT_BUILDING), _score(PB.SUPPORT_FADING)
    assert good["score"] > bad["score"], "behaviour must be able to lower it"
    assert "premium.behaviour" in good["components"]

    neutral = _score(PB.NEUTRAL)
    assert "premium.behaviour" not in neutral["components"]
    assert neutral["reporting"] == good["reporting"] - 1, (
        "Neutral must leave the denominator, not score fifty")


def test_stage_72_never_generates_an_entry_from_behaviour_alone():
    """Behaviour enriches; it does not decide. With everything else absent, a
    perfect behaviour cannot produce an entry."""
    beh = {"CALL": {"behaviour": PB.SUPPORT_BUILDING, "strength": "★★★★★",
                    "confidence": "A+", "momentum": "Accelerating",
                    "acceptance": "Accepted Above VAH", "top_reasons": ()}}
    d = EE.EntryEngine(TC.build(behaviour=beh)).run()
    assert d.state == "WAIT"


# ══════════════════════════════════════════════════════════════════════
#  8 · the Telegram payload carries the new fields
# ══════════════════════════════════════════════════════════════════════

_PAYLOAD_FIELDS = ("behaviour", "behaviour_strength", "momentum",
                   "break_probability", "fakeout_probability",
                   "premium_acceptance", "top_behaviour_reason")


def _decision():
    beh = PB.build({"CALL": _structure()}, _energy(), _fr(), _validation())
    ctx = TC.build(fr=_fr(), premium=_energy(), validation=_validation(),
                   structure={"CALL": _structure()}, behaviour=beh, cycle=3)
    return EE.EntryEngine(ctx).run()


@pytest.mark.parametrize("key", _PAYLOAD_FIELDS)
def test_the_payload_carries_the_field(key):
    assert key in _decision().telegram


def test_the_payload_reports_what_the_decision_carries():
    """A message cannot contain a behaviour the decision did not make."""
    d = _decision()
    assert d.telegram["behaviour"] == d.behaviour["behaviour"]
    assert d.telegram["behaviour_strength"] == d.behaviour["strength"]
    assert d.telegram["top_behaviour_reason"] == d.behaviour["top_reason"]


def test_the_dispatcher_carries_them_through_untouched():
    d = _decision()
    payload = DP.Dispatcher(d, now="2026-01-01T00:00:00Z").payload()
    for key in _PAYLOAD_FIELDS:
        assert payload[key] == d.telegram[key]


def test_the_dispatcher_accepts_both_contract_versions():
    """72.0 was frozen and stays replayable; 72.1 is the amendment."""
    assert DP.SUPPORTED_DECISION_VERSIONS == ("72.0", "72.1")
    assert EE.VERSION in DP.SUPPORTED_DECISION_VERSIONS


def test_the_dispatcher_gained_no_behaviour_logic():
    """*No Telegram logic changes. Only payload extension.* — the dispatcher
    must not branch on a behaviour word anywhere in its code."""
    code = _code_only(DP)
    for word in PB.BEHAVIOUR_STATES + PB.MOMENTUM_STATES:
        assert word not in code, f"the dispatcher reads {word!r}"


# ══════════════════════════════════════════════════════════════════════
#  9 · reconstructable from the consumed inputs alone
# ══════════════════════════════════════════════════════════════════════

def test_the_same_inputs_always_give_the_same_behaviour():
    """No clock, no counter, no state. Ten runs, one answer."""
    first = _run()
    for _ in range(10):
        again = _run()
        assert again["behaviour"] == first["behaviour"]
        assert again["strength"] == first["strength"]
        assert again["confidence"] == first["confidence"]
        assert again["momentum"] == first["momentum"]
        assert again["evidence"]["all"] == first["evidence"]["all"]


def test_every_reason_can_be_traced_back_to_an_input_that_reported():
    """The reconstruction test: remove the input a reason names, and the reason
    goes with it."""
    out = _run()
    codes = {r["code"] for r in out["evidence"]["all"]}
    assert "BUYER_ABSORPTION" in codes
    without = _run(structure=_structure(absorption={}))
    assert "BUYER_ABSORPTION" not in {r["code"]
                                      for r in without["evidence"]["all"]}


def test_the_verdict_is_the_ledger_and_nothing_else():
    out = _run()
    up = sum(r["weight"] for r in out["evidence"]["all"]
             if r["direction"] == PB.UP)
    down = sum(r["weight"] for r in out["evidence"]["all"]
               if r["direction"] == PB.DOWN)
    assert round(up, 2) == out["evidence"]["up"]
    assert round(down, 2) == out["evidence"]["down"]
    assert out["evidence"]["share"] == round(max(up, down) / (up + down), 3)


def test_it_analyses_one_premium_and_never_compares_the_two():
    """*Never subtract CALL from PUT.* The two sides are computed by separate
    calls that share nothing, so changing one cannot move the other."""
    both = PB.build({"CALL": _structure(), "PUT": _structure(ltp=40.0)},
                    _energy(), _fr(), _validation())
    changed = PB.build({"CALL": _structure(), "PUT": _structure(
        ltp=40.0, absorption={"seller": True}, break_probability=95.0)},
        _energy(), _fr(), _validation())
    assert changed["CALL"] == both["CALL"], "the PUT moved the CALL"


def test_analyse_never_sees_the_other_side():
    """Structural, not behavioural: `analyse` takes one structure, so there is
    no other side in scope to compare against."""
    sig = ast.parse(pathlib.Path(PB.__file__).read_text())
    fn = next(n for n in ast.walk(sig)
              if isinstance(n, ast.FunctionDef) and n.name == "analyse")
    assert [a.arg for a in fn.args.args] == ["structure", "energy", "fr",
                                             "side", "validation"]


def test_the_output_publishes_how_it_was_reached():
    out = _run()
    assert out["why"] and out["confidence_why"] and out["momentum_why"]
    assert out["engagement"]["why"]
    assert out["consumed"] == PB.CONSUMED


# ══════════════════════════════════════════════════════════════════════
#  10 · every consumed field has exactly one owner
# ══════════════════════════════════════════════════════════════════════

def test_every_consumed_field_names_a_stage():
    for name, owner in PB.CONSUMED.items():
        assert owner.startswith("Stage "), (name, owner)
        assert " — " in owner, (name, owner)


def test_no_consumed_field_is_claimed_by_this_stage():
    assert not set(PB.CONSUMED) & set(PB.COMPUTED_HERE)


def test_flow_and_volume_are_read_from_stage_71_8_not_71_7():
    """The audit's correction (§1). The specification lists CBV/CSV/CVD, RVOL
    and Volume under Stage 71.7; `premium_structure` owns the numeric totals and
    71.7 publishes no RVOL at all. Reading flow from one stage and volume from
    another would give one leg's tape two owners."""
    for name in ("cbv", "csv", "cvd", "volume", "rvol"):
        assert "71.8" in PB.CONSUMED[name], (name, PB.CONSUMED[name])


def test_the_value_area_is_the_premium_s_own():
    """The audit's §3. Stage 45's VAH/VAL are NIFTY's; a CALL accepted above
    its own value area is a different fact, and it is the one a holder needs."""
    assert "71.8" in PB.CONSUMED["premium_value_area"]
    out = _run(structure=_structure(ltp=100.0, profile={"vah": 90.0,
                                                        "val": 80.0}))
    assert out["acceptance"] == "Accepted Above VAH"


def test_a_reason_can_never_name_an_owner_the_registry_does_not_have():
    """`_vote` reads the owner out of `CONSUMED` rather than taking one, so a
    signal added without registering its owner reports UNKNOWN loudly instead of
    inventing a stage."""
    unregistered = []
    PB._vote(unregistered, PB.UP, 0.5, "X", "x", "not_a_registered_input")
    assert unregistered[0].owner == PB.UNKNOWN


def test_the_audit_exists_and_records_the_ownership_corrections():
    doc = (pathlib.Path(PB.__file__).parent.parent
           / "docs" / "AUDIT_STAGE_71_85_PREMIUM_BEHAVIOUR.md")
    assert doc.exists()
    text = doc.read_text()
    for marker in ("EXISTS", "COMPUTED", "MISSING", "71.85"):
        assert marker in text


# ══════════════════════════════════════════════════════════════════════
#  the stage's own arithmetic
# ══════════════════════════════════════════════════════════════════════

def test_engagement_picks_the_nearer_level():
    eng = PB.engagement({"ltp": 100.0, "support": 98.0, "resistance": 101.0})
    assert eng["kind"] == "resistance" and eng["distance_pct"] == 1.0


def test_no_level_within_the_band_is_no_battle():
    eng = PB.engagement({"ltp": 100.0, "support": 50.0, "resistance": 200.0})
    assert eng["kind"] is None and "no active battle" in eng["why"]


def test_a_missing_premium_price_cannot_engage_anything():
    eng = PB.engagement({"support": 98.0, "resistance": 101.0})
    assert eng["kind"] is None and "no premium LTP" in eng["why"]


@pytest.mark.parametrize("share,stars", [(1.0, "★★★★★"), (0.80, "★★★★☆"),
                                         (0.65, "★★★☆☆"), (0.56, "★★☆☆☆"),
                                         (0.51, "★☆☆☆☆")])
def test_strength_is_the_winner_s_share_of_the_evidence(share, stars):
    assert PB._strength(share) == stars


def test_strength_is_unknown_when_nothing_reported():
    assert PB._strength(None) == PB.UNKNOWN


def test_confidence_separates_agreement_from_coverage():
    """One-sided across two signals and one-sided across ten are not the same
    claim, and the grade must be able to tell them apart."""
    thin = PB._confidence(1.0, 2, "STABLE")
    thick = PB._confidence(1.0, 10, "STABLE")
    assert thin["score"] < thick["score"]
    assert PB.CONFIDENCE_GRADES.index(thin["confidence"]) >= \
        PB.CONFIDENCE_GRADES.index(thick["confidence"])


def test_stage_44_caps_confidence_and_says_so():
    calm = PB._confidence(1.0, 10, "STABLE")
    shock = PB._confidence(1.0, 10, "SHOCK")
    assert shock["score"] <= 2.0 < calm["score"]
    assert "SHOCK" in shock["why"]
    assert PB._confidence(1.0, 10, "UNSTABLE")["score"] < calm["score"]


@pytest.mark.parametrize("state,word", [
    ("Exploding", PB.ACCELERATING), ("Increasing", PB.BUILDING),
    ("Building", PB.BUILDING), ("Holding", PB.HOLDING),
    ("Compressing", PB.HOLDING), ("Distributing", PB.FADING),
    ("Decreasing", PB.FADING)])
def test_every_shift_state_maps_to_a_momentum_word(state, word):
    got = PB._momentum({"state": state}, {}, {})
    assert got["momentum"] == word


def test_acceleration_promotes_momentum():
    assert PB._momentum({"state": "Increasing", "accelerating": True},
                        {}, {})["momentum"] == PB.ACCELERATING


def test_exhaustion_outranks_everything():
    """A premium can read as accelerating on the shift and still be spent, and
    the spent reading is the one that costs money."""
    spent = PB._momentum({"state": "Exploding", "accelerating": True},
                         {}, {"behaviour": {"pressure": "exhausted"}})
    assert spent["momentum"] == PB.EXHAUSTING
    climax = PB._momentum({"state": "Exploding"},
                          {"volume_climax": {"climax": True, "why": "climax"}},
                          {})
    assert climax["momentum"] == PB.EXHAUSTING


def test_momentum_falls_back_to_vidya_and_then_to_unknown():
    assert PB._momentum({}, {"trend_read": {"momentum": 2.0}},
                        {})["momentum"] == PB.BUILDING
    assert PB._momentum({}, {"trend_read": {"momentum": -2.0}},
                        {})["momentum"] == PB.FADING
    assert PB._momentum({}, {}, {})["momentum"] == PB.UNKNOWN


def test_break_probability_means_the_opposite_at_the_two_levels():
    """The same number, opposite pressure — which is why it cannot be read
    without knowing which level is engaged."""
    at_sup, at_res = [], []
    st = _structure(break_probability=90.0, fakeout_probability=0.0)
    PB._level_votes(at_sup, st, {"kind": "support", "level": 97.0})
    PB._level_votes(at_res, st, {"kind": "resistance", "level": 130.0})
    brk_s = next(r for r in at_sup if r.code == "BREAK_PROBABILITY")
    brk_r = next(r for r in at_res if r.code == "BREAK_PROBABILITY")
    assert brk_s.direction == PB.DOWN and brk_r.direction == PB.UP


def test_a_level_that_is_not_engaged_produces_no_level_votes():
    votes = []
    PB._level_votes(votes, _structure(), {"kind": None})
    assert votes == []


def test_the_dealer_pin_reads_against_the_premium_whatever_the_level():
    """Stage 11 pins the index, and a pinned index is a premium that decays —
    so it cannot vote on where the premium's own support is."""
    votes = []
    PB._dealer_votes(votes, {"charm_pin": {"active": True}})
    assert votes and all(r.direction == PB.DOWN for r in votes)


def test_build_returns_both_sides_and_neither_leaks():
    out = PB.build({"CALL": _structure()}, _energy(), _fr(), _validation())
    assert set(out) == {"CALL", "PUT"}
    assert out["CALL"]["side"] == "CALL" and out["PUT"]["side"] == "PUT"
    assert out["PUT"]["behaviour"] in PB.BEHAVIOUR_STATES


def test_it_is_advisory_only():
    assert PB.ADVISORY_ONLY is True
    assert _run()["advisory_only"] is True


# ══════════════════════════════════════════════════════════════════════
#  Principle 12 — a value that moves a decision must be inspectable
# ══════════════════════════════════════════════════════════════════════

def test_the_app_runs_the_stage_and_hands_it_to_the_context():
    """The regression class this repo has already been bitten by: a reader kept
    while its writer was removed. If nobody calls Stage 71.85, the context
    carries UNKNOWN for a weight Stage 72 is scoring."""
    src = pathlib.Path(
        pathlib.Path(PB.__file__).parent / "ui" / "dashboard_v6.py").read_text()
    assert "premium_behaviour import build" in src
    assert "behaviour=_behaviour" in src, "the context never receives it"


def test_the_behaviour_has_a_panel_because_it_moves_the_score():
    """`premium.behaviour` is an eleventh weight in Stage 72 as of 72.1, so
    Principle 12 makes this panel mandatory rather than decorative."""
    from mios_v5.ui import premium_behaviour_panel as PANEL
    beh = PB.build({"CALL": _structure(), "PUT": _structure(ltp=40.0)},
                   _energy(), _fr(), _validation())
    html = PANEL.premium_behaviour_html(beh)
    assert beh["CALL"]["behaviour"] in html
    assert str(beh["CALL"]["strength"]) in html
    assert "Stage 71.85" in html


def test_the_panel_shows_the_evidence_against_the_verdict_too():
    """A 55/45 read must not render as a 100/0 one."""
    from mios_v5.ui import premium_behaviour_panel as PANEL
    assert PANEL._DIR_GLYPH[PB.UP] in PANEL._ledger_html(
        [{"direction": PB.UP, "weight": 0.9, "label": "x", "owner": "Stage 43"}])
    assert PANEL._DIR_GLYPH[PB.DOWN] in PANEL._ledger_html(
        [{"direction": PB.DOWN, "weight": 0.9, "label": "y", "owner": "Stage 43"}])


def test_the_panel_never_takes_the_tab_down():
    from mios_v5.ui import premium_behaviour_panel as PANEL
    for junk in (None, {}, {"CALL": "not a dict"}, {"CALL": {"ready": True}}):
        PANEL.premium_behaviour_html(junk)


def test_the_panel_computes_nothing():
    """Presentation only — it may not import a producer or define a classifier."""
    from mios_v5.ui import premium_behaviour_panel as PANEL
    tree = ast.parse(pathlib.Path(PANEL.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "indicators", "requests",
                            "streamlit", "premium_structure", "premium_energy"})
