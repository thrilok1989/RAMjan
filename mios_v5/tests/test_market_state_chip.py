"""🗺️ MARKET STATE on the header strip — the gate's verdict beside the regime.

Both facts were computed every cycle and shown only in the Market Picture panel,
far enough down the page that the frozen strip could advertise an S/R bounce while
the gate had already refused. These tests pin the wording, the silence rules (the
strip is permanent screen space) and the collection in `_chrome_extras`.
"""

from __future__ import annotations

import ast
import pathlib
from types import MappingProxyType

import pytest

from mios_v5.ui import market_state_chip as c

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "vob_minimal.py").read_text(encoding="utf-8")


def _gate(state):
    return {"state": state, "zone": None, "level": None}


def _mp(regime, state="CHOP_WAIT"):
    return {"regime": regime, "entry_gate": _gate(state)}


# ══════════════════════════════════════════════════════════════════════
#  the reading the user asked for
# ══════════════════════════════════════════════════════════════════════

def test_the_chip_the_user_asked_for():
    """`MARKET STATE / CHOP_WAIT / regime SIDEWAYS`, verbatim in substance."""
    line = c.micro(_gate("CHOP_WAIT"), _mp("SIDEWAYS"))
    assert "MARKET STATE" in line
    assert "CHOP_WAIT" in line
    assert "regime SIDEWAYS" in line


def test_both_words_are_shown_because_either_alone_loses_the_reading():
    """⚠️ The point of pairing them. Chop in a sideways tape is stand down; chop
    in an up tape is wait for the pullback. The state alone cannot tell them
    apart, and neither can the regime."""
    side = c.micro(_gate("CHOP_WAIT"), _mp("SIDEWAYS"))
    up = c.micro(_gate("CHOP_WAIT"), _mp("UP"))
    assert side != up
    assert "SIDEWAYS" in side and "UP" in up


@pytest.mark.parametrize("regime,arrow", [("UP", "↑"), ("DOWN", "↓"),
                                          ("SIDEWAYS", "→")])
def test_the_regime_carries_an_arrow(regime, arrow):
    assert arrow in c.micro(_gate("WAIT"), _mp(regime))


def test_an_unknown_regime_is_shown_without_an_arrow_rather_than_dropped():
    line = c.micro(_gate("WAIT"), {"regime": "TRANSITION"})
    assert "regime TRANSITION" in line and "↑" not in line


# ══════════════════════════════════════════════════════════════════════
#  every gate state the Market Picture can set
# ══════════════════════════════════════════════════════════════════════

def test_every_gate_state_in_the_app_is_worded():
    """⚠️ Read off `vob_minimal.py` itself, so a new gate state cannot ship with
    the chip printing a bare enum name. PINNED is excluded — `pin_chip` owns it.
    """
    found = set()
    for node in ast.walk(ast.parse(_SRC)):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "entry_gate"
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == "state"):
                v = node.value
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    found.add(v.value)
                elif isinstance(v, ast.BinOp) and isinstance(v.left, ast.Constant):
                    # `'ARMED_' + _side_word` — both sides are CALL or PUT
                    found |= {v.left.value + s for s in ("CALL", "PUT")}
    assert len(found) >= 6, f"only found {found} — the scan broke"

    worded = set(c.STAND_DOWN) | set(c.LIVE) | {c.PINNED}
    assert not (found - worded), f"unworded gate state(s): {found - worded}"
    # The CONFIRMED assignment is `entry_gate['state'] = _side_word`, a bare name
    # the scan above cannot resolve to a constant. Its two values are asserted
    # here so that path is covered rather than quietly skipped.
    assert {"CALL", "PUT"} <= set(c.LIVE)


@pytest.mark.parametrize("state", sorted(c.STAND_DOWN))
def test_a_stand_down_state_says_so_in_plain_words(state):
    line = c.micro(_gate(state), _mp("SIDEWAYS"))
    assert state in line and c.STAND_DOWN[state] in line
    assert not c.read(_gate(state))["live"]


@pytest.mark.parametrize("state", sorted(c.LIVE))
def test_a_live_state_says_so(state):
    assert c.read(_gate(state))["live"] is True
    assert c.LIVE[state] in c.micro(_gate(state), _mp("UP"))


def test_armed_is_not_confirmed():
    """Stage 72's whole confirmation step is the difference. Wording them the
    same would invite entering on the arm."""
    armed = c.micro(_gate("ARMED_CALL"), _mp("UP"))
    live = c.micro(_gate("CALL"), _mp("UP"))
    assert "awaiting confirmation" in armed
    assert "awaiting confirmation" not in live


def test_an_unrecognised_state_is_still_shown():
    """A state the gate invented and this module has not learned is exactly what
    a trader should see, not something to filter out silently."""
    line = c.micro(_gate("SOMETHING_NEW"), _mp("UP"))
    assert "SOMETHING_NEW" in line and "regime UP" in line


