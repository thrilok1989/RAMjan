"""Self-calibrating magnitude buckets for the third-order Greek nets.

The point of this module is that HIGH means "large *for this Greek right now*",
not "above a guessed constant". The tests pin exactly that: the same absolute
value buckets differently depending on the window it is compared against, a
dead-flat window never over-fires, thin data falls back to the absolute cutoff,
and the noise floor is respected regardless of the window.
"""

import math

from mios_v5.rolling_baseline import classify, MIN_SAMPLES, _percentile


def _window(mean, n=MIN_SAMPLES + 4):
    """A calibration window with real spread around `mean`."""
    return [mean * f for f in ([0.6, 0.8, 1.0, 1.2, 0.7, 0.9, 1.1, 1.3] * 3)[:n]]


def test_below_the_floor_is_low_whatever_the_window_says():
    # even against a tiny window that would rank it high, noise stays LOW
    assert classify(0.5, _window(0.1), floor=1.0, high_band=10.0) == "LOW"


def test_warm_up_falls_back_to_the_absolute_band():
    thin = [2.0, 3.0]  # fewer than MIN_SAMPLES
    assert len(thin) < MIN_SAMPLES
    # above floor, below high_band, thin history → MODERATE (absolute fallback)
    assert classify(5.0, thin, floor=1.0, high_band=10.0) == "MODERATE"
    # above high_band, thin history → HIGH
    assert classify(12.0, thin, floor=1.0, high_band=10.0) == "HIGH"


def test_it_self_calibrates_the_same_value_two_ways():
    # identical absolute value, well below the absolute high_band…
    val, floor, high = 6.0, 1.0, 100.0
    quiet = _window(50.0)   # its recent range sits far ABOVE it → not a standout
    busy = _window(3.0)     # its recent range sits BELOW it → a standout
    assert classify(val, quiet, floor=floor, high_band=high) in ("MODERATE",)
    assert classify(val, busy, floor=floor, high_band=high) == "HIGH"


def test_a_flat_window_never_fires_high():
    flat = [10.0] * (MIN_SAMPLES + 4)
    # a value above the floor but into a flat window has nothing to stand out
    # against → MODERATE at most, never HIGH
    assert classify(10.0, flat, floor=1.0, high_band=1000.0) == "MODERATE"
    assert classify(11.0, flat, floor=1.0, high_band=1000.0) == "MODERATE"


def test_high_only_when_at_or_above_the_window_high_percentile():
    win = _window(10.0)      # spread roughly 6 … 13
    # a value clearly at the top of its own range → HIGH
    assert classify(13.0, win, floor=0.1, high_band=1e9) == "HIGH"
    # a mid-range value above the floor → MODERATE
    assert classify(9.0, win, floor=0.1, high_band=1e9) == "MODERATE"


def test_bad_current_reads_low_never_raises():
    for bad in (None, float("nan"), float("inf"), "x"):
        assert classify(bad, _window(10.0), floor=1.0, high_band=10.0) == "LOW"


def test_non_numeric_history_entries_are_ignored():
    win = [10.0, None, "bad", float("nan"), 12.0, 8.0, 11.0, 9.0, 13.0, 7.0]
    # still classifies without raising despite the junk entries
    out = classify(13.0, win, floor=0.1, high_band=1e9)
    assert out in ("HIGH", "MODERATE")


def test_percentile_is_monotone_and_bounded():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(vals, 0.0) == 1.0
    assert _percentile(vals, 1.0) == 5.0
    assert _percentile(vals, 0.5) == 3.0
    assert _percentile([], 0.5) == 0.0
    assert _percentile([7.0], 0.9) == 7.0
    # monotone
    prev = -math.inf
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        cur = _percentile(vals, q)
        assert cur >= prev
        prev = cur


def test_the_bucket_is_always_a_magnitude_string_never_a_direction():
    for out in (classify(13.0, _window(10.0), floor=0.1, high_band=1e9),
                classify(0.0, _window(10.0), floor=1.0, high_band=10.0)):
        assert out in ("LOW", "MODERATE", "HIGH")
