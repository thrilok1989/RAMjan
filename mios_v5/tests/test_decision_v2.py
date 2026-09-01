"""Stage 52 — Decision Engine v2 (never enter on prediction)."""

from mios_v5.decision_v2 import (EVIDENCE_ENGINES, STATES, check_abort, decide,
                                 evidence_count)
from mios_v5.floor_ceiling import adaptive_stop, adaptive_trail, prove


def _ev(n=8):
    return {k: True for k in EVIDENCE_ENGINES[:n]}


def _proof(confirmed=True, n_passed=8, floor=True):
    return {"confirmed": confirmed, "side": "CALL" if floor else "PUT",
            "floor": floor, "entry": 23644 if floor else 23706,
            "n_passed": n_passed, "reasons": ["At support ₹23,650",
                                              "Price refusing lower levels",
                                              "Passive Buying confirmed"],
            "failed": []}


def test_all_states_declared():
    assert len(STATES) == 12
    for s in ("WAIT", "ENTRY_READY", "FLOOR_CONFIRMED", "CEILING_CONFIRMED",
              "ENTER", "HOLD", "SCALE_IN", "SCALE_OUT", "TRAIL", "EXIT",
              "COMPLETE", "ABORT"):
        assert s in STATES


def test_proof_is_required_to_enter():
    """The core rule: no proof, no entry — however good it looks."""
    d = decide(proof=_proof(confirmed=False, n_passed=7), evidence=_ev(),
               stop={"stop": 23632, "mode": "range-tight"})
    assert d["state"] == "ENTRY_READY"      # watching, NOT entering
    assert not d["actionable"]


def test_confirmed_proof_enters_at_the_refusal_price():
    d = decide(proof=_proof(), evidence=_ev(),
               stop={"stop": 23632, "mode": "range-tight"},
               trail={"mode": "normal"}, quality="A+")
    assert d["state"] == "ENTER" and d["side"] == "CALL"
    assert d["entry"] == 23644 and d["stop"] == 23632
    assert d["proof_state"] == "FLOOR_CONFIRMED"
    assert d["actionable"] and d["quality"] == "A+"


def test_never_from_a_single_engine():
    """However emphatic one engine is, thin evidence cannot produce a trade."""
    d = decide(proof=_proof(), evidence={"acceptance": True},
               stop={"stop": 23632})
    assert d["state"] == "WAIT"
    assert "engines reporting" in d["reasons"][0]
    assert evidence_count({"acceptance": True}) == 1


def test_no_valid_stop_means_no_trade():
    d = decide(proof=_proof(), evidence=_ev(),
               stop={"stop": None, "mode": "abort"})
    assert d["state"] == "WAIT"
    assert any("stop" in w.lower() for w in d["warnings"])


def test_abort_outranks_everything():
    d = decide(proof=_proof(), evidence=_ev(),
               stop={"stop": 23632, "mode": "range-tight"},
               flow={"stability": "SHOCK", "freeze_entries": True})
    assert d["state"] == "ABORT"
    assert any("flow shift" in r.lower() for r in d["reasons"])


def test_abort_closes_an_open_position_on_a_trap_against_it():
    d = decide(position={"side": "CALL", "entry": 23644},
               evidence=_ev(), reaction={"state": "BULL_TRAP"})
    assert d["state"] == "ABORT" and d["in_trade"]
    assert "Close the position now" in d["action"]


def test_abort_on_bias_reversal_against_the_position():
    d = decide(position={"side": "CALL", "entry": 23644}, evidence=_ev(),
               transition={"state": "REVERSING", "bias": "BEAR"})
    assert d["state"] == "ABORT"
    assert any("reversed" in r.lower() for r in d["reasons"])


def test_check_abort_is_quiet_when_nothing_is_wrong():
    a = check_abort({"side": "CALL"}, {"stability": "STABLE"},
                    {"state": "REJECTION"}, {"state": "STABLE", "bias": "BULL"})
    assert not a["abort"] and not a["reasons"]


def test_management_hold_trail_scale_and_complete():
    pos = {"side": "CALL", "entry": 23644, "target": 23720}

    hold = decide(position=pos, evidence=_ev(), spot=23648,
                  market_state={"state": "ROTATION"})
    assert hold["state"] == "HOLD" and hold["in_trade"]

    trail = decide(position=pos, evidence=_ev(), spot=23680,
                   market_state={"state": "TREND_UP"},
                   trail={"mode": "normal"})
    assert trail["state"] == "TRAIL"

    add = decide(position=pos, evidence=_ev(), spot=23680,
                 market_state={"state": "MARKUP"},
                 transition={"state": "STRENGTHENING"})
    assert add["state"] == "SCALE_IN"

    done = decide(position=pos, evidence=_ev(), spot=23725,
                  market_state={"state": "MARKUP"})
    assert done["state"] == "COMPLETE"


def test_scale_out_when_the_move_is_ending():
    pos = {"side": "CALL", "entry": 23644, "target": 23800}
    tired = decide(position=pos, evidence=_ev(), spot=23700,
                   absorption={"behaviour": "BUYER_EXHAUSTION"},
                   market_state={"state": "MARKUP"})
    assert tired["state"] == "SCALE_OUT"

    weak = decide(position=pos, evidence=_ev(), spot=23700,
                  transition={"state": "WEAKENING"},
                  market_state={"state": "MARKUP"})
    assert weak["state"] == "SCALE_OUT"


def test_end_to_end_the_worked_example():
    """Support 23,650 · price grinds to 23,644 and stops · everything agrees."""
    p = prove(side="CALL", zone={"price": 23650, "strength": 82},
              extremes=[23652, 23647, 23645, 23644, 23644, 23644],
              ltp={"cvd": -40, "sellers": {"state": "building"},
                   "buyers": {"state": "absorbing"}},
              absorption={"behaviour": "PASSIVE_BUYING"},
              reaction={"state": "REJECTION"}, flow={"stability": "STABLE"},
              htf={"pct": 88}, validity={"valid": True, "pct": 91})
    stop = adaptive_stop(p["entry"], floor=True, market_state="ROTATION",
                         atr=18, refusal_price=p["entry"])
    trail = adaptive_trail(True, market_state="ROTATION", atr=18)
    d = decide(proof=p, evidence=_ev(), stop=stop, trail=trail, quality="A+")

    assert d["state"] == "ENTER" and d["side"] == "CALL"
    assert d["entry"] == 23644                      # NOT 23,650
    assert d["stop"] < 23644
    assert d["confidence"] >= 85
    assert any("refusing lower" in r for r in d["reasons"])


def test_ceiling_end_to_end():
    p = prove(side="PUT", zone={"price": 23700, "strength": 85},
              extremes=[23698, 23703, 23705, 23706, 23706, 23706],
              ltp={"cvd": 40, "buyers": {"state": "building"},
                   "sellers": {"state": "absorbing"}},
              absorption={"behaviour": "PASSIVE_SELLING"},
              reaction={"state": "REJECTION"}, flow={"stability": "STABLE"},
              htf={"pct": 80}, validity={"valid": True, "pct": 88})
    d = decide(proof=p, evidence=_ev(),
               stop=adaptive_stop(p["entry"], floor=False,
                                  market_state="ROTATION", atr=18))
    assert d["state"] == "ENTER" and d["side"] == "PUT"
    assert d["entry"] == 23706 and d["stop"] > 23706


def test_flat_and_nothing_happening_is_wait():
    d = decide(proof={"confirmed": False, "n_passed": 1}, evidence=_ev())
    assert d["state"] == "WAIT" and not d["actionable"]


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"decision v2 tests passed ({len(fns)})")