# ══════════════════════════════════════════════════════════════════════
#  when the chip must stay quiet
# ══════════════════════════════════════════════════════════════════════

def test_the_chip_is_silent_on_pinned_because_pin_chip_owns_it():
    """⚠️ `pin_chip` already carries PINNED, with the strike in it. A second chip
    repeating `MARKET STATE PINNED` spends permanently frozen header space to say
    the same thing twice."""
    from mios_v5.ui.pin_chip import micro as pin_micro

    gate = {"state": "PINNED", "level": 24600,
            "why": ["pinned at ₹24600 — no directional edge, WAIT"]}
    assert c.micro(gate, _mp("SIDEWAYS", "PINNED")) == ""
    assert pin_micro(gate) != "", "the pin chip must still be the one that speaks"


@pytest.mark.parametrize("gate", [None, {}, {"state": None}, {"state": ""},
                                  {"state": "   "}, "nope", 7, []])
def test_no_state_draws_no_chip(gate):
    """The strip is frozen at the top of every screen for the whole session. A
    `MARKET STATE —` row would cost that space permanently to report nothing."""
    assert c.micro(gate, _mp("UP")) == ""


def test_a_state_with_no_regime_still_reports_the_state():
    """The regime is the optional half. Withholding the gate's verdict because
    the regime is missing would hide the more actionable of the two."""
    for mp in (None, {}, {"regime": None}, "junk"):
        line = c.micro(_gate("CHOP_WAIT"), mp)
        assert "CHOP_WAIT" in line and "regime" not in line


# ══════════════════════════════════════════════════════════════════════
#  the shapes these dicts really arrive in
# ══════════════════════════════════════════════════════════════════════

def test_a_frozen_mapping_is_read_like_a_dict():
    """⚠️ `MappingProxyType` is not a `dict` subclass. `isinstance(x, dict)` has
    silently blanked a panel in this repo four times."""
    gate = MappingProxyType({"state": "CHOP_WAIT"})
    mp = MappingProxyType({"regime": "SIDEWAYS"})
    assert "CHOP_WAIT" in c.micro(gate, mp)
    assert "regime SIDEWAYS" in c.micro(gate, mp)


def test_the_state_is_normalised_before_it_is_matched():
    for spelling in ("chop_wait", " Chop_Wait ", "CHOP_WAIT"):
        assert c.STAND_DOWN["CHOP_WAIT"] in c.micro(_gate(spelling), _mp("UP"))


def test_read_reports_the_same_shape_whatever_it_is_given():
    keys = {"state", "regime", "phrase", "live"}
    for args in ((None, None), ({}, {}), (_gate("WAIT"), _mp("UP")),
                 ("junk", 7)):
        assert set(c.read(*args)) == keys


def test_the_module_decides_nothing():
    """No thresholds, no comparisons on numbers — it words two published facts.
    A `>` in here would be a second implementation of the gate."""
    src = pathlib.Path(c.__file__).read_text()
    tree = ast.parse(src)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                and any(isinstance(o, (ast.Gt, ast.GtE, ast.Lt, ast.LtE))
                        for o in n.ops)]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal"}


# ══════════════════════════════════════════════════════════════════════
#  the wiring — a chip nobody collects reaches no header
# ══════════════════════════════════════════════════════════════════════

def _func(name):
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in vob_minimal.py")


def test_chrome_extras_actually_collects_the_chip():
    """⚠️ The guard that matters. A whole layer shipped defined-and-never-called
    once already this session; asserted on the AST so a comment naming the module
    cannot satisfy it."""
    fn = _func("_chrome_extras")
    modules = {n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)}
    assert "mios_v5.ui.market_state_chip" in modules
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_ms_micro" in called, "imported but never called"


def test_the_state_chip_is_collected_after_the_pin_and_before_the_zones():
    """Order is meaning on this strip. The veto leads; the state answers "may I
    trade?"; only then do the chips that describe a directional contest appear."""
    body = _func("_chrome_extras").body

    def _at(module):
        hits = [i for i, node in enumerate(body) for n in ast.walk(node)
                if isinstance(n, ast.ImportFrom) and n.module == module]
        assert hits, f"{module} is not imported in _chrome_extras"
        return min(hits)

    assert (_at("mios_v5.ui.pin_chip")
            < _at("mios_v5.ui.market_state_chip")
            < _at("mios_v5.ui.zone_card"))


def test_the_gate_and_the_regime_come_from_one_read():
    """Both off the same `_market_picture` dict, so the chip cannot pair this
    cycle's gate with last cycle's regime."""
    fn = _func("_chrome_extras")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_ms_micro"):
            assert len(node.args) == 2, "the regime must be passed too"
            gate, mp = node.args
            assert isinstance(gate, ast.Call) and isinstance(mp, ast.Name)
            assert mp.id == gate.func.value.id, (
                "the gate and the regime must come from the same object")
            return
    raise AssertionError("_ms_micro is never called")
