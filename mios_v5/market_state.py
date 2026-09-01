"""MIOS V5 — State Engine (what state is the market in, given recent events?).

Reads the event timeline and answers: "What is the current market regime?"

States: ACCUMULATION, DISTRIBUTION, TREND_UP, TREND_DOWN, RANGE, EXHAUSTION
← based on event sequence, not just indicators.

Pure logic, testable, no DB calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .market_events import MarketEvent, EventType, EventSeverity


class MarketRegime(Enum):
    """Current market state inferred from event sequence."""
    ACCUMULATION = "accumulation"  # Buying pressure, support holds, positive CVD
    DISTRIBUTION = "distribution"  # Selling pressure, resistance holds, negative CVD
    TREND_UP = "trend_up"          # Buyers in control, higher highs/lows, confirm from cross-market
    TREND_DOWN = "trend_down"      # Sellers in control, lower highs/lows, confirm from cross-market
    RANGE = "range"                # Confined between support/resistance, no directional conviction
    EXHAUSTION = "exhaustion"      # One-sided move showing signs of waning (high volume, OI wall rejection)
    REVERSAL = "reversal"          # Trend changing (DVP divergence, POC shift, zone break)


@dataclass
class MarketState:
    """Current market regime inferred from events."""
    regime: MarketRegime
    confidence: float  # 0–100, confidence in this regime assessment
    last_event_time: Optional[float] = None  # seconds ago
    event_count: int = 0  # how many recent events inform this state
    summary: str = ""  # human-readable narrative


def infer_regime(events: List[MarketEvent]) -> MarketState:
    """Infer current market regime from recent event sequence.

    Logic:
    1. Count recent bullish/bearish events (last 30 min window).
    2. Check for cross-market confirms (strongest signal).
    3. Look for exhaustion patterns (high volume rejection).
    4. Detect reversals (POC shift + divergence).
    5. Differentiate trend from accumulation/distribution.
    """
    if not events:
        return MarketState(
            regime=MarketRegime.RANGE,
            confidence=0,
            event_count=0,
            summary="No events yet.",
        )

    # Score recent events: bullish (+1), bearish (-1), neutral (0)
    bullish_score = 0
    bearish_score = 0
    has_cross_market_confirm = False
    has_exhaustion = False
    has_poc_shift = False
    has_cvd_divergence = False

    for event in events[-20:]:  # last ~20 events ≈ 30 min
        # Inherently bullish events
        if event.type in (
            EventType.PUT_WRITING,
            EventType.PUT_UNWINDING,
            EventType.LIQUIDITY_SWEEP,
            EventType.CVD_REVERSAL,
        ):
            bullish_score += 1

        # Inherently bearish events
        if event.type in (
            EventType.CALL_WRITING,
            EventType.CALL_UNWINDING,
            EventType.SUPPORT_BREAK,
            EventType.RESISTANCE_BREAK,
        ):
            bearish_score += 1

        # Direction-neutral but often bullish
        if event.type == EventType.BREAKOUT_CANDLE:
            bullish_score += 1

        if event.type in (EventType.OI_WALL, EventType.HIGH_VOLUME):
            # Severity indicates direction (INFO=bullish, ALERT=bearish)
            if event.severity == EventSeverity.INFO:
                bullish_score += 1
            elif event.severity == EventSeverity.ALERT:
                bearish_score += 1

        if event.type == EventType.CROSS_MARKET_CONFIRM:
            has_cross_market_confirm = True

        if event.type == EventType.OI_WALL and event.severity == EventSeverity.ALERT:
            has_exhaustion = True

        if event.type == EventType.POC_SHIFT:
            has_poc_shift = True

        if event.type == EventType.CVD_DIVERGENCE:
            has_cvd_divergence = True

    # Infer regime
    net_score = bullish_score - bearish_score
    confidence = min(100, (abs(net_score) / max(len(events), 1)) * 100)

    if has_poc_shift and has_cvd_divergence and abs(net_score) >= 2:
        regime = MarketRegime.REVERSAL
        summary = "Market reversing: POC shift + CVD divergence."
    elif has_exhaustion:
        regime = MarketRegime.EXHAUSTION
        summary = "One-sided move showing exhaustion signs (OI wall, high volume rejection)."
    elif net_score >= 3:
        regime = MarketRegime.TREND_UP if has_cross_market_confirm else MarketRegime.ACCUMULATION
        summary = (
            "Buyers in control (trend confirmed across markets)."
            if has_cross_market_confirm
            else "Accumulation phase: buying pressure building."
        )
    elif net_score <= -3:
        regime = MarketRegime.TREND_DOWN if has_cross_market_confirm else MarketRegime.DISTRIBUTION
        summary = (
            "Sellers in control (trend confirmed across markets)."
            if has_cross_market_confirm
            else "Distribution phase: selling pressure building."
        )
    else:
        regime = MarketRegime.RANGE
        summary = "Range-bound: no directional conviction yet."

    return MarketState(
        regime=regime,
        confidence=confidence,
        event_count=len(events),
        summary=summary,
    )
