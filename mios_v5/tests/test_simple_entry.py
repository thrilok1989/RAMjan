"""The simple entry system — five rules, all of which must hold.

Stage 72 produces a score; this produces a yes or a no and shows its working.
The tests are mostly about the *noes*: a gate that fires when one rule is
missing is worse than no gate, because it looks like the same signal.
"""

import ast
import pathlib

import pytest

from mios_v5 import simple_entry as SE

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "simple_entry.py"


def _mkt(**over):
    m = {"spot": 24455.0, "v5": "BULLISH", "v6": "BULLISH",
         "support": {"price": 24450, "break": 28, "bounce": 72, "trap": 15},
         "resistance": {"price": 24580, "break": 61, "bounce": 39, "trap": 44},
         "call": {"ltp": 182.4, "energy": 78, "behaviour": "Support Building"},
         "put": {"ltp": 96.2, "energy": 31, "behaviour": "Support Fading"}}
    m.update(over)
    return m


def _put_mkt(**over):
    """Spot at resistance, bearish, PUT carrying the energy and building on
    ITS OWN chart — a put premium rising as NIFTY falls."""
    m = {"spot": 24575.0, "v5": "BEARISH", "v6": "BEARISH",
         "support": {"price": 24450, "break": 61, "bounce": 39, "trap": 10},
         "resistance": {"price": 24580, "break": 30, "bounce": 70, "trap": 12},
         "call": {"ltp": 182.4, "energy": 24, "behaviour": "Support Fading"},
         "put": {"ltp": 96.2, "energy": 74, "behaviour": "Support Building"}}
    m.update(over)
    return m


# ══════════════════════════════════════════════════════════════════════
#  it fires when all five hold
# ══════════════════════════════════════════════════════════════════════

def test_a_call_fires_at_support():
    sig = SE.evaluate(_mkt())
    assert sig.fired is True and sig.side == SE.CALL
    assert sig.level == 24450 and sig.level_kind == "support"
    assert len(sig.passed) == 5 and not sig.failed


def test_a_put_fires_at_resistance():
    sig = SE.evaluate(_put_mkt())
    assert sig.fired is True and sig.side == SE.PUT
    assert sig.level_kind == "resistance"


def test_every_rule_carries_its_measurement():
    """"bounce beats break" is a claim; "72% vs 28%" is the evidence, and the
    evidence is what lets a trader disagree."""
    sig = SE.evaluate(_mkt())
    detail = {n: d for n, _ok, d in sig.rules}
    assert "5 pts away" in detail["spot at support"]
    assert "72% vs break 28%" in detail["bounce beats break"]
    assert "78 vs 31" in detail["CALL energy"]
    assert detail["CALL premium building"] == "Support Building"


# ══════════════════════════════════════════════════════════════════════
#  ⛔ each rule can block on its own
# ══════════════════════════════════════════════════════════════════════

def test_spot_too_far_from_the_level_blocks():
    assert not SE.evaluate(_mkt(spot=24350.0)).fired


def test_break_beating_bounce_blocks():
    m = _mkt(support={"price": 24450, "break": 71, "bounce": 29})
    sig = SE.evaluate(m)
    assert not sig.fired
    assert "bounce beats break" in sig.failed


def test_no_bias_agreeing_blocks():
    sig = SE.evaluate(_mkt(v5="BEARISH", v6="NEUTRAL"))
    assert not sig.fired and "bias aligned" in sig.failed


def test_either_bias_is_enough():
    """The owner asked for V5 OR V6. Requiring both would make a two-engine
    disagreement a veto, when the point of showing them is that it is
    information."""
    assert SE.evaluate(_mkt(v6="NEUTRAL")).fired
    assert SE.evaluate(_mkt(v5="NEUTRAL")).fired


def test_weak_energy_blocks():
    m = _mkt(call={"energy": 40, "behaviour": "Support Building"})
    assert not SE.evaluate(m).fired


def test_energy_that_does_not_lead_blocks():
    """Two premiums with equal energy is not a directional read."""
    m = _mkt(call={"energy": 60, "behaviour": "Support Building"},
             put={"energy": 58, "behaviour": "Support Fading"})
    sig = SE.evaluate(m)
    assert not sig.fired and "CALL energy" in sig.failed


def test_a_premium_not_building_blocks():
    m = _mkt(call={"energy": 78, "behaviour": "Support Fading"})
    sig = SE.evaluate(m)
    assert not sig.fired and "CALL premium building" in sig.failed


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ the leg-direction trap
# ══════════════════════════════════════════════════════════════════════

