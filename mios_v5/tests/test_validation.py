"""MIOS V5 — Validation Dashboard tests.

    python -m mios_v5.tests.test_validation
"""

from __future__ import annotations

import sys

from mios_v5.validation import build_validation_report


def _row(side, entry, inval, pts, reason="TARGET_HIT", strength=60, rr=2.0,
         grade="A", zone="SUPPORT", regime="TREND UP", mae=-10, mfe=30):
    return {"side": side, "spot": entry, "invalidation": inval,
            "points_moved": pts, "exit_reason": reason, "strength": strength,
            "rr": rr, "layer_grade": grade, "zone_type": zone, "regime": regime,
            "mae": mae, "mfe": mfe}


def test_insufficient_is_honest():
    vr = build_validation_report([_row("CALL", 24000, 23970, 40) for _ in range(5)])
    assert vr["sufficient"] is False
    assert vr["level"] == 1
    # Level-1 locks the breakdowns
    assert vr["by_grade"] is None and vr["quality_quadrant"] is None
    assert "Insufficient data" in " ".join(vr["notes"])
    assert "SYSTEM" in vr["disclaimer"]


def test_levels_gate_analyses():
    l2 = build_validation_report([_row("CALL", 24000, 23970, 40) for _ in range(40)])
    assert l2["level"] == 2
    assert l2["by_grade"] is not None            # unlocked
    assert l2["layer_contribution"] is None      # still locked (needs 100)
    l3 = build_validation_report([_row("CALL", 24000, 23970, 40) for _ in range(120)])
    assert l3["level"] == 3
    assert l3["layer_contribution"] is not None


def test_headline_winrate_and_expectancy():
    rows = ([_row("CALL", 24000, 23970, 60) for _ in range(20)]      # +2R wins
            + [_row("PUT", 24000, 24030, -30, reason="INVALIDATED", mfe=5)
               for _ in range(20)])                                    # -1R losses
    vr = build_validation_report(rows)
    assert vr["n"] == 40 and vr["sufficient"] is True
    assert vr["headline"]["win_rate"] == 50
    # +2R twenty times, -1R twenty times → expectancy +0.5R
    assert abs(vr["headline"]["avg_R"] - 0.5) < 0.01
    # false-gate rate: the 20 INVALIDATED with mfe<10 → 100%
    assert vr["false_gate_rate"] == 100


def test_grade_and_bucket_breakdowns():
    rows = ([_row("CALL", 24000, 23970, 60, grade="A+", strength=70) for _ in range(15)]
            + [_row("PUT", 24000, 24030, -30, grade="C", strength=48,
                    reason="INVALIDATED") for _ in range(15)])
    vr = build_validation_report(rows)
    g = {r["group"]: r for r in vr["by_grade"]}
    assert g["A+"]["win_rate"] == 100 and g["C"]["win_rate"] == 0
    s = {r["bucket"]: r for r in vr["by_strength"]}
    assert s["65+"]["win_rate"] == 100 and s["45–55"]["win_rate"] == 0


def test_quality_quadrant_separates_luck_from_skill():
    rows = ([_row("CALL", 24000, 23970, 50, grade="A+") for _ in range(20)]   # skill wins
            + [_row("PUT", 24000, 24030, -30, grade="A",                       # good trade, bad result
                    reason="INVALIDATED") for _ in range(8)]
            + [_row("CALL", 24000, 23970, 40, grade="C") for _ in range(6)])   # lucky wins
    vr = build_validation_report(rows)
    q = vr["quality_quadrant"]
    assert q["good_process_bad_result"] == 8      # A-grade losers → keep taking
    assert q["lucky_wins"] == 6                    # C-grade winners → don't reinforce


def test_layer_contribution_ranks_by_edge():
    # 'structure' agrees with winners, disagrees with losers → high contribution
    rows = []
    for _ in range(60):
        rows.append({**_row("CALL", 24000, 23970, 50),
                     "layer_leans": {"structure": "BULL", "psychology": "BEAR"}})
    for _ in range(60):
        rows.append({**_row("PUT", 24000, 24030, -30, reason="INVALIDATED"),
                     "layer_leans": {"structure": "BULL", "psychology": "BEAR"}})
    vr = build_validation_report(rows)
    lc = {r["layer"]: r for r in vr["layer_contribution"]}
    # structure agreed only with the CALL winners → 100% agree WR
    assert lc["structure"]["agree_wr"] == 100
    assert lc["structure"]["contribution"] is not None


def test_guardian_save_and_winner_mae():
    # a REVERSED exit that got out better than a full stop counts as a save
    rows = ([_row("CALL", 24000, 23970, -10, reason="REVERSED", mae=-15) for _ in range(10)]
            + [_row("CALL", 24000, 23970, 50, mae=-12, mfe=60) for _ in range(25)])
    vr = build_validation_report(rows)
    assert vr["guardian_save_rate"] == 100      # -10 > -30 stop, all saved
    assert vr["winner_mae"]["n"] == 25
    assert vr["winner_mae"]["median"] == 12


def main() -> int:
    tests = [test_insufficient_is_honest,
             test_levels_gate_analyses,
             test_headline_winrate_and_expectancy,
             test_grade_and_bucket_breakdowns,
             test_quality_quadrant_separates_luck_from_skill,
             test_layer_contribution_ranks_by_edge,
             test_guardian_save_and_winner_mae]
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
