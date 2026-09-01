"""MIOS V5 — Stage 2 Market Structure Engine tests.

    python -m mios_v5.tests.test_stage02_structure
"""

from __future__ import annotations

import sys

from mios_v5.core import Bias, Status
from mios_v5.runner import build_orchestrator


def _demand_zone_structure():
    return {
        "trend": "Strong Uptrend", "trend_stars": 5,
        "price_location": "HIGH QUALITY DEMAND ZONE",
        "support": 24300, "resistance": 24420,
        "vwap": 24280, "vwap_position": "Above",
        "volume_profile": {"poc": 24270, "vah": 24310, "val": 24240,
                            "state": "Inside Value Area", "side": "Above POC"},
        "order_block": {"label": "Fresh Demand", "freshness": "fresh"},
        "chart_pattern": "Ascending Triangle",
        "candle_pattern": "Bullish Engulfing",
        "structure_score": 91,
        "demand_supply": "Demand",
        "decision": "TRADE ZONE",
    }


def _no_trade_structure():
    return {
        "trend": "Range", "trend_stars": 2,
        "price_location": "NO CLEAR ZONE",
        "support": None, "resistance": None,
        "vwap": 24200, "vwap_position": "Near",
        "volume_profile": {"poc": 24200, "vah": 24210, "val": 24190,
                            "state": "Inside Value Area", "side": "Above POC"},
        "order_block": {"label": "None", "freshness": None},
        "chart_pattern": None, "candle_pattern": None,
        "structure_score": 28,
        "demand_supply": "Neutral",
        "decision": "NO TRADE",
    }


def test_missing_structure_is_neutral():
    orch = build_orchestrator()
    st = orch.run({"api_ok": True, "db_ok": True})
    s2 = st.get("stage02_structure")
    assert s2.status == Status.NEUTRAL
    assert s2.bias == Bias.NEUTRAL


def test_demand_zone_reports_bullish():
    orch = build_orchestrator()
    st = orch.run({"api_ok": True, "db_ok": True,
                   "market_structure": _demand_zone_structure()})
    s2 = st.get("stage02_structure")
    assert s2.status == Status.OK
    assert s2.bias == Bias.STRONG_BULL
    assert s2.confidence == 91
    assert s2.data["decision"] == "TRADE ZONE"
    assert s2.data["demand_supply"] == "Demand"
    assert any("Trend: Strong Uptrend" in e for e in s2.evidence)
    assert any("Order Block: Fresh Demand" in e for e in s2.evidence)


def test_no_trade_zone_reports_neutral_with_risk():
    orch = build_orchestrator()
    st = orch.run({"api_ok": True, "db_ok": True,
                   "market_structure": _no_trade_structure()})
    s2 = st.get("stage02_structure")
    assert s2.status == Status.OK
    assert s2.bias == Bias.NEUTRAL
    assert s2.confidence == 28
    assert s2.data["decision"] == "NO TRADE"
    assert any("not a location worth considering" in r for r in s2.risks)


def test_stage02_has_no_downstream_dependencies():
    """Structure must not depend on positioning/order-flow/options — the
    spec's separation of concerns: location vs. whether it's worth trading."""
    from mios_v5.engines.stage02_structure import MarketStructureEngine
    assert MarketStructureEngine.deps == ["stage00_health"]


def main() -> int:
    tests = [
        test_missing_structure_is_neutral,
        test_demand_zone_reports_bullish,
        test_no_trade_zone_reports_neutral_with_risk,
        test_stage02_has_no_downstream_dependencies,
    ]
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
