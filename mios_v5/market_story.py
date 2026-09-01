"""MIOS V5 — Market Story Engine (Stage 4: Chronological story building).

Links events into market narratives. A story is a sequence of related market
events that share a common market context or theme.

Examples:
- Story: Gap Up opening → Support Hold → Heavy Put Writing → Bullish Confirmation
- Story: Liquidity Sweep → CVD Reversal → OI Wall Break → Target Hit

Pure logic—no trading signals, no modification of Entry Gate/Guardian.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any

from .market_events import MarketEvent, EventType, EventSeverity


class StoryType(Enum):
    """Known market story patterns (retrospective classification)."""
    OPENING_BELL = "opening_bell"
    BULLISH_CONTINUATION = "bullish_continuation"
    BEARISH_CONTINUATION = "bearish_continuation"
    BULLISH_REVERSAL = "bullish_reversal"
    BEARISH_REVERSAL = "bearish_reversal"
    FALSE_BREAKOUT = "false_breakout"
    FALSE_BREAKDOWN = "false_breakdown"
    LIQUIDITY_GRAB = "liquidity_grab"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    TREND_EXHAUSTION = "trend_exhaustion"
    GAMMA_SQUEEZE = "gamma_squeeze"
    EXPIRY_PINNING = "expiry_pinning"
    RANGE_EXPANSION = "range_expansion"
    RANGE_ROTATION = "range_rotation"
    VALUE_ACCEPTANCE = "value_acceptance"
    VALUE_REJECTION = "value_rejection"
    UNKNOWN = "unknown"


@dataclass
class Story:
    """Chronological sequence of events forming a market narrative."""
    story_id: int
    created_at: datetime
    market_time_start: datetime
    market_time_end: Optional[datetime]
    symbol: str
    events: List[MarketEvent]
    story_type: StoryType = StoryType.UNKNOWN
    confidence: float = 0.0  # 0-100, how confident is this classification?
    summary: str = ""  # human-readable narrative
    related_trade_id: Optional[int] = None
    metadata: Dict[str, Any] = None

    def duration_seconds(self) -> int:
        """How long this story lasted."""
        if self.market_time_end is None:
            return 0
        return int((self.market_time_end - self.market_time_start).total_seconds())

    def event_count(self) -> int:
        """How many events in this story."""
        return len(self.events)

    def event_types_summary(self) -> List[str]:
        """List of unique event types in this story."""
        return list(set(e.type.value for e in self.events))


class StoryBoundary(Enum):
    """Conditions that trigger a new story."""
    OPENING_BELL = "opening_bell"  # Start of session
    REGIME_CHANGE = "regime_change"  # Market mode changes
    MAJOR_OI_SHIFT = "major_oi_shift"  # OI moves significantly
    LARGE_LIQUIDITY_EVENT = "large_liquidity_event"  # Sweep or wall break
    TREND_START = "trend_start"  # New directional move begins
    TIME_GAP = "time_gap"  # No events for N minutes
    MANUAL = "manual"  # Explicitly marked


class StoryEngine:
    """Builds and manages chronological market stories."""

    def __init__(self):
        self.stories: List[Story] = []
        self.current_story: Optional[Story] = None
        self.story_counter = 0

    def add_event(self, event: MarketEvent, boundary_type: Optional[StoryBoundary] = None) -> Story:
        """Add an event to the story stream. If boundary_type is set, start a new story."""
        if boundary_type or self.current_story is None:
            # Start a new story
            self.story_counter += 1
            self.current_story = Story(
                story_id=self.story_counter,
                created_at=datetime.now(),
                market_time_start=event.time,
                market_time_end=None,
                symbol=event.snapshot.spot if event.snapshot else "NIFTY",
                events=[event],
                metadata={},
            )
            self.stories.append(self.current_story)
        else:
            # Add to current story
            self.current_story.events.append(event)
            self.current_story.market_time_end = event.time

        return self.current_story

    def close_current_story(self) -> Optional[Story]:
        """Explicitly close the current story."""
        if self.current_story:
            self.current_story = None
        return self.current_story

    def get_stories(self, limit: int = 100) -> List[Story]:
        """Recent stories (newest first)."""
        return sorted(self.stories, key=lambda s: s.story_id, reverse=True)[:limit]

    def get_story(self, story_id: int) -> Optional[Story]:
        """Fetch a story by ID."""
        return next((s for s in self.stories if s.story_id == story_id), None)


def detect_story_boundary(
    last_event: Optional[MarketEvent],
    current_event: MarketEvent,
    minutes_threshold: int = 5,
) -> Optional[StoryBoundary]:
    """Detect if current_event should start a new story.

    Returns StoryBoundary type if a boundary is detected, else None.
    """
    if last_event is None:
        # First event of the session
        if 9 <= current_event.time.hour <= 10:  # IST opening bell window
            return StoryBoundary.OPENING_BELL
        return None

    # Check for time gap
    time_delta = (current_event.time - last_event.time).total_seconds() / 60
    if time_delta > minutes_threshold:
        return StoryBoundary.TIME_GAP

    # Check for major event types that signal boundary
    if current_event.type in (EventType.SUPPORT_BREAK, EventType.RESISTANCE_BREAK):
        return StoryBoundary.TREND_START

    if current_event.type in (EventType.OI_WALL, EventType.LIQUIDITY_SWEEP):
        return StoryBoundary.LARGE_LIQUIDITY_EVENT

    # NOTE: CVD_REVERSAL is intentionally NOT a boundary trigger — it is a
    # confirmation event that must combine with the initiating event (e.g.
    # PUT_WRITING, LIQUIDITY_SWEEP) within the SAME story for recognition
    # patterns (BULLISH_CONTINUATION, LIQUIDITY_GRAB, ...) to match.

    return None


def classify_story(story: Story) -> StoryType:
    """Classify a completed story into a known type.

    This is retrospective—run AFTER the story ends. Pattern matches against
    event sequences.

    Returns the best-matching StoryType.
    """
    if not story.events:
        return StoryType.UNKNOWN

    # Extract event types
    types = [e.type for e in story.events]

    # Pattern: Heavy put writing → reversal (has breakout)
    if (EventType.PUT_WRITING in types and
        EventType.CVD_REVERSAL in types and
        EventType.BREAKOUT_CANDLE in types):
        return StoryType.BULLISH_REVERSAL

    # Pattern: Heavy call writing + divergence + breakout → reversal
    if (EventType.CALL_WRITING in types and
        EventType.CVD_DIVERGENCE in types and
        EventType.BREAKOUT_CANDLE in types):
        return StoryType.BEARISH_REVERSAL

    # Pattern: Opening gap → support hold → bullish confirmation
    if (EventType.SUPPORT_BREAK not in types and
        EventType.PUT_WRITING in types and
        EventType.CVD_REVERSAL in types):
        return StoryType.BULLISH_CONTINUATION

    # Pattern: Support break → bearish confirmation
    if (EventType.SUPPORT_BREAK in types and
        EventType.CALL_WRITING in types and
        EventType.CVD_DIVERGENCE in types):
        return StoryType.BEARISH_CONTINUATION

    # Pattern: OI wall + break = squeeze
    if (EventType.OI_WALL in types and
        EventType.BREAKOUT_CANDLE in types and
        EventType.HIGH_VOLUME in types):
        return StoryType.GAMMA_SQUEEZE

    # Pattern: Liquidity sweep + reversal
    if (EventType.LIQUIDITY_SWEEP in types and
        EventType.CVD_REVERSAL in types):
        return StoryType.LIQUIDITY_GRAB

    # Pattern: Long buildup + no move = accumulation
    if story.duration_seconds() > 600 and EventType.HIGH_VOLUME not in types:
        return StoryType.ACCUMULATION

    return StoryType.UNKNOWN


def confidence_score(story: Story) -> float:
    """Score confidence (0-100) in story classification.

    Higher confidence = more events match the pattern.
    """
    if not story.events:
        return 0.0

    # Simple heuristic: more events + longer duration = higher confidence
    event_score = min(100, len(story.events) * 10)
    duration_score = min(100, story.duration_seconds() / 60)  # 60 sec = 100% on duration
    return (event_score + duration_score) / 2
