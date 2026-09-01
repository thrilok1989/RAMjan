"""MIOS V5 — Story Generator (Stage 8: Human-readable market narratives).

Converts event sequences into narrative summaries. Takes a Story and produces
a readable description of what happened, in chronological order.

Output example:
"Market opened with a gap up. Support held during the first pullback. Heavy put
writing appeared near support. Liquidity below the opening range was swept.
Order flow turned positive. Dynamic POC shifted upward. Market currently favors
continuation higher while support remains intact."

Pure narrative—no predictions, no trading signals.
"""

from __future__ import annotations

from typing import List

from .market_events import MarketEvent, EventType
from .market_story import Story, StoryType, classify_story


# Template mappings: event type → human-readable phrase
_EVENT_NARRATIVES = {
    EventType.PUT_WRITING: "Heavy put writing appeared (dealers hedging upside)",
    EventType.CALL_WRITING: "Heavy call writing increased (dealers hedging downside)",
    EventType.LIQUIDITY_SWEEP: "Liquidity sweep occurred below the current level",
    EventType.OI_TOUCH: "OI touched a significant level",
    EventType.OI_WALL: "OI wall rejected price movement",
    EventType.CVD_REVERSAL: "Order flow reversed to bullish",
    EventType.CVD_DIVERGENCE: "CVD divergence detected (price up, flows down)",
    EventType.BREAKOUT_CANDLE: "High-volume candle broke out of consolidation",
    EventType.HIGH_VOLUME: "Unusual volume spike occurred",
    EventType.CROSS_MARKET_CONFIRM: "BankNifty/Sectors confirmed the move",
    EventType.GLOBAL_EVENT: "Global markets moved significantly",
    EventType.VIX_SPIKE: "India VIX spiked higher",
    EventType.SUPPORT_BREAK: "Support level broke decisively",
    EventType.RESISTANCE_BREAK: "Resistance level broke decisively",
    EventType.POC_SHIFT: "Dynamic Point of Control shifted",
    EventType.ORDER_BLOCK_TEST: "Price tested an order block",
    EventType.PUT_UNWINDING: "Put positions were unwound",
    EventType.CALL_UNWINDING: "Call positions were unwound",
}

_STORY_NARRATIVES = {
    StoryType.OPENING_BELL: "The session opened",
    StoryType.BULLISH_CONTINUATION: "Market continued higher",
    StoryType.BEARISH_CONTINUATION: "Market continued lower",
    StoryType.BULLISH_REVERSAL: "Market reversed to the upside",
    StoryType.BEARISH_REVERSAL: "Market reversed to the downside",
    StoryType.FALSE_BREAKOUT: "Price moved beyond resistance but reversed",
    StoryType.FALSE_BREAKDOWN: "Price moved below support but reversed",
    StoryType.LIQUIDITY_GRAB: "Liquidity was swept and order flow shifted",
    StoryType.ACCUMULATION: "Market accumulated and built conviction",
    StoryType.DISTRIBUTION: "Market distributed and built weakness",
    StoryType.TREND_EXHAUSTION: "The trend showed signs of exhaustion",
    StoryType.GAMMA_SQUEEZE: "Gamma dynamics created explosive movement",
    StoryType.EXPIRY_PINNING: "Price pinned near an expiry level",
    StoryType.RANGE_EXPANSION: "Market broke out of its established range",
    StoryType.RANGE_ROTATION: "Market oscillated within a defined range",
    StoryType.VALUE_ACCEPTANCE: "Market accepted value at a new level",
    StoryType.VALUE_REJECTION: "Market rejected value and reversed",
    StoryType.UNKNOWN: "Market activity occurred",
}


def _summarize_story_type(story: Story) -> str:
    """Get narrative for the story's classification."""
    story_type = classify_story(story)
    story.story_type = story_type
    return _STORY_NARRATIVES.get(story_type, "Market activity occurred")


def _event_narrative(event: MarketEvent) -> str:
    """Convert a single event to human text."""
    narrative = _EVENT_NARRATIVES.get(event.type)
    if narrative:
        return narrative
    # Fallback: use event headline
    return event.headline


def _severity_adverb(event: MarketEvent) -> str:
    """Add emphasis based on severity."""
    # INFO events: neutral, no adverb
    # WARNING events: "notably", "potentially"
    # ALERT events: "significantly", "sharply"
    if event.severity.value == "info":
        return ""
    elif event.severity.value == "warning":
        return "Notably, "
    else:  # alert
        return "Significantly, "


def generate_narrative(story: Story) -> str:
    """Convert a Story into a readable market narrative.

    Output: chronological description of events, with story context.

    Example:
    "Market opened with a gap up. Support held during the first pullback.
    Heavy put writing appeared near support. Liquidity below the opening range
    was swept. Order flow turned positive. Dynamic POC shifted upward.
    Market currently favors bullish continuation while support remains intact."
    """
    if not story.events:
        return "No market activity recorded."

    lines = []

    # Opening: story classification
    story_summary = _summarize_story_type(story)
    lines.append(f"{story_summary}.")

    # Timeline: each event
    for event in story.events:
        adverb = _severity_adverb(event)
        narrative = _event_narrative(event)
        time_str = event.time.strftime("%H:%M")
        lines.append(f"{adverb}At {time_str}, {narrative.lower()}.")

    # Closing: current market state inference
    last_event = story.events[-1] if story.events else None
    if last_event:
        if last_event.type in (EventType.CVD_REVERSAL, EventType.PUT_WRITING, EventType.BREAKOUT_CANDLE):
            lines.append("Market currently favors bullish continuation while support remains intact.")
        elif last_event.type in (EventType.CVD_DIVERGENCE, EventType.CALL_WRITING, EventType.SUPPORT_BREAK):
            lines.append("Market currently shows bearish pressure while resistance remains contested.")
        else:
            lines.append("Market state remains uncertain pending the next signal.")

    narrative = " ".join(lines)
    story.summary = narrative
    return narrative


def generate_brief_narrative(story: Story) -> str:
    """Shorter version: just events, no interpretation.

    Example:
    "Gap up → Support hold → Put writing → Liquidity sweep → CVD reversal →
    High volume → POC shift → Cross-market confirm → Gate confirmed."
    """
    if not story.events:
        return "No events"

    event_phrases = []
    for event in story.events:
        # Extract short label from event type
        label = event.type.value.replace("_", " ").title()
        event_phrases.append(label)

    return " → ".join(event_phrases)
