"""MIOS V5 — Scenario Engine (what are probable next moves?).

Given current market state, generates 3–5 ranked scenarios with confidence.

Scenario A (65%): Continuation higher if support and positive CVD hold.
Scenario B (25%): Range formation around current value area.
Scenario C (10%): Bearish reversal if support breaks.

These are probability assessments, NOT predictions. Based on market state,
not crystal-ball claims.

Pure logic, testable, no DB calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .market_state import MarketRegime, MarketState


class ScenarioType(Enum):
    """Probable next market outcome."""
    CONTINUATION_UP = "continuation_up"
    CONTINUATION_DOWN = "continuation_down"
    RANGE_FORMATION = "range_formation"
    ACCELERATION_UP = "acceleration_up"
    ACCELERATION_DOWN = "acceleration_down"
    EXHAUSTION_REVERSAL = "exhaustion_reversal"
    SUPPORT_HOLD = "support_hold"
    RESISTANCE_HOLD = "resistance_hold"
    GAP_FILL = "gap_fill"


@dataclass
class Scenario:
    """Probable next move with confidence."""
    type: ScenarioType
    confidence: float  # 0–100
    description: str  # human-readable: "Continuation higher if support holds"
    key_level: Optional[float] = None  # support/resistance to watch
    watch_for: Optional[str] = None  # signal to confirm/invalidate


def generate_scenarios(state: MarketState) -> List[Scenario]:
    """Generate ranked probable scenarios from current market state.

    Returns 3–5 scenarios, most-confident first.
    Designed to be education, not prediction—show what could happen and why.
    """
    scenarios: List[Scenario] = []

    if state.regime == MarketRegime.TREND_UP:
        # Trend up: most likely is continuation
        scenarios.extend([
            Scenario(
                type=ScenarioType.CONTINUATION_UP,
                confidence=state.confidence * 0.7,  # inherit regime confidence
                description="Continuation higher: buyers remain in control.",
                watch_for="Support hold + positive CVD maintain.",
            ),
            Scenario(
                type=ScenarioType.EXHAUSTION_REVERSAL,
                confidence=state.confidence * 0.2,
                description="Exhaustion reversal: one-sided move shows fatigue.",
                watch_for="OI wall rejection, CVD divergence, high volume.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.1,
                description="Consolidation: brief range before next leg.",
                watch_for="Price oscillates around value area.",
            ),
        ])

    elif state.regime == MarketRegime.TREND_DOWN:
        scenarios.extend([
            Scenario(
                type=ScenarioType.CONTINUATION_DOWN,
                confidence=state.confidence * 0.7,
                description="Continuation lower: sellers remain in control.",
                watch_for="Resistance hold + negative CVD maintain.",
            ),
            Scenario(
                type=ScenarioType.EXHAUSTION_REVERSAL,
                confidence=state.confidence * 0.2,
                description="Exhaustion reversal: one-sided move shows fatigue.",
                watch_for="OI wall rejection, CVD divergence, high volume.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.1,
                description="Consolidation: brief range before next leg.",
                watch_for="Price oscillates around value area.",
            ),
        ])

    elif state.regime == MarketRegime.ACCUMULATION:
        scenarios.extend([
            Scenario(
                type=ScenarioType.CONTINUATION_UP,
                confidence=state.confidence * 0.6,
                description="Breakout higher: accumulation phase ends with upside push.",
                watch_for="Buyers absorb supply, positive CVD accelerates.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.3,
                description="Consolidation continues: more time to build conviction.",
                watch_for="Price stays confined, support holds.",
            ),
            Scenario(
                type=ScenarioType.EXHAUSTION_REVERSAL,
                confidence=state.confidence * 0.1,
                description="Reversal if support fails: buyers' conviction weakens.",
                watch_for="Support break with CVD divergence.",
            ),
        ])

    elif state.regime == MarketRegime.DISTRIBUTION:
        scenarios.extend([
            Scenario(
                type=ScenarioType.CONTINUATION_DOWN,
                confidence=state.confidence * 0.6,
                description="Breakdown lower: distribution phase ends with downside push.",
                watch_for="Sellers increase, negative CVD accelerates.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.3,
                description="Consolidation continues: more time to build conviction.",
                watch_for="Price stays confined, resistance holds.",
            ),
            Scenario(
                type=ScenarioType.EXHAUSTION_REVERSAL,
                confidence=state.confidence * 0.1,
                description="Reversal if resistance fails: sellers' conviction weakens.",
                watch_for="Resistance break with CVD divergence.",
            ),
        ])

    elif state.regime == MarketRegime.RANGE:
        scenarios.extend([
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.5,
                description="Range continues: no directional commitment yet.",
                watch_for="Price oscillates; support/resistance hold.",
            ),
            Scenario(
                type=ScenarioType.CONTINUATION_UP,
                confidence=state.confidence * 0.25,
                description="Breakout higher: buyers gain conviction.",
                watch_for="Resistance break + CVD spike.",
            ),
            Scenario(
                type=ScenarioType.CONTINUATION_DOWN,
                confidence=state.confidence * 0.25,
                description="Breakdown lower: sellers gain conviction.",
                watch_for="Support break + CVD spike.",
            ),
        ])

    elif state.regime == MarketRegime.EXHAUSTION:
        scenarios.extend([
            Scenario(
                type=ScenarioType.EXHAUSTION_REVERSAL,
                confidence=state.confidence * 0.7,
                description="Reversal likely: one-sided move exhausted.",
                watch_for="Continuation stalls, POC shifts, opposite-flow appears.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.2,
                description="Consolidation: brief balance before next trend.",
                watch_for="Price stabilizes around exhaustion zone.",
            ),
            Scenario(
                type=ScenarioType.ACCELERATION_UP,
                confidence=state.confidence * 0.05,
                description="Acceleration (rare): exhaustion was noise, trend resumes.",
                watch_for="Strong volume + new high.",
            ),
            Scenario(
                type=ScenarioType.ACCELERATION_DOWN,
                confidence=state.confidence * 0.05,
                description="Acceleration (rare): exhaustion was noise, trend resumes.",
                watch_for="Strong volume + new low.",
            ),
        ])

    elif state.regime == MarketRegime.REVERSAL:
        scenarios.extend([
            Scenario(
                type=ScenarioType.CONTINUATION_UP if "buyers" in state.summary.lower() else ScenarioType.CONTINUATION_DOWN,
                confidence=state.confidence * 0.6,
                description="Reversal confirmed: trend changes direction.",
                watch_for="New high/low, cross-market confirm.",
            ),
            Scenario(
                type=ScenarioType.RANGE_FORMATION,
                confidence=state.confidence * 0.3,
                description="Range formation: reversal early, balance before next trend.",
                watch_for="Price oscillates around reversal zone.",
            ),
            Scenario(
                type=ScenarioType.ACCELERATION_UP if "buyers" in state.summary.lower() else ScenarioType.ACCELERATION_DOWN,
                confidence=state.confidence * 0.1,
                description="Sharp acceleration: conviction builds quickly.",
                watch_for="OI migration, CVD surge, high-volume candles.",
            ),
        ])

    # Normalize confidences to sum to 100
    total_conf = sum(s.confidence for s in scenarios)
    if total_conf > 0:
        for s in scenarios:
            s.confidence = round((s.confidence / total_conf) * 100)

    return scenarios


def summarize_scenarios(scenarios: List[Scenario], count: int = 3) -> str:
    """Human-readable summary of top N scenarios."""
    top = sorted(scenarios, key=lambda s: s.confidence, reverse=True)[:count]
    lines = []
    for i, s in enumerate(top, 1):
        lines.append(f"Scenario {chr(64+i)} ({s.confidence}%): {s.description}")
    return "\n".join(lines)
