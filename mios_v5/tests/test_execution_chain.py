"""The execution chain — Stages 72 → 73 → 72.9, actually wired.

All three were built, frozen and tested earlier, and **nothing called them**.
A module that exists and never runs is the regression this repo has already
suffered twice: `cfb6c93` removed writers while keeping readers, and
`_atm_leg_ltf_delta` had the same problem. Tests that a stage *works* say
nothing about whether it *runs*.

So the tests here are mostly about the wiring, and about the one property that
must survive it: **nothing is sent**. Stage 72.9 is `VALIDATED_SIMULATED` with
`freeze_ready: False`, and wiring a stage is not the same as trusting it to
broadcast.
"""

import ast
import pathlib

import pytest

from mios_v5 import dispatcher as DP
from mios_v5 import entry_engine as EE
from mios_v5 import trade_lifecycle as TL
from mios_v5 import trading_context as TC
from mios_v5.tests.test_entry_engine import (_behaviour, _fr, _matrix,
                                             _premium, _structure, _validation)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DASH = ROOT / "mios_v5" / "ui" / "dashboard_v6.py"


def _ctx(**over):
    kw = dict(fr=_fr(), matrix=_matrix(), premium=_premium(),
              validation=_validation(), structure=_structure(),
              behaviour=_behaviour(), cycle=9)
    kw.update(over)
    return TC.build(**kw)


def _chain(ctx=None):
    ctx = ctx or _ctx()
    decision = EE.run(ctx)
    lifecycle = TL.run(decision, ctx)
    dispatch = DP.run(decision, ctx, lifecycle=lifecycle,
                      registry=DP.MemoryRegistry(), transport=None)
    return decision, lifecycle, dispatch


# ══════════════════════════════════════════════════════════════════════
#  the wiring — the thing that was missing
# ══════════════════════════════════════════════════════════════════════

def test_all_three_stages_have_a_caller():
    """Built, frozen, tested — and until this was wired, dead code. A test that
    a stage works says nothing about whether it runs."""
    src = DASH.read_text()
    tree = ast.parse(src)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    aliases = {alias.asname or alias.name for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "run" in imported, "no stage entry point is imported"
    for expected in ("_entry", "_lifecycle", "_dispatch"):
        assert expected in aliases, f"{expected} is not wired"


def test_the_chain_runs_from_the_assembled_context():
    src = DASH.read_text()
    assert "_run_execution_chain" in src
    assert "_trading_context" in src


def test_each_stage_receives_the_previous_ones_output():
    """72 → 73 → 72.9. A chain where stage three ignores stage two is three
    stages, not a chain."""
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_execution_chain")
    body = ast.dump(fn)
    assert "'_entry'" in body and "'_lifecycle'" in body and "'_dispatch'" in body
    assert "lifecycle" in body


def test_the_chain_publishes_its_results_for_other_readers():
    src = DASH.read_text()
    for key in ("_entry_decision", "_lifecycle_decision", "_dispatch_decision"):
        assert key in src, key


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ nothing is sent
# ══════════════════════════════════════════════════════════════════════

def test_the_transport_is_never_constructed_here():
    """⚠️ This guard replaced `test_no_transport_is_passed`, which asserted the
    transport was a literal `None`.

    Sending is now possible, so that assertion could not survive — but its
    *intent* must: **the chain may not wire a live transport of its own.** It
    may only read one somebody else decided to provide. So the argument has to
    be a plain session_state lookup, never a call, an import or a constructor.

    Stage 72.9 is still VALIDATED_SIMULATED with `freeze_ready: False`. What
    changed is who decides, not whether a decision is needed.
    """
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_execution_chain")
    found = False
    for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
        for kw in call.keywords:
            if kw.arg == "transport":
                found = True
                assert isinstance(kw.value, ast.Name), (
                    "transport must be a variable read from session_state, "
                    "never built here")
    assert found, "the chain no longer passes a transport at all"

    # …and the variable must come from session_state, defaulting to absent.
    src = DASH.read_text()
    assert '_mios_transport' in src
    assert 'st.session_state.get("_mios_transport")' in src


def test_the_send_default_is_one_findable_named_constant():
    """⚠️ This replaced an assertion that the toggle defaulted to OFF.

    The owner set it ON deliberately, so that assertion had to go — but the
    property underneath it must not: **whether this app sends unprompted has
    to be one line somebody can find.** A literal `value=True` buried in a
    sidebar call is a live signal channel nobody can locate.

    So the default is a module-level constant, and the toggle must read it
    rather than hard-code either answer.
    """
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)

    consts = [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") == "MIOS_V6_TELEGRAM_DEFAULT"
                      for t in n.targets)]
    assert consts, "the send default must be a named module-level constant"
    assert isinstance(consts[0].value, ast.Constant)
    assert isinstance(consts[0].value.value, bool)

    toggles = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "checkbox"
               and any(isinstance(a, ast.Constant)
                       and "MIOS V6 signals" in str(a.value) for a in n.args)]
    assert toggles, "no toggle for MIOS V6 Telegram signals"
    for t in toggles:
        default = next((kw.value for kw in t.keywords if kw.arg == "value"),
                       None)
        assert isinstance(default, ast.Name), (
            "the toggle must read the named constant, not hard-code a default")
        assert default.id == "MIOS_V6_TELEGRAM_DEFAULT"


