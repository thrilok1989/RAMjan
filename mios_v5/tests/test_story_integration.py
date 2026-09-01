"""MIOS V5 — Story Integration module tests.

Tests the integration layer between vob_minimal.py and the Story Engine.
Streamlit is mocked via sys.modules since it isn't installed in the test
environment and story_integration imports it lazily inside functions.

    python -m mios_v5.tests.test_story_integration
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

from mios_v5.market_events import build_event, EventType, EventSeverity
from mios_v5.story_task import StoryEngineTask


class _FakeStreamlit(types.ModuleType):
    """Minimal stand-in for the streamlit module (session_state only)."""

    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}


def _install_fake_streamlit() -> _FakeStreamlit:
    fake = _FakeStreamlit()
    sys.modules["streamlit"] = fake
    return fake


def _remove_fake_streamlit():
    sys.modules.pop("streamlit", None)
    # Drop cached story_integration module so next test gets a clean import
    sys.modules.pop("mios_v5.story_integration", None)


def test_get_story_task():
    """Get or create story task (mock Streamlit)."""
    _install_fake_streamlit()
    try:
        from mios_v5.story_integration import get_story_task

        task1 = get_story_task()
        assert isinstance(task1, StoryEngineTask)

        # Second call should return same instance
        task2 = get_story_task()
        assert task1 is task2
    finally:
        _remove_fake_streamlit()


def test_process_market_event():
    """Process a market event through story engine (mock DB)."""
    _install_fake_streamlit()
    try:
        from mios_v5.story_integration import get_story_task, process_market_event

        task = get_story_task()
        mock_db = MagicMock()
        mock_db.insert_market_story = MagicMock(return_value=1)

        # Build two events to trigger story recognition
        event1 = build_event(
            EventType.PUT_WRITING, EventSeverity.INFO,
            "x", "y", time=datetime.now()
        )
        event2 = build_event(
            EventType.CVD_REVERSAL, EventSeverity.INFO,
            "x", "y", time=datetime.now()
        )

        # First event: insufficient for recognition
        result1 = process_market_event(task, mock_db, event1)
        assert result1 is None

        # Second event: should trigger BULLISH_CONTINUATION recognition
        result2 = process_market_event(task, mock_db, event2)
        assert result2 is not None
        assert result2.get('story_type') == 'bullish_continuation'
        assert result2.get('confidence') > 0
        assert mock_db.insert_market_story.called
    finally:
        _remove_fake_streamlit()


def test_process_market_event_no_db():
    """Process event with no database available."""
    _install_fake_streamlit()
    try:
        from mios_v5.story_integration import get_story_task, process_market_event

        task = get_story_task()
        event = build_event(
            EventType.PUT_WRITING, EventSeverity.INFO,
            "x", "y", time=datetime.now()
        )

        # Process without DB should not crash
        result = process_market_event(task, None, event)
        assert result is None  # No recognition with single event
    finally:
        _remove_fake_streamlit()


def test_link_trade_to_story():
    """Link a trade to its story (mock DB)."""
    from mios_v5.story_integration import link_trade_to_story

    mock_db = MagicMock()
    mock_table = MagicMock()
    mock_db.conn.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{'story_id': 1}])

    result = link_trade_to_story(mock_db, trade_id=123, story_id=456)
    assert result is True
    mock_db.conn.table.assert_called_with('market_stories')
    mock_table.update.assert_called_with({'related_trade_id': 123})


def test_link_trade_to_story_no_db():
    """Link trade with no database."""
    from mios_v5.story_integration import link_trade_to_story

    result = link_trade_to_story(None, trade_id=123, story_id=456)
    assert result is False


def test_get_story_engine_status():
    """Get status of story engine."""
    _install_fake_streamlit()
    try:
        from mios_v5.story_integration import get_story_task, get_story_engine_status

        task = get_story_task()

        # Initially no active story
        status = get_story_engine_status(task)
        assert status['active_story_id'] is None
        assert status['active_event_count'] == 0

        # Add an event
        event = build_event(
            EventType.PUT_WRITING, EventSeverity.INFO,
            "x", "y", time=datetime.now()
        )
        task.process_event(event)

        status = get_story_engine_status(task)
        assert status['active_story_id'] is not None
        assert status['active_event_count'] > 0
        assert status['last_event_time'] is not None
    finally:
        _remove_fake_streamlit()


def test_get_story_engine_status_no_task():
    """Get status with no task."""
    from mios_v5.story_integration import get_story_engine_status

    status = get_story_engine_status(None)
    assert status['active_story_id'] is None
    assert status['active_event_count'] == 0
    assert status['total_stories_closed'] == 0


def main() -> int:
    tests = [
        test_get_story_task,
        test_process_market_event,
        test_process_market_event_no_db,
        test_link_trade_to_story,
        test_link_trade_to_story_no_db,
        test_get_story_engine_status,
        test_get_story_engine_status_no_task,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
