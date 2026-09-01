"""MIOS V5 — Story Recognition & Validation tests.

    python -m mios_v5.tests.test_story_recognition_validation
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from mios_v5.market_events import build_event, EventType, EventSeverity
from mios_v5.market_story import Story, StoryType
from mios_v5.story_recognition import (
    recognize_story, recognize_all_stories, get_recognition_summary,
    RecognitionPattern,
)
from mios_v5.story_validation import (
    TradeValidation, TradeOutcome, StoryValidationStats, ValidationDataset,
)


# ── Stage 6: Story Recognition Tests ──────────────────────────────────────

def test_recognize_bullish_continuation():
    """Recognize bullish continuation pattern."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
        build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=60)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type, confidence = recognize_story(story)
    assert story_type == StoryType.BULLISH_CONTINUATION
    assert confidence >= 60


def test_recognize_bearish_continuation():
    """Recognize bearish continuation pattern."""
    now = datetime.now()
    events = [
        build_event(EventType.SUPPORT_BREAK, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.CALL_WRITING, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
        build_event(EventType.CVD_DIVERGENCE, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=60)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type, confidence = recognize_story(story)
    assert story_type == StoryType.BEARISH_CONTINUATION
    assert confidence >= 60


def test_recognize_gamma_squeeze():
    """Recognize gamma squeeze pattern."""
    now = datetime.now()
    events = [
        build_event(EventType.OI_WALL, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.HIGH_VOLUME, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
        build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=60)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type, confidence = recognize_story(story)
    assert story_type == StoryType.GAMMA_SQUEEZE
    assert confidence >= 60


def test_recognize_liquidity_grab():
    """Recognize liquidity grab pattern."""
    now = datetime.now()
    events = [
        build_event(EventType.LIQUIDITY_SWEEP, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type, confidence = recognize_story(story)
    assert story_type == StoryType.LIQUIDITY_GRAB
    assert confidence >= 60


def test_recognize_unknown():
    """Unmatched pattern returns UNKNOWN."""
    now = datetime.now()
    events = [
        build_event(EventType.VIX_SPIKE, EventSeverity.INFO, "x", "y", time=now),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type, confidence = recognize_story(story)
    assert story_type == StoryType.UNKNOWN


def test_recognition_summary():
    """Generate human-readable recognition result."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    summary = get_recognition_summary(story)
    assert "Pattern:" in summary
    assert "confidence" in summary.lower()


def test_recognize_all_stories():
    """Recognize patterns for multiple stories."""
    now = datetime.now()
    story1 = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=now,
        market_time_end=now + timedelta(minutes=5),
        symbol="NIFTY",
        events=[
            build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
            build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
        ],
    )
    story2 = Story(
        story_id=2,
        created_at=datetime.now(),
        market_time_start=now + timedelta(minutes=10),
        market_time_end=now + timedelta(minutes=15),
        symbol="NIFTY",
        events=[
            build_event(EventType.VIX_SPIKE, EventSeverity.INFO, "x", "y", time=now + timedelta(minutes=10)),
        ],
    )
    results = recognize_all_stories([story1, story2])
    assert len(results) >= 1
    assert results[0][0] == 1  # story_id


# ── Stage 9: Story Validation Tests ────────────────────────────────────────

def test_trade_validation_outcome():
    """Trade outcome classification from points_moved."""
    trade_win = TradeValidation(
        trade_id=1, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
        side="CALL", entry_price=24000, exit_price=24050,
        points_moved=50, exit_reason="TARGET_HIT",
    )
    trade_loss = TradeValidation(
        trade_id=2, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
        side="CALL", entry_price=24000, exit_price=23970,
        points_moved=-30, exit_reason="INVALIDATED",
    )
    assert trade_win.outcome == TradeOutcome.WIN
    assert trade_loss.outcome == TradeOutcome.LOSS


def test_trade_r_multiple():
    """Compute R-multiple from points_moved and risk."""
    trade = TradeValidation(
        trade_id=1, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
        side="CALL", entry_price=24000, exit_price=24050,
        points_moved=50, exit_reason="TARGET_HIT",
    )
    r = trade.r_multiple(risk_points=25.0)
    assert r == 2.0  # 50 / 25 = 2R


def test_validation_stats_computation():
    """Compute statistics from multiple trades."""
    stats = StoryValidationStats(story_type=StoryType.BULLISH_CONTINUATION)
    stats.trades = [
        TradeValidation(
            trade_id=1, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
            side="CALL", entry_price=24000, exit_price=24050,
            points_moved=50, exit_reason="TARGET_HIT",
        ),
        TradeValidation(
            trade_id=2, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
            side="CALL", entry_price=24000, exit_price=23970,
            points_moved=-30, exit_reason="INVALIDATED",
        ),
        TradeValidation(
            trade_id=3, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
            side="CALL", entry_price=24000, exit_price=24040,
            points_moved=40, exit_reason="TARGET_HIT",
        ),
    ]
    stats.compute_stats()
    assert stats.total_trades == 3
    assert stats.wins == 2
    assert stats.losses == 1
    assert abs(stats.win_rate - 66.67) < 1  # approximately 66.67%
    assert stats.total_pnl == 60  # 50 - 30 + 40


def test_validation_dataset():
    """Accumulate and aggregate validations."""
    dataset = ValidationDataset()
    dataset.add_validation(TradeValidation(
        trade_id=1, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
        side="CALL", entry_price=24000, exit_price=24050,
        points_moved=50, exit_reason="TARGET_HIT",
    ))
    dataset.add_validation(TradeValidation(
        trade_id=2, story_id=2, story_type=StoryType.BEARISH_CONTINUATION,
        side="PUT", entry_price=24000, exit_price=23950,
        points_moved=50, exit_reason="TARGET_HIT",
    ))
    dataset.compute_all_stats()
    assert len(dataset.stats_by_type) == 2
    bc_stats = dataset.get_stats(StoryType.BULLISH_CONTINUATION)
    assert bc_stats is not None
    assert bc_stats.wins == 1


def test_validation_stats_ranking():
    """Rank statistics by win-rate."""
    dataset = ValidationDataset()
    # Add bullish continuation trades (100% win-rate)
    for i in range(3):
        dataset.add_validation(TradeValidation(
            trade_id=i, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
            side="CALL", entry_price=24000, exit_price=24050,
            points_moved=50, exit_reason="TARGET_HIT",
        ))
    # Add bearish continuation trades (50% win-rate)
    for i in range(3, 5):
        dataset.add_validation(TradeValidation(
            trade_id=i, story_id=2, story_type=StoryType.BEARISH_CONTINUATION,
            side="PUT", entry_price=24000, exit_price=23950 if i % 2 == 0 else 24010,
            points_moved=50 if i % 2 == 0 else -10, exit_reason="TARGET_HIT",
        ))
    dataset.compute_all_stats()
    ranked = dataset.get_stats_ranked(by="win_rate")
    assert ranked[0].story_type == StoryType.BULLISH_CONTINUATION
    assert ranked[0].win_rate > ranked[1].win_rate


def test_validation_summary():
    """Generate summary report."""
    dataset = ValidationDataset()
    dataset.add_validation(TradeValidation(
        trade_id=1, story_id=1, story_type=StoryType.BULLISH_CONTINUATION,
        side="CALL", entry_price=24000, exit_price=24050,
        points_moved=50, exit_reason="TARGET_HIT",
    ))
    dataset.compute_all_stats()
    summary = dataset.summary()
    assert len(summary) > 20
    assert "Summary" in summary


def main() -> int:
    tests = [
        # Stage 6: Recognition
        test_recognize_bullish_continuation,
        test_recognize_bearish_continuation,
        test_recognize_gamma_squeeze,
        test_recognize_liquidity_grab,
        test_recognize_unknown,
        test_recognition_summary,
        test_recognize_all_stories,
        # Stage 9: Validation
        test_trade_validation_outcome,
        test_trade_r_multiple,
        test_validation_stats_computation,
        test_validation_dataset,
        test_validation_stats_ranking,
        test_validation_summary,
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
