"""Stage 54 — Market Memory (how long, and how committed?)."""

from mios_v5.memory import (TRACKED, describe, for_validity, get, stars_str,
                            strength_stars, summary, track)

M = 60.0  # one minute in seconds


def _obs(state, conf=70):
    return {"market_state": {"state": state, "confidence": conf}}


def _run(states, start=0.0, step=M, conf=70):
    """Feed a sequence of states, one per minute."""
    mem, t = None, start
    for s in states:
        c = conf(s) if callable(conf) else conf
        mem = track(mem, _obs(s, c), now_ts=t)
        t += step
    return mem


def test_strength_grows_with_duration():
    assert strength_stars(1) == 1
    assert strength_stars(6) == 2
    assert strength_stars(16) == 3
    assert strength_stars(31) == 4
    assert strength_stars(56) == 5
    assert stars_str(4) == "★★★★☆"


def test_same_state_accrues_duration_and_strength():
    mem = _run(["DISTRIBUTION"] * 40)
    e = get(mem, "market_state")
    assert e["state"] == "DISTRIBUTION"
    assert e["duration_min"] == 39.0 and e["cycles"] == 40
    assert e["stars"] >= 4 and e["mature"] and not e["fresh"]


def test_state_change_resets_the_clock_and_remembers_the_previous():
    mem = _run(["DISTRIBUTION"] * 20 + ["ACCUMULATION"] * 3)
    e = get(mem, "market_state")
    assert e["state"] == "ACCUMULATION"
    assert e["previous"] == "DISTRIBUTION"
    assert e["previous_duration_min"] == 19.0
    assert e["duration_min"] == 2.0 and e["fresh"]


def test_fresh_state_is_flagged_as_too_young_to_act_on():
    mem = _run(["DISTRIBUTION"] * 3)
    e = get(mem, "market_state")
    assert e["fresh"] and not e["mature"]
    assert "too young" in describe(mem).lower()


def test_mature_rising_state_reads_as_institutional():
    mem, t = None, 0.0
    for i in range(60):                       # 59 min → the full 5 stars
        mem = track(mem, _obs("DISTRIBUTION", 40 + i * 0.9), now_ts=t)
        t += M
    e = get(mem, "market_state")
    assert e["trend"] == "increasing" and e["stars"] == 5
    assert "institutional" in describe(mem).lower()


def test_decay_detected_when_duration_high_but_conviction_falling():
    """The subtle half: long duration + falling strength = tiring, not strong."""
    mem, t = None, 0.0
    for i in range(40):
        conf = 90 - i * 1.5          # conviction draining away
        mem = track(mem, _obs("DISTRIBUTION", conf), now_ts=t)
        t += M
    e = get(mem, "market_state")
    assert e["duration_min"] >= 30
    assert e["trend"] == "decreasing"
    assert e["transition_risk"] >= 50
    assert "fading" in describe(mem).lower()


def test_even_healthy_states_age_out():
    mem, t = None, 0.0
    for _ in range(60):
        mem = track(mem, _obs("COMPRESSION", 70), now_ts=t)
        t += M
    e = get(mem, "market_state")
    assert e["trend"] == "steady" and e["transition_risk"] > 0


def test_persistence_scales_to_100():
    short = get(_run(["TREND_UP"] * 6), "market_state")
    long_ = get(_run(["TREND_UP"] * 60), "market_state")
    assert long_["persistence"] > short["persistence"]
    assert long_["persistence"] <= 100


def test_tracks_multiple_engines_independently():
    mem, t = None, 0.0
    for i in range(20):
        mem = track(mem, {
            "market_state": {"state": "DISTRIBUTION", "confidence": 80},
            "energy": {"state": "COMPRESSION", "confidence": 70},
            "bias_transition": {"state": "WEAKENING", "confidence": 60},
        }, now_ts=t)
        t += M
    assert get(mem, "market_state")["state"] == "DISTRIBUTION"
    assert get(mem, "energy")["state"] == "COMPRESSION"
    assert get(mem, "bias_transition")["state"] == "WEAKENING"
    rows = summary(mem)
    assert len(rows) == 3 and all(r["label"] for r in rows)


def test_summary_is_ordered_by_how_established():
    mem, t = None, 0.0
    for i in range(30):
        obs = {"market_state": {"state": "DISTRIBUTION", "confidence": 80}}
        if i >= 25:                     # energy state arrived late
            obs["energy"] = {"state": "EXPANSION", "confidence": 70}
        mem = track(mem, obs, now_ts=t)
        t += M
    rows = summary(mem)
    assert rows[0]["key"] == "market_state"     # the most established first


def test_for_validity_payload():
    mem = _run(["DISTRIBUTION"] * 40)
    p = for_validity(mem)
    for k in ("state", "state_duration_min", "state_stars", "state_trend",
              "state_mature", "state_fresh", "state_transition_risk"):
        assert k in p
    assert p["state_mature"] is True


def test_empty_memory_is_safe():
    assert track(None, None, 0.0) == {}
    assert describe(None) == "No memory yet."
    assert summary(None) == [] and get(None, "market_state") == {}


def test_all_tracked_keys_have_labels():
    from mios_v5.memory import LABEL
    for k in TRACKED:
        assert k in LABEL


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"market memory tests passed ({len(fns)})")