def test_the_toggle_can_still_turn_sending_off():
    """Defaulting on is a decision about the starting state, not a removal of
    the switch. Turning it off mid-session must still stop sending."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert 'st.session_state.pop("_mios_transport", None)' in src
    # AST, not a text slice — the phrase now appears in the constant's comment
    # as well as the widget, and slicing on the first hit found the comment.
    tree = ast.parse(src)
    assert any(isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "checkbox"
               and any(isinstance(a, ast.Constant)
                       and "MIOS V6 signals" in str(a.value) for a in n.args)
               for n in ast.walk(tree)), "the switch itself was removed"


def test_the_transport_key_is_removed_when_the_toggle_is_off():
    """Not merely unset on first run — actively popped, so turning the toggle
    off mid-session stops sending immediately rather than at the next reload."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert 'st.session_state.pop("_mios_transport", None)' in src


def test_the_dispatch_reports_not_sent():
    _, _, dispatch = _chain()
    assert dispatch.telegram_state == "NOT_SENT"
    # `should_send` is the dispatcher's verdict; `telegram_state` is what
    # happened. With no transport the second must be NOT_SENT whatever the
    # first says — that gap is the whole point of running it unwired.
    assert dispatch.record is None or dispatch.record.telegram_message_id is None


def test_the_dashboard_never_imports_a_network_client():
    """`import requests` inside this path is a named forbidden failure mode."""
    tree = ast.parse(DASH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "urllib3", "telegram"})


def test_the_delivery_banner_tracks_the_dispatch_state():
    """It used to assert "Nothing is sent" unconditionally. That was true while
    the dispatcher ran with no transport and became a lie the moment the
    sidebar toggle started passing one in — a panel swearing nothing was sent
    while the message lands on the phone is worse than no panel. So it is
    derived, and `freeze_ready: False` is stated either way."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain()
    html = execution_html(decision, lifecycle, dispatch)
    assert "Not sent this cycle" in html
    assert "freeze_ready: False" in html

    sent = dict(dispatch.to_dict(), telegram_state="SENT")
    html_sent = execution_html(decision, lifecycle, sent)
    assert "Not sent this cycle" not in html_sent
    assert "Sent." in html_sent
    assert "freeze_ready: False" in html_sent


def test_delivered_is_not_coloured_as_success():
    """Nothing in this build delivers, so a green delivery badge would be a lie
    waiting to happen."""
    from mios_v5.ui import execution_panel as P
    assert P._DISPATCH_COL["DELIVERED"] != P.BULL


# ══════════════════════════════════════════════════════════════════════
#  the chain describes ONE decision
# ══════════════════════════════════════════════════════════════════════

def test_the_lifecycle_references_the_entry_decision_rather_than_minting_one():
    decision, lifecycle, _ = _chain()
    assert lifecycle.decision_id == decision.id
    assert lifecycle.id != decision.id


def test_the_entry_decision_still_verifies_after_the_chain_has_run():
    """Nothing downstream may alter what Stage 72 concluded."""
    decision, _, _ = _chain()
    assert decision.verify() is True


def test_the_panel_flags_a_lifecycle_that_does_not_match():
    """A chain that silently describes two decisions is worse than one that
    fails loudly."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain()
    html = execution_html(decision, {"action": "HOLD", "decision_id": "other"},
                          dispatch)
    assert "does not reference the entry decision" in html


