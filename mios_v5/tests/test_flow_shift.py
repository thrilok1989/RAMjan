"""Stage 44 — Sudden Flow Shift + Stability (the interrupt)."""

from mios_v5.flow_shift import detect_shift, trace_push, zscore


def _hist(n=6, **over):
    base = {"spot": 23900.0, "cvd_pct": 5.0, "oi_total": 1_000_000.0,
            "gamma_net": 500.0, "iv": 13.0, "volume": 100_000.0, "mf_net": 200.0}
    base.update(over)
    return [dict(base) for _ in range(n)]


def _cur(**over):
    c = dict(_hist(1)[0])
    c.update(over)
    return c


def test_quiet_tape_is_stable():
    r = detect_shift(_cur(), _hist())
    assert r["stability"] == "STABLE" and not r["detected"]
    assert not r["freeze_entries"] and r["reason"] == "flow steady"


def test_single_signal_is_noise_not_a_shift():
    # one moderate signal alone must not trip the interrupt
    r = detect_shift(_cur(cvd_pct=35.0), _hist())
    assert r["n"] == 1 and not r["detected"]


def test_corroborated_shift_detected_and_freezes():
    r = detect_shift(_cur(cvd_pct=-45.0, spot=23820.0, volume=300_000.0),
                     _hist())
    assert r["detected"] and r["freeze_entries"]
    assert r["n"] >= 2 and r["score"] >= 40
    assert any(s["key"] == "cvd" for s in r["signals"])


def test_shock_state_and_recovery_arc():
    hot = _cur(cvd_pct=-60.0, spot=23780.0, volume=400_000.0,
               gamma_net=100.0, iv=15.0)
    shock = detect_shift(hot, _hist())
    assert shock["stability"] == "SHOCK" and shock["freeze_entries"]
    # tape calms → RECOVERY, not straight back to STABLE
    calm = detect_shift(_cur(), _hist(), prev_state="SHOCK")
    assert calm["stability"] == "RECOVERY"
    assert not calm["freeze_entries"]          # recovery must not freeze forever
    # needs a few quiet cycles before it earns STABLE back
    assert detect_shift(_cur(), _hist(), prev_state="RECOVERY",
                        cycles_since_shock=1)["stability"] == "RECOVERY"
    assert detect_shift(_cur(), _hist(), prev_state="RECOVERY",
                        cycles_since_shock=5)["stability"] == "STABLE"


def test_oi_velocity_and_gamma_shift():
    r = detect_shift(_cur(oi_total=1_060_000.0, gamma_net=200.0), _hist())
    keys = {s["key"] for s in r["signals"]}
    assert "oi" in keys and "gamma" in keys
    assert r["velocity"]["oi"] > 0


def test_missing_inputs_are_skipped_not_guessed():
    r = detect_shift({"spot": 23900.0}, _hist())
    assert r["n"] == 0 and r["stability"] == "STABLE"
    # no history at all → nothing to compare against, must not fire
    assert detect_shift(_cur(cvd_pct=-90.0), [])["n"] == 0
    assert detect_shift(None, None)["score"] == 0


def test_price_displacement_fires():
    r = detect_shift(_cur(spot=23960.0), _hist())      # +0.25%
    assert any(s["key"] == "price" for s in r["signals"])


def test_non_directional_output_shape():
    r = detect_shift(_cur(cvd_pct=-45.0, spot=23820.0), _hist())
    for k in ("signals", "score", "detected", "stability",
              "freeze_entries", "velocity", "reason", "label"):
        assert k in r
    assert r["stability"] in ("STABLE", "UNSTABLE", "SHOCK", "RECOVERY")
    assert "bias" not in r          # it warns, it never leans


def test_zscore_needs_enough_history():
    assert zscore(10, _hist(2), "cvd_pct") is None      # too few points
    assert zscore(10, _hist(6), "cvd_pct") is None      # zero variance → None
    varied = [{"cvd_pct": v} for v in (1, 5, 3, 9, 2, 7)]
    z = zscore(40, varied, "cvd_pct")
    assert z is not None and z > 2


def test_trace_push_is_bounded():
    t = []
    for i in range(30):
        t = trace_push(t, {"spot": 23900 + i}, keep=12)
    assert len(t) == 12 and t[-1]["spot"] == 23929


if __name__ == "__main__":
    for fn in [test_quiet_tape_is_stable, test_single_signal_is_noise_not_a_shift,
               test_corroborated_shift_detected_and_freezes,
               test_shock_state_and_recovery_arc,
               test_oi_velocity_and_gamma_shift,
               test_missing_inputs_are_skipped_not_guessed,
               test_price_displacement_fires,
               test_non_directional_output_shape,
               test_zscore_needs_enough_history,
               test_trace_push_is_bounded]:
        fn()
    print("flow shift tests passed")
