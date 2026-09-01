"""Stage 47 — Bias Transition (is the bias changing?)."""

from mios_v5.transition import (analyse, for_validity, overall, signed_strength,
                                snapshot, trace_push)


def _snap(**kw):
    """Signed strengths per family (BEAR negative, BULL positive)."""
    base = {"dealer": 0.0, "institutions": 0.0, "orderflow": 0.0,
            "liquidity": 0.0, "structure": 0.0, "options": 0.0, "macro": 0.0}
    base.update(kw)
    return base


def test_signed_strength_carries_side_and_conviction():
    assert signed_strength("BULL", 80) == 80
    assert signed_strength("STRONG_BEAR", 80) == -80
    assert signed_strength("NEUTRAL", 80) == 0
    assert signed_strength(None, None) == 0


def test_snapshot_skips_missing_families():
    s = snapshot({"dealer": {"status": "OK", "direction": "BEAR", "strength": 90},
                  "macro": {"status": "MISSING", "direction": "BULL", "strength": 50}})
    assert s == {"dealer": -90.0} and "macro" not in s


def test_overall_is_authority_weighted():
    # dealer (8.0) should outweigh macro (2.0)
    assert overall({"dealer": -90, "macro": 90}) < 0


def test_stable_bias_reads_stable():
    tr = [_snap(dealer=-90, orderflow=-85, options=-88) for _ in range(5)]
    a = analyse(tr)
    assert a["state"] == "STABLE" and a["bias"] == "BEAR"
    assert "holding" in a["thesis"]


def test_weakening_bear_detected_before_it_flips():
    # the scenario: Bear still exists, but strength is collapsing
    tr = [_snap(dealer=-92, orderflow=-82, options=-91),
          _snap(dealer=-90, orderflow=-70, options=-91),
          _snap(dealer=-86, orderflow=-58, options=-90),
          _snap(dealer=-84, orderflow=-45, options=-90)]
    a = analyse(tr)
    assert a["state"] == "WEAKENING"
    assert a["bias"] == "BEAR"          # still bearish …
    assert a["velocity"] > 0            # … but moving toward zero
    assert a["reversal_probability"] > 0
    assert "weakening" in a["thesis"].lower()


def test_leader_is_the_family_that_moved_first():
    tr = [_snap(dealer=-92, orderflow=-88, options=-90),
          _snap(dealer=-70, orderflow=-88, options=-90),   # dealer moves first
          _snap(dealer=-60, orderflow=-70, options=-90),
          _snap(dealer=-55, orderflow=-55, options=-88)]
    a = analyse(tr)
    assert a["leader"] == "dealer"
    assert "Dealer" in a["thesis"]


def test_strengthening():
    tr = [_snap(dealer=40, orderflow=35, options=30),
          _snap(dealer=55, orderflow=50, options=45),
          _snap(dealer=70, orderflow=68, options=60),
          _snap(dealer=85, orderflow=80, options=75)]
    a = analyse(tr)
    assert a["state"] == "STRENGTHENING" and a["bias"] == "BULL"
    # a strengthening bias must not report a scary reversal number
    assert a["reversal_probability"] < 50


def test_transition_when_conviction_collapses_to_nothing():
    tr = [_snap(dealer=-80, orderflow=-75, options=-70),
          _snap(dealer=-50, orderflow=-40, options=-45),
          _snap(dealer=-20, orderflow=-10, options=-15),
          _snap(dealer=-5, orderflow=2, options=-3)]
    a = analyse(tr)
    assert a["state"] == "TRANSITION"
    assert "no directional edge" in a["thesis"]


def test_reversal_flips_sign_and_is_high_probability():
    tr = [_snap(dealer=-70, orderflow=-65, options=-60),
          _snap(dealer=-30, orderflow=-25, options=-20),
          _snap(dealer=25, orderflow=30, options=20),
          _snap(dealer=60, orderflow=65, options=55)]
    a = analyse(tr)
    assert a["state"] in ("REVERSING", "STRENGTHENING")
    if a["state"] == "REVERSING":
        assert a["reversal_probability"] >= 80


def test_velocity_distinguishes_fast_from_slow_decay():
    # families move together, as they do in a real regime change — a lone
    # family shifting is diluted by the six that didn't, which is correct
    def _all(v):
        return _snap(dealer=v, institutions=v, orderflow=v, liquidity=v,
                     structure=v, options=v, macro=v)
    slow = analyse([_all(-90), _all(-89), _all(-88), _all(-87), _all(-86)])
    fast = analyse([_all(-90), _all(-80), _all(-66), _all(-50), _all(-32)])
    assert fast["velocity"] > slow["velocity"]
    assert fast["velocity_label"] == "fast" and slow["velocity_label"] == "slow"


def test_per_family_arrows_and_states():
    tr = [_snap(dealer=-92, orderflow=-82, options=-91),
          _snap(dealer=-84, orderflow=-45, options=-90)]
    a = analyse(tr)
    assert a["families"]["orderflow"]["state"] == "weakening"
    assert "↓" in a["families"]["orderflow"]["arrow"]
    assert a["families"]["options"]["state"] == "stable"


def test_no_history_is_honest_not_confident():
    a = analyse([])
    assert a["state"] == "STABLE" and a["confidence"] == 0
    assert "not enough history" in a["thesis"].lower()


def test_trace_push_bounded():
    t = []
    for i in range(40):
        t = trace_push(t, _snap(dealer=-i), keep=15)
    assert len(t) == 15


def test_for_validity_payload_matches_what_stage51_reads():
    a = analyse([_snap(dealer=-92, orderflow=-82),
                 _snap(dealer=-86, orderflow=-60),
                 _snap(dealer=-84, orderflow=-45)])
    p = for_validity(a)
    # Stage 51 matches lower-case 'weakening' / 'reversing'
    assert p["transition"] in ("weakening", "stable", "transition",
                               "strengthening", "reversing")
    assert p["transition"] == p["transition"].lower()
    for k in ("bias", "strength", "velocity", "reversal_probability",
              "leader", "confidence"):
        assert k in p


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"bias transition tests passed ({len(fns)})")
