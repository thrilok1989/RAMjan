"""Stage 52 — Floor / Ceiling proof (never enter on prediction)."""

from mios_v5.floor_ceiling import (CHECKS, adaptive_stop, adaptive_trail,
                                   detect_refusal, prove)


def _ok_floor(**over):
    """Everything a FLOOR needs, so each test can knock out one thing."""
    kw = dict(
        side="CALL",
        zone={"price": 23650, "strength": 82},
        # ground down to 23644 and stopped — the proof
        extremes=[23652, 23647, 23645, 23644, 23644, 23644],
        ltp={"cvd": -40, "sellers": {"state": "building"},
             "buyers": {"state": "absorbing"}},
        absorption={"behaviour": "PASSIVE_BUYING", "label": "Passive Buying"},
        reaction={"state": "REJECTION"},
        flow={"stability": "STABLE"},
        htf={"pct": 88},
        validity={"valid": True, "pct": 91},
    )
    kw.update(over)
    return kw


def test_the_worked_example_enters_at_the_refusal_not_the_zone():
    r = prove(**_ok_floor())
    assert r["confirmed"] and r["label"] == "FLOOR CONFIRMED"
    # support is 23,650 — but the market proved itself at 23,644
    assert r["entry"] == 23644
    assert r["zone_price"] == 23650
    assert r["n_passed"] == 8


def test_prediction_alone_is_never_enough():
    """Everything bullish, but price is STILL making new lows → no entry."""
    r = prove(**_ok_floor(extremes=[23652, 23648, 23644, 23640, 23636]))
    assert not r["confirmed"]
    assert r["checks"]["refusal"] is False
    assert any("new low" in f for f in r["failed"])


def test_refusal_needs_pressure_to_have_arrived():
    """A quiet level nobody tested proves nothing."""
    r = prove(**_ok_floor(ltp={"cvd": -1, "sellers": {"state": "neutral"},
                               "buyers": {"state": "neutral"}}))
    assert not r["confirmed"] and r["checks"]["pressure"] is False
    assert any("nothing has been tested" in f for f in r["failed"])


def test_rejection_at_support_QUALIFIES_as_floor_proof():
    """At a SUPPORT, 'rejection' = price probed lower and was pushed back.
    That IS the floor — excluding it would block the primary entry case."""
    assert prove(**_ok_floor(reaction={"state": "REJECTION"}))["checks"]["reaction"]
    assert prove(**_ok_floor(reaction={"state": "DEFENDED"}))["checks"]["reaction"]
    assert prove(**_ok_floor(reaction={"state": "BEAR_TRAP"}))["checks"]["reaction"]


def test_states_that_genuinely_invalidate_a_floor():
    for bad in ("CONFIRMED_BREAKDOWN", "BULL_TRAP", "FAILED_BREAKOUT"):
        r = prove(**_ok_floor(reaction={"state": bad}))
        assert not r["confirmed"] and r["checks"]["reaction"] is False


def test_every_gate_can_veto_on_its_own():
    assert not prove(**_ok_floor(zone={}))["confirmed"]
    assert not prove(**_ok_floor(absorption={"behaviour": "NONE"}))["confirmed"]
    assert not prove(**_ok_floor(flow={"stability": "SHOCK"}))["confirmed"]
    assert not prove(**_ok_floor(htf={"pct": 30}))["confirmed"]
    assert not prove(**_ok_floor(validity={"valid": False, "pct": 41,
                                           "reasons": ["HTF conflict"]}))["confirmed"]


def test_ceiling_mirrors_the_floor():
    r = prove(side="PUT", zone={"price": 23700, "strength": 85},
              extremes=[23698, 23703, 23705, 23706, 23706, 23706],
              ltp={"cvd": 40, "buyers": {"state": "building"},
                   "sellers": {"state": "absorbing"}},
              absorption={"behaviour": "PASSIVE_SELLING"},
              reaction={"state": "REJECTION"}, flow={"stability": "STABLE"},
              htf={"pct": 80}, validity={"valid": True, "pct": 88})
    assert r["confirmed"] and r["label"] == "CEILING CONFIRMED"
    assert r["entry"] == 23706          # the high it could not exceed


def test_refusal_requires_enough_attempts():
    few = detect_refusal([23644, 23644], floor=True)
    assert not few["proven"] and "attempts" in few["reason"]
    many = detect_refusal([23650, 23646, 23644, 23644, 23644], floor=True)
    assert many["proven"] and many["price"] == 23644


def test_refusal_detects_still_falling():
    r = detect_refusal([23660, 23652, 23646, 23640, 23634], floor=True)
    assert not r["proven"]


def test_adaptive_stop_by_mood():
    trend = adaptive_stop(23644, floor=True, market_state="MARKUP", atr=30)
    rng = adaptive_stop(23644, floor=True, market_state="ROTATION", atr=30)
    assert trend["distance"] > rng["distance"]      # trends need room
    assert trend["stop"] < 23644 and rng["stop"] < 23644

    comp = adaptive_stop(23644, floor=True, energy_state="COMPRESSION", atr=30)
    assert comp["mode"] == "below-accumulation"
    exp = adaptive_stop(23644, floor=True, energy_state="EXPANSION", atr=30)
    assert exp["mode"] == "atr"


def test_shock_has_no_valid_stop_it_has_an_abort():
    r = adaptive_stop(23644, floor=True, energy_state="SHOCK")
    assert r["stop"] is None and r["mode"] == "abort"


def test_stop_sits_beyond_the_refusal_not_the_entry():
    r = adaptive_stop(23650, floor=True, market_state="ROTATION", atr=20,
                      refusal_price=23644)
    assert r["stop"] < 23644


def test_adaptive_trail_loosens_and_tightens():
    strong = adaptive_trail(True, market_state="MARKUP",
                            transition={"state": "STRENGTHENING"}, atr=30)
    assert strong["mode"] == "loose" and strong["multiplier"] > 2

    weak = adaptive_trail(True, market_state="MARKUP",
                          transition={"state": "WEAKENING"}, atr=30)
    assert weak["mode"] == "lock-profit" and weak["multiplier"] < strong["multiplier"]

    tired = adaptive_trail(True, market_state="TREND_UP",
                           absorption={"behaviour": "BUYER_EXHAUSTION"}, atr=30)
    assert tired["mode"] == "tight"

    flipped = adaptive_trail(True, market_state="TREND_UP", dealer_flip=True,
                             atr=30)
    assert flipped["multiplier"] <= 0.7

    shocked = adaptive_trail(True, market_state="TREND_UP",
                             flow={"stability": "SHOCK"}, atr=30)
    assert shocked["mode"] == "review"


def test_all_checks_are_declared_and_reported():
    r = prove(**_ok_floor())
    assert set(r["checks"]) == set(CHECKS)
    assert len(r["reasons"]) >= 6


def test_empty_input_is_safe():
    r = prove("CALL")
    assert not r["confirmed"] and r["entry"] is None
    assert adaptive_stop(None, True)["stop"] is None


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"floor/ceiling tests passed ({len(fns)})")
