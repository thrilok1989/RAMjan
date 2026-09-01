"""MIOS V6 — tests for the independent V6 bias and the V5 ‖ V6 comparison."""

from mios_v5.v6_bias import (WEIGHTS, compare, compute, sign)


def _fr(**kw):
    """A final read with the four V6 voters present unless overridden."""
    base = {
        "preferred_bias": "BULL",
        "confidence": 71,
        "families_read": {"dominant": "BULL", "agreement_pct": 80,
                          "severity": "LOW"},
        "reaction": {"state": "REJECTION", "label": "🟢 Rejection",
                     "winner": "Buyers", "confidence": 78, "side": "SUPPORT"},
        "htf": {"alignment": {"bias": "BULL", "score": 72, "stars": "★★★★☆",
                              "label": "4/6 Bull", "disagree": []}},
        "absorption": {"behaviour": "PASSIVE_BUYING", "tone": "bull",
                       "label": "🟢 Passive Buying", "confidence": 70},
    }
    base.update(kw)
    return base


def test_all_four_voters_agree_gives_a_strong_read():
    r = compute(_fr())
    assert r["bias"] in ("BULL", "STRONG_BULL")
    assert r["coverage"] == 4 and r["coverage_of"] == len(WEIGHTS)
    assert r["confidence"] > 40
    assert r["agreement_pct"] == 100


def test_no_voters_is_honest_rather_than_neutral():
    r = compute({"preferred_bias": "BULL", "confidence": 80})
    assert r["bias"] == "NONE" and r["confidence"] == 0
    assert "warming up" in r["sentence"]
    # it must not silently agree with V5 just because it has nothing to say
    assert r["agrees"] is None


def test_reaction_outweighs_htf_when_they_conflict():
    """Executed evidence over derived evidence — a rejection that HAPPENED
    carries more weight than a higher-timeframe inference about what SHOULD
    happen. Two near-equal voters in opposition still land NEUTRAL, which is
    the honest answer; what must hold is which way the net leans."""
    fr = _fr(families_read=None, absorption=None,
             reaction={"winner": "Buyers", "confidence": 80,
                       "label": "Rejection", "state": "REJECTION"},
             htf={"alignment": {"bias": "BEAR", "score": 80, "stars": "",
                                "label": "4/6 Bear", "disagree": []}})
    r = compute(fr)
    assert WEIGHTS["reaction"] > WEIGHTS["htf"]
    assert r["bull_weight"] > r["bear_weight"]
    assert sign(r["bias"]) >= 0, r          # never BEAR
    # a 2-voter standoff is not a signal
    assert r["bias"] == "NEUTRAL" and r["confidence"] <= 40


def test_families_is_the_heaviest_voter():
    assert WEIGHTS["families"] == max(WEIGHTS.values())


def test_transition_weakening_discounts_but_does_not_flip():
    strong = compute(_fr())
    weak = compute(_fr(transition={"state": "WEAKENING", "bias": "BULL",
                                   "label": "↓ Weakening"}))
    assert weak["bias"] == strong["bias"]          # direction unchanged
    assert weak["confidence"] < strong["confidence"]
    assert any(m["key"] == "transition" for m in weak["modifiers"])


def test_transition_pointing_the_other_way_bites_harder():
    same = compute(_fr(transition={"state": "WEAKENING", "bias": "BULL",
                                   "label": "↓ Weakening"}))
    against = compute(_fr(transition={"state": "WEAKENING", "bias": "BEAR",
                                      "label": "↓ Weakening"}))
    assert against["confidence"] < same["confidence"]


def test_transition_never_adds_a_vote():
    """Stage 47's bias is derived from Stage 53's families — letting it vote
    would count the family read twice."""
    r = compute(_fr(transition={"state": "STRENGTHENING", "bias": "BULL",
                                "label": "↑"}))
    assert all(v["key"] != "transition" for v in r["voters"])
    assert r["coverage"] == 4


def test_flow_shift_freezes_the_read():
    r = compute(_fr(flow_shift={"freeze_entries": True, "score": 82,
                                "reason": "CVD swing"}))
    assert r["frozen"] is True
    assert r["confidence"] <= 25
    assert "frozen" in r["sentence"].lower()


def test_recovery_caps_confidence_without_freezing():
    r = compute(_fr(stability="RECOVERY"))
    assert r["frozen"] is False
    assert r["confidence"] <= 60