# ══════════════════════════════════════════════════════════════════════
#  the registry
# ══════════════════════════════════════════════════════════════════════

def test_a_registry_is_used_because_without_one_duplicate_has_no_answer():
    src = DASH.read_text()
    assert "MemoryRegistry" in src
    assert "_dispatch_registry" in src, "the registry must outlive one cycle"


def test_dispatching_the_same_decision_twice_is_recognised():
    ctx = _ctx()
    decision = EE.run(ctx)
    lifecycle = TL.run(decision, ctx)
    registry = DP.MemoryRegistry()
    first = DP.run(decision, ctx, lifecycle=lifecycle, registry=registry,
                   transport=None)
    second = DP.run(decision, ctx, lifecycle=lifecycle, registry=registry,
                    transport=None)
    assert first is not None and second is not None
    # Whatever the states, the second must not be MORE ready than the first —
    # a re-run of an identical decision cannot become newly sendable.
    assert not (second.dispatch_state == "READY"
                and first.dispatch_state != "READY")


# ══════════════════════════════════════════════════════════════════════
#  it never takes the tab down
# ══════════════════════════════════════════════════════════════════════

def test_the_chain_survives_a_thin_context():
    decision, lifecycle, dispatch = _chain(TC.build())
    assert decision.state in ("WAIT", "ABORT")
    assert lifecycle is not None and dispatch is not None


def test_the_panel_never_raises():
    from mios_v5.ui.execution_panel import execution_html
    for junk in ("a string", 42, {}, []):
        execution_html(junk, junk, junk)


# ══════════════════════════════════════════════════════════════════════
#  ⭐ silence and WAIT are not the same reading
# ══════════════════════════════════════════════════════════════════════

def test_no_decision_renders_did_not_run_rather_than_nothing():
    """The panel used to return "" here, and a chain that never ran looked
    exactly like a chain that decided not to trade. They mean opposite things:
    one is the system declining, the other is the system absent."""
    from mios_v5.ui.execution_panel import execution_html
    html = execution_html(None)
    assert html, "a blank panel is indistinguishable from 'no trade'"
    assert "did not run" in html
    assert "not</b> a decision to wait" in html


def test_the_not_run_card_carries_the_reason_it_was_given():
    from mios_v5.ui.execution_panel import execution_html
    html = execution_html(None, not_run_reason="the option chain is empty")
    assert "the option chain is empty" in html


