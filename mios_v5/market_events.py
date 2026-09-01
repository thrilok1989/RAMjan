"""MIOS V5 — Market intelligence events (what is happening, not what to do).

Captures market structure and dynamics events at the point they occur:
- What: put/call writing, POC shifts, liquidity sweeps, OI touches, CVD divergence, etc.
- When: timestamp + price point
- Context: regime, zone, trade state, cross-market confirm
- Routes: Discord (live feed) + Supabase (complete record)

Pure, testable logic—no Streamlit/DB calls here; those live in the UI/task.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(Enum):
    """Market intelligence event types (what's happening, not what to do)."""
    PUT_WRITING = "put_writing"
    CALL_WRITING = "call_writing"
    PUT_UNWINDING = "put_unwinding"
    CALL_UNWINDING = "call_unwinding"
    POC_SHIFT = "poc_shift"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    OI_TOUCH = "oi_touch"
    OI_WALL = "oi_wall"
    CVD_REVERSAL = "cvd_reversal"
    CVD_DIVERGENCE = "cvd_divergence"
    BREAKOUT_CANDLE = "breakout_candle"
    HIGH_VOLUME = "high_volume"
    CROSS_MARKET_CONFIRM = "cross_market_confirm"
    GLOBAL_EVENT = "global_event"
    VIX_SPIKE = "vix_spike"
    SUPPORT_BREAK = "support_break"
    RESISTANCE_BREAK = "resistance_break"
    ORDER_BLOCK_TEST = "order_block_test"


class EventSeverity(Enum):
    """Event importance for Discord display (green/amber/red)."""
    INFO = "info"        # 🟢 - supportive, confirmatory
    WARNING = "warning"  # 🟡 - conflicting, uncertain
    ALERT = "alert"      # 🔴 - bearish, hostile


@dataclass
class EventSnapshot:
    """Immutable snapshot of market state at event time."""
    timestamp: datetime
    price: float  # spot price
    spot: Optional[float] = None  # explicit spot (for cross-market)
    futures: Optional[float] = None
    atm_strike: Optional[int] = None
    option_chain_snapshot: Optional[Dict[str, Any]] = None  # ATM IV, skew, etc.
    oi_snapshot: Optional[Dict[str, Any]] = None  # OI by strike
    cvd_snapshot: Optional[float] = None  # current CVD level
    volume: Optional[int] = None
    delta_index: Optional[float] = None  # weighted put/call delta
    liquidity_depth: Optional[Dict[str, Any]] = None  # bids/asks at key levels
    regime: Optional[str] = None  # "TREND UP" / "RANGE" / "TREND DOWN"
    zone: Optional[str] = None  # "SUPPORT" / "RESISTANCE" / "MIDPOINT"
    trade_state: Optional[str] = None  # "ARMED" / "ON_TRACK" / "PATIENT" / etc.


@dataclass
class MarketEvent:
    """Timestamped market intelligence event."""
    type: EventType
    severity: EventSeverity
    time: datetime
    headline: str  # short 1-liner for Discord: "Heavy Put Writing at 24850"
    detail: str  # why this matters: "Dealers hedging upside; expect support hold"
    price_point: Optional[float] = None  # strike/level where event occurred
    snapshot: Optional[EventSnapshot] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage/logging."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "time": self.time.isoformat(),
            "headline": self.headline,
            "detail": self.detail,
            "price_point": self.price_point,
            "snapshot": asdict(self.snapshot) if self.snapshot else None,
        }


class EventRouter:
    """Routes events to appropriate channels based on type."""

    @staticmethod
    def route_to_discord(event: MarketEvent) -> bool:
        """Should this event appear in Discord live feed?"""
        # All market events go to Discord (market intelligence)
        return True

    @staticmethod
    def route_to_supabase(event: MarketEvent) -> bool:
        """Should this event be stored for audit trail?"""
        # All events stored for validation dataset
        return True

    @staticmethod
    def route_to_telegram(event: MarketEvent) -> bool:
        """Should this event reach Telegram? (No—only gate states do.)"""
        return False

    @staticmethod
    def discord_color(severity: EventSeverity) -> str:
        """Emoji for Discord display."""
        if severity == EventSeverity.INFO:
            return "🟢"
        elif severity == EventSeverity.WARNING:
            return "🟡"
        else:
            return "🔴"


def build_event(
    type_: EventType,
    severity: EventSeverity,
    headline: str,
    detail: str,
    time: Optional[datetime] = None,
    price_point: Optional[float] = None,
    snapshot: Optional[EventSnapshot] = None,
) -> MarketEvent:
    """Factory for market events."""
    return MarketEvent(
        type=type_,
        severity=severity,
        time=time or datetime.now(),
        headline=headline,
        detail=detail,
        price_point=price_point,
        snapshot=snapshot,
    )


def format_discord_message(event: MarketEvent) -> str:
    """Format event for Discord live feed.

    Returns markdown-friendly message:
    {emoji} {HH:MM} {headline}
    └─ {detail}
    """
    color = EventRouter.discord_color(event.severity)
    time_str = event.time.strftime("%H:%M")
    return f"{color} {time_str}  {event.headline}\n└─ {event.detail}"
