"""Stage 51 — Signal Validity Filter (the gatekeeper)."""

from mios_v5.validity import WEIGHTS, evaluate_validity


def _good(**over):
    """A context where everything supports a CALL."""
    c = {"bias": "BULL", "bias_transition": "strengthening",
         "htf_validity_pct": 92, "dealer_bias": "BULL",
         "institutions_bias": "BULL", "reaction_state": "CONFIRMED_BREAKOUT",
         "flow_stability": "STABLE", "energy": 65, "orderflow_bias": "BULL",
         "zone_lifecycle": "building", "zone_health_pct": 84}
    c.update(over)
    return c


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_full_agreement_is_valid():
    v = evaluate_validity("CALL", _good())
    assert v["valid"] and v["verdict"] == "VALID"
    assert v["pct"] >= 95 and v["stars"].count("★") == 5
    assert not v["failed"] and not v["vetoes"]
    assert "Bias" in v["passed"] and "HTF Alignment" in v["passed"]


def test_higher_timeframes_against_rejects():
    v = evaluate_validity("CALL", _good(htf_validity_pct=42,
                                        institutions_bias="BEAR",
                                        dealer_bias="BEAR",
                                        zone_lifecycle="fading"))
    assert not v["valid"] and v["verdict"] == "INVALID"
    assert any("HTF" in f for f in v["failed"])
    assert any("Institutions" in f for f in v["failed"])


def test_every_rejection_explains_itself():
    v = evaluate_validity("CALL", _good(institutions_bias="BEAR",
                                        dealer_bias="BEAR",
                                        orderflow_bias="BEAR",
                                        htf_validity_pct=30))
    assert not v["valid"]
    assert v["reasons"], "a rejection with no reason is untrustworthy"
    assert all(isinstance(r, str) and r for r in v["reasons"])


def test_flow_shock_is_a_hard_veto_regardless_of_score():
    v = evaluate_validity("CALL", _good(flow_stability="SHOCK"))
    assert not v["valid"] and v["vetoes"]
    assert any("flow shift" in x.lower() for x in v["vetoes"])


def test_live_event_is_a_hard_veto():
    v = evaluate_validity("CALL", _good(event_active=True))
    assert not v["valid"] and any("event" in x.lower() for x in v["vetoes"])


def test_unconfirmed_failed_break_is_vetoed():
    v = evaluate_validity("PUT", _good(bias="BEAR", dealer_bias="BEAR",
                                       institutions_bias="BEAR",
                                       orderflow_bias="BEAR",
                                       reaction_state="FAILED_BREAKOUT"))
    assert not v["valid"]
    assert any("not confirmed" in x.lower() for x in v["vetoes"])


def test_confirmed_trap_is_tradable():
    # a BULL TRAP is a confirmed short setup
    v = evaluate_validity("PUT", _good(bias="BEAR", dealer_bias="BEAR",
                                       institutions_bias="BEAR",
                                       orderflow_bias="BEAR",
                                       htf_validity_pct=88,
                                       reaction_state="BULL_TRAP",
                                       zone_lifecycle="holding"))
    assert v["valid"] and "Trap Confirmation" in v["passed"]


def test_weakening_bias_does_not_count_as_support():
    strong = evaluate_validity("CALL", _good(bias_transition="strengthening"))
    weak = evaluate_validity("CALL", _good(bias_transition="weakening"))
    assert weak["pct"] < strong["pct"]
    assert any("weakening" in f for f in weak["failed"])


def test_neutral_is_no_support_but_not_missing():
    v = evaluate_validity("CALL", _good(institutions_bias="NEUTRAL"))
    assert v["checks"]["institutions"] is False       # scored, and it failed
    assert v["coverage"] == 100


def test_missing_inputs_are_excluded_not_passed():
    v = evaluate_validity("CALL", {"bias": "BULL", "dealer_bias": "BULL"})
    # only 2 of 9 checks available → cannot judge
    assert v["checks"]["htf"] is None
    assert not v["valid"] and v["coverage"] < 60
    assert any("insufficient evidence" in r.lower() for r in v["reasons"])


def test_no_evidence_at_all_is_invalid_not_valid():
    v = evaluate_validity("CALL", {})
    assert not v["valid"] and v["pct"] == 0


def test_partial_but_sufficient_evidence_can_pass():
    v = evaluate_validity("CALL", {
        "bias": "BULL", "htf_validity_pct": 90, "dealer_bias": "BULL",
        "institutions_bias": "BULL", "orderflow_bias": "BULL",
        "flow_stability": "STABLE", "reaction_state": "CONFIRMED_BREAKOUT"})
    assert v["coverage"] >= 60 and v["valid"]


def test_side_mirroring():
    bull_ctx = _good()
    assert evaluate_validity("CALL", bull_ctx)["valid"]
    assert not evaluate_validity("PUT", bull_ctx)["valid"]


def test_unknown_side_is_safe():
    v = evaluate_validity(None, _good())
    assert v["verdict"] == "UNKNOWN" and not v["valid"]


def test_it_never_creates_a_signal():
    v = evaluate_validity("CALL", _good())
    for forbidden in ("action", "entry", "target", "stop", "decision"):
        assert forbidden not in v


def test_imminent_reversal_vetoes_trading_the_prevailing_bias():
    """A collapsing bear is still 'BEAR', but shorts into it must be refused."""
    ctx = _good(bias="BEAR", dealer_bias="BEAR", institutions_bias="BEAR",
                orderflow_bias="BEAR", reaction_state="CONFIRMED_BREAKDOWN",
                bias_transition="weakening", reversal_probability=78)
    v = evaluate_validity("PUT", ctx)
    assert not v["valid"]
    assert any("reversal probability" in x.lower() for x in v["vetoes"])
    # and a low reversal number must NOT veto
    ok = evaluate_validity("PUT", dict(ctx, reversal_probability=20))
    assert not ok["vetoes"]


def test_dead_energy_fails_the_energy_gate():
    v = evaluate_validity("CALL", _good(energy_state="DEAD", energy=12))
    assert v["checks"]["energy"] is False
    assert any("energy dead" in f.lower() for f in v["failed"])


def test_compression_energy_still_counts_as_alive():
    v = evaluate_validity("CALL", _good(energy_state="COMPRESSION", energy=70))
    assert v["checks"]["energy"] is True


def test_full_nine_of_nine_coverage_is_reachable():
    """With Stage 37 promoted, every gate has a real input — 9/9, no Nones."""
    v = evaluate_validity("CALL", _good(energy_state="EXPANSION",
                                        reversal_probability=15))
    assert v["coverage"] == 100
    assert all(x is not None for x in v["checks"].values())
    assert len(v["checks"]) == 9


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"signal validity tests passed ({len(fns)})")
