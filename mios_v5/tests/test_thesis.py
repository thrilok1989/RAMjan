"""Dashboard V6 — AI thesis + market controller."""

from mios_v5.thesis import build_thesis, market_controller, recent_changes


def _fam(name, direction="BEAR", strength=85, reliability="HIGH"):
    return {name: {"status": "OK", "direction": direction,
                   "strength": strength, "reliability": reliability}}


def test_controller_picks_highest_authority_aligned_family():
    fams = {}
    fams.update(_fam("dealer", "BEAR", 85, "HIGH"))
    fams.update(_fam("macro", "BULL", 95, "HIGH"))
    c = market_controller(fams)
    assert c["controller"] == "dealer"      # authority beats raw strength
    assert c["direction"] == "BEAR"


def test_controller_discounts_unreliable_families():
    strong_unreliable = _fam("dealer", "BEAR", 90, "LOW")
    weaker_reliable = _fam("orderflow", "BULL", 80, "HIGH")
    c = market_controller({**strong_unreliable, **weaker_reliable})
    assert c["controller"] == "orderflow"


def test_nobody_in_control_is_a_real_answer():
    """When nothing is aligned and reliable, saying 'retail' is more useful
    than naming a winner that isn't leading."""
    c = market_controller(_fam("macro", "BULL", 20, "LOW"))
    assert c["controller"] == "retail"
    assert "no institutional group" in c["reason"]


def test_controller_ignores_neutral_families():
    c = market_controller(_fam("dealer", "NEUTRAL", 90, "HIGH"))
    assert c["controller"] == "retail"


def test_controller_empty_is_safe():
    assert market_controller(None)["controller"] is None


def test_thesis_has_all_three_sections():
    t = build_thesis({
        "decision_v2": {"state": "ENTER", "side": "CALL", "entry": 23644,
                        "stop": 23632, "reasons": ["Price refusing lower levels"],
                        "proof": {"confirmed": True, "label": "FLOOR CONFIRMED",
                                  "zone_price": 23650}},
        "absorption": {"behaviour": "PASSIVE_BUYING", "label": "Passive Buying",
                       "expectation": "Accumulation continues"},
        "market_state": {"label": "🟢 ACCUMULATION", "next_state": "MARKUP",
                         "next_label": "MARK UP", "next_probability": 78},
        "validity": {"verdict": "VALID", "pct": 91},
        "memory_read": {"state_duration_min": 22},
        "transition": {"reversal_probability": 45},
    })
    assert t["has_edge"]
    assert any("FLOOR CONFIRMED" in w for w in t["why"])
    assert any("MARK UP" in e for e in t["expect"])
    # invalidation is the section that matters most
    assert any("23,632" in i for i in t["invalidation"])
    assert any("Dealer flip" in i for i in t["invalidation"])


def test_thesis_is_honest_when_there_is_no_edge():
    t = build_thesis({})
    assert not t["has_edge"]
    assert "standing aside" in t["why"][0]
    assert t["expect"] and t["invalidation"]      # never empty sections


def test_invalidation_is_never_empty():
    """An idea you cannot invalidate is not an idea."""
    for fr in ({}, {"decision_v2": {"state": "WAIT"}}):
        assert build_thesis(fr)["invalidation"]


def test_recent_changes_reports_only_changes():
    ch = recent_changes({
        "transition": {"state": "WEAKENING", "leader": "dealer"},
        "flow_shift": {"detected": True, "reason": "CVD collapse"},
        "absorption": {"behaviour": "PASSIVE_SELLING", "label": "Passive Selling"},
    }, evolution_changes=["Regime BULL → NEUTRAL"])
    assert any("Regime" in c for c in ch)
    assert any("weakening" in c.lower() for c in ch)
    assert any("Flow shift" in c for c in ch)
    assert len(ch) <= 8


def test_recent_changes_quiet_when_nothing_changed():
    assert recent_changes({"transition": {"state": "STABLE"}}) == []


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"thesis tests passed ({len(fns)})")
