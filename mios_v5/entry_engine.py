"""Stage 72 — the Entry Engine.

The first **execution** stage in MIOS. It answers one question:

> **Is there an executable trade right now?**

Not *which direction* — Stage 71 answered that. Not *which strike* — Stage 71.8
did. Not *which premium has energy* — Stage 71.7. Those already exist, and this
stage reads their verdicts rather than forming its own.

## It consumes exactly one object

```
Market  →  TradingContext  →  Stage 72  →  Trade Manager  →  Telegram
```

`EntryEngine(ctx).run()`. No other argument, no other import. It cannot read
Stage 42, Stage 44, the Opportunity Matrix, Premium Structure or any engine
directly — a test asserts the import graph, because that guarantee is the whole
value of the bridge. See `docs/AUDIT_STAGE_72_ENTRY_ENGINE.md`.

## The state machine is Stage 52's, imported

`decision_v2.STATES` is imported, never restated. The specification for this
stage listed ten states; Stage 52 implements twelve, overlapping in seven —
`WATCH`, `PARTIAL_EXIT` and `FULL_EXIT` do not exist in it. Adopting the spec's
list would have been inventing three states, which the same instruction
forbids, so the implementation wins and `SPEC_ALIAS` records the mapping. A
reader looking for `FULL_EXIT` finds `EXIT` rather than nothing.

## What it computes, and what it refuses to

Four calculations, all of them **over verdicts the context already carries**:
the entry score (a documented weighted mean), risk:reward (arithmetic over three
known values), the readiness gate (boolean composition) and the entry-zone band
(a table lookup). No price is derived, no bias re-decided, no confidence
recomputed.

**`target2` and `target3` are `UNKNOWN` by name.** Stage 35 publishes one
`next_target`; a ladder is new computation and outside this stage's remit.
Deriving them from R-multiples would be fabricating levels — the spec's own rule
settles it: *UNKNOWN where unavailable, never fabricate.*

## Advisory, and it sends nothing

`telegram` is a **prepared payload**. This stage imports no network client and
has no side effects; whether that payload is ever sent belongs to something
downstream that a human switched on.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .decision_v2 import LABEL as _STATE_LABEL, STATES
from .trading_context import UNKNOWN, TradingContext, _freeze, _thaw

#: The frozen execution contract. **Bump only for a breaking change to
#: `EntryDecision`**, never for a fix inside a phase — a consumer replaying a
#: stored decision needs this to mean "the shape I was written against".
#:
#: ### 72.0 → 72.1 — the Stage 71.85 amendment
#:
#: `STAGE72_FROZEN.md` says *do not change entry scoring, weights, gates or
#: recommendation logic — bug fixes only*, and Stage 71.85 adds an eleventh
#: weight. That is a scoring change, so it is not a quiet edit inside a frozen
#: stage: the contract version moves, the dispatcher accepts **both**, and a
#: stored `72.0` decision still replays against the shape it was written for.
#: A freeze that can be edited without a version bump is not a freeze; a freeze
#: that can never change is a museum. The bump is the difference.
#:
#: The philosophy is untouched — same weighted mean, same unknown-excluded
#: denominator, same gates. One more component reports into it.
VERSION = "72.1"

ADVISORY_ONLY = True

#: The fields `decision.hash` is computed over, in this order. Identity plus the
#: verdict: two decisions agreeing on all six are the same decision, and a
#: stored one whose hash no longer matches has been altered since it was made.
#:
#: Deliberately NOT the whole object. A hash over every field would change when
#: a reason's wording changed, which is not a different decision, and would make
#: the integrity check cry wolf until someone stopped reading it.
HASH_FIELDS: Tuple[str, ...] = ("id", "version", "state", "confidence",
                                "score", "created_at")


def _now_iso() -> str:
    """UTC, ISO 8601, seconds. One timestamp per decision, never rewritten."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def decision_hash(decision_id: str, version: str, state: str,
                  confidence: Any, score: Any, created_at: str) -> str:
    """A stable SHA-256 over the six identity fields.

    Exposed as a module function so a consumer can verify a decision it read
    back from storage without reconstructing an `EntryDecision`, and so the
    determinism can be tested without depending on `uuid4`.

    Values are rendered through `repr` of their string form so `72` and `"72"`
    cannot collide — a score stored as text and a score stored as a number are
    the same decision, and must hash the same.
    """
    parts = [str(decision_id), str(version), str(state), str(confidence),
             str(score), str(created_at)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

#: The spec's vocabulary → the state Stage 52 actually implements. Recorded so a
#: reader looking for a spec name finds the real one instead of nothing.
SPEC_ALIAS: Mapping[str, str] = MappingProxyType({
    "WATCH": "WAIT",            # Stage 52 has one pre-entry state
    "PARTIAL_EXIT": "SCALE_OUT",
    "FULL_EXIT": "EXIT",
})

#: Outputs the spec asks for that no producer publishes. Named, never derived.
MISSING_PRODUCERS: Tuple[str, ...] = (
    "target2",      # Stage 35 publishes ONE next_target — a ladder is new work
    "target3",
)

READY, NOT_READY = "READY", "NOT_READY"

#: Phase 3 — where in the move an entry would land.
EARLY, OPTIMAL, LATE, MISSED = "Early", "Optimal", "Late", "Missed"

#: Phase 4 · 5 — the bands, ordered.
RISK_BANDS = ("Very Low", "Low", "Medium", "High", "Extreme")
REWARD_BANDS = ("Poor", "Average", "Good", "Excellent")

#: Phase 6 — the only types this stage may report. Each maps from a verdict
#: Stage 71.5 already published; a type it cannot source stays UNKNOWN rather
#: than being inferred from price action this stage does not measure.
ENTRY_TYPES = ("Momentum", "Pullback", "Breakout", "Reversal",
               "Continuation", "Mean Reversion")

#: Stage 71.5's opportunity type → this stage's entry type. Read, not inferred.
_TYPE_MAP: Mapping[str, str] = MappingProxyType({
    "BREAKOUT": "Breakout", "BREAKDOWN": "Breakout",
    "CONFIRMED BREAKOUT": "Breakout", "CONFIRMED BREAKDOWN": "Breakout",
    "REVERSAL": "Reversal", "BULL TRAP": "Reversal", "BEAR TRAP": "Reversal",
    "TREND": "Momentum", "MOMENTUM": "Momentum", "MARK UP": "Momentum",
    "MARK DOWN": "Momentum",
    "PULLBACK": "Pullback", "RETEST": "Pullback",
    "CONTINUATION": "Continuation", "TREND CONTINUATION": "Continuation",
    "RANGE": "Mean Reversion", "ROTATION": "Mean Reversion",
    "MEAN REVERSION": "Mean Reversion",
})

#: Stage 42 states that mean price has already reacted — the entry is late to
#: the *event* even when the move has further to run.
_REACTED = ("CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN", "ACCEPTANCE")
#: States where the reaction is forming — the window the spec calls Optimal.
_FORMING = ("BREAK", "TOUCH", "REJECTION", "ABSORPTION")

# ══════════════════════════════════════════════════════════════════════
#  Phase 2 — the entry score
# ══════════════════════════════════════════════════════════════════════

#: Every weight, documented, and every one reading a DIFFERENT context field.
#:
#: The ordering is a claim about execution, not about analysis: strike
#: validation leads because a correct read on an unvalidated strike is the one
#: failure that cannot be recovered by being right, and premium energy is second
#: because a premium nobody trades cannot express a thesis however good it is.
#: Opportunity score comes third — it is the strongest *analysis* input, and
#: this is not an analysis stage.
WEIGHTS: Mapping[str, float] = MappingProxyType({
    "strike.validation": 2.5,
    "energy.energy": 2.0,
    "opportunity.opportunity_score": 2.0,
    "premium.premium_score": 1.5,
    # Stage 71.85 — what the premium is doing at its own level, as distinct
    # from how good its structure is. A premium with an excellent structure
    # score whose support is giving way underneath it is a different execution
    # proposition from the same score with the support being defended, and
    # `premium_score` cannot tell those apart because it does not look at the
    # LTP's interaction with the level at all.
    "premium.behaviour": 1.5,
    "opportunity.confidence": 1.5,
    "strike.liquidity": 1.5,
    "energy.spike_probability": 1.0,
    "risk.validity": 1.0,
    "htf.alignment": 1.0,
    "market.stability": 1.0,
})

#: Categorical context values → the 0–100 the score works in. A value absent
#: from its table reports UNKNOWN and leaves the denominator; it is never
#: guessed at 50.
_SCALES: Mapping[str, Mapping[str, float]] = MappingProxyType({
    "strike.validation": MappingProxyType(
        {"VALID": 100.0, "WEAK": 45.0, "INVALID": 0.0}),
    "strike.liquidity": MappingProxyType(
        {"Agree": 100.0, "Partially Agree": 50.0, "Disagree": 0.0}),
    "risk.validity": MappingProxyType(
        {"VALID": 100.0, "STRONG": 100.0, "WEAK": 40.0, "INVALID": 0.0,
         "UNKNOWN": None}),
    "market.stability": MappingProxyType(
        {"STABLE": 100.0, "RECOVERY": 55.0, "UNSTABLE": 20.0, "SHOCK": 0.0}),
    # Stage 71.85's six behaviours, scored as what they mean for **holding this
    # premium**: its floor being defended is the best backdrop, its ceiling
    # giving way is nearly as good, and its floor giving way is the worst.
    #
    # `Neutral` maps to `None` deliberately. Stage 71.85 emits it when the
    # evidence did not agree enough to name a fight, which is an absence of a
    # read — so it leaves the denominator exactly as an unreported input does,
    # rather than scoring 50 and pretending something was measured.
    "premium.behaviour": MappingProxyType({
        "Support Building": 100.0,
        "Resistance Fading": 90.0,
        "Acceptance": 70.0,
        "Resistance Building": 30.0,
        "Support Fading": 10.0,
        "Neutral": None,
        UNKNOWN: None,
    }),
})


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _side_value(v: Any, side: Optional[str]) -> Any:
    """A per-side context value, reduced to the side under consideration.

    `energy.energy` is `{CALL: 78, PUT: 22}`. Scoring a CALL entry against the
    PUT's energy would be reading the wrong half of a correct field.
    """
    if isinstance(v, Mapping) and side in v:
        return v[side]
    return v


@dataclass(frozen=True)
class Reason:
    """One contributor, traceable to the context field it came from."""
    code: str
    label: str
    weight: int
    owner: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "label": self.label, "weight": self.weight,
                "owner": self.owner, "source": self.source}


