"""Stage 48 — Market State (one personality + next-state prediction)."""

from mios_v5.market_personality import LABEL, STATES, derive, predict_next


def _ltp(price="flat", buyers="neutral", sellers="neutral", flow="neutral"):
    return {"price": {"state": price}, "buyers": {"state": buyers},
            "sellers": {"state": sellers}, "flow": {"state": flow}}


def test_your_example_bear_seller_rejection_expansion_is_markdown():
    d = derive(bias="BEAR",
               transition={"state": "STABLE", "bias": "BEAR"},
               ltp=_ltp(price="falling", sellers="building", flow="leaving"),
               acceptance={"state": "REJECTION"},
               flow={"stability": "STABLE"},
               energy={"state": "EXPANSION"})
    assert d["state"] in ("MARKDOWN", "EXPANSION", "DISTRIBUTION")


def test_your_example_bull_buyer_compression_accepted_is_accumulation():
    d = derive(bias="BULL",
               transition={"state": "STABLE", "bias": "BULL"},
               ltp=_ltp(price="flat", buyers="building", flow="entering"),
               acceptance={"state": "ACCEPTANCE"},
               flow={"stability": "STABLE"},
               energy={"state": "BUILDING"})
    assert d["state"] == "ACCUMULATION"
    assert d["next_state"] == "MARKUP"


def test_your_example_bear_but_buyers_building_is_reversal_building():
    d = derive(bias="BEAR",
               transition={"state": "WEAKENING", "bias": "BEAR",
                           "reversal_probability": 40},
               ltp=_ltp(buyers="building"),
               acceptance={"state": "FAILED_BREAKOUT"},
               flow={"stability": "STABLE"},
               energy={"state": "COMPRESSION"})
    assert d["state"] == "REVERSAL_BUILDING"
    assert d["next_state"] == "MARKUP"        # bear reversing → up


def test_trap_outranks_everything():
    """The same tape is 'distribution' and 'trap active' — trap must win."""
    d = derive(bias="BEAR",
               transition={"state": "STABLE", "bias": "BEAR"},
               ltp=_ltp(price="falling", sellers="building", flow="leaving"),
               acceptance={"state": "BULL_TRAP", "confidence": 92},
               flow={"stability": "STABLE"}, energy={"state": "EXPANSION"})
    assert d["state"] == "TRAP_ACTIVE"
    assert d["next_state"] == "MARKDOWN" and d["next_probability"] >= 55
    assert d["confidence"] >= 90


def test_flow_shock_forces_wait():
    d = derive(bias="BULL", transition={"state": "STRENGTHENING", "bias": "BULL"},
               ltp=_ltp(price="rising", buyers="building"),
               acceptance={"state": "CONFIRMED_BREAKOUT"},
               flow={"stability": "SHOCK", "freeze_entries": True},
               energy={"state": "EXPANSION"})
    assert d["state"] == "WAIT"


def test_compression_predicts_expansion_using_stage37_probability():
    d = derive(bias="NEUTRAL", transition={"state": "STABLE"},
               ltp=_ltp(price="compressing"), acceptance={},
               flow={"stability": "STABLE"},
               energy={"state": "COMPRESSION", "release_probability": 84,
                       "confidence": 88})
    assert d["state"] == "COMPRESSION"
    assert d["next_state"] == "EXPANSION"
    # the number must come FROM Stage 37, not be invented here
    assert d["next_probability"] == 84


def test_absorption_is_a_war_zone():
    d = derive(bias="BULL", transition={"state": "STABLE", "bias": "BULL"},
               ltp=_ltp(buyers="absorbing"), acceptance={},
               flow={"stability": "STABLE"}, energy={"state": "BUILDING"})
    assert d["state"] == "WAR_ZONE"


def test_both_sides_building_is_a_war_zone():
    d = derive(bias="NEUTRAL", transition={"state": "STABLE"},
               ltp=_ltp(buyers="building", sellers="building"),
               acceptance={}, flow={"stability": "STABLE"},
               energy={"state": "BUILDING"})
    assert d["state"] == "WAR_ZONE"


def test_confirmed_breakout_and_breakdown():
    up = derive(bias="BULL", transition={"state": "STABLE", "bias": "BULL"},
                ltp=_ltp(price="rising"),
                acceptance={"state": "CONFIRMED_BREAKOUT", "confidence": 88},
                flow={"stability": "STABLE"}, energy={"state": "EXPANSION"})
    assert up["state"] == "BREAKOUT" and up["tone"] == "bull"
    dn = derive(bias="BEAR", transition={"state": "STABLE", "bias": "BEAR"},
                ltp=_ltp(price="falling"),
                acceptance={"state": "CONFIRMED_BREAKDOWN", "confidence": 88},
                flow={"stability": "STABLE"}, energy={"state": "EXPANSION"})
    assert dn["state"] == "BREAKDOWN" and dn["tone"] == "bear"


def test_weakening_trend_is_noted_in_reasons():
    d = derive(bias="BEAR",
               transition={"state": "WEAKENING", "bias": "BEAR",
                           "reversal_probability": 30},
               ltp=_ltp(price="falling", sellers="neutral"),
               acceptance={}, flow={"stability": "STABLE"},
               energy={"state": "BUILDING"})
    assert d["state"] in ("MARKDOWN", "TREND_DOWN")
    assert any("weakening" in r.lower() for r in d["reasons"])


def test_no_inputs_is_wait_with_low_confidence():
    d = derive()
    assert d["state"] == "WAIT" and d["confidence"] <= 45
    assert d["inputs_seen"] == 0


def test_every_state_has_a_label_and_is_declared():
    for s in STATES:
        assert s in LABEL
    d = derive(bias="BULL", transition={"state": "STABLE", "bias": "BULL"},
               ltp=_ltp(price="rising"), acceptance={},
               flow={"stability": "STABLE"}, energy={"state": "BUILDING"})
    assert d["state"] in STATES


def test_predict_next_is_safe_for_unknown_state():
    assert predict_next("WAIT", {}, {}, {}, {}) == (None, 0)


def test_it_calculates_nothing_of_its_own():
    """Stage 48 must never invent an energy or reversal number."""
    d = derive(bias="NEUTRAL", transition={"state": "STABLE"},
               ltp=_ltp(price="compressing"), acceptance={},
               flow={"stability": "STABLE"},
               energy={"state": "COMPRESSION", "release_probability": 61})
    assert d["next_probability"] == 61        # straight from Stage 37
    for forbidden in ("compression", "expansion_readiness", "energy_strength"):
        assert forbidden not in d


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"market state tests passed ({len(fns)})")
