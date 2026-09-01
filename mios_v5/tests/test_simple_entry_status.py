"""The simple entry system's status line.

`run_simple_entry` stored its verdict in `session_state` and **nothing read
it** — the record of why a signal did not fire was invisible to the trader it
was written for. That is the writer-without-a-reader pattern this codebase has
been bitten by three times, and this line is the reader.
"""

import ast
import pathlib

import pytest

from mios_v5.simple_entry import evaluate
from mios_v5.tests.test_simple_entry import _mkt
from mios_v5.ui import simple_entry_panel as P
from mios_v5.ui.theme import BULL, MICRO, WARN

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_a_firing_signal_says_what_to_buy_and_where():
    line = P.status_line(evaluate(_mkt()))
    assert "FIRING" in line and "BUY CALL" in line and "24,450" in line
    assert P.status_tone(evaluate(_mkt())) == BULL


def test_a_blocked_signal_names_the_rule_and_its_measurement():
    """The whole point: "why didn't it fire" answered without opening
    anything."""
    sig = evaluate(_mkt(call={"energy": 78, "behaviour": "Support Fading"}))
    line = P.status_line(sig)
    assert "blocked on CALL premium building" in line
    assert "Support Fading" in line
    assert "4/5" in line


def test_it_names_only_the_first_failure():
    """Rule order is deliberate — "price isn't at a level" is more useful than
    "and also the behaviour is wrong", which is true most of the day."""
    sig = evaluate(_mkt(spot=24000.0, v5="BEARISH", v6="BEARISH"))
    line = P.status_line(sig)
    assert line.count("blocked on") == 1


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ a near miss must mean something
# ══════════════════════════════════════════════════════════════════════

def test_four_of_five_is_amber_only_when_price_is_at_the_level():
    """Four rules passing while spot is 450 points away is not "almost" — the
    other four are measured against a level price is nowhere near, and amber
    every cycle is a colour nobody reads by Wednesday."""
    at_level = evaluate(_mkt(call={"energy": 78,
                                   "behaviour": "Support Fading"}))
    far_away = evaluate(_mkt(spot=24000.0))
    assert len(P._rules(far_away)) and sum(
        1 for _n, ok, _d in P._rules(far_away) if ok) >= P.NEAR_MISS
    assert P.status_tone(at_level) == WARN
    assert P.status_tone(far_away) == MICRO, (
        "distance from the level must not read as a near miss")


def test_standing_aside_is_quiet():
    assert P.status_tone(evaluate(_mkt(spot=24000.0))) == MICRO


# ══════════════════════════════════════════════════════════════════════
#  it never breaks the sidebar
# ══════════════════════════════════════════════════════════════════════

def test_before_the_first_cycle():
    assert "waiting" in P.status_line(None)


def test_an_empty_market_still_produces_a_line():
    from mios_v5.simple_entry import run
    line = P.status_line(run({}))
    assert line and "Simple entry" in line


def test_a_stored_signal_reads_like_a_live_one():
    """A replayed verdict is a dict; a live one is frozen."""
    sig = evaluate(_mkt())
    assert P.status_line(sig) == P.status_line(sig.to_dict())


def test_it_never_raises():
    for junk in (None, {}, "a string", 42, [], {"rules": None}):
        P.status_line(junk)
        P.status_tone(junk)
    P.render_status(None, evaluate(_mkt()))     # no slot → no-op


def test_the_panel_computes_nothing():
    tree = ast.parse((ROOT / "mios_v5" / "ui"
                      / "simple_entry_panel.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"streamlit", "numpy", "pandas", "requests",
                            "simple_entry"})


# ══════════════════════════════════════════════════════════════════════
#  it is actually read
# ══════════════════════════════════════════════════════════════════════

def test_the_verdict_now_has_a_reader():
    """The gap this closes: `_simple_entry` was written once and read by
    nothing."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert "render_status" in src
    assert "_simple_entry_slot" in src


def test_the_status_is_drawn_into_a_placeholder_made_earlier():
    """The sidebar is built near the top of the script and the rules run near
    the bottom. A direct write would show the PREVIOUS cycle's answer, which
    for a status line is worse than showing none."""
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    slots, renders = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", "")
            if name == "empty":
                slots.append(n.lineno)
            elif name == "render_status" or getattr(n.func, "id", "") == \
                    "render_status":
                renders.append(n.lineno)
    assert slots and renders
    assert min(slots) < min(renders), "the placeholder must be made first"