def test_a_wait_decision_says_why_no_signal():
    """The question a blank panel never answered."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain(TC.build())
    html = execution_html(decision, lifecycle, dispatch)
    assert "Why no signal?" in html
    assert dict(decision.metadata)["state_reason"] in html


def test_every_hard_gate_is_shown_not_only_the_first():
    """`state()` puts blocks[0] into state_reason, so three failing gates used
    to surface as one — and a trader fixes the wrong thing."""
    decision = EE.run(_ctx())
    meta = dict(decision.metadata)
    assert "readiness_blocks" in meta
    assert isinstance(meta["readiness_blocks"], tuple)


def test_the_gate_block_separates_gates_from_weights():
    """A component scoring 30 has not failed a gate — it voted low and was
    outvoted. Rendering the two as one list would misstate the engine."""
    from mios_v5.ui.execution_panel import execution_html
    html = execution_html(*_chain())
    assert "Hard gates" in html
    assert "Weighted inputs" in html
    assert "not gates" in html


def test_an_input_that_did_not_report_says_so_rather_than_scoring_zero():
    """Unknown-excluded scoring, made visible: a score over four inputs and a
    score over eleven must never look the same."""
    from mios_v5.ui.execution_panel import execution_html
    html = execution_html(*_chain(TC.build()))
    assert "not reported" in html


def test_frozen_metadata_is_readable_by_the_panel():
    """`MappingProxyType` is NOT a `dict` subclass, and the panel's accessor
    tested `isinstance(obj, dict)` — so every metadata field it read fell
    through to the default. `state_reason`, the single line explaining a WAIT,
    rendered blank from the day the panel was written.

    Asserted on the real frozen type rather than a plain dict, because a plain
    dict is exactly what made this pass while the app showed nothing."""
    from types import MappingProxyType
    from mios_v5.ui.execution_panel import _get
    frozen = MappingProxyType({"state_reason": "score 41 is below the entry "
                                               "threshold"})
    assert not isinstance(frozen, dict), "the premise of the bug"
    assert _get(frozen, "state_reason") == ("score 41 is below the entry "
                                            "threshold")
    # …and end to end, through a real decision
    decision = EE.run(_ctx())
    from mios_v5.ui.execution_panel import execution_html
    assert dict(decision.metadata)["state_reason"] in execution_html(decision)


def test_the_chain_is_not_nested_inside_the_strike_picker():
    """Its old home was `_strike_validation`, which returns early when the ATM
    ladder is unpublished and wraps ~145 lines in one `except`. Either firing
    meant Stage 72 never ran and the only trace was a caption about the strike
    picker. The call must sit at the top level so a strike-picker problem
    cannot take the trade verdict down with it.

    AST, not a text scan: the source explains this rule in a comment naming
    both functions, and a substring search matches the prose describing the
    rule rather than the code obeying it — the failure mode this repo has hit
    seven times."""
    tree = ast.parse(DASH.read_text())
    holders = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "_run_execution_chain"):
                holders.add(fn.name)
    assert holders, "the execution chain is never called"
    assert "_strike_validation" not in holders, (
        "the chain is nested inside the strike picker again — its early return "
        "and shared `except` will hide Stage 72")


def test_every_failure_path_renders_the_panel_rather_than_a_caption():
    """Three paths could fail to produce a decision, and all three used to end
    in `return` or a bare caption. Each must now reach the panel, because a
    caption reading "Strike Validation unavailable" while the real casualty was
    Stage 72 is how this stayed invisible."""
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_execution_chain")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_render_chain_panel" in called
    # the ctx-is-None branch and the except branch both render, so more than
    # one call site — a single one would mean a path still returns silently
    sites = sum(1 for c in ast.walk(fn) if isinstance(c, ast.Call)
                and getattr(c.func, "id", "") == "_render_chain_panel")
    assert sites >= 2, "a failure path still returns without rendering"


def test_the_last_valid_signal_survives_a_quiet_cycle():
    """A blank panel in a slow market is what makes a working system feel
    broken, so the morning's signal stays on screen."""
    from mios_v5.ui.execution_panel import execution_html, remember_signal
    last = {"state": "ENTER", "side": "CALL", "strike": 24500,
            "entry": 182.4, "stop": 160.0, "score": 81, "at": "10:42"}
    html = execution_html(None, last_signal=last)
    assert "Last valid signal" in html and "10:42" in html
    # …and a WAIT never overwrites it
    assert remember_signal({"state": "WAIT", "side": "CALL"}) is None
    assert remember_signal(None) is None
    kept = remember_signal({"state": "ENTER", "side": "PUT", "strike": 24400,
                            "created_at": "2026-08-06T10:42:00+00:00"})
    assert kept and kept["side"] == "PUT" and kept["at"] == "10:42"


def test_the_panel_renders_a_stored_decision_like_a_live_one():
    """A replayed decision is a dict; a live one is frozen. Identity is how a
    reader tells the chain describes one decision, so both must show it."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain()
    live = execution_html(decision, lifecycle, dispatch)
    stored = execution_html(decision.to_dict(), lifecycle, dispatch)
    assert decision.id[:8] in live and decision.id[:8] in stored


def test_the_panel_computes_nothing():
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "execution_panel.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "streamlit", "requests",
                            "entry_engine", "dispatcher", "trade_lifecycle"})


# ══════════════════════════════════════════════════════════════════════
#  no module built this session is left without a caller
# ══════════════════════════════════════════════════════════════════════

def test_every_stage_built_this_session_is_reachable_from_the_app():
    """The guard for the whole class. This is how three frozen stages sat
    unreachable for a day without anything noticing."""
    import re
    app = "\n".join(
        p.read_text() for p in
        [ROOT / "vob_minimal.py", ROOT / "mios_v5" / "runner.py"]
        + list((ROOT / "mios_v5" / "ui").glob("*.py")))
    for module in ("premium_energy", "premium_structure", "strike_validation",
                   "premium_behaviour", "trading_context", "entry_engine",
                   "dispatcher", "trade_lifecycle", "liquidity",
                   "liquidity_context", "liquidity_telemetry"):
        assert re.search(rf"\b{module}\b", app), f"{module} has no caller"
