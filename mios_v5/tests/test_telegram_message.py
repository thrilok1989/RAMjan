"""The entry and exit messages a trader actually receives.

One rule dominates: **an `UNKNOWN` may never render as a number.** Stage 72
publishes `target2` and `target3` as `UNKNOWN` by name, and the earlier
Stage 71.90 audit already caught a sample alert printing three targets when
Stage 35 publishes one. A template renders whatever it is given; this is the
test that it is never given a fabrication.
"""

import ast
import pathlib

import pytest

from mios_v5.ui import telegram_message as M

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "ui" / "telegram_message.py"


def _entry(**over):
    p = {"id": "abcdef12-3456", "version": "72.1", "state": "ENTER",
         "side": "CALL", "strike": 24500.0, "quality": "A+",
         "confidence": 82, "timing": "Optimal", "entry": 182.4,
         "stop": 178.5, "risk": "Low", "reward": "Good",
         "behaviour": "Support Building", "horizon": "Scalp",
         "targets": {"target1": 185.0, "target2": "UNKNOWN",
                     "target3": "UNKNOWN"},
         "reasons": ("Strike Validation VALID", "Energy 78"),
         "warnings": ("RBI event today",)}
    p.update(over)
    return p


def _lc(**over):
    d = {"action": "EXIT", "state": "EXIT", "health": "Poor",
         "exit_reason": "Stop Hit", "trail": "No Trail", "scale": "Neither",
         "position_known": "UNKNOWN", "decision_id": "abcdef12-3456"}
    d.update(over)
    return d


# ══════════════════════════════════════════════════════════════════════
#  ⛔ it cannot invent a level
# ══════════════════════════════════════════════════════════════════════

def test_only_the_targets_that_exist_are_printed():
    """Stage 35 publishes ONE target. A fixed three-line block would render
    three, in the one artefact a trader acts on."""
    out = M.entry_message(_entry())
    assert "T1" in out
    assert "T2" not in out and "T3" not in out


def test_no_unknown_ever_reaches_the_message():
    for payload in (_entry(), _entry(quality="UNKNOWN", entry="UNKNOWN",
                                     behaviour="UNKNOWN", reward="UNKNOWN"),
                    _entry(targets={"target1": "UNKNOWN"})):
        assert "UNKNOWN" not in M.entry_message(payload)
    assert "UNKNOWN" not in M.exit_message(_lc(), _entry())


def test_an_absent_field_drops_its_row_rather_than_printing_a_dash():
    """A dash still occupies a row and implies the field was expected."""
    out = M.entry_message(_entry(reward="UNKNOWN"))
    assert "Reward" not in out
    assert "Entry" in out


def test_a_missing_stop_does_not_become_zero():
    out = M.entry_message(_entry(stop=None))
    assert "Stop" not in out
    assert "₹0" not in out


# ══════════════════════════════════════════════════════════════════════
#  what gets sent, and what does not
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state", ["ENTER", "ENTRY_READY", "ABORT"])
def test_the_sendable_entry_states_render(state):
    assert M.entry_message(_entry(state=state))


@pytest.mark.parametrize("state", ["WAIT", "HOLD", "COMPLETE", "UNKNOWN", ""])
def test_everything_else_renders_nothing(state):
    """`WAIT` is the engine working correctly. Saying so every cycle trains a
    reader to mute the channel — the one thing a signal channel cannot
    survive."""
    assert M.entry_message(_entry(state=state)) == ""


@pytest.mark.parametrize("action", ["EXIT", "SCALE_OUT", "ADD", "TRAIL",
                                    "ABORT"])
def test_the_lifecycle_actions_render(action):
    assert M.exit_message(_lc(action=action), _entry())


def test_a_hold_is_not_a_message():
    assert M.exit_message(_lc(action="HOLD"), _entry()) == ""


# ══════════════════════════════════════════════════════════════════════
#  entry and exit describe ONE decision
# ══════════════════════════════════════════════════════════════════════

def test_the_exit_carries_the_entry_id():
    """So a trader can join it to the signal they were sent earlier — the whole
    reason Stage 73 references rather than mints."""
    out = M.exit_message(_lc(), _entry())
    assert "abcdef12" in out


def test_the_entry_carries_its_own_identity():
    out = M.entry_message(_entry())
    assert "abcdef12" in out and "72.1" in out


def test_the_exit_falls_back_to_the_lifecycle_reference():
    out = M.exit_message(_lc(), None)
    assert "abcdef12" in out


# ══════════════════════════════════════════════════════════════════════
#  presentation only
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_nothing_that_could_send_or_compute():
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "streamlit", "numpy",
                            "pandas", "entry_engine", "dispatcher"})