def test_building_is_the_same_word_on_both_legs():
    """Every leg engine reports in the LEG's own direction: a PUT premium
    rising as NIFTY falls is that premium moving up off ITS OWN support. So a
    PUT buy is confirmed by `Support Building`, never `Resistance Building` —
    reading the spot direction into the leg's label is the mistake."""
    assert "Support Building" in SE.GOOD_BEHAVIOUR
    assert "Resistance Building" not in SE.GOOD_BEHAVIOUR
    assert SE.evaluate(_put_mkt()).fired
    wrong = SE.evaluate(_put_mkt(
        put={"energy": 74, "behaviour": "Resistance Building"}))
    assert not wrong.fired


# ══════════════════════════════════════════════════════════════════════
#  absent is not zero
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("missing", [
    {"spot": None}, {"support": {}},
    {"support": {"price": 24450}},                       # no odds
    {"call": {"energy": None, "behaviour": "Support Building"}},
    {"call": {"energy": 78}},                            # no behaviour
])
def test_a_missing_input_fails_its_rule_rather_than_passing(missing):
    """A missing energy is not zero energy, and neither is a reason to trade."""
    assert not SE.evaluate(_mkt(**missing)).fired


def test_nothing_at_all():
    for junk in (None, {}, {"spot": "x"}):
        sig = SE.run(junk)
        assert sig.fired is False and sig.side == SE.NONE


def test_it_never_raises():
    for junk in ("a string", 42, [], {"support": "x", "call": 3}):
        assert SE.run(junk if isinstance(junk, dict) else {}).fired is False


# ══════════════════════════════════════════════════════════════════════
#  a near miss explains itself
# ══════════════════════════════════════════════════════════════════════

def test_a_signal_that_did_not_fire_names_the_rule_that_missed():
    """The thing a score can never do."""
    sig = SE.evaluate(_mkt(v5="BEARISH", v6="BEARISH"))
    assert not sig.fired
    assert "bias aligned" in sig.why or "bias aligned" in sig.failed
    assert sig.rules, "a near miss must still list its rules"


def test_the_closest_side_is_reported_when_neither_fires():
    sig = SE.evaluate(_mkt(spot=24000.0))
    assert sig.side == SE.NONE
    assert "closest was" in sig.why


# ══════════════════════════════════════════════════════════════════════
#  trap warns, it does not block
# ══════════════════════════════════════════════════════════════════════

def test_a_high_trap_warns_without_blocking():
    """The owner's rules do not include trap. Silently adding a sixth gate
    would make a signal fail for a reason nobody asked for."""
    m = _mkt(support={"price": 24450, "break": 28, "bounce": 72, "trap": 55})
    sig = SE.evaluate(m)
    assert sig.fired is True
    assert any("trap" in w for w in sig.warnings)


def test_a_low_trap_says_nothing():
    assert not SE.evaluate(_mkt()).warnings


# ══════════════════════════════════════════════════════════════════════
#  it computes nothing, and it runs
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_engine_and_no_io():
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "streamlit", "pandas", "numpy",
                            "entry_engine", "dispatcher", "db"})


def test_the_verdict_is_frozen():
    sig = SE.evaluate(_mkt())
    with pytest.raises(Exception):
        sig.fired = False


def test_it_has_a_caller_and_its_own_switch():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "run_simple_entry()" in src
    assert "SIMPLE_ENTRY_DEFAULT" in src
    assert "_simple_entry_on" in src


def test_it_runs_after_the_dashboard_publishes_its_inputs():
    """It reads `_sr_levels` and `_premium_structures`, which the dashboard
    render publishes. Running first would evaluate five rules against last
    cycle's data."""
    # Line numbers of the CALLS, from the AST. `src.index("run_simple_entry()")`
    # matched the `def run_simple_entry():` line, which sits thousands of lines
    # ABOVE the render — so the text version compared the definition, not the
    # call, and failed on correct code.
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    calls = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", "") or getattr(n.func, "attr", "")
            if name in ("run_simple_entry", "render_dashboard_v6"):
                calls.setdefault(name, n.lineno)
    assert "run_simple_entry" in calls, "the runner is never called"
    assert calls["render_dashboard_v6"] < calls["run_simple_entry"]


def test_it_does_not_borrow_stage_72_9s_claim_protocol():
    """That dispatcher claims on an EntryDecision hash, and this produces no
    decision. Feeding it one would mean minting a fake decision to satisfy a
    claim protocol."""
    # AST again: the function's DOCSTRING explains why it does not use the
    # dispatcher, so a text scan for "dispatcher" matched the prose describing
    # the rule and failed on code that obeys it.
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "run_simple_entry")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not (called & {"reserve", "confirm", "release", "run_dispatch"})
    imported = {(n.module or "") for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom)}
    assert not any("dispatcher" in m for m in imported)
    # …and it carries its own, narrower guard
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_simple_entry_key" in literals
