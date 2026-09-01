"""MIOS V5 — Market events, state inference, and scenario generation tests.

    python -m mios_v5.tests.test_market_events
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from mios_v5.market_events import (
    build_event, EventType, EventSeverity, EventRouter, format_discord_message
)
from mios_v5.market_state import infer_regime, MarketRegime
from mios_v5.scenario_engine import generate_scenarios, summarize_scenarios


def test_event_routing():
    """Events route to correct channels."""
    event = build_event(
        EventType.PUT_WRITING,
        EventSeverity.INFO,
        "Heavy Put Writing at 24850",
        "Dealers hedging upside.",
    )
    assert EventRouter.route_to_discord(event) is True
    assert EventRouter.route_to_supabase(event) is True
    assert EventRouter.route_to_telegram(event) is False


def test_discord_formatting():
    """Discord message format is clean."""
    event = build_event(
        EventType.PUT_WRITING,
        EventSeverity.INFO,
        "Heavy Put Writing at 24850",
        "Dealers hedging upside.",
        time=datetime(2026, 1, 15, 9, 18),
    )
    msg = format_discord_message(event)
    assert "09:18" in msg
    assert "Heavy Put Writing" in msg
    assert "Dealers hedging upside" in msg
    assert "🟢" in msg  # INFO severity


def test_discord_colors():
    """Severity maps to correct emoji."""
    info_event = build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y")
    warn_event = build_event(EventType.CVD_DIVERGENCE, EventSeverity.WARNING, "x", "y")
    alert_event = build_event(EventType.SUPPORT_BREAK, EventSeverity.ALERT, "x", "y")

    assert EventRouter.discord_color(info_event.severity) == "🟢"
    assert EventRouter.discord_color(warn_event.severity) == "🟡"
    assert EventRouter.discord_color(alert_event.severity) == "🔴"


def test_infer_trend_up():
    """Bullish event sequence infers TREND_UP."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=5)),
        build_event(EventType.LIQUIDITY_SWEEP, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=4)),
        build_event(EventType.CVD_REVERSAL, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=3)),
        build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=2)),
        build_event(EventType.CROSS_MARKET_CONFIRM, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
    ]
    state = infer_regime(events)
    assert state.regime == MarketRegime.TREND_UP
    assert state.confidence > 50
    assert "Buyers" in state.summary


def test_infer_distribution():
    """Bearish event sequence infers DISTRIBUTION."""
    now = datetime.now()
    events = [
        build_event(EventType.CALL_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=5)),
        build_event(EventType.SUPPORT_BREAK, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=4)),
        build_event(EventType.CALL_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=3)),
        build_event(EventType.CALL_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=2)),
        build_event(EventType.RESISTANCE_BREAK, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
    ]
    state = infer_regime(events)
    assert state.regime == MarketRegime.DISTRIBUTION
    assert "selling" in state.summary.lower()


def test_infer_exhaustion():
    """OI wall rejection signals exhaustion."""
    now = datetime.now()
    events = [
        build_event(EventType.OI_WALL, EventSeverity.ALERT, "x", "y", time=now - timedelta(minutes=2)),
    ]
    state = infer_regime(events)
    assert state.regime == MarketRegime.EXHAUSTION
    assert "exhaustion" in state.summary.lower()


def test_infer_reversal():
    """POC shift + CVD divergence + net bullish score signal reversal."""
    now = datetime.now()
    events = [
        build_event(EventType.POC_SHIFT, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=3)),
        build_event(EventType.CVD_DIVERGENCE, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=2)),
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=0, seconds=30)),
    ]
    state = infer_regime(events)
    assert state.regime == MarketRegime.REVERSAL


def test_empty_events_returns_range():
    """No events → RANGE (no conviction)."""
    state = infer_regime([])
    assert state.regime == MarketRegime.RANGE
    assert state.confidence == 0


def test_scenarios_from_trend_up():
    """Trend-up state generates continuation-favored scenarios."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=4)),
        build_event(EventType.LIQUIDITY_SWEEP, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=3)),
        build_event(EventType.BREAKOUT_CANDLE, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=2)),
        build_event(EventType.CROSS_MARKET_CONFIRM, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
    ]
    state = infer_regime(events)
    scenarios = generate_scenarios(state)
    top = sorted(scenarios, key=lambda s: s.confidence, reverse=True)[0]
    assert "continuation" in top.description.lower() or "up" in top.description.lower()


def test_scenarios_normalize_to_100():
    """Scenario confidences sum to 100."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
    ]
    state = infer_regime(events)
    scenarios = generate_scenarios(state)
    total = sum(s.confidence for s in scenarios)
    assert total == 100


def test_summarize_scenarios():
    """Scenario summary is human-readable."""
    now = datetime.now()
    events = [
        build_event(EventType.PUT_WRITING, EventSeverity.INFO, "x", "y", time=now - timedelta(minutes=1)),
    ]
    state = infer_regime(events)
    scenarios = generate_scenarios(state)
    summary = summarize_scenarios(scenarios, count=2)
    assert "Scenario A" in summary
    assert "Scenario B" in summary
    assert "%" in summary


def main() -> int:
    tests = [
        test_event_routing,
        test_discord_formatting,
        test_discord_colors,
        test_infer_trend_up,
        test_infer_distribution,
        test_infer_exhaustion,
        test_infer_reversal,
        test_empty_events_returns_range,
        test_scenarios_from_trend_up,
        test_scenarios_normalize_to_100,
        test_summarize_scenarios,
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