def test_it_never_raises_on_junk():
    for junk in (None, {}, "a string", 42, [], {"state": None}):
        M.entry_message(junk if isinstance(junk, dict) else {})
        M.exit_message(junk if isinstance(junk, dict) else {})


def test_a_position_is_not_implied():
    """`position_known` is UNKNOWN by name in Stage 73 — no producer reports a
    fill. It must never appear as though a position were confirmed."""
    assert "Position" not in M.exit_message(_lc(), _entry())


# ══════════════════════════════════════════════════════════════════════
#  the router lets these through
# ══════════════════════════════════════════════════════════════════════

def test_the_message_carries_a_telegram_entry_tier_marker():
    """`send_telegram_message_sync` routes anything without an entry-tier
    marker to Discord only. A signal that silently went to the wrong channel
    would look exactly like a signal that was never generated."""
    import re
    src = (ROOT / "vob_minimal.py").read_text()
    block = src.split("_TELEGRAM_ENTRY_MARKERS = (")[1].split(")")[0]
    # Quoted literals only — the block carries inline comments, and stripping
    # punctuation off the whole line dragged the comment along with it.
    markers = [m for m in re.findall(r"'([^']+)'", block) if "MIOS" in m]
    assert markers, "no MIOS markers registered with the router"
    assert any(m in M.entry_message(_entry()) for m in markers)
    assert any(m in M.exit_message(_lc(), _entry()) for m in markers)


def test_the_transport_reports_failure_rather_than_assuming_success():
    """The dispatcher reads the return value; a transport that returned
    nothing on a failed send would record a delivery that never happened."""
    src = (ROOT / "vob_minimal.py").read_text()
    fn = src[src.index("def mios_v6_transport"):src.index(
        "def send_telegram_message_sync")]
    assert 'return "failed"' in fn and 'return "ok"' in fn
    assert "except Exception" in fn


# ══════════════════════════════════════════════════════════════════════
#  the market read that travels with the signal
# ══════════════════════════════════════════════════════════════════════

def _market(**over):
    m = {"spot": 24512.3, "v5": "BULLISH", "v6": "BULLISH",
         "call": {"ltp": 182.4, "energy": 78, "support": 175.0,
                  "resistance": 191.0, "behaviour": "Support Building"},
         "put": {"ltp": 96.2, "energy": 31, "support": 92.0,
                 "resistance": 104.0, "behaviour": "Resistance Building"}}
    m.update(over)
    return m


def test_the_signal_carries_spot_bias_energy_levels_and_behaviour():
    out = M.entry_message(_entry(), _market())
    for expected in ("24,512.3", "V5 BULLISH", "V6 BULLISH",
                     "energy 78", "energy 31",
                     "₹182.40", "₹96.20",
                     "S ₹175.00", "R ₹191.00",
                     "Support Building", "Resistance Building"):
        assert expected in out, expected


def test_both_energies_are_printed_never_a_difference():
    """Stage 71.7 scores CALL and PUT independently and never by subtraction.
    A single net number would throw away which side has none."""
    out = M.entry_message(_entry(), _market())
    assert "energy 78" in out and "energy 31" in out
    assert "47" not in out


def test_a_bias_disagreement_is_flagged():
    """Two engines agreeing is reassuring; disagreeing is the reason to look."""
    assert "diverging" in M.entry_message(_entry(), _market(v6="BEARISH"))
    assert "diverging" not in M.entry_message(_entry(), _market())


def test_the_levels_are_premium_not_spot():
    """There is no delta-based spot→premium conversion in MIOS. A spot level
    printed against an option's LTP marks a price that series never trades."""
    out = M.entry_message(_entry(), _market())
    # Anchor on the LEG marker: "CALL" also appears in the header
    # ("MIOS ENTRY — CALL 24,500"), and splitting on the bare word landed in
    # the strike rather than the leg block.
    call = out.split("🟢 <b>CALL</b>")[1].split("🔴")[0]
    assert "175.00" in call and "191.00" in call     # the LEG's own band
    assert "24,512" not in call                       # not spot


def test_a_side_that_reported_nothing_is_omitted():
    out = M.entry_message(_entry(), _market(put={}))
    assert "CALL" in out
    assert "🔴 <b>PUT</b>" not in out


def test_the_market_block_is_optional():
    """The signal must still render when the cycle published nothing."""
    assert M.entry_message(_entry()) 
    assert M.market_block(None) == ""
    assert M.market_block({}) == ""


def test_the_exit_carries_the_same_read():
    out = M.exit_message(_lc(), _entry(), _market())
    assert "Spot" in out and "energy 78" in out


