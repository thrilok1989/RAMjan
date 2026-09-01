"""MIOS V5 — Core engine contract.

Every stage engine (0–41) returns the same typed result so downstream stages,
the fusion layer, the dashboard, and the health engine can treat all engines
uniformly. Three hard rules from the V5.0 spec are enforced here:

1. HONESTY  — an engine that cannot compute returns status=NEUTRAL (never a
              fabricated value) and says why.
2. ERRORS   — failures are structured records (engine / type / reason /
              severity / source / recovery), not swallowed exceptions.
3. PROVENANCE — every result carries its data source, trust tier and
              freshness so narrative layers never present a spoofable
              Tier-3 signal with Tier-1 confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import pytz

IST = pytz.timezone("Asia/Kolkata")


# ──────────────────────────────────────────────────────────────────────
#  Enums
# ──────────────────────────────────────────────────────────────────────

class Bias(str, Enum):
    """Directional read an engine reports. NEUTRAL = balanced;
    NONE = engine does not produce a direction (e.g. health, data)."""
    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"
    SIDEWAYS = "SIDEWAYS"
    NONE = "NONE"


class Status(str, Enum):
    OK = "OK"                # computed normally
    NEUTRAL = "NEUTRAL"      # could not compute → honest neutral (missing data)
    DEGRADED = "DEGRADED"    # computed, but with stale/partial inputs
    ERROR = "ERROR"          # engine raised / produced an invalid result
    DISABLED = "DISABLED"    # structurally off (data source doesn't exist)


class Severity(str, Enum):
    INFO = "INFO"            # expected limitation (e.g. no L2 depth at retail)
    WARNING = "WARNING"      # degraded but usable
    ERROR = "ERROR"          # engine failed this cycle
    CRITICAL = "CRITICAL"    # systemic (API down, DB unreachable)


class ErrorType(str, Enum):
    MISSING_API = "MISSING_API"
    MISSING_DATA = "MISSING_DATA"
    FAILED_FORMULA = "FAILED_FORMULA"
    TIMEOUT = "TIMEOUT"
    INVALID_CALCULATION = "INVALID_CALCULATION"
    DATA_LIMIT = "DATA_LIMIT"          # structurally unavailable (by design)
    STALE_DATA = "STALE_DATA"


class Tier(int, Enum):
    """Data-trust hierarchy (from the app's own philosophy):
    1 = executed volume / traded prints (can't be faked)
    2 = derived analytics (greeks, profiles, OI — trustworthy but modeled)
    3 = resting quotes / stated intent (spoofable)"""
    EXECUTED = 1
    DERIVED = 2
    RESTING = 3


# ──────────────────────────────────────────────────────────────────────
#  Records
# ──────────────────────────────────────────────────────────────────────

@dataclass
class EngineError:
    """Structured error record — mirrors sql/009_engine_errors.sql."""
    engine: str
    error_type: ErrorType
    reason: str
    severity: Severity = Severity.ERROR
    data_source: str = ""
    recovery: str = "pending"          # pending | retrying | recovered | permanent
    ts: str = field(default_factory=lambda: datetime.now(IST).isoformat())

    def to_row(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "trading_day": self.ts[:10],
            "engine": self.engine,
            "error_type": self.error_type.value,
            "reason": self.reason[:500],
            "severity": self.severity.value,
            "data_source": self.data_source[:120],
            "recovery": self.recovery,
        }


@dataclass
class Provenance:
    """Where a result's data came from and how much to trust it."""
    source: str = ""                   # e.g. "dhan:optionchain", "session:cache"
    tier: Tier = Tier.DERIVED
    freshness_ts: Optional[str] = None # ISO ts of the underlying data
    notes: str = ""


@dataclass
class EngineResult:
    """Uniform output of every MIOS V5 engine."""
    engine: str
    stage: int = -1
    status: Status = Status.NEUTRAL
    bias: Bias = Bias.NONE
    confidence: float = 0.0            # 0–100
    evidence: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    opportunities: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)   # engine-specific payload
    provenance: Provenance = field(default_factory=Provenance)
    errors: List[EngineError] = field(default_factory=list)
    runtime_ms: float = 0.0
    ts: str = field(default_factory=lambda: datetime.now(IST).isoformat())

    # -- helpers ---------------------------------------------------------
    @classmethod
    def neutral(cls, engine: str, reason: str,
                error_type: ErrorType = ErrorType.MISSING_DATA,
                severity: Severity = Severity.INFO,
                data_source: str = "") -> "EngineResult":
        """Honest 'cannot compute' result — Rule 1 of the spec."""
        return cls(
            engine=engine, status=Status.NEUTRAL, bias=Bias.NEUTRAL,
            confidence=0.0, evidence=[f"NEUTRAL: {reason}"],
            errors=[EngineError(engine=engine, error_type=error_type,
                                reason=reason, severity=severity,
                                data_source=data_source)],
        )

    @classmethod
    def disabled(cls, engine: str, reason: str,
                 data_source: str = "") -> "EngineResult":
        """Structurally unavailable (data-limit by design) — logged as INFO,
        never as an alarm. E.g. L2 order-book depth at retail Dhan."""
        return cls(
            engine=engine, status=Status.DISABLED, bias=Bias.NONE,
            confidence=0.0, evidence=[f"DISABLED: {reason}"],
            errors=[EngineError(engine=engine, error_type=ErrorType.DATA_LIMIT,
                                reason=reason, severity=Severity.INFO,
                                data_source=data_source, recovery="permanent")],
        )

    @classmethod
    def failure(cls, engine: str, exc: BaseException,
                data_source: str = "") -> "EngineResult":
        """Engine raised — captured as a structured ERROR result."""
        return cls(
            engine=engine, status=Status.ERROR, bias=Bias.NEUTRAL,
            confidence=0.0, evidence=[f"ERROR: {type(exc).__name__}: {exc}"],
            errors=[EngineError(engine=engine,
                                error_type=ErrorType.FAILED_FORMULA,
                                reason=f"{type(exc).__name__}: {exc}",
                                severity=Severity.ERROR,
                                data_source=data_source)],
        )

    @property
    def ok(self) -> bool:
        return self.status in (Status.OK, Status.DEGRADED)


# ──────────────────────────────────────────────────────────────────────
#  Shared state
# ──────────────────────────────────────────────────────────────────────

class MarketState:
    """Shared blackboard the orchestrator fills in dependency order.

    raw:      inputs handed in by the host app (spot, df, option_data, …)
    results:  {engine_name: EngineResult} — each stage reads its deps here.
    """

    def __init__(self, raw: Optional[Dict[str, Any]] = None):
        self.raw: Dict[str, Any] = raw or {}
        self.results: Dict[str, EngineResult] = {}
        self.started_at: str = datetime.now(IST).isoformat()

    def get(self, engine_name: str) -> Optional[EngineResult]:
        return self.results.get(engine_name)

    def require(self, engine_name: str) -> EngineResult:
        """Dependency access that never explodes: a missing upstream result
        returns an honest NEUTRAL placeholder instead of raising."""
        res = self.results.get(engine_name)
        if res is None:
            return EngineResult.neutral(
                engine_name, f"upstream '{engine_name}' has not run")
        return res

    def all_errors(self) -> List[EngineError]:
        errs: List[EngineError] = []
        for r in self.results.values():
            errs.extend(r.errors)
        return errs


# ──────────────────────────────────────────────────────────────────────
#  Engine base class
# ──────────────────────────────────────────────────────────────────────

class Engine:
    """Base class for every MIOS V5 stage engine.

    Subclasses set:
        name  — unique id, e.g. "stage09_volume_profile"
        stage — spec stage number (0–41)
        deps  — names of engines whose results must exist first
    and implement compute(state) → EngineResult.

    The orchestrator calls run(), which wraps compute() with timing and
    structured error capture so a crashing engine can never take down the
    pipeline (Rule: fail → structured error, not exception).
    """

    name: str = "engine"
    stage: int = -1
    deps: List[str] = []

    def compute(self, state: MarketState) -> EngineResult:   # pragma: no cover
        raise NotImplementedError

    def run(self, state: MarketState) -> EngineResult:
        import time as _t
        t0 = _t.perf_counter()
        try:
            result = self.compute(state)
            if not isinstance(result, EngineResult):
                result = EngineResult.failure(
                    self.name,
                    TypeError(f"compute() returned {type(result).__name__}, "
                              f"expected EngineResult"))
        except Exception as exc:            # noqa: BLE001 — contract boundary
            result = EngineResult.failure(self.name, exc)
        result.engine = self.name
        result.stage = self.stage
        result.runtime_ms = round((_t.perf_counter() - t0) * 1000, 2)
        return result
