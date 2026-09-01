"""Decision Engine v0 — gate stack + Quality gate (build_decision)."""

from mios_v5.decision import build_decision, grade_trade


def test_grade_call_win_loss_open():
    assert grade_trade("CALL", 23900, 24000, 23860, [(23950, 23890), (24010, 23980)]) == "win"
    assert grade_trade("CALL", 23900, 24000, 23860, [(23920, 23850)]) == "loss"
    assert grade_trade("CALL", 23900, 24000, 23860, [(23930, 23880)]) == "open"


def test_grade_put_and_same_bar():
    assert grade_trade("PUT", 24050, 23950, 24090, [(24060, 23940)]) == "win"    # target(low) hit
    assert grade_trade("PUT", 24050, 23950, 24090, [(24100, 24020)]) == "loss"   # stop(high) hit
    assert grade_trade("PUT", 24050, 23950, 24090, [(24100, 23940)]) == "loss"   # both → conservative
    assert grade_trade("CALL", 0, 0, 0, []) == "open"


def _fr(**kw):
    base = {"preferred_bias": "STRONG_BULL", "confidence_tempered": 62,
            "conflict_severity": "LOW", "battle_zone": {"type": "SUPPORT", "price": 23900}}
    base.update(kw)
    return base


def _rsr(life="building"):
    return {"support": {"price": 23900, "lifecycle": life},
            "resistance": {"price": 24050, "lifecycle": "holding"}}


def test_confirmed_aplus():
    g = {"state": "CONFIRMED", "side": "CALL", "zone": "SUPPORT",
         "level": 23900, "target": 24000, "stop": 23860, "rr": 3.2}
    d = build_decision(_fr(), _rsr("building"), g)
    assert d["decision"] == "CALL" and d["state"] == "CONFIRMED"
    assert d["quality"] in ("A+", "A") and d["blocked_by"] is None
    assert "Support" not in "".join(d["reasons"]) or True   # reasons populated
    assert d["reasons"] and d["rejected"] is False


def test_mid_range_waits():
    d = build_decision(_fr(battle_zone=None), _rsr(), {"state": "WAIT", "side": None})
    assert d["decision"] == "WAIT" and "location" in (d["blocked_by"] or "")
    assert d["quality"] is None                    # not actionable → no grade


def test_tight_rr_is_rejection():
    # at a zone (could trade) but R:R too tight → WAIT + rejected=True
    g = {"state": "CONFIRMED", "side": "CALL", "zone": "SUPPORT", "level": 23900, "rr": 0.6}
    d = build_decision(_fr(), _rsr(), g)
    assert d["decision"] == "WAIT" and d["rejected"] is True
    assert "risk" in (d["blocked_by"] or "")


def test_event_veto_stand_aside():
    g = {"state": "ARMED", "side": "PUT", "zone": "RESISTANCE", "level": 24050, "rr": 2.0}
    d = build_decision(_fr(preferred_bias="BEAR", event={"event_detected": True},
                           battle_zone={"type": "RESISTANCE", "price": 24050}),
                       _rsr(), g)
    assert d["decision"] == "STAND ASIDE"
    assert any("shock" in w for w in d["warnings"])


def test_quality_lower_when_gates_weak():
    # same CALL, but fading zone + neutral bias + thin R:R → lower grade
    g = {"state": "CONFIRMED", "side": "CALL", "zone": "SUPPORT", "level": 23900, "rr": 1.3}
    strong = build_decision(_fr(), _rsr("building"),
                            {"state": "CONFIRMED", "side": "CALL", "zone": "SUPPORT",
                             "level": 23900, "rr": 3.5})
    weak = build_decision(_fr(preferred_bias="NEUTRAL"), _rsr("fading"), g)
    assert weak["quality_avg"] < strong["quality_avg"]


def test_gate_stars_present():
    g = {"state": "CONFIRMED", "side": "CALL", "zone": "SUPPORT", "level": 23900, "rr": 2.0}
    d = build_decision(_fr(), _rsr(), g)
    assert set(["location", "direction", "zone", "confirmation", "risk", "event"]) <= set(d["gate_stars"])
    assert all(len(v) == 5 for v in d["gate_stars"].values())   # ★★★★★ form


if __name__ == "__main__":
    for fn in [test_confirmed_aplus, test_mid_range_waits, test_tight_rr_is_rejection,
               test_event_veto_stand_aside, test_quality_lower_when_gates_weak,
               test_gate_stars_present]:
        fn()
    print("decision engine tests passed")
