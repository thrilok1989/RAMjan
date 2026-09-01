"""MIOS V5 — Story Engine and Story Generator tests.

    python -m mios_v5.tests.test_story_engine
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from mios_v5.market_events import build_event, EventType, EventSeverity
from mios_v5.market_story import (
    StoryEngine, StoryBoundary, Story, classify_story, confidence_score,
    detect_story_boundary,
)
from mios_v5.story_generator import (
    generate_narrative, generate_brief_narrative,
)


def test_story_engine_init():
    """Story engine starts with no stories."""
    engine = StoryEngine()
    assert engine.story_counter == 0
    assert len(engine.stories) == 0
    assert engine.current_story is None


def test_add_event_starts_story():
    """First event creates a new story."""
    engine = StoryEngine()
    event = build_event(
        EventType.PUT_WRITING,
        EventSeverity.INFO,
        "x", "y",
        time=datetime(2026, 1, 15, 9, 15),
    )
    story = engine.add_event(event)
    assert story is not None
    assert story.story_id == 1
    assert len(story.events) == 1
    assert story.events[0].type == EventType.PUT_WRITING


def test_add_event_to_current_story():
    """Subsequent events add to current story."""
    engine = StoryEngine()
    now = datetime.now()
    event1 = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now)
    event2 = build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30))

    engine.add_event(event1)
    story = engine.add_event(event2)

    assert story.story_id == 1
    assert len(story.events) == 2
    assert story.events[1].type == EventType.CVD_REVERSAL


def test_story_boundary_starts_new_story():
    """Boundary condition creates a new story."""
    engine = StoryEngine()
    now = datetime.now()
    event1 = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now)
    event2 = build_event(EventType.SUPPORT_BREAK, EventSeverity.INFO, "x", "y", time=now + timedelta(minutes=1))

    engine.add_event(event1)
    story2 = engine.add_event(event2, boundary_type=StoryBoundary.TREND_START)

    assert len(engine.stories) == 2
    assert engine.stories[0].story_id == 1
    assert story2.story_id == 2


def test_detect_time_gap_boundary():
    """Time gap > threshold triggers boundary."""
    now = datetime.now()
    event1 = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now)
    event2 = build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now + timedelta(minutes=6))

    boundary = detect_story_boundary(event1, event2, minutes_threshold=5)
    assert boundary == StoryBoundary.TIME_GAP


def test_detect_trend_start_boundary():
    """Support/resistance break triggers boundary."""
    now = datetime.now()
    event1 = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now)
    event2 = build_event(EventType.SUPPORT_BREAK, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30))

    boundary = detect_story_boundary(event1, event2)
    assert boundary == StoryBoundary.TREND_START


def test_story_duration():
    """Story duration calculation."""
    now = datetime.now()
    event1 = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now)
    event2 = build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(minutes=5))

    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=event1.time,
        market_time_end=event2.time,
        symbol="NIFTY",
        events=[event1, event2],
    )
    assert story.duration_seconds() == 300


def test_classify_story_bullish_continuation():
    """Story with put writing + CVD reversal (no support break) = bullish continuation."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
        build_event(EventType.HIGH_VOLUME, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=60)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    story_type = classify_story(story)
    assert story_type.value == "bullish_continuation"


def test_classify_story_bearish_continuation():
    """Story with support break + call writing + CVD divergence = bearish continuation."""
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
    story_type = classify_story(story)
    assert story_type.value == "bearish_continuation"


def test_confidence_score():
    """More events = higher confidence."""
    now = datetime.now()
    events_short = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
    ]
    events_long = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=i*30))
        for i in range(5)
    ]
    story_short = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events_short[0].time,
        market_time_end=events_short[0].time,
        symbol="NIFTY",
        events=events_short,
    )
    story_long = Story(
        story_id=2,
        created_at=datetime.now(),
        market_time_start=events_long[0].time,
        market_time_end=events_long[-1].time,
        symbol="NIFTY",
        events=events_long,
    )
    conf_short = confidence_score(story_short)
    conf_long = confidence_score(story_long)
    assert conf_long > conf_short


def test_generate_narrative():
    """Narrative generation produces readable text."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "Heavy Put Writing", "x", time=now),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "Order flow reversed", "x", time=now + timedelta(seconds=30)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    narrative = generate_narrative(story)
    assert len(narrative) > 20
    assert "H:" in narrative or ":" in narrative  # Time reference
    assert "put" in narrative.lower() or "order" in narrative.lower()


def test_generate_brief_narrative():
    """Brief narrative is short event chain."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now),
        build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now + timedelta(seconds=30)),
    ]
    story = Story(
        story_id=1,
        created_at=datetime.now(),
        market_time_start=events[0].time,
        market_time_end=events[-1].time,
        symbol="NIFTY",
        events=events,
    )
    brief = generate_brief_narrative(story)
    assert "→" in brief
    assert "Put Writing" in brief
    assert "Breakout Candle" in brief


def test_get_stories():
    """Fetch recent stories."""
    engine = StoryEngine()
    now = datetime.now()
    for i in range(3):
        event = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now + timedelta(minutes=i))
        engine.add_event(event, boundary_type=StoryBoundary.TIME_GAP if i > 0 else None)

    stories = engine.get_stories()
    assert len(stories) >= 3


def test_get_story_by_id():
    """Fetch a specific story."""
    engine = StoryEngine()
    event = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y")
    engine.add_event(event)
    story = engine.get_story(1)
    assert story is not None
    assert story.story_id == 1


def main() -> int:
    tests = [
        test_story_engine_init,
        test_add_event_starts_story,
        test_add_event_to_current_story,
        test_story_boundary_starts_new_story,
        test_detect_time_gap_boundary,
        test_detect_trend_start_boundary,
        test_story_duration,
        test_classify_story_bullish_continuation,
        test_classify_story_bearish_continuation,
        test_confidence_score,
        test_generate_narrative,
        test_generate_brief_narrative,
        test_get_stories,
        test_get_story_by_id,
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
