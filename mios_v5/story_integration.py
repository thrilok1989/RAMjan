"""MIOS V5 — Story Engine Integration with Live Trading.

Wires the StoryEngineTask into vob_minimal.py event processing.
Captures market microstructure events and feeds them to the story engine
for real-time pattern recognition and narrative generation.

Usage in vob_minimal.py:
    from mios_v5.story_integration import get_story_task, process_market_event

    # Once at session start:
    task = get_story_task()

    # Whenever a significant market event occurs:
    story_result = process_market_event(task, db, event)
"""

from __future__ import annotations

from typing import Optional

from .story_task import StoryEngineTask
from .market_events import MarketEvent


def get_story_task() -> StoryEngineTask:
    """Get or create the stateful StoryEngineTask for this session.

    Streamlit reruns on each interaction, so we store the task in
    session_state to preserve engine state across reruns.
    """
    import streamlit as st
    if '_story_engine_task' not in st.session_state:
        st.session_state['_story_engine_task'] = StoryEngineTask()
    return st.session_state['_story_engine_task']


def process_market_event(
    task: StoryEngineTask,
    db,
    event: MarketEvent
) -> Optional[dict]:
    """Process one market event through the story engine.

    Returns story result dict if a story was recognized, else None.

    Args:
        task: StoryEngineTask instance
        db: SupabaseDB instance (for persistence)
        event: MarketEvent to process

    Returns:
        {
            'story_id': int,
            'story_type': str,
            'confidence': float,
            'narrative': str,
            'brief': str,
            'event_count': int,
            'duration_seconds': int,
        } or None
    """
    if not task or not event:
        return None

    # Process event through story engine
    story_result = task.process_event(event)

    if story_result and db:
        try:
            # Persist recognized story to database
            db.insert_market_story(story_result)
        except Exception as e:
            # Log but don't break live trading
            try:
                import streamlit as st
                st.session_state['_story_db_error'] = str(e)
            except Exception:
                pass

    return story_result


def link_trade_to_story(db, trade_id: int, story_id: int) -> bool:
    """Link a closed trade to its market story for validation.

    Called when a trade exits. Marks the trade-story relationship
    so validation can later connect outcome to pattern.

    Args:
        db: SupabaseDB instance
        trade_id: ID of the closed trade
        story_id: ID of the market story it happened in

    Returns:
        True if link was successful, False otherwise
    """
    if not db or not trade_id or not story_id:
        return False

    try:
        # Update the related_trade_id in market_stories table
        result = db.conn.table('market_stories').update(
            {'related_trade_id': trade_id}
        ).eq('story_id', story_id).execute()
        return bool(result.data)
    except Exception:
        return False


def get_story_engine_status(task: StoryEngineTask) -> dict:
    """Get current story engine status for dashboard display.

    Returns:
        {
            'active_story_id': int or None,
            'active_story_type': str or None,
            'active_event_count': int,
            'total_stories_closed': int,
            'last_event_time': str or None,
        }
    """
    if not task:
        return {
            'active_story_id': None,
            'active_story_type': None,
            'active_event_count': 0,
            'total_stories_closed': 0,
            'last_event_time': None,
        }

    current = task.current_story()
    stories = task.get_stories(limit=1)

    return {
        'active_story_id': current.story_id if current else None,
        'active_story_type': str(current.story_type) if current else None,
        'active_event_count': len(current.events) if current else 0,
        'total_stories_closed': len(stories),
        'last_event_time': task.last_event.time.isoformat() if task.last_event else None,
    }
