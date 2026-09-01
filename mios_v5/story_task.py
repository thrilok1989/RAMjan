"""MIOS V5 — Story Engine Task (continuous story building from events).

Runs asynchronously during live trading. Consumes events, builds stories,
recognizes patterns, generates narratives—all without touching trading logic.

Usage in vob_minimal.py:
    engine = StoryEngine()
    for event in incoming_events:
        story = engine.add_event(event)
        # Recognize pattern
        story_type, confidence = recognize_story(story)
        # Generate narrative
        narrative = generate_narrative(story)
        # Store
        db.insert_market_story({...})
"""

from __future__ import annotations

from typing import List, Optional

from .market_events import MarketEvent
from .market_story import StoryEngine, Story, detect_story_boundary, StoryBoundary
from .story_recognition import recognize_story
from .story_generator import generate_narrative, generate_brief_narrative


class StoryEngineTask:
    """Continuous story building task (stateful, runs live)."""

    def __init__(self):
        self.engine = StoryEngine()
        self.last_event: Optional[MarketEvent] = None

    def process_event(self, event: MarketEvent) -> Optional[dict]:
        """Process one incoming event.

        Returns dict with story info if story changed/recognized, else None.

        Structure:
        {
            'story_id': int,
            'story_type': str,
            'confidence': float,
            'narrative': str,
            'brief': str,
            'event_count': int,
        }
        """
        # Detect if this event should start a new story
        boundary = detect_story_boundary(self.last_event, event, minutes_threshold=5)
        story = self.engine.add_event(event, boundary_type=boundary)
        self.last_event = event

        if not story or len(story.events) < 2:
            # Need at least 2 events for recognition
            return None

        # Recognize pattern
        story_type, confidence = recognize_story(story)
        if confidence == 0:
            # No pattern matched
            return None

        # Generate narrative
        narrative = generate_narrative(story)
        brief = generate_brief_narrative(story)

        return {
            'story_id': story.story_id,
            'story_type': story_type.value,
            'confidence': confidence,
            'narrative': narrative,
            'brief': brief,
            'event_count': len(story.events),
            'duration_seconds': story.duration_seconds(),
        }

    def current_story(self) -> Optional[Story]:
        """Get active story."""
        return self.engine.current_story

    def get_stories(self, limit: int = 10) -> List[Story]:
        """Get recent closed stories."""
        return self.engine.get_stories(limit=limit)


def serialize_story_for_db(story: Story, narrative: str, brief: str) -> dict:
    """Convert Story to database row format."""
    from datetime import datetime
    story_type, confidence = recognize_story(story)
    return {
        'story_id': story.story_id,
        'market_time_start': story.market_time_start.isoformat(),
        'market_time_end': story.market_time_end.isoformat() if story.market_time_end else None,
        'symbol': story.symbol,
        'story_type': story_type.value,
        'confidence': confidence,
        'summary': narrative,
        'event_count': len(story.events),
        'duration_seconds': story.duration_seconds(),
    }