@dataclass(frozen=True)
class EntryDecision:
    """One cycle's execution verdict.

    **Frozen, and it represents history.** A decision is what this engine
    concluded at one instant from one context; a consumer that could edit it
    could rewrite what was decided, and every replay, audit and learning row
    built on it would be describing something that never happened.

    Immutability is deep: nested mappings are `MappingProxyType` and sequences
    are tuples, all the way down.

    `id`, `version`, `created_at` and `hash` are the identity every downstream
    stage references. Stage 73+ **extend** a decision — they never mint their
    own id and never restate its timestamp.
    """
    state: str
    confidence: Any
    quality: Any
    entry_type: Any
    side: Any
    strike: Any
    horizon: Any
    timing: Any
    risk: Any
    reward: Any
    entry_zone: Any
    stop: Any
    targets: Mapping[str, Any]
    lifetime: Any
    readiness: str
    score: Any
    entry: Any
    risk_reward: Any
    reason_codes: Tuple[Reason, ...]
    top_trigger: Any
    warnings: Tuple[str, ...]
    invalidations: Tuple[str, ...]
    telegram: Mapping[str, Any]
    metadata: Mapping[str, Any]
    #: Stage 71.85's read for the side under consideration, carried whole.
    #: **Read from the context, never computed here** — Stage 72 is the only
    #: stage holding a context, so it is the only one that can put this on the
    #: decision for Stage 72.9 to transport.
    behaviour: Mapping[str, Any] = _dc_field(
        default_factory=lambda: MappingProxyType({}))
    #: identity — assigned once, at construction, and never again
    id: str = ""
    version: str = VERSION
    created_at: str = ""
    hash: str = ""
    advisory_only: bool = ADVISORY_ONLY

    @property
    def label(self) -> str:
        return _STATE_LABEL.get(self.state, self.state)

    @property
    def top_reasons(self) -> Tuple[Reason, ...]:
        return self.reason_codes[:5]

    def verify(self) -> bool:
        """Does this decision still hash to what it was created with?

        The integrity check a replay or a learning row runs before trusting a
        stored decision. `False` means the record was altered after the fact,
        not that the decision was wrong.
        """
        return self.hash == decision_hash(
            self.id, self.version, self.state, self.confidence, self.score,
            self.created_at)

    def identity(self) -> Dict[str, Any]:
        """The four fields a downstream stage references. Stage 73+ carry these
        forward rather than generating their own."""
        return {"id": self.id, "version": self.version,
                "created_at": self.created_at, "hash": self.hash}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "version": self.version,
            "created_at": self.created_at, "hash": self.hash,
            "state": self.state, "label": self.label,
            "confidence": _thaw(self.confidence), "quality": _thaw(self.quality),
            "entry_type": _thaw(self.entry_type), "side": _thaw(self.side),
            "strike": _thaw(self.strike), "horizon": _thaw(self.horizon),
            "timing": _thaw(self.timing), "risk": _thaw(self.risk),
            "reward": _thaw(self.reward), "entry_zone": _thaw(self.entry_zone),
            "entry": _thaw(self.entry), "stop": _thaw(self.stop),
            "targets": _thaw(self.targets), "risk_reward": _thaw(self.risk_reward),
            "lifetime": _thaw(self.lifetime), "readiness": self.readiness,
            "score": _thaw(self.score),
            "reason_codes": [r.to_dict() for r in self.reason_codes],
            "top_trigger": _thaw(self.top_trigger),
            "warnings": list(self.warnings),
            "invalidations": list(self.invalidations),
            "telegram": _thaw(self.telegram),
            "metadata": _thaw(self.metadata),
            "behaviour": _thaw(self.behaviour),
            "advisory_only": self.advisory_only,
        }

    def summary(self) -> Dict[str, Any]:
        """Phase 10 — the whole verdict in the shape a human reads.

        `why` and `why_not` are both present on every decision. A stage that
        explains itself only when it acts teaches a trader to read the absence
        of explanation as permission.
        """
        acting = self.state in ("ENTER", "ENTRY_READY", "SCALE_IN")
        return {
            "id": self.id, "version": self.version,
            "created_at": self.created_at,
            "trade": acting,
            "state": self.state, "label": self.label,
            "why": [r.label for r in self.top_reasons] if acting else [],
            "why_not": list(self.warnings) if not acting else [],
            "confidence": _thaw(self.confidence), "quality": _thaw(self.quality),
            "risk": _thaw(self.risk), "reward": _thaw(self.reward),
            "best_horizon": _thaw(self.horizon), "side": _thaw(self.side),
            "strike": _thaw(self.strike), "timing": _thaw(self.timing),
            "warnings": list(self.warnings),
            "advisory_only": self.advisory_only,
        }


