"""MIOS V5 — Data-integrity strip tests.

    python -m mios_v5.tests.test_health_strip
"""

from __future__ import annotations

import sys

from mios_v5.core import Status
from mios_v5.health_strip import build_engine_status
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_phase_c import _raw_at_support


def test_strip_shape():
    st = build_orchestrator().run(_raw_at_support())
    es = build_engine_status(st)
    assert set(es) >= {"engines", "integrity", "ok_n", "total", "impaired",
                       "trust_note"}
    assert es["integrity"] in ("OK", "DEGRADED", "COMPROMISED")
    assert es["total"] == 7
    for e in es["engines"]:
        assert e["emoji"] and e["reason"] is not None


def test_core_impairment_degrades_integrity():
    st = build_orchestrator().run(_raw_at_support())
    # drop a CORE engine result → data integrity must fall from OK
    st.results.pop("stage14_orderflow", None)
    es = build_engine_status(st)
    assert es["integrity"] in ("DEGRADED", "COMPROMISED")
    assert any(e["engine"].startswith("Order Flow") for e in es["impaired"])


def test_error_compromises_and_reason_shown():
    st = build_orchestrator().run(_raw_at_support())
    of = st.get("stage12_options")
    if of is not None:
        of.status = Status.ERROR
        of.errors = of.errors or []
    es = build_engine_status(st)
    assert es["integrity"] == "COMPROMISED"
    assert "do NOT trust" in es["trust_note"]


def main() -> int:
    tests = [test_strip_shape,
             test_core_impairment_degrades_integrity,
             test_error_compromises_and_reason_shown]
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
