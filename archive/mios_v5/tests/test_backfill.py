"""MIOS V5 — Stage 2 historical backfill tests.

    python -m mios_v5.tests.test_backfill
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from mios_v5.backfill import (
    BACKFILL_ENGINE_VERSION,
    build_backfill_engine_state_row,
    classify_trend_from_price,
    compute_backfill_structure,
    iter_backfill_samples,
)


def _uptrend_df(n=60):
    closes = np.linspace(100, 120, n)
    return pd.DataFrame({
        "high": closes + 0.5, "low": closes - 0.5, "close": closes,
        "open": closes - 0.2, "volume": [1000] * n,
        "datetime": pd.date_range("2026-01-01 09:15", periods=n, freq="1min"),
    })


def _flat_df(n=60):
    closes = [100.0] * n
    return pd.DataFrame({
        "high": [100.5] * n, "low": [99.5] * n, "close": closes,
        "open": closes, "volume": [1000] * n,
        "datetime": pd.date_range("2026-01-01 09:15", periods=n, freq="1min"),
    })


def test_classify_trend_uptrend():
    trend, stars = classify_trend_from_price(_uptrend_df())
    assert "Uptrend" in trend
    assert stars > 0


def test_classify_trend_flat_is_range():
    trend, stars = classify_trend_from_price(_flat_df())
    assert trend == "Range"


def test_classify_trend_insufficient_data():
    trend, stars = classify_trend_from_price(_flat_df(n=5))
    assert trend == "Unknown" and stars == 0


def test_iter_backfill_samples_respects_stride_and_lookback():
    df = _uptrend_df(n=100)
    samples = list(iter_backfill_samples(df, stride=20, lookback=30))
    assert len(samples) > 0
    for window, spot, ts in samples:
        assert len(window) <= 31  # lookback + current bar
        assert isinstance(spot, float)


def test_compute_backfill_structure_no_crash_with_stub_detectors():
    df = _uptrend_df()
    result = compute_backfill_structure(
        df, spot=119.0,
        swing_sr=lambda d: ([100.0], [125.0]),
        vwap=lambda d: pd.Series([110.0] * len(d)),
        order_blocks=lambda d: {},
        chart_pattern=lambda d: None,
        candle_pattern=lambda d: None,
    )
    assert result["trend"]
    assert 0 <= result["structure_score"] <= 100
    assert result["bias"] in ("STRONG_BULL", "BULL", "STRONG_BEAR", "BEAR", "NEUTRAL")


def test_compute_backfill_structure_demand_zone():
    df = _uptrend_df()
    result = compute_backfill_structure(
        df, spot=100.2,  # right at support
        swing_sr=lambda d: ([100.0], [130.0]),
        vwap=lambda d: pd.Series([98.0] * len(d)),  # spot above vwap
        order_blocks=lambda d: {
            "bullish_ob": {"low": 99.0, "high": 101.0, "avg": 100.0, "bar_idx": 5},
        },
        chart_pattern=lambda d: {"pattern": "Ascending Triangle", "direction": "Bullish"},
        candle_pattern=lambda d: {"pattern": "Bullish Engulfing", "direction": "Bullish"},
    )
    assert result["demand_supply"] == "Demand"
    assert result["structure_score"] >= 75
    assert result["decision"] == "TRADE ZONE"
    assert result["order_block"]["freshness"] in ("fresh", "retested")


def test_compute_backfill_structure_handles_detector_exceptions():
    """A detector raising must never propagate — matches the live
    engine's exception-safety philosophy."""
    df = _uptrend_df()
    def _boom(d):
        raise RuntimeError("boom")
    result = compute_backfill_structure(
        df, spot=119.0, swing_sr=_boom, vwap=_boom,
        order_blocks=_boom, chart_pattern=_boom, candle_pattern=_boom,
    )
    assert result["support"] is None and result["resistance"] is None
    assert result["vwap_position"] == "Unknown"


def test_build_backfill_engine_state_row_shape_and_version():
    structure = compute_backfill_structure(
        _uptrend_df(), spot=119.0,
        swing_sr=lambda d: ([], []), vwap=lambda d: pd.Series(dtype=float),
        order_blocks=lambda d: {}, chart_pattern=lambda d: None,
        candle_pattern=lambda d: None,
    )
    ts = datetime(2026, 1, 1, 10, 0)
    row = build_backfill_engine_state_row(structure, spot=119.0, ts=ts,
                                          trading_day="2026-01-01")
    assert row["engine_version"] == BACKFILL_ENGINE_VERSION
    assert row["trading_day"] == "2026-01-01"
    assert row["structure_score"] == structure["structure_score"]
    assert "stage02_structure" in row["full_state"]


def main() -> int:
    tests = [
        test_classify_trend_uptrend,
        test_classify_trend_flat_is_range,
        test_classify_trend_insufficient_data,
        test_iter_backfill_samples_respects_stride_and_lookback,
        test_compute_backfill_structure_no_crash_with_stub_detectors,
        test_compute_backfill_structure_demand_zone,
        test_compute_backfill_structure_handles_detector_exceptions,
        test_build_backfill_engine_state_row_shape_and_version,
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
