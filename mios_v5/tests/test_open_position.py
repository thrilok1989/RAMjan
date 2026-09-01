"""🎯 Stage 52's `open_position` — the contract, derived not guessed.

`stage52_decision` read `open_position` and nothing published it, so `decide()`
ran every cycle as though the book were flat.

The fix is a **rename of one field**, and these tests exist to keep it one: the
contract is whatever `decision_v2` actually reads, and the moment somebody adds a
field "because a position obviously has one" this stops being a rename and starts
being an interpretation of a trading decision.

See `docs/CONTRACT_POSITION_STATE.md`.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from mios_v5.runner import _open_position

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The app's real shape — `vob_minimal.py:8176`.
_ACTIVE = {
    "side": "CALL", "zone": "SUPPORT", "level": 24500.0,
    "target": 24680.0, "invalidation": 24440.0,
    "entry_spot": 24523.5, "db_id": 91, "entry_ts": "2026-08-11T10:14:02+05:30",
    "story_id": "s-7",
}


# ══════════════════════════════════════════════════════════════════════
#  the contract is what decision_v2 reads — and only that
# ══════════════════════════════════════════════════════════════════════

def _fields_decision_v2_reads():
    """Every `position` field `decision_v2` reads, from its AST.

    Derived rather than listed, so adding a read in the engine fails this suite
    instead of silently widening the contract.
    """
    src = (_ROOT / "mios_v5" / "decision_v2.py").read_text()
    tree = ast.parse(src)
    fields = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        aliases = {"position"} if "position" in params else set()
        if "pos" in params:
            aliases.add("pos")
        # `pf, pos = proof or {}, position or {}`  and  `pos = position or {}`
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                pairs = []
                if isinstance(n.value, ast.Tuple) and isinstance(n.targets[0], ast.Tuple):
                    pairs = list(zip(n.targets[0].elts, n.value.elts))
                else:
                    pairs = [(n.targets[0], n.value)]
                for t, v in pairs:
                    if (isinstance(v, ast.BoolOp) and v.values
                            and isinstance(v.values[0], ast.Name)
                            and v.values[0].id in aliases
                            and isinstance(t, ast.Name)):
                        aliases.add(t.id)
        if not aliases:
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in aliases
                    and n.args and isinstance(n.args[0], ast.Constant)):
                fields.add(n.args[0].value)
    return fields


def test_the_contract_is_exactly_the_fields_the_engine_reads():
    """⚠️ The guard against re-guessing. `is_open`, `strike`, `quantity`,
    `entry_time`, `signal_id` and `source` are read by NOTHING — they were on an
    early speculative list and would have been dead weight in a trading input."""
    from mios_v5.runner import _POSITION_FIELDS

    read = _fields_decision_v2_reads()
    assert read, "the AST walk found nothing — the extraction broke"
    assert read <= set(_POSITION_FIELDS), (
        f"decision_v2 reads field(s) the producer does not supply: "
        f"{sorted(read - set(_POSITION_FIELDS))}")
    for absent in ("is_open", "strike", "quantity", "entry_time", "signal_id",
                   "source"):
        assert absent not in read, (
            f"{absent} is now read — the contract changed, update the producer "
            f"and docs/CONTRACT_POSITION_STATE.md")


def test_sides_presence_is_the_in_a_position_flag():
    """`if pos.get("side"): return _manage(...)` — there is no `is_open`, and the
    producer must therefore never emit `side` for a flat book."""
    src = (_ROOT / "mios_v5" / "decision_v2.py").read_text()
    assert 'if pos.get("side"):' in src
    assert _open_position({}) == {}


# ══════════════════════════════════════════════════════════════════════
#  the rename, and the arithmetic that proves it
# ══════════════════════════════════════════════════════════════════════

def test_entry_spot_becomes_entry():
    out = _open_position({"_entry_gate_active": _ACTIVE})
    assert out == {"side": "CALL", "entry": 24523.5, "target": 24680.0}
    assert "entry_spot" not in out, "the rename is the point of this function"


def test_entry_is_a_spot_level_and_the_two_sites_still_agree():
    """⚠️ The evidence the whole wiring rests on. The app and the engine compute
    the SAME gain from the same two numbers, which is what makes `entry_spot` and
    `entry` the same quantity rather than two things with similar names.

    If either site is reworded, this fails and the mapping must be re-argued.
    """
    app = (_ROOT / "vob_minimal.py").read_text()
    assert "(spot_price - _act['entry_spot']) if _side_x == 'CALL'" in app
    assert "(_act['entry_spot'] - spot_price)" in app

    eng = (_ROOT / "mios_v5" / "decision_v2.py").read_text()
    assert "gain = ((st - entry) if up else (entry - st))" in eng


def test_the_gain_computed_both_ways_matches():
    """Behaviour, not text: run the engine's own management path and check the
    points-from-entry it reports is what the app would show."""
    from mios_v5.decision_v2 import decide

    spot = 24_575.0
    pos = _open_position({"_entry_gate_active": _ACTIVE})
    out = decide(position=pos, spot=spot, market_state={"state": "TREND_UP"})
    app_gain = spot - _ACTIVE["entry_spot"]          # vob_minimal.py:8266, CALL
    assert out["in_trade"] is True
    assert any(f"{app_gain:+.0f} pts" in r for r in out["reasons"]), out["reasons"]


def test_a_put_reverses_the_sign_the_same_way():
    from mios_v5.decision_v2 import decide

    spot = 24_400.0
    act = dict(_ACTIVE, side="PUT", entry_spot=24_523.5, target=24_300.0)
    out = decide(position=_open_position({"_entry_gate_active": act}),
                 spot=spot, market_state={"state": "TREND_DOWN"})
    app_gain = act["entry_spot"] - spot              # vob_minimal.py:8267, PUT
    assert any(f"{app_gain:+.0f} pts" in r for r in out["reasons"]), out["reasons"]


# ══════════════════════════════════════════════════════════════════════
#  what must NOT come through
# ══════════════════════════════════════════════════════════════════════

def test_the_premium_keyed_producer_is_not_used():
    """⚠️ `_entry_signal_open` is per-leg and its `entry` is an option PREMIUM.
    `gain = 24,500 - 120` would drive TRAIL/SCALE_IN off a meaningless number."""
    src = inspect.getsource(_open_position)
    read = {n.args[0].value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)}
    assert "_entry_gate_active" in read
    assert "_entry_signal_open" not in read
    assert "_entry_armed_setups" not in read


@pytest.mark.parametrize("side", ["", None, "ARMED_CALL", "ARMED_PUT", "WAIT",
                                  "CHOP_WAIT", "PINNED", "NO_ROOM", "REVERSED",
                                  "AT_ZONE_WAIT", 7, [], True, "CALLS", "LONG"])
def test_only_a_confirmed_call_or_put_counts_as_a_position(side):
    """⚠️ `_entry_gate_active` is only WRITTEN under `if _st_a in ('CALL','PUT')`
    (vob_minimal.py:8091), but the reader must not depend on that — an ARMED
    state leaking through would tell Stage 52 it is managing a trade that was
    never entered."""
    out = _open_position({"_entry_gate_active": dict(_ACTIVE, side=side)})
    assert out == {}, f"{side!r} was accepted as an open position"


@pytest.mark.parametrize("spelling", ["CALL", "call", " Call ", "cAlL"])
def test_a_sloppy_side_spelling_is_normalised(spelling):
    """The producer writes exactly 'CALL'/'PUT', so this is defensive only — but
    normalising costs nothing and a case-mismatch would read as flat."""
    out = _open_position({"_entry_gate_active": dict(_ACTIVE, side=spelling)})
    assert out["side"] == "CALL"


def test_a_missing_entry_still_reports_the_side():
    """Partial is fine ABOVE `side` — `_manage` handles `entry=None` (`gain`
    becomes None and it falls through to HOLD). Missing `side` is not."""
    out = _open_position({"_entry_gate_active":
                          {k: v for k, v in _ACTIVE.items() if k != "entry_spot"}})
    assert out == {"side": "CALL", "target": 24680.0}

    from mios_v5.decision_v2 import decide
    d = decide(position=out, spot=24_575.0, market_state={"state": "TREND_UP"})
    assert d["in_trade"] is True and d["state"] in ("HOLD", "TRAIL", "SCALE_OUT",
                                                    "SCALE_IN", "COMPLETE")


@pytest.mark.parametrize("junk", [None, {}, "nope", 7, [], ("side", "CALL"),
                                  {"side": "CALL", "entry_spot": "abc"},
                                  {"side": "CALL", "entry_spot": float("nan")}])
def test_junk_never_produces_a_broken_position(junk):
    out = _open_position({"_entry_gate_active": junk})
    assert isinstance(out, dict)
    if out:
        assert out["side"] in ("CALL", "PUT")
        assert "entry" not in out or isinstance(out["entry"], float)


def test_a_hostile_state_object_does_not_crash():
    class Hostile:
        def get(self, _k):
            raise RuntimeError("boom")
    assert _open_position(Hostile()) == {}


# ══════════════════════════════════════════════════════════════════════
#  the lifecycle that makes wiring safe at all
# ══════════════════════════════════════════════════════════════════════

def test_the_producer_is_cleared_on_exit():
    """⚠️ A position dict that is never cleared traps Stage 52 in `_manage`
    FOREVER — worse than the flat-forever bug this replaces. Both exit paths must
    keep popping it."""
    app = (_ROOT / "vob_minimal.py").read_text()
    assert app.count("st.session_state.pop('_entry_gate_active', None)") >= 2, (
        "an exit path stopped clearing the active trade")
    assert "if _st_a in ('CALL', 'PUT')" in app, (
        "the write is no longer gated to confirmed sides")


def test_it_is_wired_into_the_runners_raw():
    """A producer nothing forwards changes nothing — the original bug."""
    src = (_ROOT / "mios_v5" / "runner.py").read_text()
    tree = ast.parse(src)
    keys = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if (isinstance(t, ast.Name) and t.id == "raw"
                        and isinstance(n.value, ast.Dict)):
                    keys |= {k.value for k in n.value.keys
                             if isinstance(k, ast.Constant)}
    assert "open_position" in keys


def test_stage_52_sees_the_position_end_to_end():
    """Through the real engine, not the helper."""
    from mios_v5.core.contract import MarketState
    from mios_v5.engines.stage52_decision import DecisionEngineV2

    state = MarketState(raw={"spot": 24_575.0,
                             "open_position": _open_position(
                                 {"_entry_gate_active": _ACTIVE})})
    res = DecisionEngineV2().compute(state)
    assert (res.data or {}).get("in_trade") is True, res.evidence


# ══════════════════════════════════════════════════════════════════════
#  zone_extremes stays unwired, and the reason must stay written down
# ══════════════════════════════════════════════════════════════════════

def test_stage_52_still_cannot_enter_without_zone_extremes():
    """⚠️ Not "decides as if flat" — structurally incapable of an ENTER. Pinned so
    that if somebody supplies `zone_extremes`, this fails and forces the strategy
    decision to be made deliberately rather than as a side effect."""
    from mios_v5.floor_ceiling import CHECKS, detect_refusal, prove

    assert "refusal" in CHECKS
    assert detect_refusal([], floor=True)["proven"] is False
    assert detect_refusal(None, floor=False)["proven"] is False

    # and an otherwise-perfect proof cannot confirm without it
    p = prove(side="CALL", zone={"price": 24500.0, "strength": 80},
              extremes=[], ltp={"cvd": -9e9, "sellers": {"state": "EXHAUSTED"}},
              absorption={"behaviour": "SELLER_EXHAUSTION"},
              reaction={"action": "ENTER CALL"}, flow={"stability": "STABLE"},
              htf={"pct": 95}, validity={"pct": 95})
    assert p["confirmed"] is False
    assert p["checks"]["refusal"] is False


def test_zone_extremes_is_still_listed_as_unpublished_with_its_reason():
    from mios_v5.tests.test_screen_order import KNOWN_UNPUBLISHED

    assert "zone_extremes" in KNOWN_UNPUBLISHED
    assert "open_position" not in KNOWN_UNPUBLISHED, (
        "open_position is wired now — it must not still be excused")
    doc = (_ROOT / "docs" / "CONTRACT_POSITION_STATE.md").read_text()
    assert "zone_extremes" in doc and "never issue an ENTER" in doc
