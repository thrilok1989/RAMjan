"""The Liquidity Context — computed once per cycle, read by every stage.

The specification's own runtime rule:

> *Compute liquidity once per refresh. Expose a centralized Liquidity Context
> object. Every stage reads from this object. Do not recompute inside
> individual stages.*

That is `TradingContext` (Stage 71.95) applied to liquidity, and it is built the
same way for the same reasons: a field is not a value, it is a `Field` carrying
`value`, `owner`, `stage` and the **literal dotted path** it was read from.
Principle 12 — nothing may influence a trading decision unless the trader can
inspect that exact value somewhere.

## Three charts, one object

The specification asks for profiles on NIFTY, on the premium, and on the option
chain. `docs/AUDIT_LIQUIDITY_INTELLIGENCE.md` found that the **premium chart is
already fully covered by Stage 71.8**, and the option chain by six values that
exist and get collapsed into a glyph. So this object does not rebuild either —
it carries all three, reading 71.8 for the premium and the chain fields from
where they already live.

## Why the profiles are arguments and not computed here

`calculate_money_flow_profile` is a Python loop over every bar × every bin, and
`compute_dynamic_poc` runs a histogram per bar. At a 20-second refresh those
cannot run once per stage — which is exactly what this object prevents — but
they also must not run inside a *context builder*, because a context that
computes is a context whose cost nobody can see. The caller builds the profiles
once, and hands them in finished.

## Immutable, and honest about what is missing

Deep-frozen, reusing Stage 71.95's `_freeze`. An absent producer yields
`UNKNOWN`, never `0` — a zero on a liquidity reading looks like a measurement.
`missing()` names what did not report and `coverage()` says how much of the
object this cycle filled.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field as _dc_field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from .liquidity import CONSUMED as _LIQ_CONSUMED
from .liquidity import analyse as _analyse
from .trading_context import UNKNOWN, Field, _freeze, _get, _thaw

VERSION = "74.0.0"

ADVISORY_ONLY = True

#: The three charts this context carries, in the order every panel prints them.
CHARTS: Tuple[str, ...] = ("index", "premium", "chain")

#: What each group reads, and from which root. The shape mirrors
#: `trading_context.SPEC`: name → (owner, stage, root, dotted path).
#:
#: `liq` is this cycle's `liquidity.analyse()` for the index; `premium` is Stage
#: 71.8's structure; `chain` is the option-chain block. Nothing is computed on
#: the way through — a value that is not on one of those roots is UNKNOWN.
SPEC: Dict[str, Dict[str, Tuple[str, str, str, str]]] = {
    # ── the index chart ──
    "index": {
        "poc": ("Dynamic POC", "74", "liq", "poc_migration.poc"),
        "poc_previous": ("Dynamic POC", "74", "liq", "poc_migration.previous"),
        "poc_trend": ("Liquidity Intelligence", "74", "liq",
                      "poc_migration.trend"),
        "poc_velocity": ("Liquidity Intelligence", "74", "liq",
                         "poc_migration.velocity"),
        "poc_stability": ("Liquidity Intelligence", "74", "liq",
                          "poc_migration.stability"),
        # Direction and magnitude are separate facts, and the second one is
        # judged against this instrument's OWN recent movement rather than a
        # constant — so the same reading works on a quiet Tuesday and on expiry.
        "poc_regime": ("Liquidity Intelligence", "74", "liq",
                       "poc_regime.regime"),
        "value_area_high": ("Money Flow Profile", "74", "liq",
                            "value_area.high"),
        "value_area_low": ("Money Flow Profile", "74", "liq",
                           "value_area.low"),
        "shift": ("Liquidity Intelligence", "74", "liq",
                  "liquidity_shift.shift"),
        "imbalance": ("Liquidity Intelligence", "74", "liq",
                      "liquidity_imbalance.pct"),
        "dominance": ("Liquidity Intelligence", "74", "liq",
                      "liquidity_imbalance.dominance"),
        "net_sentiment": ("Liquidity Intelligence", "74", "liq",
                          "net_sentiment.score"),
        "sentiment_shift": ("Liquidity Intelligence", "74", "liq",
                            "sentiment_shift.sentiment_shift"),
        "divergence": ("Liquidity Intelligence", "74", "liq",
                       "money_flow_divergence.divergence"),
        "high_nodes": ("Money Flow Profile", "74", "liq", "nodes.high"),
        "low_nodes": ("Money Flow Profile", "74", "liq", "nodes.low"),
    },
    # ── clustered levels: the audit's highest-value item ──
    "levels": {
        "support": ("Liquidity Intelligence", "74", "liq", "levels.support"),
        "resistance": ("Liquidity Intelligence", "74", "liq",
                       "levels.resistance"),
        "major_support": ("Liquidity Intelligence", "74", "liq",
                          "levels.major_support"),
        "major_resistance": ("Liquidity Intelligence", "74", "liq",
                             "levels.major_resistance"),
        "clusters": ("Liquidity Intelligence", "74", "liq", "levels.clusters"),
        # The tolerance is volatility-adaptive, so a consumer comparing two
        # cycles' clusters needs to know whether the band moved underneath it.
        "tolerance_pct": ("Liquidity Intelligence", "74", "liq",
                          "levels.tolerance_pct"),
        # The frozen contract version every `Level` was written against.
        "schema": ("Liquidity Intelligence", "74", "liq", "levels.schema"),
    },
    # ── the premium chart · ALL of this is Stage 71.8, none of it is new ──
    "premium": {
        "poc": ("Premium Structure", "71.8", "premium", "{side}.vp_poc"),
        "support": ("Premium Structure", "71.8", "premium", "{side}.support"),
        "resistance": ("Premium Structure", "71.8", "premium",
                       "{side}.resistance"),
        "high_nodes": ("Premium Structure", "71.8", "premium", "{side}.hvn"),
        "low_nodes": ("Premium Structure", "71.8", "premium", "{side}.lvn"),
        "acceptance": ("Premium Structure", "71.8", "premium",
                       "{side}.acceptance"),
        "rejection": ("Premium Structure", "71.8", "premium",
                      "{side}.rejection"),
        "money_flow": ("Premium Structure", "71.8", "premium", "{side}.cvd"),
    },
    # ── the option chain · six values that already exist ──
    "chain": {
        "oi_wall": ("Option Chain", "03", "chain", "oi_wall"),
        "chgoi_wall": ("Option Chain", "03", "chain", "chgoi_wall"),
        "gamma_flip": ("Dealer Positioning", "11", "chain", "gamma_flip_level"),
        "dealer_bias": ("Dealer Positioning", "11", "chain", "dealer_bias"),
        "support_wall": ("Option Chain", "03", "chain", "support_strength"),
        "resistance_wall": ("Option Chain", "03", "chain",
                            "resistance_strength"),
    },
}

#: Which `build()` argument each root names, for the message when one is absent.
ROOTS: Tuple[str, ...] = ("liq", "premium", "chain")

SIDES: Tuple[str, str] = ("CALL", "PUT")


def _side_map(root: Any, path: str) -> Any:
    """A `{side}` path expanded to one read per CALL/PUT.

    `UNKNOWN` when neither side reported, rather than a dict of two `UNKNOWN`s —
    a field that is present but empty reads as measured.
    """
    out = {}
    for side in SIDES:
        got = _get(root, path.replace("{side}", side))
        if got is not UNKNOWN and got != UNKNOWN:
            out[side] = got
    return out or UNKNOWN


@dataclass(frozen=True)
class LiquidityContext:
    """One cycle's liquidity picture, immutable, every value owned.

    Read by name — `ctx.get("index.poc").value` — or through the helpers. A
    consumer cannot alter what it was handed, so two stages reading the same
    context in one cycle cannot see different numbers.
    """
    index: Mapping[str, Field]
    levels: Mapping[str, Field]
    premium: Mapping[str, Field]
    chain: Mapping[str, Field]
    meta: Mapping[str, Any]
    advisory_only: bool = ADVISORY_ONLY

    GROUPS: Tuple[str, ...] = _dc_field(
        default=("index", "levels", "premium", "chain"), repr=False)

    # ── access ────────────────────────────────────────────────────────
    def group(self, name: str) -> Mapping[str, Field]:
        return getattr(self, name, MappingProxyType({}))

    def get(self, dotted: str) -> Field:
        """`ctx.get("index.poc")`. Always a `Field`, never a `KeyError`."""
        grp, _, fld = str(dotted).partition(".")
        got = self.group(grp).get(fld)
        if isinstance(got, Field):
            return got
        return Field(UNKNOWN, UNKNOWN, UNKNOWN, dotted,
                     note="no such field in this liquidity context")

    def value(self, dotted: str, default: Any = UNKNOWN) -> Any:
        f = self.get(dotted)
        return f.value if f.known else default

    def known(self, dotted: str) -> bool:
        return self.get(dotted).known

    # ── inspection · Principle 12 ─────────────────────────────────────
    def owners(self) -> Tuple[Dict[str, Any], ...]:
        rows = []
        for grp in self.GROUPS:
            for name, f in self.group(grp).items():
                rows.append({"field": f"{grp}.{name}", "owner": f.owner,
                             "stage": f.stage, "source": f.source,
                             "known": f.known})
        return tuple(rows)

    def missing(self) -> Tuple[str, ...]:
        return tuple(r["field"] for r in self.owners() if not r["known"])

    def coverage(self) -> Dict[str, Any]:
        rows = self.owners()
        known = sum(1 for r in rows if r["known"])
        return {"known": known, "total": len(rows),
                "pct": (round(100.0 * known / len(rows)) if rows else 0)}

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"meta": _thaw(self.meta),
                               "advisory_only": self.advisory_only,
                               "coverage": self.coverage()}
        for grp in self.GROUPS:
            out[grp] = {n: f.to_dict() for n, f in self.group(grp).items()}
        return out


def build(profile: Any = None, vpfr: Any = None,
          dynamic_poc: Any = None, vob: Any = None, pools: Any = None,
          dealer: Any = None, spot: Any = None, price_change: Any = None,
          previous: Any = None, premium: Any = None, chain: Any = None,
          atr: Any = None, strike_gap: Any = None,
          cycle: Optional[int] = None, premium_lag: int = 0,
          timestamp: Optional[float] = None) -> LiquidityContext:
    """Assemble one cycle's liquidity context. Never raises.

    `profile`      — `calculate_money_flow_profile(...)` for the index
    `vpfr`         — `compute_vpfr(...)`, the one POC owner
    `dynamic_poc`  — `compute_dynamic_poc(...)`'s series
    `vob`          — `analyze_vob_volume(...)` zones
    `pools`        — `_detect_liquidity_pools(...)`
    `dealer`       — Stage 11's levels
    `previous`     — the last cycle's `profile`, for the shift reads
    `premium`      — `{"CALL": premium_structure.analyse(…), "PUT": …}`
    `chain`        — the option-chain liquidity block

    Every argument is a **finished output**. The engine runs once, here, and
    every consumer reads the result — which is the specification's runtime rule
    and the reason this object exists at all.
    """
    liq = _analyse(profile=profile, vpfr=vpfr, dynamic_poc=dynamic_poc,
                   vob=vob, pools=pools, dealer=dealer, spot=spot,
                   price_change=price_change, previous=previous,
                   atr=atr, strike_gap=strike_gap)

    roots: Dict[str, Any] = {"liq": liq, "premium": premium, "chain": chain}

    groups: Dict[str, Mapping[str, Field]] = {}
    for grp, fields in SPEC.items():
        built: Dict[str, Field] = {}
        for name, (owner, stage, root, path) in fields.items():
            src = roots.get(root)
            raw = (_side_map(src, path) if "{side}" in path
                   else _get(src, path))
            built[name] = Field(value=_freeze(raw),
                                owner=f"Stage {stage} — {owner}",
                                stage=stage, source=f"{root}.{path}")
        groups[grp] = MappingProxyType(built)

    meta = MappingProxyType({
        "timestamp": float(timestamp if timestamp is not None else _time.time()),
        "cycle": cycle,
        "version": VERSION,
        "roots_supplied": tuple(r for r in ROOTS if roots.get(r) is not None),
        "roots_missing": tuple(r for r in ROOTS if roots.get(r) is None),
        "fields": sum(len(f) for f in groups.values()),
        # How many render passes behind the premium group is. The app builds
        # this context before Dashboard V6 writes the premium structures, so
        # that group is one pass old — recorded rather than hidden, because a
        # stale value a reader believes is live is worse than a missing one.
        "premium_lag": int(premium_lag),
        "engine": _freeze({"ready": liq.get("ready"),
                           "computed_here": liq.get("computed_here"),
                           "consumed": dict(_LIQ_CONSUMED)}),
        # The engine's whole output, carried as **provenance, not contract**.
        #
        # Consumers read fields — `ctx.value("index.poc")` — because those are
        # what `SPEC` guarantees. This is here for the two callers that
        # legitimately need more than the contract exposes: the telemetry, which
        # histograms every cluster rather than the handful the fields carry, and
        # the panel, which draws per-bin rows.
        #
        # Carrying it costs nothing — the engine already ran, and running it a
        # second time to get the same answer is exactly what this object exists
        # to prevent.
        "engine_output": _freeze(liq),
    })

    return LiquidityContext(index=groups["index"], levels=groups["levels"],
                            premium=groups["premium"], chain=groups["chain"],
                            meta=meta)


def spec_rows() -> Tuple[Dict[str, str], ...]:
    """The ownership table without a context — for docs, and for the test that
    asserts no two fields read the same path."""
    rows = []
    for grp, fields in SPEC.items():
        for name, (owner, stage, root, path) in fields.items():
            rows.append({"field": f"{grp}.{name}", "owner": owner,
                         "stage": stage, "source": f"{root}.{path}"})
    return tuple(rows)
