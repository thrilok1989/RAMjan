"""Stage 71.95 — the Unified Trading Context.

One immutable object carrying every analysis result a trading decision needs, so
that **Stage 72 reads one thing instead of thirty**.

Not an engine. Not in `ALL_ENGINES`. No Streamlit, no session_state, no network,
no state of its own. It calculates nothing, infers nothing, averages nothing and
mutates nothing — every value is *transported* from the stage that owns it.

## Why this exists

Without it, Stage 72 would read `final_read`, the Opportunity Matrix, Stage
71.7, Stage 71.8, Premium Structure and a dozen `sections.*` nodes directly.
That produces duplicated reads, versions that drift within one cycle, ordering
dependencies nobody wrote down, and a decision whose inputs cannot be listed.

```
Market  →  TradingContext  →  Stage 72  →  Trade Manager  →  Telegram
```

## Every field names its owner ⚠️ BINDING

Principle 12: *nothing may influence a trading decision unless the trader can
inspect that exact value somewhere in the UI.* A value with no owner cannot be
inspected, because nobody knows where to look.

So a field is not a value here — it is a `Field`, carrying `value`, `owner`,
`stage` and the **literal dotted path** it was read from. The path is not
documentation: `_get()` reads it, so a source that goes stale produces `UNKNOWN`
rather than a wrong number, and `owners()` can print the whole table.

## One fact, one owner

Two fields may read the same *object* for different facts — `market.stability`
and `risk.shock` are both Stage 44 — but **no two fields may read the same
path**. That would give one fact two names, and two names drift.

Where the spec asks for a field that *is* another field's value,
`ALIAS` records the pointer instead of copying it. `risk.recovery` is the
example: `RECOVERY` is one of the four values `market.stability` takes, so
reading it separately would be the duplication this module exists to end.

## Immutable after creation

Deep-frozen: mappings become `MappingProxyType`, sequences become tuples, all
the way down. A consumer cannot alter the context it was handed, so two stages
reading the same context in one cycle cannot see different values.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field as _dc_field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

VERSION = "71.95.2"

#: The value of a field whose owner did not report. Never `None`, never `0` —
#: a zero looks like a measurement.
UNKNOWN = "UNKNOWN"

ADVISORY_ONLY = True


@dataclass(frozen=True)
class Field:
    """One value and the provenance that makes it inspectable.

    `source` is the live dotted path, not a comment: it is what `_get` read.
    """
    value: Any = UNKNOWN
    owner: str = UNKNOWN
    stage: str = UNKNOWN
    source: str = UNKNOWN
    note: str = ""

    @property
    def known(self) -> bool:
        return self.value is not UNKNOWN and self.value != UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {"value": _thaw(self.value), "owner": self.owner,
                "stage": self.stage, "source": self.source,
                "known": self.known, **({"note": self.note} if self.note else {})}


# ══════════════════════════════════════════════════════════════════════
#  the ownership table — the whole contract, in one place
# ══════════════════════════════════════════════════════════════════════

#: `(group, field) → (owner, stage, root, path)`.
#:
#: `root` names which argument of `build()` the value comes from; `path` is
#: read literally. `path` may index a sequence (`reasons.0`) and may name a
#: per-side read with `{side}`, which expands to one entry per CALL/PUT.
SPEC: Dict[str, Dict[str, Tuple[str, str, str, str]]] = {
    "market": {
        "market_state": ("Market State", "48", "fr", "market_state.state"),
        "market_phase": ("Regime", "05", "fr", "regime"),
        "day_type": ("Market Day Classification", "68", "fr",
                     "day_classification.day_type"),
        "session": ("Session Intelligence", "69", "fr", "session_intel.window"),
        "trend": ("Conflict Engine — the arbitrated read", "27", "fr",
                  "preferred_bias"),
        "transition": ("Bias Transition", "47", "fr", "transition.state"),
        "stability": ("Sudden Flow Shift + Stability", "44", "fr", "stability"),
        # ── added for Stage 72 (see docs/AUDIT_STAGE_72_ENTRY_ENGINE.md §2) ──
        # The Entry Engine may read nothing but this context, so a phase whose
        # inputs are absent here cannot be built at all. Each of these has one
        # real owner and one real path; carrying them across the bridge is what
        # the bridge is for.
        "acceptance": ("Acceptance / Rejection / Trap", "42", "fr",
                       "reaction.state"),
        "reaction_level": ("Acceptance / Rejection / Trap", "42", "fr",
                           "reaction_level"),
        "session_conviction": ("Time Cycle", "06", "fr",
                               "session_conviction"),
    },
    "opportunity": {
        "best_horizon": ("Trade Opportunity Matrix", "71", "matrix", "best"),
        "best_side": ("Trade Opportunity Matrix", "71", "matrix",
                      "best_trade.side"),
        "opportunity_score": ("Trade Opportunity Matrix", "71", "matrix",
                              "best_trade.score"),
        "confidence": ("Trade Opportunity Matrix", "71", "matrix",
                       "best_trade.confidence"),
        "top_reason": ("Trade Opportunity Matrix", "71", "matrix",
                       "best_trade.reasons.0"),
        "timing": ("Opportunity Intelligence", "71.5", "matrix",
                   "best_trade.intel.timing.timing"),
        "entry_type": ("Opportunity Intelligence", "71.5", "matrix",
                       "best_trade.intel.type"),
        "trade_quality": ("Opportunity Intelligence", "71.5", "matrix",
                          "best_trade.intel.quality.grade"),
        # Named apart from `risk.risk` on purpose: Stage 4 owns the TAPE's
        # breakout risk, Stage 71.5 owns THIS HORIZON's trade risk. One word,
        # two facts, so they cannot share a name.
        "trade_risk": ("Opportunity Intelligence", "71.5", "matrix",
                       "best_trade.intel.risk.level"),
        "lifetime": ("Opportunity Intelligence", "71.5", "matrix",
                     "best_trade.intel.lifetime.label"),
    },
    "premium": {
        "selected_call": ("Strike Validation", "71.8", "validation",
                          "selected.CALL"),
        "selected_put": ("Strike Validation", "71.8", "validation",
                         "selected.PUT"),
        "preferred_premium": ("Premium Energy & Spike", "71.7", "premium",
                              "preferred.preferred"),
        "premium_structure": ("Premium Structure", "71.8", "structure",
                              "{side}"),
        "premium_score": ("Premium Structure", "71.8", "structure",
                          "{side}.structure_score"),
        "premium_confidence": ("Premium Structure", "71.8", "structure",
                               "{side}.confidence"),
        # Added for Stage 73 (docs/AUDIT_STAGE_73_LIFECYCLE.md §3). The blob is
        # one field and a specific fact inside it is another, on a distinct
        # path — the precedent `premium_score` already set. Stage 73 needs the
        # live premium by name to report Target Hit and Stop Hit.
        "premium_ltp": ("Premium Structure", "71.8", "structure",
                        "{side}.ltp"),
        # ── added for Stage 71.85 (docs/AUDIT_STAGE_71_85_PREMIUM_BEHAVIOUR.md)
        # Transport only. Four of these read Stage 71.85, which computes them;
        # the other six read the stage that already owned the fact, because
        # 71.85 transporting a number it did not measure would give that number
        # a second owner — the one thing this module exists to prevent.
        "behaviour": ("Premium LTP Behaviour", "71.85", "behaviour",
                      "{side}.behaviour"),
        "behaviour_strength": ("Premium LTP Behaviour", "71.85", "behaviour",
                               "{side}.strength"),
        "behaviour_confidence": ("Premium LTP Behaviour", "71.85", "behaviour",
                                 "{side}.confidence"),
        "momentum": ("Premium LTP Behaviour", "71.85", "behaviour",
                     "{side}.momentum"),
        "top_reason": ("Premium LTP Behaviour", "71.85", "behaviour",
                       "{side}.top_reasons.0.label"),
        "break_probability": ("Premium Structure", "71.8", "structure",
                              "{side}.break_probability"),
        "fakeout_probability": ("Premium Structure", "71.8", "structure",
                                "{side}.fakeout_probability"),
        # The premium's OWN acceptance against its OWN value area. Named apart
        # from `market.acceptance`, which is Stage 42's read on NIFTY: a CALL
        # can be accepted above its value area while NIFTY is rejecting, and a
        # trader holding that CALL needs the first one.
        "acceptance": ("Premium LTP Behaviour", "71.85", "behaviour",
                       "{side}.acceptance"),
        "structure_state": ("Premium Structure", "71.8", "structure",
                            "{side}.levels.state"),
        "structure_strength": ("Strike Validation", "71.8", "validation",
                               "sides.{side}.checks.premium_sr_strength"),
    },
    "strike": {
        "selected_strike": ("Strike Validation", "71.8", "validation",
                            "bridge.selected_strike"),
        "validation": ("Strike Validation", "71.8", "validation",
                       "bridge.premium_validation"),
        "liquidity": ("Strike Validation", "71.8", "validation",
                      "bridge.premium_liquidity"),
        "agreement": ("Strike Validation", "71.8", "validation",
                      "bridge.most_traded_agreement"),
    },
    "energy": {
        "energy": ("Premium Energy & Spike", "71.7", "premium",
                   "bridge.energy_score"),
        "dominance": ("Premium Energy & Spike", "71.7", "premium", "dominance"),
        "rotation": ("Premium Energy & Spike", "71.7", "premium",
                     "bridge.rotation"),
        "shift": ("Premium Energy & Spike", "71.7", "premium",
                  "bridge.energy_shift"),
        "energy_acceleration": ("Premium Energy & Spike", "71.7", "premium",
                                "bridge.energy_acceleration"),
        "spike_probability": ("Premium Energy & Spike", "71.7", "premium",
                              "bridge.spike_probability"),
    },
    "htf": {
        "htf_bias": ("Higher-Timeframe VPFR", "45", "fr",
                     "htf_alignment.bias"),
        "migration": ("Higher-Timeframe VPFR", "45", "fr", "value_migration"),
        "alignment": ("Higher-Timeframe VPFR", "45", "fr",
                      "htf_alignment.score"),
        "structure": ("Higher-Timeframe VPFR", "45", "fr", "htf.structure"),
    },
    "risk": {
        "risk": ("Market Context — breakout risk", "04", "fr", "breakout_risk"),
        "validity": ("Signal Validity Filter", "51", "fr", "validity.verdict"),
        "freeze": ("Sudden Flow Shift + Stability", "44", "fr",
                   "flow_shift.freeze_entries"),
        "shock": ("Sudden Flow Shift + Stability", "44", "fr",
                  "flow_shift.detected"),
        "next_target": ("Reaction Zone", "35", "fr", "next_target"),
        "invalidation": ("Reaction Zone", "35", "fr", "invalidation"),
    },
}

#: Fields the spec asks for that **are a value of another field**. Recorded as a
#: pointer so the consumer can find the fact, without a second owner claiming it.
ALIAS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "risk": {
        "recovery": ("risk.stability_word → market.stability",
                     "RECOVERY is one of the four values Stage 44's stability "
                     "takes (STABLE · UNSTABLE · SHOCK · RECOVERY). Reading it "
                     "separately would give one fact two owners"),
    },
}

#: Which `build()` argument each root names, for the error message when one is
#: missing — a context built without the matrix should say so, not read empty.
ROOTS: Tuple[str, ...] = ("fr", "matrix", "premium", "validation", "structure",
                          "behaviour")

#: The two option sides, in the order every panel prints them.
SIDES: Tuple[str, str] = ("CALL", "PUT")


# ══════════════════════════════════════════════════════════════════════
#  reading and freezing
# ══════════════════════════════════════════════════════════════════════

def _get(root: Any, path: str) -> Any:
    """Read a dotted path, or `UNKNOWN`.

    Supports mapping keys and integer sequence indices (`reasons.0`). Never
    raises and never returns `None` for a missing key — `None` is a value some
    engines publish deliberately, and it must not be confused with absence.
    """
    cur = root
    if cur is None:
        return UNKNOWN
    for part in str(path).split("."):
        if isinstance(cur, Mapping):
            if part not in cur:
                return UNKNOWN
            cur = cur[part]
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return UNKNOWN
        else:
            return UNKNOWN
        if cur is None:
            return UNKNOWN
    return cur


def _freeze(v: Any) -> Any:
    """Deep-freeze. Mappings become read-only, sequences become tuples.

    Shallow immutability would be a promise the object cannot keep: a frozen
    dataclass holding a plain dict lets a consumer edit the context another
    consumer is about to read.
    """
    if isinstance(v, Mapping):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, set):
        return frozenset(_freeze(x) for x in v)
    return v


def _thaw(v: Any) -> Any:
    """The inverse, for serialisation. `MappingProxyType` is not JSON-safe."""
    if isinstance(v, Mapping):
        return {k: _thaw(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_thaw(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(_thaw(x) for x in v)
    return v


# ══════════════════════════════════════════════════════════════════════
#  the context
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TradingContext:
    """One cycle's analysis, immutable, every value owned.

    Consumers read groups by name (`ctx.market["stability"].value`) or use the
    helpers below. Nothing here can be written to.
    """
    market: Mapping[str, Field]
    opportunity: Mapping[str, Field]
    premium: Mapping[str, Field]
    strike: Mapping[str, Field]
    energy: Mapping[str, Field]
    htf: Mapping[str, Field]
    risk: Mapping[str, Field]
    meta: Mapping[str, Any]
    advisory_only: bool = ADVISORY_ONLY

    #: group order, fixed so serialisation and the owners table are stable
    GROUPS: Tuple[str, ...] = _dc_field(
        default=("market", "opportunity", "premium", "strike", "energy",
                 "htf", "risk"), repr=False)

    # ── access ────────────────────────────────────────────────────────
    def group(self, name: str) -> Mapping[str, Field]:
        return getattr(self, name, MappingProxyType({}))

    def get(self, dotted: str) -> Field:
        """`ctx.get("risk.freeze")`. Always a `Field`, never a `KeyError`.

        An unknown name returns an `UNKNOWN` field naming itself, so a consumer
        that asks for something that does not exist gets a value it can print
        rather than an exception three frames away.
        """
        grp, _, fld = str(dotted).partition(".")
        got = self.group(grp).get(fld)
        if isinstance(got, Field):
            return got
        return Field(UNKNOWN, UNKNOWN, UNKNOWN, dotted,
                     note="no such field in this context")

    def value(self, dotted: str, default: Any = UNKNOWN) -> Any:
        f = self.get(dotted)
        return f.value if f.known else default

    def known(self, dotted: str) -> bool:
        return self.get(dotted).known

    # ── inspection · Principle 12 ─────────────────────────────────────
    def owners(self) -> Tuple[Dict[str, Any], ...]:
        """Every field with its owner, stage and source — the table a panel
        prints so a trader can check any value that reached a decision."""
        rows = []
        for grp in self.GROUPS:
            for name, f in self.group(grp).items():
                rows.append({"field": f"{grp}.{name}", "owner": f.owner,
                             "stage": f.stage, "source": f.source,
                             "known": f.known,
                             **({"note": f.note} if f.note else {})})
        return tuple(rows)

    def missing(self) -> Tuple[str, ...]:
        """Fields whose owner did not report this cycle."""
        return tuple(r["field"] for r in self.owners() if not r["known"])

    def coverage(self) -> Dict[str, Any]:
        rows = self.owners()
        known = sum(1 for r in rows if r["known"])
        return {"known": known, "total": len(rows),
                "pct": (round(100.0 * known / len(rows)) if rows else 0)}

    # ── serialisation ─────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe, including provenance. What gets logged."""
        out: Dict[str, Any] = {"meta": _thaw(self.meta),
                               "advisory_only": self.advisory_only,
                               "coverage": self.coverage()}
        for grp in self.GROUPS:
            out[grp] = {n: f.to_dict() for n, f in self.group(grp).items()}
        return out

    def values_only(self) -> Dict[str, Any]:
        """The same shape without provenance — for a consumer that has already
        checked ownership and wants the numbers."""
        return {grp: {n: _thaw(f.value) for n, f in self.group(grp).items()}
                for grp in self.GROUPS}