def test_invalid_validity_caps_the_matching_side():
    ok = compute(_fr())
    bad = compute(_fr(validity_both={
        "CALL": {"verdict": "INVALID", "valid": False, "pct": 38},
        "PUT": {"verdict": "VALID", "valid": True, "pct": 70}}))
    assert bad["confidence"] < ok["confidence"]
    assert any("validity" in n for n in bad["gates"]["notes"])


def test_fresh_state_is_discounted_and_mature_is_not():
    fresh = compute(_fr(memory_read={"state": "TREND", "state_fresh": True,
                                     "state_duration_min": 2.0}))
    mature = compute(_fr(memory_read={"state": "TREND", "state_mature": True,
                                      "state_duration_min": 40.0}))
    assert fresh["confidence"] < mature["confidence"]


def test_high_transition_risk_discounts():
    calm = compute(_fr(memory_read={"state": "TREND", "state_mature": True,
                                    "state_duration_min": 40.0,
                                    "state_transition_risk": 10}))
    risky = compute(_fr(memory_read={"state": "TREND", "state_mature": True,
                                     "state_duration_min": 40.0,
                                     "state_transition_risk": 75}))
    assert risky["confidence"] < calm["confidence"]


def test_partial_coverage_lowers_confidence():
    full = compute(_fr())
    part = compute(_fr(htf=None, absorption=None))
    assert part["coverage"] == 2
    assert part["confidence"] < full["confidence"]


def test_split_voters_land_neutral_with_low_confidence():
    fr = _fr(families_read={"dominant": "BULL", "agreement_pct": 70,
                            "severity": "HIGH"},
             reaction={"winner": "Sellers", "confidence": 78,
                       "label": "Breakdown", "state": "CONFIRMED_BREAKDOWN"},
             htf={"alignment": {"bias": "BEAR", "score": 70, "stars": "",
                                "label": "4/6 Bear", "disagree": []}},
             absorption={"behaviour": "PASSIVE_BUYING", "tone": "bull",
                         "label": "x", "confidence": 70})
    r = compute(fr)
    assert r["bias"] == "NEUTRAL"
    assert r["confidence"] <= 40
    assert r["agreement_pct"] < 100


def test_neutral_families_does_not_vote():
    r = compute(_fr(families_read={"dominant": "NEUTRAL", "agreement_pct": 40,
                                   "severity": "HIGH"}))
    assert all(v["key"] != "families" for v in r["voters"])


def test_absorption_none_does_not_vote():
    r = compute(_fr(absorption={"behaviour": "NONE", "tone": "neutral",
                                "confidence": 0}))
    assert all(v["key"] != "absorption" for v in r["voters"])


def test_divergence_is_explained_when_they_disagree():
    fr = _fr(preferred_bias="BEAR")
    c = compare(fr)
    assert c["agrees"] is False
    assert c["divergence"] and "OPPOSITE" in c["divergence"]


def test_agreement_produces_no_divergence_text():
    c = compare(_fr())
    assert c["agrees"] is True and c["divergence"] is None


def test_v5_neutral_v6_directional_is_explained_not_hidden():
    c = compare(_fr(preferred_bias="NEUTRAL"))
    assert c["agrees"] is False
    assert "V5 calls flat" in (c["divergence"] or "")


def test_compare_normalises_odd_v5_labels():
    c = compare(_fr(preferred_bias="STRONG_BULL"))
    assert c["v5"]["bias"] == "STRONG_BULL"
    assert c["v5"]["label"] == "STRONG BULLISH"
    c2 = compare(_fr(preferred_bias=None, families_read=None, reaction=None,
                     htf=None, absorption=None))
    assert c2["v5"]["bias"] == "NONE"


def test_read_is_always_advisory():
    assert compute(_fr())["advisory_only"] is True
    assert compute({})["advisory_only"] is True


def test_none_input_never_raises():
    r = compute(None)
    assert r["bias"] == "NONE"
    c = compare(None)
    assert c["v5"]["bias"] == "NONE" and c["v6"]["bias"] == "NONE"


def test_html_strip_renders_and_is_empty_when_blank():
    from mios_v5.ui.bias_compare import bias_compare_html, v6_detail_html
    html = bias_compare_html(compare(_fr()))
    assert "MIOS V5" in html and "MIOS V6" in html
    assert "observational" in html
    assert bias_compare_html(None) == ""
    d = v6_detail_html(compute(_fr()))
    assert "S53" in d and "S42" in d


def test_disagreement_is_flagged_loudly_in_html():
    from mios_v5.ui.bias_compare import bias_compare_html
    html = bias_compare_html(compare(_fr(preferred_bias="BEAR")))
    assert "DISAGREE" in html


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"v6 bias tests passed ({len(fns)})")
