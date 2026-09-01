"""Stage 73 — the Trade Lifecycle Engine.

Owns **life after entry**, and nothing before it.

```
Market → TradingContext → Stage 72 → Stage 73 → Learning · Analytics · Replay
                                     ↑ here
```

It never decides whether to enter — Stage 72 is frozen and that verdict is
read, not revisited. It never mutates an `EntryDecision`: a decision is
history, so this stage builds a **new** object that references `decision.id`.

## Two inputs, and only two

```python
lifecycle = TradeLifecycle(decision, ctx).run()
```

`entry_engine` and `trading_context` are the only local modules imported, and a
test asserts exactly that set. Everything about the market arrives through the
context; everything about the trade arrives through the decision.

## ⛔ It cannot know whether a trade is open

`EntryDecision.state == "ENTER"` means *Stage 72 concluded an entry was
executable*. It does not mean an order was placed or filled, and nothing
downstream of Stage 72 exists yet to report that.

So `position_known` is **always `UNKNOWN`**, named in `MISSING_PRODUCERS`, and
`intent` reports what Stage 72 decided as a separate fact. Treating `ENTER` as
"we are in a trade" would make every trail, scale and exit decision after it
manage a position that may not exist — and the output would look completely
normal while doing it.

When a position store is added it becomes a third input and `position_known`
starts reporting, **with no other phase changing**: every other phase reads the
tape and the levels, not the fill.

## Its states are its own

`WAIT_ENTRY · ENTERED · HOLD · ADD · SCALE_OUT · TRAIL · EXIT · COMPLETE ·
ABORT`. Entry states are not reused — Stage 52's machine describes *getting
into* a trade, this one describes *being in* one, and sharing a vocabulary
across the two would make "WAIT" mean two different things one stage apart.

## What it computes, and what it consumes

Everything here is a **classification over values the two inputs already
carry**. The clearest line is the trail: this stage produces a *band* —
"trail aggressively" — and never a *level*. `adaptive_trail` belongs to Stage 52
and the stop level is consumed from `EntryDecision.stop`. A consumer wanting a
number applies the band to that stop.

Exit reasons **report**, they never predict. First trigger wins, and the one
that fired is named.

## Not owned, deliberately

Position sizing, lot count, PnL and broker integration are **not** here. They
need capital, risk-per-trade and fills — three inputs that do not exist — and
their absence would otherwise infect every phase. Lifecycle decisions are a
function of the tape and the levels, and both are already available.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .entry_engine import EntryDecision
from .trading_context import UNKNOWN, TradingContext, _freeze, _thaw

#: The lifecycle contract. Bump only for a breaking change to
#: `TradeLifecycleDecision`.
VERSION = "73.0"

ADVISORY_ONLY = True

#: Facts no producer publishes. Named, never inferred.
MISSING_PRODUCERS: Tuple[str, ...] = (
    "position_state",   # nothing reports whether an order was filled
    "fill_price",       # …or at what price
)

# ══════════════════════════════════════════════════════════════════════
#  the lifecycle state machine — Stage 73's own
# ══════════════════════════════════════════════════════════════════════

#: Stage 52's machine describes getting INTO a trade; this one describes being
#: IN one. Sharing a vocabulary would make "WAIT" mean two different things one
#: stage apart, so these are deliberately distinct names.
STATES: Tuple[str, ...] = (
    "WAIT_ENTRY", "ENTERED", "HOLD", "ADD", "SCALE_OUT", "TRAIL",
    "EXIT", "COMPLETE", "ABORT",
)

LABEL: Mapping[str, str] = MappingProxyType({
    "WAIT_ENTRY": "⏳ WAIT ENTRY", "ENTERED": "🎬 ENTERED", "HOLD": "🤝 HOLD",
    "ADD": "➕ ADD", "SCALE_OUT": "➖ SCALE OUT", "TRAIL": "📈 TRAIL",
    "EXIT": "🚪 EXIT", "COMPLETE": "🏁 COMPLETE", "ABORT": "🛑 ABORT",
})

#: Phase 3 — exactly one is chosen per cycle.
ACTIONS: Tuple[str, ...] = ("HOLD", "ADD", "SCALE_OUT", "TRAIL", "EXIT",
                            "ABORT")

#: Phase 1
ENTERED_INTENT, NO_ENTRY, ABORTED = "ENTERED_INTENT", "NO_ENTRY", "ABORTED"

#: Phase 2 — worst to best, so an index comparison is meaningful.
HEALTH_BANDS: Tuple[str, ...] = ("Critical", "Poor", "Average", "Good",
                                 "Excellent")

#: Phase 4 — bands, never levels.
NO_TRAIL, SOFT_TRAIL = "No Trail", "Soft Trail"
NORMAL_TRAIL, AGGRESSIVE_TRAIL = "Normal Trail", "Aggressive Trail"
TRAIL_BANDS: Tuple[str, ...] = (NO_TRAIL, SOFT_TRAIL, NORMAL_TRAIL,
                                AGGRESSIVE_TRAIL)

#: Phase 5
SCALE_ADD, SCALE_REDUCE, SCALE_NEITHER = "Add", "Reduce", "Neither"

#: Phase 6 — reported, never predicted. Order is priority: the first trigger
#: that fires is the reason, because a stop hit during a shock is a stop hit.
EXIT_REASONS: Tuple[str, ...] = (
    "Stop Hit", "Target Hit", "Shock", "Illiquidity", "Structure Failure",
    "Energy Collapse", "Expiry", "Manual",
)

#: What `hash` covers — identity plus verdict, the same shape Stage 72 uses and
#: for the same reason: a digest that changed when a warning's wording changed
#: would make the integrity check cry wolf.
HASH_FIELDS: Tuple[str, ...] = ("id", "decision_id", "version", "state",
                                "action", "created_at")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lifecycle_hash(lifecycle_id: str, decision_id: str, version: str,
                   state: str, action: str, created_at: str) -> str:
    """Stable SHA-256 over the six identity fields.

    A module function so a consumer can verify a stored row without
    reconstructing the object, and so determinism is testable without `uuid4`.
    """
    parts = [str(lifecycle_id), str(decision_id), str(version), str(state),
             str(action), str(created_at)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _side_value(v: Any, side: Optional[str]) -> Any:
    if isinstance(v, Mapping) and side in v:
        return v[side]
    return v


# ══════════════════════════════════════════════════════════════════════
#  Phase 2 — position health
# ══════════════════════════════════════════════════════════════════════

#: Every health input, its weight, and the context field it reads. One field
#: each: two weights on one fact would count the tape twice, which is the
#: failure Stage 53 exists to fix and the one this stack keeps re-learning.
#:
#: Stability leads because it is the only input that can invalidate the read the
#: trade was opened on. Energy is second — a premium losing participation is a
#: position losing its exit.
HEALTH_WEIGHTS: Mapping[str, float] = MappingProxyType({
    "market.stability": 2.5,
    "energy.energy": 2.0,
    "premium.premium_score": 2.0,
    "strike.liquidity": 1.5,
    "energy.shift": 1.0,
    "opportunity.trade_risk": 1.0,
    "opportunity.timing": 1.0,
    "risk.validity": 1.0,
})

#: Categorical → 0–100. A value absent from its table leaves the denominator; it
#: is never guessed at 50.
_HEALTH_SCALES: Mapping[str, Mapping[str, Optional[float]]] = MappingProxyType({
    "market.stability": MappingProxyType(
        {"STABLE": 100.0, "RECOVERY": 55.0, "UNSTABLE": 20.0, "SHOCK": 0.0}),
    "strike.liquidity": MappingProxyType(
        {"Agree": 100.0, "Partially Agree": 50.0, "Disagree": 0.0}),
    "energy.shift": MappingProxyType(
        {"Exploding": 100.0, "Increasing": 85.0, "Building": 70.0,
         "Holding": 55.0, "Compressing": 50.0, "Distributing": 25.0,
         "Decreasing": 20.0, "UNKNOWN": None}),
    "opportunity.trade_risk": MappingProxyType(
        {"LOW": 100.0, "MEDIUM": 60.0, "HIGH": 30.0, "EXTREME": 0.0}),
    "opportunity.timing": MappingProxyType(
        {"NOW": 100.0, "PREPARE": 70.0, "WAIT": 50.0, "LATE": 30.0,
         "MISSED": 0.0}),
    "risk.validity": MappingProxyType(
        {"VALID": 100.0, "STRONG": 100.0, "WEAK": 40.0, "INVALID": 0.0,
         "UNKNOWN": None}),
})


@dataclass(frozen=True)
class Reason:
    """One contributor, traceable to the input it came from."""
    code: str
    label: str
    weight: int
    owner: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "label": self.label, "weight": self.weight,
                "owner": self.owner, "source": self.source}


@dataclass(frozen=True)
class TradeLifecycleDecision:
    """One cycle's lifecycle verdict.

    **Frozen, and it references rather than replaces.** `decision_id` points at
    the `EntryDecision` this manages; that decision is untouched and remains
    the record of what was decided. This object is the record of what was done
    about it afterwards.
    """
    state: str
    action: str
    confidence: Any
    quality: Any
    risk: Any
    health: Any
    intent: str
    position_known: str
    trail: Any
    scale: Any
    exit_reason: Any
    reason_codes: Tuple[Reason, ...]
    top_trigger: Any
    warnings: Tuple[str, ...]
    telegram_payload: Mapping[str, Any]
    metadata: Mapping[str, Any]
    id: str = ""
    decision_id: str = ""
    version: str = VERSION
    created_at: str = ""
    hash: str = ""
    advisory_only: bool = ADVISORY_ONLY

    @property
    def label(self) -> str:
        return LABEL.get(self.state, self.state)

    @property
    def top_reasons(self) -> Tuple[Reason, ...]:
        return self.reason_codes[:5]

    def verify(self) -> bool:
        return self.hash == lifecycle_hash(
            self.id, self.decision_id, self.version, self.state, self.action,
            self.created_at)

    def identity(self) -> Dict[str, Any]:
        """What Stage 74+ carry forward. `decision_id` is the join back to the
        entry that started this trade."""
        return {"id": self.id, "decision_id": self.decision_id,
                "version": self.version, "created_at": self.created_at,
                "hash": self.hash}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "decision_id": self.decision_id,
            "version": self.version, "created_at": self.created_at,
            "hash": self.hash,
            "state": self.state, "label": self.label, "action": self.action,
            "confidence": _thaw(self.confidence), "quality": _thaw(self.quality),
            "risk": _thaw(self.risk), "health": _thaw(self.health),
            "intent": self.intent, "position_known": self.position_known,
            "trail": _thaw(self.trail), "scale": _thaw(self.scale),
            "exit_reason": _thaw(self.exit_reason),
            "reason_codes": [r.to_dict() for r in self.reason_codes],
            "top_trigger": _thaw(self.top_trigger),
            "warnings": list(self.warnings),
            "telegram_payload": _thaw(self.telegram_payload),
            "metadata": _thaw(self.metadata),
            "advisory_only": self.advisory_only,
        }

    def summary(self) -> Dict[str, Any]:
        """Phase 7. `why` and `why_not` both appear on every lifecycle decision,
        for the reason Stage 72's summary does: a stage that explains itself
        only when it acts teaches a trader to read silence as permission."""
        acting = self.action in ("ADD", "SCALE_OUT", "EXIT", "ABORT", "TRAIL")
        return {
            "id": self.id, "decision_id": self.decision_id,
            "version": self.version, "created_at": self.created_at,
            "action": self.action, "state": self.state, "label": self.label,
            "why": [r.label for r in self.top_reasons],
            "why_not": list(self.warnings) if not acting else [],
            "confidence": _thaw(self.confidence), "risk": _thaw(self.risk),
            "health": _thaw(self.health),
            "warnings": list(self.warnings),
            "top_trigger": _thaw(self.top_trigger),
            "advisory_only": self.advisory_only,
        }


class TradeLifecycle:
    """`TradeLifecycle(decision, ctx).run()` → `TradeLifecycleDecision`."""

    def __init__(self, decision: Optional[EntryDecision] = None,
                 ctx: Optional[TradingContext] = None) -> None:
        self.decision = decision
        self.ctx = ctx

    # ── input access ──────────────────────────────────────────────────
    def _v(self, name: str, default: Any = UNKNOWN) -> Any:
        return self.ctx.value(name, default) if self.ctx is not None else default

    def _known(self, name: str) -> bool:
        return bool(self.ctx is not None and self.ctx.known(name))

    def _field(self, name: str):
        from .trading_context import Field
        if self.ctx is None:
            return Field(UNKNOWN, UNKNOWN, UNKNOWN, name)
        return self.ctx.get(name)

    def _d(self, attr: str, default: Any = UNKNOWN) -> Any:
        return getattr(self.decision, attr, default) if self.decision else default

    def _side(self) -> Optional[str]:
        s = self._d("side")
        return s if s in ("CALL", "PUT") else None

    def _reason(self, name: str, label: str, weight: float) -> Reason:
        f = self._field(name)
        return Reason(code=label.upper().replace(" ", "_").replace(":", ""),
                      label=label, weight=round(weight),
                      owner=f.owner, source=f.source)

    # ── Phase 1 · position awareness ──────────────────────────────────
    def awareness(self) -> Dict[str, Any]:
        """What Stage 72 *intended*, and — separately — whether a position
        actually exists.

        The second is `UNKNOWN` unconditionally. Nothing in MIOS reports a fill,
        and inferring one from `state == "ENTER"` would have every later phase
        managing a position that may not be there, with output that looked
        entirely normal.
        """
        state = str(self._d("state") or UNKNOWN)
        if self.decision is None:
            intent, why = UNKNOWN, "no entry decision supplied"
        elif state == "ABORT":
            intent, why = ABORTED, "Stage 72 aborted before entry"
        elif state == "ENTER":
            intent, why = ENTERED_INTENT, "Stage 72 concluded an entry"
        else:
            intent, why = NO_ENTRY, f"Stage 72 is at {state}"
        return {
            "intent": intent,
            "position_known": UNKNOWN,
            "why": why,
            "position_why": ("no producer reports a fill — "
                             "`position_state` and `fill_price` are unbuilt"),
        }

    # ── Phase 2 · position health ─────────────────────────────────────
    def health(self, side: Optional[str]) -> Dict[str, Any]:
        """Excellent · Good · Average · Poor · Critical · UNKNOWN.

        Unknown inputs leave the denominator — a position graded on two of eight
        reads is not unhealthy, it is barely observed, and the two must not
        render alike.
        """
        parts: Dict[str, float] = {}
        for name, _w in HEALTH_WEIGHTS.items():
            raw = _side_value(self._v(name), side)
            if raw is UNKNOWN or raw == UNKNOWN:
                continue
            scale = _HEALTH_SCALES.get(name)
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
            return {"health": UNKNOWN, "score": UNKNOWN, "reporting": 0,
                    "of": len(HEALTH_WEIGHTS),
                    "components": MappingProxyType({}),
                    "why": "no health input reported"}
        total = sum(HEALTH_WEIGHTS[k] for k in parts)
        score = sum(parts[k] * HEALTH_WEIGHTS[k] for k in parts) / total
        band = ("Excellent" if score >= 80 else "Good" if score >= 62 else
                "Average" if score >= 45 else "Poor" if score >= 25 else
                "Critical")
        return {"health": band, "score": round(score),
                "reporting": len(parts), "of": len(HEALTH_WEIGHTS),
                "components": MappingProxyType({k: round(v)
                                                for k, v in parts.items()}),
                "why": f"{len(parts)} of {len(HEALTH_WEIGHTS)} inputs, "
                       f"mean {score:.0f}/100"}

    # ── Phase 4 · trailing ────────────────────────────────────────────
    def trail(self, health: str) -> Dict[str, Any]:
        """A **band**, never a level.

        `adaptive_trail` belongs to Stage 52 and the stop level is consumed from
        `EntryDecision.stop`. "Trail aggressively" is a lifecycle judgement;
        "trail to 118.4" is a computation with an owner elsewhere. A consumer
        wanting a number applies the band to the stop this returns.
        """
        stop = self._d("stop")
        if stop is UNKNOWN or stop == UNKNOWN:
            return {"trail": UNKNOWN, "stop": UNKNOWN,
                    "why": "no stop was published — nothing to trail"}
        if health == UNKNOWN:
            return {"trail": UNKNOWN, "stop": stop,
                    "why": "health did not report"}

        stability = str(self._v("market.stability")).upper()
        shift = str(_side_value(self._v("energy.shift"), self._side()))
        if stability in ("SHOCK", "UNSTABLE"):
            band, why = AGGRESSIVE_TRAIL, f"Stage 44 {stability.title()}"
        elif health in ("Critical", "Poor"):
            band, why = AGGRESSIVE_TRAIL, f"health {health}"
        elif shift in ("Distributing", "Decreasing"):
            band, why = NORMAL_TRAIL, f"energy {shift.lower()}"
        elif health == "Excellent" and shift in ("Exploding", "Increasing"):
            band, why = SOFT_TRAIL, f"health {health}, energy {shift.lower()}"
        elif health in ("Good", "Excellent"):
            band, why = NORMAL_TRAIL, f"health {health}"
        else:
            band, why = NO_TRAIL, f"health {health} — nothing to protect yet"
        return {"trail": band, "stop": stop,
                "why": why + " · apply the band to the stop Stage 72 published"}

    # ── Phase 5 · scale ───────────────────────────────────────────────
    def scale(self, side: Optional[str], health: str) -> Dict[str, Any]:
        """Add · Reduce · Neither. **Never an average.**

        Three separate reads vote, and a disagreement returns `Neither` rather
        than a blend. Averaging "energy is collapsing" against "structure is
        strong" produces a middling number that recommends adding to a position
        that is losing its exit.
        """
        energy = _f(_side_value(self._v("energy.energy"), side))
        struct = _f(_side_value(self._v("premium.premium_score"), side))
        stability = str(self._v("market.stability")).upper()
        if energy is None and struct is None:
            return {"scale": UNKNOWN, "why": "neither energy nor structure "
                                             "reported"}
        if stability in ("SHOCK", "UNSTABLE"):
            return {"scale": SCALE_REDUCE,
                    "why": f"Stage 44 {stability.title()} — size down before "
                           f"anything else"}

        add_votes, cut_votes, why = [], [], []
        if energy is not None:
            (add_votes if energy >= 65 else cut_votes if energy < 35
             else why).append(f"energy {energy:.0f}")
        if struct is not None:
            (add_votes if struct >= 65 else cut_votes if struct < 40
             else why).append(f"structure {struct:.0f}")
        if health in ("Critical", "Poor"):
            cut_votes.append(f"health {health}")
        elif health == "Excellent":
            add_votes.append(f"health {health}")

        if add_votes and not cut_votes:
            return {"scale": SCALE_ADD, "why": " · ".join(add_votes)}
        if cut_votes and not add_votes:
            return {"scale": SCALE_REDUCE, "why": " · ".join(cut_votes)}
        both = add_votes + cut_votes + why
        return {"scale": SCALE_NEITHER,
                "why": (" · ".join(both) + " — reads disagree"
                        if add_votes and cut_votes else
                        " · ".join(both) or "nothing decisive")}

    # ── Phase 6 · exit reasons ────────────────────────────────────────
    def exit_reason(self, side: Optional[str], health: str) -> Dict[str, Any]:
        """Which trigger fired, first match wins. **Reported, never predicted.**

        `Stop Hit` outranks `Shock` because a stop hit during a shock is still a
        stop hit, and a learning row that recorded the shock instead would
        blame the tape for a level doing its job.
        """
        ltp = _f(_side_value(self._v("premium.premium_ltp"), side))
        stop = _f(self._d("stop"))
        targets = self._d("targets") or {}
        t1 = _f(targets.get("target1") if isinstance(targets, Mapping) else None)

        if ltp is not None and stop is not None and ltp <= stop:
            return {"exit_reason": "Stop Hit", "fired": True,
                    "why": f"premium {ltp:.1f} at or below the stop {stop:.1f}"}
        if ltp is not None and t1 is not None and ltp >= t1:
            return {"exit_reason": "Target Hit", "fired": True,
                    "why": f"premium {ltp:.1f} at or above target1 {t1:.1f}"}
        if str(self._v("market.stability")).upper() == "SHOCK":
            return {"exit_reason": "Shock", "fired": True,
                    "why": "Stage 44 reports SHOCK"}
        if str(_side_value(self._v("strike.liquidity"), side)) == "Disagree":
            return {"exit_reason": "Illiquidity", "fired": True,
                    "why": "the strike is no longer liquid"}
        struct = _f(_side_value(self._v("premium.premium_score"), side))
        if struct is not None and struct < 25:
            return {"exit_reason": "Structure Failure", "fired": True,
                    "why": f"premium structure {struct:.0f}/100"}
        energy = _f(_side_value(self._v("energy.energy"), side))
        if energy is not None and energy < 20:
            return {"exit_reason": "Energy Collapse", "fired": True,
                    "why": f"premium energy {energy:.0f} — nobody is trading it"}
        if str(self._v("market.day_type")).upper() in ("EXPIRY_PIN", "EXPIRY"):
            return {"exit_reason": "Expiry", "fired": False,
                    "why": "expiry session — decay accelerates, not an exit "
                           "trigger on its own"}
        if ltp is None:
            return {"exit_reason": UNKNOWN, "fired": False,
                    "why": "no live premium — Stop Hit and Target Hit cannot "
                           "be checked"}
        return {"exit_reason": None, "fired": False,
                "why": "no exit trigger fired"}

    # ── Phase 3 · the action, and the state ───────────────────────────
    @staticmethod
    def _checked(state: str) -> str:
        if state not in STATES:
            raise ValueError(
                f"{state!r} is not a Stage 73 lifecycle state. "
                f"Valid: {', '.join(STATES)}")
        return state

    @staticmethod
    def _checked_action(action: str) -> str:
        if action not in ACTIONS:
            raise ValueError(
                f"{action!r} is not a Stage 73 action. "
                f"Valid: {', '.join(ACTIONS)}")
        return action

    def action(self, aware: Dict[str, Any], health: Dict[str, Any],
               exiting: Dict[str, Any], scaling: Dict[str, Any],
               trailing: Dict[str, Any]) -> Tuple[str, str, str]:
        """Exactly one action, and the lifecycle state that goes with it.

        A priority ladder, not a score: an exit trigger is not something that
        can be outvoted by good health, and a freeze is not something to trail
        through. The first rung that matches wins and names itself.
        """
        if aware["intent"] in (NO_ENTRY, UNKNOWN):
            return (self._checked("WAIT_ENTRY"), self._checked_action("HOLD"),
                    aware["why"])
        if aware["intent"] == ABORTED:
            return (self._checked("ABORT"), self._checked_action("ABORT"),
                    aware["why"])
        if self._v("risk.freeze") is True:
            return (self._checked("ABORT"), self._checked_action("ABORT"),
                    "Stage 44 froze entries — the tape repriced")
        if exiting.get("fired"):
            reason = exiting["exit_reason"]
            done = reason in ("Stop Hit", "Target Hit")
            return (self._checked("COMPLETE" if done else "EXIT"),
                    self._checked_action("EXIT"),
                    f"{reason}: {exiting['why']}")
        if scaling.get("scale") == SCALE_REDUCE:
            return (self._checked("SCALE_OUT"),
                    self._checked_action("SCALE_OUT"), scaling["why"])
        if scaling.get("scale") == SCALE_ADD:
            return (self._checked("ADD"), self._checked_action("ADD"),
                    scaling["why"])
        if trailing.get("trail") in (NORMAL_TRAIL, AGGRESSIVE_TRAIL):
            return (self._checked("TRAIL"), self._checked_action("TRAIL"),
                    trailing["why"])
        if health.get("health") == UNKNOWN:
            return (self._checked("ENTERED"), self._checked_action("HOLD"),
                    "health did not report — holding rather than acting blind")
        return (self._checked("HOLD"), self._checked_action("HOLD"),
                f"health {health['health']}, nothing else fired")

    # ── Phase 8 · Telegram ────────────────────────────────────────────
    def telegram(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Prepared only. **This stage sends nothing.**

        Every field is copied from the lifecycle decision, so a message cannot
        carry a value the decision did not make.
        """
        return MappingProxyType({
            "id": body.get("id"), "decision_id": body.get("decision_id"),
            "version": body.get("version"),
            "created_at": body.get("created_at"), "hash": body.get("hash"),
            "ready": bool(body.get("action") in ("EXIT", "SCALE_OUT", "ADD",
                                                 "ABORT")),
            "state": body.get("state"), "action": body.get("action"),
            "health": body.get("health"), "risk": body.get("risk"),
            "trail": body.get("trail"), "scale": body.get("scale"),
            "exit_reason": body.get("exit_reason"),
            "confidence": body.get("confidence"),
            "reasons": tuple(r.label for r in body.get("reason_codes", ())[:5]),
            "warnings": body.get("warnings"),
            "advisory_only": True,
            "sent": False,
            "note": "prepared by Stage 73 — sending belongs downstream",
        })

    # ── Phase 7 · reasons and warnings ────────────────────────────────
    def _reasons(self, side: Optional[str],
                 health: Dict[str, Any]) -> Tuple[Reason, ...]:
        pool: List[Tuple[float, Reason]] = []
        for name, val in (health.get("components") or {}).items():
            weight = HEALTH_WEIGHTS.get(name, 1.0) * (val / 100.0)
            raw = _side_value(self._v(name), side)
            label = f"{name.split('.')[-1].replace('_', ' ').title()} {raw}"
            pool.append((weight * 20.0, self._reason(name, label, val)))
        pool.sort(key=lambda x: -x[0])
        return tuple(r for _, r in pool[:5])

    def _warnings(self, side: Optional[str], aware: Dict[str, Any],
                  health: Dict[str, Any], exiting: Dict[str, Any]
                  ) -> Tuple[str, ...]:
        out: List[str] = [aware["position_why"]]
        if str(self._v("market.stability")).upper() in ("UNSTABLE", "SHOCK"):
            out.append(f"Stage 44 reports {self._v('market.stability')}")
        if health.get("health") in ("Critical", "Poor"):
            out.append(f"position health {health['health']}")
        if health.get("reporting", 0) and health["reporting"] < 4:
            out.append(f"only {health['reporting']} of {health['of']} health "
                       f"inputs reported")
        if exiting.get("exit_reason") == UNKNOWN:
            out.append(exiting["why"])
        inval = self._v("risk.invalidation")
        if inval is not UNKNOWN and inval != UNKNOWN:
            out.append(f"invalidation: {inval}")
        return tuple(dict.fromkeys(out))

    # ── run ───────────────────────────────────────────────────────────
    def run(self) -> TradeLifecycleDecision:
        """The whole stage. Always returns a decision, never raises."""
        side = self._side()
        aware = self.awareness()
        health = self.health(side)
        exiting = self.exit_reason(side, health.get("health"))
        scaling = self.scale(side, health.get("health"))
        trailing = self.trail(health.get("health"))
        state, action, why = self.action(aware, health, exiting, scaling,
                                         trailing)
        reasons = self._reasons(side, health)
        warnings = self._warnings(side, aware, health, exiting)

        lifecycle_id = str(uuid.uuid4())
        decision_id = str(self._d("id", "") or "")
        created_at = _now_iso()
        digest = lifecycle_hash(lifecycle_id, decision_id, VERSION, state,
                                action, created_at)

        body: Dict[str, Any] = {
            "id": lifecycle_id, "decision_id": decision_id,
            "version": VERSION, "created_at": created_at, "hash": digest,
            "state": state, "action": action,
            "confidence": self._d("confidence"),
            "quality": self._d("quality"),
            "risk": self._d("risk"),
            "health": health.get("health"),
            "intent": aware["intent"],
            "position_known": aware["position_known"],
            "trail": trailing.get("trail"), "scale": scaling.get("scale"),
            "exit_reason": exiting.get("exit_reason"),
            "reason_codes": reasons,
            "top_trigger": (exiting.get("exit_reason")
                            if exiting.get("fired")
                            else reasons[0].label if reasons else UNKNOWN),
            "warnings": warnings,
        }

        meta = MappingProxyType({
            "version": VERSION,
            "action_reason": why,
            "health_reason": health.get("why"),
            "trail_reason": trailing.get("why"),
            "scale_reason": scaling.get("why"),
            "exit_why": exiting.get("why"),
            "intent_reason": aware["why"],
            "components": health.get("components"),
            "weights": HEALTH_WEIGHTS,
            "missing_producers": MISSING_PRODUCERS,
            "stop_consumed": trailing.get("stop"),
            "entry_version": self._d("version"),
            "entry_state": self._d("state"),
            "context_version": (dict(self.ctx.meta).get("version")
                                if self.ctx is not None else UNKNOWN),
            "context_cycle": (dict(self.ctx.meta).get("cycle")
                              if self.ctx is not None else UNKNOWN),
            "context_coverage": (self.ctx.coverage()
                                 if self.ctx is not None else UNKNOWN),
        })

        return TradeLifecycleDecision(
            **{k: (_freeze(v) if k in ("targets",) else v)
               for k, v in body.items()},
            telegram_payload=self.telegram(body),
            metadata=meta)


def run(decision: Optional[EntryDecision] = None,
        ctx: Optional[TradingContext] = None) -> TradeLifecycleDecision:
    """Convenience: `trade_lifecycle.run(decision, ctx)`."""
    return TradeLifecycle(decision, ctx).run()
