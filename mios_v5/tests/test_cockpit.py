"""Priority 3 — the Stage 52 cockpit, and the Priority 5 polish guards.

The cockpit is a VIEW. It reads `decision_v2` and renders it; it never decides
which state applies and never re-derives a condition. Most of what is tested
here is what it refuses to claim.

The sharpest case is the optional step. Stage 52 publishes only the CURRENT
state, so once a trade is at TRAIL there is no way to know whether it ever
scaled in. Ticking that box would assert a scale-in nobody took.
"""

import pathlib
import re

import pytest

from mios_v5.decision_v2 import LABEL, STATES
from mios_v5.ui import cockpit_panel as CP


def _d(state, **kw):
    d = {"state": state, "label": LABEL.get(state, state)}
    d.update(kw)
    return d


def _text(html):
    return re.sub(r"<[^>]+>", " ", html)


# ── it is a view, not an engine ─────────────────────────────────────────

def test_the_cockpit_computes_nothing():
    src = pathlib.Path(CP.__file__).read_text()
    for banned in ("cumsum", "rolling(", "ewm(", "clip(0, 1)", "def classify"):
        assert banned not in src, banned


def test_it_exposes_no_mutators():
    for banned in ("decide", "apply", "promote", "set_state", "advance",
                   "enter", "exit_trade"):
        assert not hasattr(CP, banned), f"cockpit_panel.{banned}"


def test_every_output_is_advisory():
    assert CP.cockpit(_d("ENTER"))["advisory_only"] is True


def test_it_never_raises():
    for d in (None, {}, {"state": None}, {"state": "NOT_A_STATE"},
              {"state": 42}):
        assert isinstance(CP.cockpit(d), dict)
        assert isinstance(CP.cockpit_html(d), str)


# ── the progression tracks the real state machine ───────────────────────

def test_every_progression_state_is_a_real_stage_52_state():
    """A typo here would leave a step permanently unreachable."""
    for entry in CP._ORDER:
        for st in CP._states(entry):
            assert st in STATES, f"{st} is not in decision_v2.STATES"


def test_every_stage_52_state_is_accounted_for():
    """A new state added to Stage 52 must not silently vanish from the
    cockpit — it would look like the trade skipped a rung."""
    covered = {s for e in CP._ORDER for s in CP._states(e)} | {"ABORT"}
    assert set(STATES) == covered, set(STATES) ^ covered


def test_floor_and_ceiling_share_one_rung():
    """Same rung reached from opposite sides; two rows would leave one
    permanently unreachable on every trade."""
    assert CP._position("FLOOR_CONFIRMED") == CP._position("CEILING_CONFIRMED")


def test_the_ladder_advances_monotonically():
    seq = ["WAIT", "ENTRY_READY", "FLOOR_CONFIRMED", "ENTER", "HOLD",
           "TRAIL", "EXIT", "COMPLETE"]
    pos = [CP._position(s) for s in seq]
    assert pos == sorted(pos) and None not in pos


# ── what it refuses to claim ────────────────────────────────────────────

def test_a_passed_optional_step_is_not_ticked():
    """At TRAIL the trade may never have scaled in. Stage 52 cannot tell us,
    so a tick would be a fabrication."""
    rows = {r["label"]: r for r in CP.steps(_d("TRAIL"))}
    assert rows["Scaled in"]["mark"] == CP._SKIP
    assert rows["Scaled in"]["optional"] is True
    assert rows["Holding"]["mark"] == CP._DONE      # not optional → a real tick


def test_only_scale_steps_are_optional():
    opt = {r["label"] for r in CP.steps(_d("COMPLETE")) if r["optional"]}
    assert opt == {"Scaled in", "Partial exit"}


def test_an_unknown_state_claims_no_progress():
    """A cockpit that invents a position is worse than one admitting it does
    not know where it is."""
    c = CP.cockpit(_d("SOMETHING_NEW"))
    assert c["known"] is False
    assert all(r["mark"] == CP._TODO for r in c["steps"])
    assert "not reported" in _text(CP.cockpit_html(_d("SOMETHING_NEW")))


def test_no_decision_at_all_claims_no_progress():
    assert CP.cockpit(None)["known"] is False


# ── the marks are right at each stage ───────────────────────────────────

@pytest.mark.parametrize("state,done_label,now_label", [
    ("WAIT", None, "Waiting — no setup"),
    ("ENTRY_READY", "Waiting — no setup", "Setup identified"),
    ("ENTER", "Level confirmed", "Entry taken"),
    ("HOLD", "Entry taken", "Holding"),
    ("COMPLETE", "Exited", "Complete"),
])
def test_marks_advance_with_the_state(state, done_label, now_label):
    rows = {r["label"]: r for r in CP.steps(_d(state))}
    assert rows[now_label]["mark"] == CP._NOW
    if done_label:
        assert rows[done_label]["mark"] == CP._DONE


