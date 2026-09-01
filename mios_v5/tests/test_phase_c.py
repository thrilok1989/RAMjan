"""MIOS V5 Phase-C tests — Time Cycle, Conflict, Reaction Zone, Evolution.

    python -m mios_v5.tests.test_phase_c
"""

from __future__ import annotations

import sys
from datetime import time as dtime

from mios_v5.core import Bias, Status
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_adapters import _rich_raw


def _raw_at_support():
    """Spot sitting on a strong support with a bullish read → expect bounce."""
    raw = _rich_raw()
    raw["spot"] = 24205
    raw["market_picture"]["sup"] = {"price": 24200, "sources": ["VP", "PDL"],
                                    "src_count": 2, "ztype": "support"}
    raw["market_picture"]["res"] = {"price": 24500, "sources": ["VAH"],
                                    "src_count": 1, "ztype": "resistance"}
    raw["full_market_read"]["support_strength"] = 82
    raw["full_market_read"]["resistance_strength"] = 45
    raw["now_ist_time"] = dtime(10, 0)      # high-conviction window
    return raw


def test_timecycle_phases():
    orch = build_orchestrator()
    for t, expect in [(dtime(9, 20), "Opening"),
                      (dtime(10, 0), "Institutional"),
                      (dtime(12, 30), "Lunch"),
                      (dtime(16, 0), "Post-Market")]:
        st = orch.run({"now_ist_time": t})
        tc = st.get("stage06_timecycle")
        assert tc.status == Status.OK and tc.bias == Bias.NONE
        assert expect.lower() in tc.data["phase"].lower(), \
            f"{t} → {tc.data['phase']} (wanted {expect})"
    # lunch is low conviction, opening/inst higher
    lo = orch.run({"now_ist_time": dtime(12, 30)}).get("stage06_timecycle").data["conviction"]
    hi = orch.run({"now_ist_time": dtime(10, 0)}).get("stage06_timecycle").data["conviction"]
    assert lo < hi


def test_reaction_zone_bounce():
    st = build_orchestrator().run(_raw_at_support())
    rz = st.get("stage35_reaction_zone")
    assert rz.status == Status.OK
    bz = rz.data["battle_zone"]
    assert bz and bz["type"] == "SUPPORT" and bz["price"] == 24200
    # strong support + bullish lean → buyers/bounce
    assert rz.bias == Bias.BULL
    assert "Buyers" in rz.data["expected_winner"]
    assert rz.data["probabilities"]["bounce"] > 55
    assert rz.data["next_target"] == 24500          # next resistance
    assert rz.data["invalidation"] < 24200          # below support


def test_reaction_zone_midrange_neutral_conf():
    raw = _rich_raw()
    raw["spot"] = 24350
    raw["market_picture"]["sup"] = {"price": 24100, "sources": ["VP"], "src_count": 1}
    raw["market_picture"]["res"] = {"price": 24600, "sources": ["VAH"], "src_count": 1}
    st = build_orchestrator().run(raw)
    rz = st.get("stage35_reaction_zone")
    assert rz.status == Status.OK
    assert rz.data["battle_zone"] is None            # mid-range, no active battle


def test_conflict_agreement_vs_conflict():
    # aligned bullish cycle → LOW conflict
    st = build_orchestrator().run(_rich_raw())
    cf = st.get("stage27_conflict")
    assert cf.status == Status.OK
    assert cf.bias in (Bias.BULL, Bias.STRONG_BULL)
    assert cf.data["severity"] in ("LOW", "MEDIUM")

    # inject a hard clash: flip order flow bearish with high confidence
    raw = _rich_raw()
    raw["leg_bias_cache"] = (None, {"label": "Bear", "em": "🔴", "bull": 2,
                                    "bear": 9, "net": -7,
                                    "by_speed": {"fast": {"label": "STRONG BEAR", "net": -4}}})
    st2 = build_orchestrator().run(raw)
    cf2 = st2.get("stage27_conflict")
    assert cf2.data["conflicts"], "should name the opposing engine(s)"
    assert cf2.data["agreement_pct"] < cf.data["agreement_pct"]


def test_evolution_diff():
    orch = build_orchestrator()
    # pass 1 — baseline
    st1 = orch.run(_rich_raw())
    from mios_v5.engines.stage29_evolution import snapshot_of
    snap = snapshot_of(st1)
    ev1 = st1.get("stage29_evolution")
    assert ev1.data["n_changes"] == 0        # no prev snapshot → baseline

    # pass 2 — regime flips DOWN, feed prior snapshot
    raw2 = _rich_raw()
    raw2["market_picture"]["regime"] = "DOWN"
    raw2["market_picture"]["p_up"] = 20
    raw2["market_picture"]["p_down"] = 62
    raw2["prev_snapshot"] = snap
    st2 = orch.run(raw2)
    ev2 = st2.get("stage29_evolution")
    assert ev2.data["n_changes"] >= 1
    assert any("Regime" in c for c in ev2.data["changes"])


def main() -> int:
    tests = [test_timecycle_phases, test_reaction_zone_bounce,
             test_reaction_zone_midrange_neutral_conf,
             test_conflict_agreement_vs_conflict, test_evolution_diff]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:            # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
