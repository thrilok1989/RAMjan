"""Stage 37 — Market Energy (promoted to a first-class engine)."""

from mios_v5.energy import STATES, advise, classify, risk_label


def test_dead_energy():
    r = classify(energy=15, compression=10, breakout_risk=5)
    assert r["state"] == "DEAD" and not r["tradeable"]
    assert "dead" in advise(r).lower()


def test_compression_is_loaded_not_dead():
    """The core distinction: quiet-because-coiled ≠ quiet-because-damped."""
    coiled = classify(energy=70, compression=80, breakout_risk=55)
    damped = classify(energy=15, compression=80, breakout_risk=5)
    assert coiled["state"] == "COMPRESSION" and coiled["tradeable"]
    assert damped["state"] == "DEAD" and not damped["tradeable"]
    assert coiled["release_probability"] > damped["release_probability"]


def test_expansion_when_breakout_risk_high():
    r = classify(energy=80, compression=20, breakout_risk=85)
    assert r["state"] == "EXPANSION"
    assert r["release_probability"] >= 75
    assert "with the move" in advise(r).lower()


def test_release_detected_when_a_coil_lets_go():
    r = classify(energy=75, compression=30, breakout_risk=60,
                 prev_state="COMPRESSION", prev_compression=78)
    assert r["state"] == "RELEASED"


def test_duration_raises_release_probability():
    fresh = classify(energy=70, compression=75, breakout_risk=50,
                     duration_cycles=0)
    aged = classify(energy=70, compression=75, breakout_risk=50,
                    duration_cycles=12)
    assert aged["release_probability"] > fresh["release_probability"]
    assert aged["confidence"] > fresh["confidence"]


def test_expansion_readiness_scales():
    low = classify(energy=30, compression=10, breakout_risk=10)
    high = classify(energy=85, compression=85, breakout_risk=85)
    assert high["expansion_readiness"] > low["expansion_readiness"]


def test_risk_labels():
    assert risk_label(10) == "Low" and risk_label(90) == "Very High"
    assert risk_label(None) == "Unknown"


def test_missing_energy_is_honest():
    r = classify(None, None, None)
    assert not r["ready"] and r["state"] is None and r["confidence"] == 0


def test_all_states_are_declared():
    for e, c, b in ((15, 5, 5), (70, 80, 40), (55, 30, 20), (85, 10, 90)):
        assert classify(e, c, b)["state"] in STATES


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"market energy tests passed ({len(fns)})")