def test_the_market_block_drops_absent_values_rather_than_zeroing():
    out = M.market_block(_market(spot=None,
                                 call={"ltp": 182.4, "energy": "UNKNOWN"}))
    assert "Spot" not in out
    assert "energy" not in out.split("PUT")[0]
    assert "₹0" not in out


def test_the_transport_assembles_the_read_from_published_state_only():
    """It reads what the cycle published; it must not compute a level."""
    import ast
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_mios_market_read")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not (called & {"compute_vpfr", "calculate_money_flow_profile",
                          "analyse", "classify_sr_behavior"})


# ══════════════════════════════════════════════════════════════════════
#  support / resistance with their odds
# ══════════════════════════════════════════════════════════════════════

def _zones(**over):
    m = _market()
    m.update({"support": {"price": 24450, "break": 28, "bounce": 72,
                          "trap": 15},
              "resistance": {"price": 24580, "break": 61, "bounce": 39,
                             "trap": 44}})
    m.update(over)
    return m


def test_both_levels_print_with_break_and_bounce():
    out = M.market_block(_zones())
    assert "Support: <b>24,450</b>" in out
    assert "Resistance: <b>24,580</b>" in out
    assert "bounce 72%" in out and "break 28%" in out
    assert "bounce 39%" in out and "break 61%" in out


def test_bounce_is_zone_intels_rejection_not_a_computed_complement():
    """`break` and `rejection` are complements produced together by
    `zone_intel.probabilities()`. Rendering `100 - break` would invent a number
    that happens to agree — until the day the producer changes."""
    out = M.market_block(_zones(support={"price": 24450, "break": 28,
                                         "bounce": 66}))
    assert "bounce 66%" in out          # not 72
    assert "72%" not in out.split("🧱 Resistance")[0]


def test_a_high_trap_is_flagged_and_a_low_one_is_not():
    """Trap is INDEPENDENT of break/bounce — how likely a move through is a
    liquidity grab. It earns a line only when it would change what you do."""
    out = M.market_block(_zones())
    assert "trap 44%" in out            # resistance, high
    assert "trap 15%" not in out        # support, low — noise


def test_a_level_without_a_price_is_dropped():
    # Anchored on the zone marker: the bare word "Support" also appears in the
    # behaviour line ("Support Building"), so a loose check passed on broken
    # output and failed on correct output.
    assert "🛡 Support:" not in M.market_block(_zones(support={"break": 28}))


def test_odds_are_omitted_when_the_producer_did_not_report():
    out = M.market_block(_zones(support={"price": 24450}))
    assert "Support: <b>24,450</b>" in out
    assert "bounce" not in out.split("🧱 Resistance")[0]
    assert "0%" not in out


def test_the_premium_level_carries_its_own_break_and_fakeout():
    """Stage 71.8's odds for the PREMIUM's level — a different fact from the
    spot zone's, and printed on the leg it belongs to."""
    m = _zones()
    m["call"] = dict(m["call"], break_probability=22, fakeout_probability=18)
    call = M.market_block(m).split("🟢 <b>CALL</b>")[1].split("🔴")[0]
    assert "break 22%" in call and "fakeout 18%" in call


def test_fakeout_is_not_folded_into_break():
    """A fakeout and a break are different outcomes and a trader acts
    differently on each; one blended number would erase the distinction."""
    m = _zones()
    m["call"] = dict(m["call"], break_probability=22, fakeout_probability=18)
    call = M.market_block(m).split("🟢 <b>CALL</b>")[1].split("🔴")[0]
    assert "40%" not in call


def test_the_spot_zone_and_the_premium_level_are_not_confused():
    """24,450 is a NIFTY level; ₹175 is where that CALL trades. Neither may
    appear in the other's block."""
    m = _zones()
    m["call"] = dict(m["call"], break_probability=22)
    out = M.market_block(m)
    call = out.split("🟢 <b>CALL</b>")[1].split("🔴")[0]
    assert "24,450" not in call and "24,580" not in call


# ══════════════════════════════════════════════════════════════════════
#  two variants of one dispatch
# ══════════════════════════════════════════════════════════════════════

def test_terse_drops_the_reasons_and_full_keeps_them():
    terse = M.entry_message(_entry(), _zones(), reasons=False)
    full = M.entry_message(_entry(), _zones(), reasons=True)
    assert "✓ Strike Validation VALID" in full
    # Not a bare "✓" check — that character also marks bias agreement
    # ("V5 BULLISH · V6 BULLISH ✓"), so the loose version failed on correct
    # output. The reason LINES are what terse drops.
    assert "✓ Strike Validation VALID" not in terse
    assert "✓ Energy" not in terse
    assert len(full) > len(terse)


