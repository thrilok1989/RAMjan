"""MIOS V5 Phase-D tests — final-read assembler.

    python -m mios_v5.tests.test_phase_d
"""

from __future__ import annotations

import sys
from datetime import time as dtime

from mios_v5.final_read import build_final_read, final_read_line
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_phase_c import _raw_at_support


def test_final_read_shape_and_content():
    st = build_orchestrator().run(_raw_at_support())
    fr = build_final_read(st)

    # required keys present
    for k in ("preferred_bias", "confidence", "confidence_tempered",
              "conflict_severity", "battle_zone", "expected_winner",
              "risks", "opportunities", "evidence", "sections"):
        assert k in fr, f"missing {k}"

    # bullish support bounce scenario → bullish preferred bias
    assert fr["preferred_bias"] in ("BULL", "STRONG_BULL")
    # reaction zone populated
    assert fr["battle_zone"]["type"] == "SUPPORT"
    assert "Buyers" in fr["expected_winner"]
    assert fr["next_target"] and fr["invalidation"]
    # session temper applied (10:00 conviction 80 → temper factor ~0.91)
    assert 0 < fr["confidence_tempered"] <= fr["confidence"] + 1
    # section chips have the institutional engines
    assert set(fr["sections"]) >= {"dealer", "intent", "orderflow",
                                    "options", "regime"}
    # one-line summary renders
    line = final_read_line(fr)
    assert "MIOS:" in line and fr["preferred_bias"] in line


def test_final_read_empty_pipeline():
    """No caches → neutral read, no crash, no fabricated levels."""
    st = build_orchestrator().run({"api_ok": True, "db_ok": True,
                                   "now_ist_time": dtime(10, 0)})
    fr = build_final_read(st)
    assert fr["preferred_bias"] in ("NEUTRAL", "NONE")
    assert fr["battle_zone"] is None
    assert fr["evidence"] == [] or all(isinstance(e, str) for e in fr["evidence"])


def test_alert_retirement_flag():
    """The app-level retirement flag is on and the confirmed-entry class is
    among the retired set (locked decision #1)."""
    import importlib.util
    import os
    spec_path = os.path.join(os.path.dirname(__file__), "..", "..",
                             "vob_minimal.py")
    # cheap textual check (importing vob_minimal pulls streamlit) —
    # assert the retirement config is present and enabled.
    with open(os.path.abspath(spec_path), encoding="utf-8") as f:
        src = f.read()
    assert "RETIRE_ENTRY_ALERTS = True" in src
    for cls in ("confirmed_entry", "fresh_entry", "leg_entry", "bias_enter"):
        assert f"'{cls}'" in src


def main() -> int:
    tests = [test_final_read_shape_and_content, test_final_read_empty_pipeline,
             test_alert_retirement_flag]
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
