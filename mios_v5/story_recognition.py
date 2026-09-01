"""MIOS V5 — Story Recognition (Stage 6: Real-time pattern matching).

Recognizes known story patterns as they unfold (in-progress stories).
Provides early detection without waiting for story completion.

Examples:
- "This looks like accumulation" (3 min into the story)
- "Pattern matches bullish reversal" (confidence 72%)
- "Could be a gamma squeeze" (watching for confirmation)

Pure observation—does NOT influence trading logic.
"""

from __future__ import annotations

from typing import List, Tuple, Optional

from .market_events import MarketEvent, EventType
from .market_story import Story, StoryType


class RecognitionPattern:
    """Pattern to match against a story's event sequence."""

    def __init__(
        self,
        story_type: StoryType,
        required_events: List[EventType],
        forbidden_events: Optional[List[EventType]] = None,
        min_confidence: float = 50.0,
    ):
        """
        Args:
            story_type: The story type this pattern represents
            required_events: Event types that MUST appear (in any order)
            forbidden_events: Event types that MUST NOT appear
            min_confidence: Minimum confidence (0-100) to classify as this type
        """
        self.story_type = story_type
        self.required_events = required_events
        self.forbidden_events = forbidden_events or []
        self.min_confidence = min_confidence

    def match_confidence(self, events: List[MarketEvent]) -> float:
        """Score how well these events match this pattern (0-100)."""
        if not events:
            return 0.0

        event_types = [e.type for e in events]

        # Check forbidden events
        for forbidden in self.forbidden_events:
            if forbidden in event_types:
                return 0.0

        # Count how many required events are present
        required_count = sum(1 for req in self.required_events if req in event_types)
        match_ratio = required_count / len(self.required_events) if self.required_events else 0.5
        confidence = match_ratio * 100
        return confidence


# Pattern definitions for known story types
RECOGNITION_PATTERNS = [
    # Bullish Continuation: put writing + CVD reversal (no support break)
    RecognitionPattern(
        StoryType.BULLISH_CONTINUATION,
        required_events=[EventType.PUT_WRITING, EventType.CVD_REVERSAL],
        forbidden_events=[EventType.SUPPORT_BREAK],
        min_confidence=60.0,
    ),

    # Bearish Continuation: support break + call writing + CVD divergence
    RecognitionPattern(
        StoryType.BEARISH_CONTINUATION,
        required_events=[EventType.SUPPORT_BREAK, EventType.CALL_WRITING, EventType.CVD_DIVERGENCE],
        forbidden_events=[],
        min_confidence=70.0,
    ),

    # Bullish Reversal: put writing + CVD reversal + breakout
    RecognitionPattern(
        StoryType.BULLISH_REVERSAL,
        required_events=[EventType.PUT_WRITING, EventType.CVD_REVERSAL, EventType.BREAKOUT_CANDLE],
        forbidden_events=[],
        min_confidence=75.0,
    ),

    # Bearish Reversal: call writing + CVD divergence + breakout
    RecognitionPattern(
        StoryType.BEARISH_REVERSAL,
        required_events=[EventType.CALL_WRITING, EventType.CVD_DIVERGENCE, EventType.BREAKOUT_CANDLE],
        forbidden_events=[],
        min_confidence=75.0,
    ),

    # Liquidity Grab: liquidity sweep + CVD reversal
    RecognitionPattern(
        StoryType.LIQUIDITY_GRAB,
        required_events=[EventType.LIQUIDITY_SWEEP, EventType.CVD_REVERSAL],
        forbidden_events=[],
        min_confidence=65.0,
    ),

    # Gamma Squeeze: OI wall + high volume + breakout
    RecognitionPattern(
        StoryType.GAMMA_SQUEEZE,
        required_events=[EventType.OI_WALL, EventType.HIGH_VOLUME, EventType.BREAKOUT_CANDLE],
        forbidden_events=[],
        min_confidence=70.0,
    ),

    # Accumulation: long duration without major moves
    RecognitionPattern(
        StoryType.ACCUMULATION,
        required_events=[EventType.PUT_WRITING, EventType.SUPPORT_BREAK],  # "soft" pattern
        forbidden_events=[EventType.BREAKOUT_CANDLE, EventType.HIGH_VOLUME],
        min_confidence=50.0,
    ),

    # Distribution: long duration with call writing
    RecognitionPattern(
        StoryType.DISTRIBUTION,
        required_events=[EventType.CALL_WRITING, EventType.RESISTANCE_BREAK],
        forbidden_events=[EventType.BREAKOUT_CANDLE],
        min_confidence=50.0,
    ),

    # Trend Exhaustion: breakout + OI wall rejection
    RecognitionPattern(
        StoryType.TREND_EXHAUSTION,
        required_events=[EventType.BREAKOUT_CANDLE, EventType.OI_WALL, EventType.HIGH_VOLUME],
        forbidden_events=[],
        min_confidence=70.0,
    ),

    # Range Expansion: resistance/support break + follow-through
    RecognitionPattern(
        StoryType.RANGE_EXPANSION,
        required_events=[EventType.RESISTANCE_BREAK, EventType.BREAKOUT_CANDLE],
        forbidden_events=[],
        min_confidence=65.0,
    ),

    # False Breakout: breakout followed by reversal
    RecognitionPattern(
        StoryType.FALSE_BREAKOUT,
        required_events=[EventType.RESISTANCE_BREAK, EventType.CVD_DIVERGENCE],
        forbidden_events=[],
        min_confidence=60.0,
    ),

    # False Breakdown: support break followed by recovery
    RecognitionPattern(
        StoryType.FALSE_BREAKDOWN,
        required_events=[EventType.SUPPORT_BREAK, EventType.CVD_REVERSAL],
        forbidden_events=[],
        min_confidence=60.0,
    ),
]


def recognize_story(story: Story) -> Tuple[StoryType, float]:
    """Recognize current story pattern (in-progress or complete).

    Returns (best_matching_story_type, confidence_0_to_100)

    This runs on partial/incomplete stories, not just final ones.
    Multiple patterns may match—returns the best match.
    """
    if not story.events:
        return (StoryType.UNKNOWN, 0.0)

    best_match = (StoryType.UNKNOWN, 0.0)

    for pattern in RECOGNITION_PATTERNS:
        confidence = pattern.match_confidence(story.events)
        if confidence >= pattern.min_confidence and confidence > best_match[1]:
            best_match = (pattern.story_type, confidence)

    return best_match


def recognize_all_stories(stories: List[Story]) -> List[Tuple[int, StoryType, float]]:
    """Recognize patterns for multiple stories.

    Returns list of (story_id, story_type, confidence) tuples.
    """
    results = []
    for story in stories:
        story_type, confidence = recognize_story(story)
        if confidence > 0:
            results.append((story.story_id, story_type, confidence))
    return results


def get_recognition_summary(story: Story) -> str:
    """Human-readable summary of story recognition result."""
    story_type, confidence = recognize_story(story)
    if confidence == 0:
        return f"Pattern: Unknown (insufficient data)"
    return f"Pattern: {story_type.value.title()} ({confidence:.0f}% confidence)"
