"""MIOS V5 — Engine State snapshot tests.

    python -m mios_v5.tests.test_engine_state
"""

from __future__ import annotations

import sys

from mios_v5.engine_state import ENGINE_VERSION, build_engine_state_row
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_adapters import _rich_raw
from mios_v5.tests.test_stage02_structure import _demand_zone_structure


def test_row_has_version_and_timestamp():
    orch = build_orchestrator()
    state = orch.run({"api_ok": True, "db_ok": True})
    row = build_engine_state_row(state, spot=24310)
    assert row["engine_version"] == ENGINE_VERSION
    assert row["spot"] == 24310
    assert row["ts"] and row["trading_day"]


def test_row_flattens_engine_scores():
    raw = _rich_raw()
    raw["market_structure"] = _demand_zone_structure()
    orch = build_orchestrator()
    state = orch.run(raw)
    row = build_engine_state_row(state, spot=24310)

    assert row["structure_bias"] == "STRONG_BULL"
    assert row["structure_score"] == 91
    assert row["structure_decision"] == "TRADE ZONE"
    assert row["regime_bias"] == "STRONG_BULL"
    assert row["dealer_confidence"] == 62
    assert row["institutional_bias"] == "BULL"

    # full_state carries every engine's status/bias/confidence/data, even
    # ones not flattened into top-level columns
    assert "stage00_health" in row["full_state"]
    assert row["full_state"]["stage02_structure"]["data"]["structure_score"] == 91


def test_row_missing_engines_are_null_not_fabricated():
    """An engine that hasn't computed (NEUTRAL/missing) must produce None,
    never a fabricated bias/score — the honesty rule applies to storage too."""
    orch = build_orchestrator()
    state = orch.run({"api_ok": True, "db_ok": True})
    row = build_engine_state_row(state)
    assert row["structure_bias"] is None
    assert row["structure_score"] is None
    assert row["dealer_bias"] is None


def main() -> int:
    tests = [
        test_row_has_version_and_timestamp,
        test_row_flattens_engine_scores,
        test_row_missing_engines_are_null_not_fabricated,
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
