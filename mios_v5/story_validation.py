"""MIOS V5 — Story Validation (Stage 9: Trade outcome linking & statistics).

Links closed trades to their market stories. Enables statistical analysis:
- Which story patterns have the highest win-rate?
- Which patterns produce the best R-multiples?
- Which patterns have the largest MAE/MFE?

Uses closed trades (with exit_reason + points_moved) to compute outcomes.

Pure measurement—no modification to trading logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

from .market_story import Story, StoryType


class TradeOutcome(Enum):
    """Closed trade outcome classification."""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"


@dataclass
class TradeValidation:
    """Links a closed trade to a market story."""
    trade_id: int
    story_id: int
    story_type: StoryType
    side: str  # "CALL" or "PUT"
    entry_price: float
    exit_price: float
    points_moved: float  # +/- points at exit
    exit_reason: str  # "TARGET_HIT", "INVALIDATED", "TIME_EXIT", "REVERSED"
    mae: Optional[float] = None  # Max Adverse Excursion
    mfe: Optional[float] = None  # Max Favorable Excursion
    duration_seconds: Optional[int] = None
    outcome: TradeOutcome = field(default=TradeOutcome.BREAKEVEN)

    def __post_init__(self):
        """Compute outcome classification."""
        if self.points_moved > 0:
            self.outcome = TradeOutcome.WIN
        elif self.points_moved < 0:
            self.outcome = TradeOutcome.LOSS
        else:
            self.outcome = TradeOutcome.BREAKEVEN

    def r_multiple(self, risk_points: float = 30.0) -> float:
        """Compute R-multiple (points_moved / risk)."""
        if risk_points == 0:
            return 0.0
        return self.points_moved / risk_points


@dataclass
class StoryValidationStats:
    """Statistical summary of a story pattern's outcomes."""
    story_type: StoryType
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate: float = 0.0  # %
    avg_points: float = 0.0
    avg_r_multiple: float = 0.0  # R units
    avg_mae: Optional[float] = None
    avg_mfe: Optional[float] = None
    max_loss: Optional[float] = None
    best_win: Optional[float] = None
    total_pnl: float = 0.0  # sum of points_moved
    trades: List[TradeValidation] = field(default_factory=list)

    def compute_stats(self):
        """Recompute statistics from trades list."""
        if not self.trades:
            return

        self.total_trades = len(self.trades)
        self.wins = sum(1 for t in self.trades if t.outcome == TradeOutcome.WIN)
        self.losses = sum(1 for t in self.trades if t.outcome == TradeOutcome.LOSS)
        self.breakevens = sum(1 for t in self.trades if t.outcome == TradeOutcome.BREAKEVEN)

        self.win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0.0

        self.avg_points = (
            sum(t.points_moved for t in self.trades) / self.total_trades
            if self.total_trades > 0
            else 0.0
        )

        self.total_pnl = sum(t.points_moved for t in self.trades)

        # R-multiple average
        r_values = [t.r_multiple() for t in self.trades if t.outcome != TradeOutcome.BREAKEVEN]
        self.avg_r_multiple = sum(r_values) / len(r_values) if r_values else 0.0

        # MAE/MFE averages
        maes = [t.mae for t in self.trades if t.mae is not None]
        mfes = [t.mfe for t in self.trades if t.mfe is not None]
        self.avg_mae = sum(maes) / len(maes) if maes else None
        self.avg_mfe = sum(mfes) / len(mfes) if mfes else None

        # Extremes
        self.max_loss = min((t.points_moved for t in self.trades), default=None)
        self.best_win = max((t.points_moved for t in self.trades if t.outcome == TradeOutcome.WIN), default=None)

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"{self.story_type.value}: {self.wins}W-{self.losses}L "
            f"({self.win_rate:.0f}%) avg={self.avg_points:+.1f}pts "
            f"R={self.avg_r_multiple:+.2f}"
        )


class ValidationDataset:
    """Accumulates trade validations linked to stories."""

    def __init__(self):
        self.validations: List[TradeValidation] = []
        self.stats_by_type: Dict[StoryType, StoryValidationStats] = {}

    def add_validation(self, trade: TradeValidation):
        """Add a closed trade with its story link."""
        self.validations.append(trade)
        # Update stats
        if trade.story_type not in self.stats_by_type:
            self.stats_by_type[trade.story_type] = StoryValidationStats(story_type=trade.story_type)
        self.stats_by_type[trade.story_type].trades.append(trade)

    def compute_all_stats(self):
        """Recompute all statistics."""
        for stats in self.stats_by_type.values():
            stats.compute_stats()

    def get_stats(self, story_type: StoryType) -> Optional[StoryValidationStats]:
        """Fetch statistics for a story type."""
        return self.stats_by_type.get(story_type)

    def get_stats_ranked(self, by: str = "win_rate") -> List[StoryValidationStats]:
        """Get all stats ranked by metric (win_rate, avg_r_multiple, avg_points, etc.)."""
        stats_list = list(self.stats_by_type.values())
        if by == "win_rate":
            return sorted(stats_list, key=lambda s: s.win_rate, reverse=True)
        elif by == "avg_r_multiple":
            return sorted(stats_list, key=lambda s: s.avg_r_multiple, reverse=True)
        elif by == "total_pnl":
            return sorted(stats_list, key=lambda s: s.total_pnl, reverse=True)
        elif by == "avg_points":
            return sorted(stats_list, key=lambda s: s.avg_points, reverse=True)
        else:
            return stats_list

    def summary(self) -> str:
        """Human-readable summary of all story validation stats."""
        lines = []
        lines.append("Story Validation Summary")
        lines.append("=" * 60)

        if not self.stats_by_type:
            return "No validations yet."

        # Ranked by win-rate
        ranked = self.get_stats_ranked(by="win_rate")
        for i, stats in enumerate(ranked, 1):
            lines.append(f"{i}. {stats}")

        return "\n".join(lines)
