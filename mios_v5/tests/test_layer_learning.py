"""MIOS V5 — SHADOW layer-weight learning tests.

    python -m mios_v5.tests.test_layer_learning
"""

from __future__ import annotations

import sys

from mios_v5.layer_learning import (base_weights, build_shadow_weights,
                                    weight_delta_table)


def _rows(n, key_good, key_bad):
    """n graded trades: `key_good` layer always right, `key_bad` always wrong."""
    out = []
    for i in range(n):
        win = (i % 2 == 0)                 # alternate outcomes
        side = "CALL" if win else "PUT"    # so 'good' agreeing==win holds
        leans = {key_good: "BULL",         # BULL agrees with CALL; right iff win
                 key_bad: "BEAR"}          # BEAR opposes CALL; right iff loss
        out.append({"leans": leans, "side": side, "win": win})
    return out


def test_insufficient_returns_base():
    sw = build_shadow_weights([])
    assert sw["sufficient"] is False
    assert sw["shadow"] == sw["base"]      # unchanged until data
    assert "self-populates" in " ".join(sw["notes"])
    assert "do NOT drive the live" in sw["disclaimer"]


def test_weights_normalise_to_one():
    sw = build_shadow_weights([])
    assert abs(sum(sw["shadow"].values()) - 1.0) < 1e-6
    assert abs(sum(base_weights().values()) - 1.0) < 0.05


def test_good_layer_up_bad_layer_down():
    # 'structure' always right, 'psychology' always wrong, plenty of samples
    rows = _rows(40, "structure", "psychology")
    sw = build_shadow_weights(rows)
    assert sw["sufficient"] is True
    assert sw["shadow"]["structure"] > sw["base"]["structure"]
    assert sw["shadow"]["psychology"] < sw["base"]["psychology"]
    assert sw["accuracy"]["structure"] == 100
    assert sw["accuracy"]["psychology"] == 0
    # normalised
    assert abs(sum(sw["shadow"].values()) - 1.0) < 1e-6
    # delta table sorts by magnitude of change
    tbl = weight_delta_table(sw)
    assert abs(tbl[0]["delta"]) >= abs(tbl[-1]["delta"])


def test_thin_layer_keeps_base_weight():
    # only 3 samples for a layer → below _MIN_PER_LAYER → weight unchanged
    rows = _rows(3, "structure", "psychology")
    # pad to clear the total minimum with rows that give NO layer a direction
    rows += [{"leans": {}, "side": "CALL", "win": True} for _ in range(20)]
    sw = build_shadow_weights(rows)
    assert sw["accuracy"]["structure"] is None      # not enough per-layer data
    assert sw["shadow"]["structure"] == sw["base"]["structure"]


def main() -> int:
    tests = [test_insufficient_returns_base,
             test_weights_normalise_to_one,
             test_good_layer_up_bad_layer_down,
             test_thin_layer_keeps_base_weight]
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
