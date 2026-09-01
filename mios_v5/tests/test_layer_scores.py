"""MIOS V5 — 7-Layer Scorecard tests.

    python -m mios_v5.tests.test_layer_scores
"""

from __future__ import annotations

import sys

from mios_v5.core import Bias, Status
from mios_v5.layer_scores import build_layer_scores, layer_scores_line
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_phase_c import _raw_at_support


def test_scorecard_shape_and_bounds():
    st = build_orchestrator().run(_raw_at_support())
    ls = build_layer_scores(st)
    assert set(ls) >= {"layers", "composite", "alignment", "direction",
                       "grade", "available", "total_layers", "disclaimer"}
    assert len(ls["layers"]) == 7
    assert 0 <= ls["composite"] <= 100
    assert 0 <= ls["alignment"] <= 100
    assert ls["grade"] in ("A+", "A", "B", "C")
    assert ls["direction"] in ("BULL", "BEAR", "NEUTRAL")
    # never a buy/sell instruction
    assert "not a buy/sell" in ls["disclaimer"].lower()
    for ly in ls["layers"]:
        assert ly["score"] is None or 0 <= ly["score"] <= 100
        assert ly["lean"] in ("BULL", "BEAR", "NEUTRAL", "N/A")


def test_missing_layer_is_na_not_faked():
    """A layer whose engines didn't compute is N/A and excluded — never 0-faked."""
    st = build_orchestrator().run(_raw_at_support())
    # blank out the order-flow engine result → its layer must go N/A
    st.results.pop("stage14_orderflow", None)
    ls = build_layer_scores(st)
    of = next(ly for ly in ls["layers"] if ly["key"] == "orderflow")
    assert of["score"] is None and of["lean"] == "N/A"
    assert ls["available"] <= ls["total_layers"] - 1


def test_health_and_thin_pipeline_cap_grade():
    """Few layers or weak health can't earn the top grade."""
    st = build_orchestrator().run(_raw_at_support())
    # strip most engines so < 4 layers remain available
    keep = {"stage35_reaction_zone", "stage03_memory"}
    st.results = {k: v for k, v in st.results.items() if k in keep}
    ls = build_layer_scores(st, health_score=100)
    assert ls["available"] < 4
    assert ls["grade"] not in ("A+", "A")   # capped to B/C
    assert any("layers available" in n for n in ls["notes"])


def test_line_summary():
    st = build_orchestrator().run(_raw_at_support())
    line = layer_scores_line(build_layer_scores(st))
    assert "Trade-Quality" in line and "composite" in line


def main() -> int:
    tests = [test_scorecard_shape_and_bounds,
             test_missing_layer_is_na_not_faked,
             test_health_and_thin_pipeline_cap_grade,
             test_line_summary]
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
