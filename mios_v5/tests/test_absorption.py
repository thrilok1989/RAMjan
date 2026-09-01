"""Stage 43 — Institutional Absorption (WHY it is happening)."""

from mios_v5.absorption import (BEHAVIOURS, EXPECTATION, LABEL, classify,
                                story, trace_push)


def _ltp(price="flat", buyers="neutral", sellers="neutral",
         volume="healthy", flow="neutral"):
    return {"price": {"state": price}, "buyers": {"state": buyers},
            "sellers": {"state": sellers}, "volume": {"state": volume},
            "flow": {"state": flow}}


def test_passive_buying_is_the_counter_intuitive_read():
    """Heavy aggressive SELLING into flat price is bullish — someone is being
    filled. A retail read sees selling; the institutional read sees a buyer."""
    r = classify(ltp=_ltp(price="flat", buyers="absorbing", sellers="building"),
                 reaction={"state": "REJECTION"})
    assert r["behaviour"] == "PASSIVE_BUYING"
    assert r["tone"] == "bull" and r["passive"]
    assert "accumulation" in r["expectation"].lower()


def test_passive_selling_mirrors():
    r = classify(ltp=_ltp(price="flat", sellers="absorbing", buyers="building"),
                 reaction={"state": "REJECTION"})
    assert r["behaviour"] == "PASSIVE_SELLING" and r["tone"] == "bear"
    assert "distribution" in r["expectation"].lower()


def test_aggressive_buying_needs_price_volume_and_delta_together():
    r = classify(ltp=_ltp(price="rising", buyers="building", volume="healthy"))
    assert r["behaviour"] == "AGGRESSIVE_BUYING" and r["aggressive"]
    # rising price alone, on dry volume, is NOT aggression — it's exhaustion
    r2 = classify(ltp=_ltp(price="rising", buyers="neutral", volume="dry"))
    assert r2["behaviour"] == "BUYER_EXHAUSTION"


def test_aggressive_selling():
    r = classify(ltp=_ltp(price="falling", sellers="building",
                          volume="explosive"))
    assert r["behaviour"] == "AGGRESSIVE_SELLING"


def test_exhaustion_from_stage50_state():
    r = classify(ltp=_ltp(price="rising", buyers="exhausted"))
    assert r["behaviour"] == "BUYER_EXHAUSTION"
    assert "reversal risk" in r["expectation"].lower()
    r2 = classify(ltp=_ltp(price="falling", sellers="exhausted"))
    assert r2["behaviour"] == "SELLER_EXHAUSTION" and r2["tone"] == "bull"


def test_reloading_requires_a_gap_between_episodes():
    """absorb → pause → absorb again = programme. Continuous absorption is
    just one long fill and must NOT be called reloading."""
    lb = _ltp(price="flat", buyers="absorbing", sellers="building")
    continuous = ["PASSIVE_BUYING"] * 6
    assert classify(ltp=lb, trace=continuous)["behaviour"] == "PASSIVE_BUYING"

    gapped = ["PASSIVE_BUYING", "NONE", "NONE", "PASSIVE_BUYING"]
    r = classify(ltp=lb, trace=gapped)
    assert r["behaviour"] == "BUYER_RELOADING"
    assert "programme" in " ".join(r["reasons"]).lower()


def test_seller_reloading():
    lb = _ltp(price="flat", sellers="absorbing", buyers="building")
    gapped = ["PASSIVE_SELLING", "NONE", "NONE", "PASSIVE_SELLING"]
    assert classify(ltp=lb, trace=gapped)["behaviour"] == "SELLER_RELOADING"


def test_confidence_rises_with_duration_and_direct_evidence():
    lb = _ltp(price="flat", buyers="absorbing", sellers="building")
    short = classify(ltp=lb, duration_cycles=0)
    long_ = classify(ltp=lb, duration_cycles=8)
    assert long_["confidence"] > short["confidence"]
    assert long_["stars"].count("★") >= 4
    # a direct Stage-50 'absorbing' read beats an inference
    inferred = classify(ltp=_ltp(price="flat", sellers="building"),
                        reaction={"state": "REJECTION"})
    assert short["confidence"] > inferred["confidence"]


def test_no_footprint_when_nothing_lines_up():
    r = classify(ltp=_ltp(), reaction={})
    assert r["behaviour"] == "NONE" and r["confidence"] == 0
    assert "no clear institutional footprint" in story(r).lower()


def test_story_explains_rather_than_labels():
    r = classify(ltp=_ltp(price="flat", buyers="absorbing", sellers="building"),
                 duration_cycles=5)
    s = story(r, zone_label="Support ₹23,700")
    assert "passively absorbing aggressive selling" in s
    assert "Support ₹23,700" in s
    assert "inventory accumulation" in s and "panic" in s


def test_every_behaviour_has_label_tone_and_expectation():
    for b in BEHAVIOURS:
        assert b in LABEL and b in EXPECTATION


def test_trace_push_bounded():
    t = []
    for _ in range(30):
        t = trace_push(t, "PASSIVE_BUYING", keep=12)
    assert len(t) == 12


def test_it_never_claims_icebergs():
    """Iceberg detection needs L2 depth we don't receive — inferring it would
    be fabrication."""
    r = classify(ltp=_ltp(price="flat", buyers="absorbing"))
    blob = (str(r) + story(r)).lower()
    assert "iceberg" not in blob and "hidden order" not in blob


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"absorption tests passed ({len(fns)})")
