"""MIOS V5 Phase-B adapter-engine tests.

    python -m mios_v5.tests.test_adapters
"""

from __future__ import annotations

import sys

from mios_v5.core import Bias, Status
from mios_v5.runner import build_orchestrator


def _rich_raw():
    """Simulate a populated cycle: the caches the host app stashes."""
    return {
        "api_ok": True, "db_ok": True,
        "option_data": {"underlying": 24310, "pcr": 1.18, "pcr_bias": "Bullish"},
        "market_picture": {
            "regime": "UP", "p_up": 62, "p_down": 20, "p_side": 18,
            "reasons": ["CE↔PE aligned UP", "FAST net +3"],
            "atm_bias": {"strike": 24300, "verdict": "Bullish", "score": 3},
            "doi_bias": {"label": "Bullish (PE writers building support)"},
            "oi_floor": (24200, 12.4), "oi_ceiling": (24500, 9.1),
            "gex_disp": {"total": -180, "signal": "Breakout", "flip": 24350,
                         "spot_vs_flip": "Below Gamma Flip"},
            "dex_bias": {"net_dex": 51, "bias": "BULL", "label": "Call-delta heavy"},
            "skew_bias": {"ratio": 1.18, "bias": "BEAR", "label": "Put skew", "em": "🔴"},
            "vc_exp": {"net_vanna": 12.0, "net_charm": -3.0},
            "global_bias": {"label": "BULL", "score": 2.5},
            "commodity_bias": {"regime": "Risk-On"},
            "news_bias": {"label": "BULL", "em": "🟢", "net": 3, "n": 12},
            "oflow_imb": {"label": "Call bids stacked", "call_net": 45000, "put_net": -12000},
        },
        "full_market_read": {
            "call_mode": "Short Covering", "put_mode": "Writing",
            "call_strength": 72, "put_strength": 80, "call_conf": 70, "put_conf": 75,
            "market_label": "🟢 Bullish", "market_kind": "bull",
            "support_strength": 78, "resistance_strength": 40,
            "breakout": 71, "breakdown": 29, "gamma_blast": "HIGH",
            "dealer_score": 62, "dealer_dir": "bull",
            "institution_score": 74, "institution_bias": "bull",
            "short_squeeze": 60, "overall_conf": 73,
        },
        "leg_bias_cache": (None, {"label": "Bull", "em": "🟢", "bull": 8,
                                  "bear": 3, "net": 5,
                                  "by_speed": {"fast": {"label": "STRONG BULL", "net": 4}}}),
    }


def test_empty_cycle_all_neutral_or_disabled():
    """First cycle: no caches → market engines NEUTRAL, microstructure DISABLED,
    health OK. Nothing crashes, nothing fakes a value."""
    orch = build_orchestrator()
    st = orch.run({"api_ok": True, "db_ok": True})
    rep = st.raw["_run_report"]
    assert st.get("stage00_health").status == Status.OK
    assert st.get("stage05_regime").status == Status.NEUTRAL
    assert st.get("stage11_dealer").status == Status.NEUTRAL
    assert st.get("stage15_microstructure").status == Status.DISABLED
    # disabled excluded from health denominator
    assert rep.disabled >= 1
    assert rep.errors == 0


def test_rich_cycle_engines_report():
    orch = build_orchestrator()
    st = orch.run(_rich_raw())

    reg = st.get("stage05_regime")
    assert reg.status == Status.OK and reg.bias == Bias.STRONG_BULL

    dealer = st.get("stage11_dealer")
    assert dealer.status == Status.OK and dealer.bias == Bias.BULL
    assert dealer.confidence == 62

    inst = st.get("stage13_institutional")
    assert inst.status == Status.OK and inst.bias == Bias.BULL
    assert any("Short Covering" in e for e in inst.evidence)

    of = st.get("stage14_orderflow")
    assert of.status == Status.OK and of.bias in (Bias.STRONG_BULL, Bias.BULL)

    prob = st.get("stage31_probability")
    assert prob.data["breakout"] == 71 and prob.bias == Bias.BULL

    # fusion engine read the institutional engines and agreed bull
    intent = st.get("stage25_intent")
    assert intent.status == Status.OK
    assert intent.bias in (Bias.BULL, Bias.STRONG_BULL)
    assert intent.data["contributors"]

    micro = st.get("stage15_microstructure")
    assert micro.status == Status.DISABLED
    assert "top_of_book_imbalance" in micro.data   # Tier-3 context still surfaced

    rep = st.raw["_run_report"]
    assert rep.errors == 0
    assert rep.ok >= 8


def test_intent_depends_on_institutional_order():
    orch = build_orchestrator()
    st = orch.run(_rich_raw())
    order = st.raw["_run_report"].order
    for dep in ("stage11_dealer", "stage13_institutional", "stage14_orderflow"):
        assert order.index(dep) < order.index("stage25_intent"), \
            f"{dep} must run before fusion"


def main() -> int:
    tests = [test_empty_cycle_all_neutral_or_disabled,
             test_rich_cycle_engines_report,
             test_intent_depends_on_institutional_order]
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