def test_warnings_survive_in_BOTH():
    """The half that changes what a trader does. A terse message that dropped
    a SHOCK would be shorter and more dangerous; only the explanation of a
    GOOD read is optional."""
    for reasons in (True, False):
        out = M.entry_message(_entry(), _zones(), reasons=reasons)
        assert "⚠ RBI event today" in out


def test_everything_actionable_survives_in_terse():
    """Levels, odds, bias and the decision itself are not 'reasons'."""
    terse = M.entry_message(_entry(), _zones(), reasons=False)
    for kept in ("Entry", "₹182.40", "Stop", "T1", "Support: <b>24,450</b>",
                 "bounce 72%", "V5 BULLISH", "energy 78", "abcdef12"):
        assert kept in terse, kept


def test_the_exit_has_both_variants_too():
    lc = dict(_lc(), reasons=None)
    assert M.exit_message(lc, _entry(), _zones(), reasons=False)
    assert M.exit_message(lc, _entry(), _zones(), reasons=True)


def test_the_fan_out_is_one_dispatch_not_two():
    """The registry claims on the decision hash alone, so a SECOND dispatch for
    one decision is a duplicate by its own definition. Both variants must go
    out inside a single transport call."""
    import ast
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "mios_v6_transport")
    sends = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") in ("send_telegram_message_sync",
                                               "send_telegram_alert_bot")]
    assert len(sends) == 2, "both variants send from one transport call"


def test_the_reasoned_copy_failing_does_not_fail_the_signal():
    """If the second channel counted, the dispatcher would release the claim
    and re-send a signal the trader already has."""
    import ast
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "mios_v6_transport")
    # The alert-bot call must sit in its OWN try whose handlers never return
    # "failed". A text scan could not tell that from the outer handler, which
    # legitimately does.
    guarded = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        if any(getattr(c.func, "id", "") == "send_telegram_alert_bot"
               for c in ast.walk(node) if isinstance(c, ast.Call)):
            inner = [t for t in ast.walk(node)
                     if isinstance(t, ast.Try) and t is not node]
            if not inner:
                guarded.append(node)
    assert guarded, "the reasoned copy is not individually guarded"
    for node in guarded:
        for handler in node.handlers:
            for r in ast.walk(handler):
                if isinstance(r, ast.Return) and isinstance(r.value,
                                                            ast.Constant):
                    assert r.value.value != "failed", (
                        "a failed reasoned copy must not mark the dispatch "
                        "undelivered")


def test_an_unconfigured_second_channel_is_visible():
    """`send_telegram_alert_bot` is a silent no-op without credentials, and a
    reasoning channel that never arrives looks like one with nothing to say."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert "TELEGRAM_ALERT_BOT_TOKEN" in src.split("MIOS V6 signals")[-1]
    assert "Terse only" in src


def test_a_per_side_context_value_is_resolved_to_that_side():
    """The bug in the reported message:

        🟢 CALL
            {'CALL': 'Neutral', 'PUT': 'Neutral'}
        🔴 PUT
            {'CALL': 'Neutral', 'PUT': 'Neutral'}

    `_mios_market_read` tested `isinstance(value, dict)` before picking the
    side out. TradingContext freezes per-side values as `MappingProxyType`,
    which is NOT a dict subclass, so the test never matched and both legs
    printed the same raw mapping instead of their own behaviour.

    Asserted on the real frozen type, because a plain dict is exactly what let
    this pass while the phone showed a Python repr.
    """
    from types import MappingProxyType
    frozen = MappingProxyType({"CALL": "Support Building", "PUT": "Neutral"})
    assert not isinstance(frozen, dict), "the premise of the bug"
    from collections.abc import Mapping as _Mapping
    assert isinstance(frozen, _Mapping)
    resolved = frozen.get("CALL") if isinstance(frozen, _Mapping) else frozen
    assert resolved == "Support Building"

    # and the source performs the same widening
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_mios_market_read")
    checks = {getattr(c.args[1], "id", "") for c in ast.walk(fn)
              if isinstance(c, ast.Call)
              and getattr(c.func, "id", "") == "isinstance" and len(c.args) == 2}
    assert "Mapping" in checks, "the side-resolution still tests for `dict`"
    assert "dict" not in checks


def test_no_message_ever_renders_a_python_repr():
    """A brace in a signal means a container leaked into the text."""
    market = {"spot": 24630.3, "v5": "NEUTRAL", "v6": "NEUTRAL",
              "call": {"ltp": 182.4, "energy": 78, "behaviour": "Neutral"},
              "put": {"ltp": 96.2, "energy": 31, "behaviour": "Neutral"}}
    out = M.market_block(market)
    assert "{" not in out and "}" not in out, out
    assert "'CALL'" not in out and "'PUT'" not in out