class EntryEngine:
    """`EntryEngine(ctx).run()` → `EntryDecision`.

    Holds no state between calls and mutates nothing. The context is read; the
    decision is built once and frozen.
    """

    def __init__(self, ctx: Optional[TradingContext] = None) -> None:
        self.ctx = ctx

    # ── context access ────────────────────────────────────────────────
    def _v(self, name: str, default: Any = UNKNOWN) -> Any:
        return self.ctx.value(name, default) if self.ctx is not None else default

    def _known(self, name: str) -> bool:
        return bool(self.ctx is not None and self.ctx.known(name))

    def _field(self, name: str):
        from .trading_context import Field
        if self.ctx is None:
            return Field(UNKNOWN, UNKNOWN, UNKNOWN, name)
        return self.ctx.get(name)

    def _reason(self, name: str, label: str, weight: float) -> Reason:
        """A reason carrying the context's own provenance, so `owner` traces to
        a stage and `source` to a dotted path."""
        f = self._field(name)
        return Reason(code=label.upper().replace(" ", "_").replace(":", ""),
                      label=label, weight=round(weight),
                      owner=f.owner, source=f.source)

    # ── Phase 1 · readiness ───────────────────────────────────────────
    def readiness(self, side: Optional[str]) -> Dict[str, Any]:
        """Is execution allowed at all?

        Blocks are absolute and are checked before any score is looked at: a
        frozen tape, a shocked tape or an invalid strike cannot be outvoted by
        agreement elsewhere. That is the difference between a gate and a weight,
        and Stage 44 has been a gate everywhere else in V6.
        """
        blocks: List[str] = []
        unknowns: List[str] = []

        if self._v("risk.freeze") is True:
            blocks.append("Stage 44 froze entries — the tape repriced")
        if str(self._v("market.stability")).upper() == "SHOCK":
            blocks.append("Stage 44 reports SHOCK")
        if str(_side_value(self._v("strike.validation"), side)) == "INVALID":
            blocks.append("Stage 71.8 could not validate the selected strike")
        if str(_side_value(self._v("strike.liquidity"), side)) == "Disagree":
            blocks.append("the selected strike is illiquid")
        if str(self._v("risk.validity")).upper() == "INVALID":
            blocks.append("Stage 51 rejected the signal")

        for need in ("opportunity.best_side", "strike.validation",
                     "energy.energy"):
            if not self._known(need):
                unknowns.append(need)

        if blocks:
            return {"readiness": NOT_READY, "blocks": tuple(blocks),
                    "unknowns": tuple(unknowns)}
        if unknowns:
            return {"readiness": UNKNOWN, "blocks": (),
                    "unknowns": tuple(unknowns),
                    "why": "the context did not carry enough to judge"}
        return {"readiness": READY, "blocks": (), "unknowns": ()}

    # ── Phase 2 · the entry score ─────────────────────────────────────
    def score(self, side: Optional[str]) -> Dict[str, Any]:
        """A weighted mean over execution inputs, 0–100.

        Unknown inputs **leave the denominator** — Stage 63's rule, applied
        here for the same reason it applies there: a decision resting on three
        of ten inputs is not a weak decision, it is a barely-informed one, and
        the two must not render as the same number.
        """
        parts: Dict[str, float] = {}
        for name, weight in WEIGHTS.items():
            raw = _side_value(self._v(name), side)
            if raw is UNKNOWN or raw == UNKNOWN:
                continue
            scale = _SCALES.get(name)
            if scale is not None:
                val = scale.get(str(raw))
                if val is None:
                    continue
            else:
                val = _f(raw)
                if val is None:
                    continue
                val = max(0.0, min(100.0, val))
            parts[name] = val

        if not parts:
            return {"score": UNKNOWN, "reporting": 0, "of": len(WEIGHTS),
                    "components": MappingProxyType({}),
                    "reason": "no execution input reported"}
        total = sum(WEIGHTS[k] for k in parts)
        value = sum(parts[k] * WEIGHTS[k] for k in parts) / total
        return {"score": round(value), "reporting": len(parts),
                "of": len(WEIGHTS),
                "components": MappingProxyType({k: round(v) for k, v in parts.items()}),
                "reason": f"{len(parts)} of {len(WEIGHTS)} execution inputs"}

    # ── Phase 3 · entry zone ──────────────────────────────────────────
    def entry_zone(self) -> Dict[str, Any]:
        """Early · Optimal · Late · Missed.

        A table lookup over two context fields — Stage 42's reaction and Stage
        71.5's timing — never a recomputation of either. Where the two disagree
        the **later** reading wins: being early to a move that has already run
        is the expensive direction of the error.
        """
        timing = str(self._v("opportunity.timing") or UNKNOWN).upper()
        reaction = str(self._v("market.acceptance") or UNKNOWN).upper()
        if timing == UNKNOWN and reaction == UNKNOWN:
            return {"zone": UNKNOWN,
                    "why": "neither Stage 42 nor Stage 71.5 reported"}

        by_timing = {"NOW": OPTIMAL, "PREPARE": EARLY, "WAIT": EARLY,
                     "LATE": LATE, "MISSED": MISSED}.get(timing)
        by_reaction = (LATE if reaction in _REACTED else
                       OPTIMAL if reaction in _FORMING else
                       MISSED if reaction in ("BULL_TRAP", "BEAR_TRAP") else None)

        order = (EARLY, OPTIMAL, LATE, MISSED)
        got = [z for z in (by_timing, by_reaction) if z]
        if not got:
            return {"zone": UNKNOWN,
                    "why": f"timing {timing} and reaction {reaction} are not "
                           f"states this stage can place"}
        zone = max(got, key=order.index)
        return {"zone": zone,
                "why": f"timing {timing.title()} · reaction "
                       f"{reaction.replace('_', ' ').title()}"}

    # ── Phase 4 · risk ────────────────────────────────────────────────
    def risk(self) -> Dict[str, Any]:
        """One of five bands, or UNKNOWN. Read from Stage 71.5, escalated by
        the context's own risk flags — never averaged."""
        base = str(self._v("opportunity.trade_risk") or UNKNOWN).title()
        if base not in RISK_BANDS:
            base = {"Low": "Low", "Medium": "Medium", "High": "High",
                    "Extreme": "Extreme"}.get(base, UNKNOWN)
        drivers: List[str] = []
        if base is UNKNOWN or base == UNKNOWN:
            if not self._known("risk.risk"):
                return {"risk": UNKNOWN, "drivers": (),
                        "why": "no stage reported a risk level"}
            base = {"LOW": "Low", "MODERATE": "Medium", "MEDIUM": "Medium",
                    "HIGH": "High"}.get(str(self._v("risk.risk")).upper(),
                                        UNKNOWN)
            drivers.append(f"Stage 4 breakout risk {self._v('risk.risk')}")
            if base == UNKNOWN:
                return {"risk": UNKNOWN, "drivers": tuple(drivers),
                        "why": "risk level not in a band this stage reports"}

        idx = RISK_BANDS.index(base)
        # Escalation, not averaging: an unstable tape makes any trade riskier
        # than its horizon says, and the two facts have different owners.
        if str(self._v("market.stability")).upper() in ("UNSTABLE", "SHOCK"):
            idx = min(idx + 1, len(RISK_BANDS) - 1)
            drivers.append(f"Stage 44 {self._v('market.stability')}")
        if str(_side_value(self._v("strike.validation"), self._side())) == "WEAK":
            idx = min(idx + 1, len(RISK_BANDS) - 1)
            drivers.append("Stage 71.8 validation WEAK")
        return {"risk": RISK_BANDS[idx], "drivers": tuple(drivers),
                "why": f"Stage 71.5 {base}"
                       + (f", escalated by {len(drivers)}" if drivers else "")}

    # ── Phase 5 · reward ──────────────────────────────────────────────
    def reward(self, side: Optional[str]) -> Dict[str, Any]:
        """Execution quality, **not** a price forecast.

        It answers *how good is this fill likely to be*, from the grade Stage
        71.5 gave the opportunity, the structure score behind the premium and
        where in the move the entry lands.
        """
        grade = str(self._v("opportunity.trade_quality") or UNKNOWN).upper()
        struct = _f(_side_value(self._v("premium.premium_score"), side))
        zone = self.entry_zone().get("zone")

        pts: List[float] = []
        if grade in ("A+", "A", "B", "C", "AVOID"):
            pts.append({"A+": 100.0, "A": 82.0, "B": 62.0, "C": 40.0,
                        "AVOID": 0.0}[grade])
        if struct is not None:
            pts.append(struct)
        if zone in (EARLY, OPTIMAL, LATE, MISSED):
            pts.append({EARLY: 70.0, OPTIMAL: 100.0, LATE: 40.0,
                        MISSED: 0.0}[zone])
        if not pts:
            return {"reward": UNKNOWN,
                    "why": "neither quality, structure nor zone reported"}
        v = sum(pts) / len(pts)
        band = ("Excellent" if v >= 80 else "Good" if v >= 60 else
                "Average" if v >= 40 else "Poor")
        return {"reward": band, "why": f"{len(pts)} inputs, mean {v:.0f}/100"}

    # ── Phase 6 · entry type ──────────────────────────────────────────
    def entry_type(self) -> Dict[str, Any]:
        """One of six, mapped from Stage 71.5's opportunity type.

        A type this stage cannot source stays UNKNOWN. Inferring `Pullback`
        from price behaviour would mean measuring price behaviour, which is not
        this stage's job and is already somebody else's.
        """
        raw = self._v("opportunity.entry_type")
        if raw is UNKNOWN or raw == UNKNOWN:
            return {"entry_type": UNKNOWN, "why": "Stage 71.5 did not report"}
        key = str(raw).upper().replace("-", " ").strip()
        got = _TYPE_MAP.get(key)
        if got is None:
            for k, v in _TYPE_MAP.items():
                if k in key:
                    got = v
                    break
        if got is None:
            return {"entry_type": UNKNOWN,
                    "why": f"'{raw}' is not a type this stage can express"}
        return {"entry_type": got, "why": f"Stage 71.5 {raw}"}

    # ── Phase 7 · the trade package ───────────────────────────────────
    def package(self, side: Optional[str]) -> Dict[str, Any]:
        """Entry, stop and targets, in premium. UNKNOWN where unavailable.

        Entry and stop come from Premium Structure's own levels, which are the
        leg's own zones — premium prices, not NIFTY levels converted through a
        delta no engine publishes.

        `target2` and `target3` are permanently UNKNOWN: Stage 35 publishes one
        target and a ladder would be this stage inventing levels.
        """
        struct = _side_value(self._v("premium.premium_structure"), side) or {}
        if not isinstance(struct, Mapping):
            struct = {}
        support = _f(struct.get("support"))
        resistance = _f(struct.get("resistance"))

        # A CALL premium is entered toward its resistance and stopped under its
        # support; a PUT premium the same way on its own chart, because every
        # leg engine reports in the LEG's own direction.
        entry = _f(struct.get("ltp")) or _f(self._v("market.reaction_level"))
        stop = support if side == "CALL" else support
        t1 = _f(self._v("risk.next_target")) or resistance

        rr = UNKNOWN
        if None not in (entry, stop, t1) and entry is not None:
            risk_pts, reward_pts = entry - stop, t1 - entry
            if risk_pts > 0 and reward_pts > 0:
                rr = round(reward_pts / risk_pts, 2)

        return {
            "entry": entry if entry is not None else UNKNOWN,
            "stop": stop if stop is not None else UNKNOWN,
            "targets": MappingProxyType({
                "target1": t1 if t1 is not None else UNKNOWN,
                "target2": UNKNOWN, "target3": UNKNOWN}),
            "risk_reward": rr,
            "missing": MISSING_PRODUCERS,
        }

    # ── Stage 71.85 · read, never computed ────────────────────────────
    def behaviour(self, side: Optional[str]) -> Mapping[str, Any]:
        """Stage 71.85's seven published facts for this side.

        Every one is `self._v(...)` — a context read. This stage does not
        interpret them, does not re-rank them and does not decide what they
        mean; the score already consumed `premium.behaviour` through `WEIGHTS`
        like any other component, and this block exists so Stage 72.9 can put
        the same values in a message without reaching past the bridge for them.
        """
        return MappingProxyType({
            "behaviour": _side_value(self._v("premium.behaviour"), side),
            "strength": _side_value(self._v("premium.behaviour_strength"), side),
            "confidence": _side_value(
                self._v("premium.behaviour_confidence"), side),
            "momentum": _side_value(self._v("premium.momentum"), side),
            "break_probability": _side_value(
                self._v("premium.break_probability"), side),
            "fakeout_probability": _side_value(
                self._v("premium.fakeout_probability"), side),
            "acceptance": _side_value(self._v("premium.acceptance"), side),
            "top_reason": _side_value(self._v("premium.top_reason"), side),
            "structure_state": _side_value(
                self._v("premium.structure_state"), side),
            "structure_strength": _side_value(
                self._v("premium.structure_strength"), side),
            "owner": "Stage 71.85 — Premium LTP Behaviour",
        })

    # ── Phase 8 · the Telegram payload ────────────────────────────────
    def telegram(self, decision: Dict[str, Any]) -> Mapping[str, Any]:
        """A prepared payload. **This stage does not send it.**

        Every field is copied from the decision, so the message cannot contain
        a value the decision did not make. `ready` says the payload is
        well-formed, not that anything should go out — sending is somebody
        else's decision, behind a switch a human flipped.
        """
        _b = decision.get("behaviour") or {}
        return MappingProxyType({
            # identity first: a payload that cannot be traced back to the
            # decision it came from is a message with no record behind it, and
            # the replay/audit path needs the join key more than the prose.
            "id": decision.get("id"), "version": decision.get("version"),
            "created_at": decision.get("created_at"),
            "hash": decision.get("hash"),
            "ready": bool(decision.get("state") in ("ENTER", "ENTRY_READY")),
            "state": decision.get("state"),
            "side": decision.get("side"), "strike": decision.get("strike"),
            "horizon": decision.get("horizon"), "timing": decision.get("timing"),
            "entry": decision.get("entry"), "stop": decision.get("stop"),
            "targets": decision.get("targets"),
            "risk": decision.get("risk"), "reward": decision.get("reward"),
            "confidence": decision.get("confidence"),
            "quality": decision.get("quality"),
            "reasons": tuple(r.label for r in decision.get("reason_codes", ())[:5]),
            "warnings": decision.get("warnings"),
            # ── Stage 71.85, appended (72.1) ──
            # Copied from the same decision body as everything above, so the
            # message cannot report a behaviour the decision did not carry.
            "behaviour": _b.get("behaviour", UNKNOWN),
            "behaviour_strength": _b.get("strength", UNKNOWN),
            "momentum": _b.get("momentum", UNKNOWN),
            "break_probability": _b.get("break_probability", UNKNOWN),
            "fakeout_probability": _b.get("fakeout_probability", UNKNOWN),
            "premium_acceptance": _b.get("acceptance", UNKNOWN),
            "top_behaviour_reason": _b.get("top_reason", UNKNOWN),
            "advisory_only": True,
            "sent": False,
            "note": "prepared by Stage 72 — sending belongs downstream",
        })

    # ── Phase 9 · explainability ──────────────────────────────────────
    def _reasons(self, side: Optional[str],
                 scored: Dict[str, Any]) -> Tuple[Reason, ...]:
        """At most five, strongest first, each tracing to a context field."""
        pool: List[Tuple[float, Reason]] = []
        for name, val in (scored.get("components") or {}).items():
            weight = WEIGHTS.get(name, 1.0) * (val / 100.0)
            raw = _side_value(self._v(name), side)
            label = f"{name.split('.')[-1].replace('_', ' ').title()} {raw}"
            pool.append((weight * 20.0, self._reason(name, label, val)))
        pool.sort(key=lambda x: -x[0])
        return tuple(r for _, r in pool[:5])

    def _warnings(self, side: Optional[str],
                  ready: Dict[str, Any]) -> Tuple[str, ...]:
        out = list(ready.get("blocks") or ())
        if str(self._v("market.stability")).upper() == "UNSTABLE":
            out.append("Stage 44 reports UNSTABLE — the read may not hold")
        if str(_side_value(self._v("strike.agreement"), side)) == "Disagree":
            out.append("the selected strike is not the busiest by volume")
        if str(_side_value(self._v("strike.validation"), side)) == "WEAK":
            out.append("Stage 71.8 validated the strike only weakly")
        zone = self.entry_zone().get("zone")
        if zone in (LATE, MISSED):
            out.append(f"entry would be {str(zone).lower()} to this move")
        for name in (ready.get("unknowns") or ()):
            out.append(f"{name} did not report")
        return tuple(dict.fromkeys(out))

    def _invalidations(self) -> Tuple[str, ...]:
        out: List[str] = []
        inv = self._v("risk.invalidation")
        if inv is not UNKNOWN and inv != UNKNOWN:
            out.append(str(inv))
        lvl = self._v("market.reaction_level")
        if lvl is not UNKNOWN and lvl != UNKNOWN:
            out.append(f"a close back through {lvl} invalidates the reaction")
        if str(self._v("market.transition")).upper() in ("WEAKENING", "DECAYING"):
            out.append("Stage 47 reports the bias weakening")
        return tuple(out)

    # ── the state ─────────────────────────────────────────────────────
    def _side(self) -> Optional[str]:
        s = self._v("opportunity.best_side")
        return s if s in ("CALL", "PUT") else None

    @staticmethod
    def _checked(state: str, why: str) -> Tuple[str, str]:
        """Every state this stage emits must be one Stage 52 already has.

        The import is not decoration: a typo or a well-meaning new state name
        fails here rather than reaching a Trade Manager that has never heard
        of it."""
        if state not in STATES:
            raise ValueError(
                f"{state!r} is not a Stage 52 state — Stage 72 may not invent "
                f"one. Valid: {', '.join(STATES)}")
        return state, why

    def state(self, ready: Dict[str, Any], scored: Dict[str, Any],
              zone: str) -> Tuple[str, str]:
        """One of Stage 52's states, with the reason it was chosen.

        `ABORT` is checked first and unconditionally, exactly as Stage 52 does:
        a shocked tape invalidates the read the setup was computed on, and a
        score cannot argue with that.
        """
        if ready.get("readiness") == NOT_READY:
            blocks = ready.get("blocks") or ()
            hard = any("froze" in b or "SHOCK" in b for b in blocks)
            return self._checked("ABORT" if hard else "WAIT",
                             blocks[0] if blocks else "not ready")
        if ready.get("readiness") == UNKNOWN:
            return self._checked("WAIT",
                                 "the context did not carry enough to judge")

        score = scored.get("score")
        if score is UNKNOWN or score == UNKNOWN:
            return self._checked("WAIT", "no execution input reported")
        if zone == MISSED:
            return self._checked("WAIT", "the move has already gone")
        if scored.get("reporting", 0) < 4:
            return self._checked("WAIT", f"only {scored.get('reporting')} of "
                                 f"{scored.get('of')} execution inputs reported")
        if score >= 75 and zone in (OPTIMAL, EARLY):
            return self._checked(
                "ENTER", f"score {score} in the {str(zone).lower()} window")
        if score >= 60:
            return self._checked(
                "ENTRY_READY", f"score {score} — waiting on the window")
        return self._checked(
            "WAIT", f"score {score} is below the entry threshold")

    # ── run ───────────────────────────────────────────────────────────
    def run(self) -> EntryDecision:
        """The whole stage. Always returns a decision, never raises."""
        side = self._side()
        ready = self.readiness(side)
        scored = self.score(side)
        zone_read = self.entry_zone()
        zone = zone_read.get("zone")
        state, why = self.state(ready, scored, zone)
        pkg = self.package(side)
        risk = self.risk()
        reward = self.reward(side)
        etype = self.entry_type()
        reasons = self._reasons(side, scored)
        warnings = self._warnings(side, ready)
        behaviour = self.behaviour(side)

        strike = (self._v("premium.selected_call") if side == "CALL"
                  else self._v("premium.selected_put") if side == "PUT"
                  else UNKNOWN)

        body: Dict[str, Any] = {
            "state": state,
            "confidence": self._v("opportunity.confidence"),
            "quality": self._v("opportunity.trade_quality"),
            "entry_type": etype["entry_type"],
            "side": side or UNKNOWN,
            "strike": strike,
            "horizon": self._v("opportunity.best_horizon"),
            "timing": self._v("opportunity.timing"),
            "risk": risk["risk"], "reward": reward["reward"],
            "entry_zone": zone,
            "entry": pkg["entry"], "stop": pkg["stop"],
            "targets": pkg["targets"], "risk_reward": pkg["risk_reward"],
            "lifetime": self._v("opportunity.lifetime"),
            "readiness": ready["readiness"], "score": scored["score"],
            "reason_codes": reasons,
            "top_trigger": (reasons[0].label if reasons else UNKNOWN),
            "warnings": warnings,
            "invalidations": self._invalidations(),
        }

        meta = MappingProxyType({
            "version": VERSION,          # same value as `decision.version`
            "state_reason": why,
            # ── every hard gate that blocked, not just the first ──────
            # `state()` puts `blocks[0]` into `state_reason`, so when three
            # gates fail a trader is told about one and fixes the wrong thing.
            # Carried here in full.
            #
            # This is not a change to the frozen contract: `STAGE72_FROZEN.md`
            # forbids editing scoring, weights, gates or recommendation logic,
            # and this touches none of them — the same gates run and reach the
            # same verdict. `metadata` is also outside `HASH_FIELDS`, so a
            # stored 72.1 decision hashes identically with or without it.
            "readiness_blocks": tuple(ready.get("blocks") or ()),
            "readiness_unknowns": tuple(ready.get("unknowns") or ()),
            "score_reason": scored.get("reason"),
            "zone_reason": zone_read.get("why"),
            "risk_reason": risk.get("why"), "reward_reason": reward.get("why"),
            "type_reason": etype.get("why"),
            "components": scored.get("components"),
            "weights": WEIGHTS,
            "missing_producers": MISSING_PRODUCERS,
            "context_version": (dict(self.ctx.meta).get("version")
                                if self.ctx is not None else UNKNOWN),
            "context_cycle": (dict(self.ctx.meta).get("cycle")
                              if self.ctx is not None else UNKNOWN),
            "context_coverage": (self.ctx.coverage()
                                 if self.ctx is not None else UNKNOWN),
        })

        # ── identity, minted exactly once ─────────────────────────────
        # Created here rather than in `__post_init__` so the Telegram payload
        # is built from the same values the decision carries — a payload with a
        # different id than the decision it describes is worse than no id.
        decision_id = str(uuid.uuid4())
        created_at = _now_iso()
        digest = decision_hash(decision_id, VERSION, body["state"],
                               body["confidence"], body["score"], created_at)
        ident = {"id": decision_id, "version": VERSION,
                 "created_at": created_at, "hash": digest}

        return EntryDecision(
            **{k: (_freeze(v) if k in ("targets",) else v)
               for k, v in body.items()},
            **ident,
            telegram=self.telegram({**body, **ident,
                                    "reason_codes": reasons,
                                    "behaviour": behaviour}),
            behaviour=behaviour,
            metadata=meta)


def run(ctx: Optional[TradingContext] = None) -> EntryDecision:
    """Convenience: `entry_engine.run(ctx)`."""
    return EntryEngine(ctx).run()