def _side_map(root: Any, path: str) -> Any:
    """A `{side}` path, expanded to one read per CALL/PUT.

    Returns `UNKNOWN` when neither side reported, rather than a dict of two
    `UNKNOWN`s — a field that is present but empty reads as measured.
    """
    out = {}
    for side in SIDES:
        got = _get(root, path.replace("{side}", side))
        if got is not UNKNOWN and got != UNKNOWN:
            out[side] = got
    return out or UNKNOWN


def build(fr: Optional[Mapping[str, Any]] = None,
          matrix: Optional[Mapping[str, Any]] = None,
          premium: Optional[Mapping[str, Any]] = None,
          validation: Optional[Mapping[str, Any]] = None,
          structure: Optional[Mapping[str, Any]] = None,
          behaviour: Optional[Mapping[str, Any]] = None,
          cycle: Optional[int] = None,
          timestamp: Optional[float] = None) -> TradingContext:
    """Assemble one cycle's context. Always returns a context, never raises.

    `fr`         — `final_read`, the V5/V6 stage payload
    `matrix`     — Stage 71, enriched by 71.5
    `premium`    — Stage 71.7
    `validation` — Stage 71.8
    `structure`  — `{"CALL": premium_structure.analyse(…), "PUT": …}`
    `behaviour`  — Stage 71.85, `premium_behaviour.build(…)`

    Every argument is a **finished output**. Nothing is fetched, nothing is
    computed, and an absent argument yields `UNKNOWN` fields rather than an
    error — a degraded cycle should produce a thin context a consumer can see
    through, not an exception in the middle of a render.
    """
    roots: Dict[str, Any] = {
        "fr": fr, "matrix": matrix, "premium": premium,
        "validation": validation, "structure": structure,
        "behaviour": behaviour,
    }

    groups: Dict[str, Mapping[str, Field]] = {}
    for grp, fields in SPEC.items():
        built: Dict[str, Field] = {}
        for name, (owner, stage, root, path) in fields.items():
            src = roots.get(root)
            raw = (_side_map(src, path) if "{side}" in path
                   else _get(src, path))
            built[name] = Field(
                value=_freeze(raw), owner=f"Stage {stage} — {owner}",
                stage=stage, source=f"{root}.{path}")
        for name, (points_at, why) in (ALIAS.get(grp) or {}).items():
            built[name] = Field(value=UNKNOWN, owner="— alias —",
                                stage="—", source=points_at, note=why)
        groups[grp] = MappingProxyType(built)

    meta = MappingProxyType({
        "timestamp": float(timestamp if timestamp is not None else _time.time()),
        "cycle": cycle,
        "version": VERSION,
        "roots_supplied": tuple(r for r in ROOTS if roots.get(r) is not None),
        "roots_missing": tuple(r for r in ROOTS if roots.get(r) is None),
        "fields": sum(len(f) for f in groups.values()),
    })

    return TradingContext(
        market=groups["market"], opportunity=groups["opportunity"],
        premium=groups["premium"], strike=groups["strike"],
        energy=groups["energy"], htf=groups["htf"], risk=groups["risk"],
        meta=meta)


def spec_rows() -> Tuple[Dict[str, str], ...]:
    """The ownership table without a context — for docs and for the test that
    asserts no two fields read the same path."""
    rows = []
    for grp, fields in SPEC.items():
        for name, (owner, stage, root, path) in fields.items():
            rows.append({"field": f"{grp}.{name}", "owner": owner,
                         "stage": stage, "source": f"{root}.{path}"})
    return tuple(rows)