def test_exactly_one_step_is_current():
    for state in ("WAIT", "ENTER", "TRAIL", "COMPLETE"):
        assert sum(1 for r in CP.steps(_d(state)) if r["current"]) == 1


# ── ABORT replaces the ladder ───────────────────────────────────────────

def test_abort_is_not_a_rung():
    """It can arrive at any point; "step 11 of 12" would read as a trade
    nearly done when the correct read is stop now."""
    assert CP._position("ABORT") is None
    c = CP.cockpit(_d("ABORT", reasons=["trap confirmed"]))
    assert c["aborted"] is True and c["known"] is True


def test_abort_renders_its_reasons_and_action():
    html = CP.cockpit_html(_d("ABORT", reasons=["shocked tape", "trap"],
                              action="Close the position now"))
    t = _text(html)
    assert "ABORT" in t and "shocked tape" in t
    assert "Close the position now" in t


def test_abort_without_reasons_still_says_something():
    assert "invalidated" in _text(CP.cockpit_html(_d("ABORT")))


# ── rendering ───────────────────────────────────────────────────────────

def test_html_shows_both_phases_and_every_step():
    t = _text(CP.cockpit_html(_d("HOLD", side="CALL")))
    assert "Getting in" in t and "Managing it" in t
    for r in CP.steps(_d("HOLD")):
        assert r["label"] in t


def test_the_side_tints_the_card():
    from mios_v5.ui.theme import BEAR, BULL
    assert BULL in CP.cockpit_html(_d("ENTER", side="CALL"))
    assert BEAR in CP.cockpit_html(_d("ENTER", side="PUT"))


def test_warnings_surface_when_present():
    html = CP.cockpit_html(_d("HOLD", side="CALL",
                              warnings=["trail tightening"]))
    assert "trail tightening" in _text(html)


# ══════════════════════════════════════════════════════════════════
#  Priority 5 — the polish guards
# ══════════════════════════════════════════════════════════════════

_NEW_PANELS = ("cockpit_panel.py", "opportunity_panel.py")


@pytest.mark.parametrize("name", _NEW_PANELS)
def test_new_panels_use_no_retired_grey(name):
    from mios_v5.ui.theme import RETIRED
    src = (pathlib.Path(CP.__file__).parent / name).read_text().lower()
    assert not [g for g in RETIRED if g in src]


@pytest.mark.parametrize("name", _NEW_PANELS)
def test_new_panels_have_no_hard_pixel_widths(name):
    """A HARD width cannot shrink, so it clips on a phone — and the app sets
    `overflow-x: hidden`, so clipped content is lost rather than scrollable.
    `min-width` on a wrapping row is fine; this only catches the hard kind."""
    src = (pathlib.Path(CP.__file__).parent / name).read_text()
    bad = [m for m in re.findall(r"(?<!min-)(?<!max-)width:\s*(\d+)px", src)
           if int(m) > 60]
    assert not bad, f"{name} has hard widths: {bad}"


@pytest.mark.parametrize("name", _NEW_PANELS)
def test_min_widths_fit_a_narrow_phone(name):
    """A 170px min-label beside a reason overflows a 320px screen. Anything
    that needs more room than this must be `flex: 1 1 <basis>` so it can
    shrink, not a floor it can never go under."""
    src = (pathlib.Path(CP.__file__).parent / name).read_text()
    bad = [m for m in re.findall(r"min-width:\s*(\d+)px", src) if int(m) > 145]
    assert not bad, f"{name} min-widths too wide for a phone: {bad}"


@pytest.mark.parametrize("name", _NEW_PANELS)
def test_new_panels_wrap_rather_than_overflow(name):
    """Every flex row must wrap, or a narrow screen scrolls the page
    sideways — which the app's own CSS forbids."""
    src = (pathlib.Path(CP.__file__).parent / name).read_text()
    flex = src.count("display:flex")
    wrap = src.count("flex-wrap:wrap") + src.count("margin-left:auto")
    assert wrap >= flex - 3, f"{name}: {flex} flex rows, {wrap} wrap/auto"


def test_the_sync_and_flow_legend_is_on_the_chart():
    """Priority 4 — the flow colours are new and unexplained, and the split into
    three fullscreen-able charts changed what the shared clock now means, so the
    legend has to say it: one timeline and one zoom window, but no shared
    crosshair. The Fullscreen affordance is itself part of the legend now."""
    src = (pathlib.Path(CP.__file__).parent / "dashboard_v6.py").read_text()
    assert "own Fullscreen button" in src
    assert "one zoom window" in src
    assert "who was buying" in src
    assert "CVD" in src


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        if not hasattr(fn, "pytestmark"):
            fn()
    print(f"cockpit + polish tests passed ({len(fns)})")
