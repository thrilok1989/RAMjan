"""A simple entry system — five rules, all of which must hold.

Stage 72 scores eleven weighted components and produces a number. This does
not. It is a **plain AND-gate** over facts the cycle already published, and it
exists because a rule you can hold in your head is a rule you can trust at
09:20 when the tape is moving.

    BUY CALL when   spot is AT support
                    and support is more likely to bounce than break
                    and V5 or V6 is bullish
                    and CALL has the energy
                    and the CALL premium is building at its own support

    BUY PUT  when   spot is AT resistance
                    and resistance is more likely to bounce than break
                    and V5 or V6 is bearish
                    and PUT has the energy
                    and the PUT premium is building at its own support

Every rule reports pass or fail by name, so a signal that did not fire tells
you which condition missed — the thing a score can never do.

## ⚠️ "Building" means the same word on both legs

Every leg engine in MIOS reports **in the leg's own direction**: a PUT premium
rising as NIFTY falls is that premium moving UP off ITS OWN support. So the
behaviour that confirms a buy is `Support Building` for **both** sides, never
`Resistance Building` for the put. Reading the spot direction into the leg's
label is the mistake this note exists to prevent.

## It computes nothing

Spot, the levels, the odds, the biases, the energies and the behaviours all
arrive from `_mios_market_read()`. This module compares them. An input that did
not report fails its rule rather than being assumed — a missing energy is not
zero energy, and neither is a reason to trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

UNKNOWN = "UNKNOWN"

VERSION = "SE.1"

ADVISORY_ONLY = True

CALL, PUT, NONE = "CALL", "PUT", "NONE"

#: How close spot must be to a level to count as "at" it, in index points.
#: A level is a zone, not a line — but 25 points either side of a NIFTY level
#: is the width at which "price is at support" stops being a description and
#: starts being a hope.
NEAR_POINTS = 25.0

#: The minimum energy the side being bought must carry. Below this the premium
#: is not being traded enough to express the thesis, whatever the level says.
MIN_ENERGY = 55.0

#: …and it must lead the other side. Two premiums with equal energy is not a
#: directional read, it is a market that has not decided.
ENERGY_LEAD = 10.0

#: The leg behaviours that confirm a BUY on that leg. Both are the premium
#: strengthening at its own level — see the docstring note on leg direction.
GOOD_BEHAVIOUR = ("Support Building", "Resistance Fading")

#: Trap above this is reported as a warning. It does NOT block: the rules the
#: owner asked for do not include it, and silently adding a sixth gate would
#: make a signal fail for a reason nobody asked for. It is loud instead.
WARN_TRAP = 40.0


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    return str(v or "").strip().upper()


@dataclass(frozen=True)
class SimpleSignal:
    """The verdict, and every rule that produced it.

    `rules` is ordered and complete — it lists the failures too, so a message
    can say *why not* as easily as *why*.
    """
    side: str
    fired: bool
    level: Any
    level_kind: str
    rules: Tuple[Tuple[str, bool, str], ...]
    warnings: Tuple[str, ...]
    why: str
    version: str = VERSION
    advisory_only: bool = ADVISORY_ONLY

    @property
    def passed(self) -> Tuple[str, ...]:
        return tuple(name for name, ok, _ in self.rules if ok)

    @property
    def failed(self) -> Tuple[str, ...]:
        return tuple(name for name, ok, _ in self.rules if not ok)

    def to_dict(self) -> Dict[str, Any]:
        return {"side": self.side, "fired": self.fired, "level": self.level,
                "level_kind": self.level_kind, "why": self.why,
                "rules": [{"rule": n, "ok": ok, "detail": d}
                          for n, ok, d in self.rules],
                "warnings": list(self.warnings), "version": self.version}


def _bias_agrees(market: Mapping[str, Any], want: str) -> Tuple[bool, str]:
    """V5 **or** V6 — the owner asked for either, not both.

    Requiring both would make the two-engine disagreement a veto, and the whole
    point of publishing them side by side is that a disagreement is information
    rather than a stop sign.
    """
    v5, v6 = _txt(market.get("v5")), _txt(market.get("v6"))
    hits = [name for name, val in (("V5", v5), ("V6", v6)) if want in val]
    if hits:
        return True, f"{' and '.join(hits)} {want.lower()}"
    seen = " · ".join(x for x in (f"V5 {v5}" if v5 else "",
                                  f"V6 {v6}" if v6 else "") if x)
    return False, f"neither engine is {want.lower()}" + (f" ({seen})" if seen else "")


def evaluate(market: Optional[Mapping[str, Any]] = None) -> SimpleSignal:
    """Run both sides; return the one that fired, or a NONE with its reasons."""
    m = dict(market or {})
    spot = _f(m.get("spot"))

    best: Optional[SimpleSignal] = None
    for side, key, want in ((CALL, "support", "BULL"),
                            (PUT, "resistance", "BEAR")):
        zone = m.get(key) or {}
        leg = m.get(side.lower()) or {}
        if not isinstance(zone, Mapping) or not isinstance(leg, Mapping):
            zone, leg = {}, {}

        price = _f(zone.get("price"))
        bounce, brk = _f(zone.get("bounce")), _f(zone.get("break"))
        energy = _f(leg.get("energy"))
        other = _f((m.get(PUT.lower() if side == CALL else CALL.lower())
                    or {}).get("energy"))
        behaviour = str(leg.get("behaviour") or "").strip()

        rules = []

        # 1 · spot is AT the level
        dist = abs(spot - price) if (spot is not None and price is not None) else None
        rules.append((
            f"spot at {key}", dist is not None and dist <= NEAR_POINTS,
            f"{dist:.0f} pts away" if dist is not None
            else "spot or level not reported"))

        # 2 · the level is more likely to hold than to give
        rules.append((
            "bounce beats break",
            bounce is not None and brk is not None and bounce > brk,
            f"bounce {bounce:.0f}% vs break {brk:.0f}%"
            if bounce is not None and brk is not None else "odds not reported"))

        # 3 · a bias agrees
        ok_bias, why_bias = _bias_agrees(m, want)
        rules.append(("bias aligned", ok_bias, why_bias))

        # 4 · the side being bought carries the energy, and leads
        leads = (energy is not None and other is not None
                 and energy - other >= ENERGY_LEAD)
        rules.append((
            f"{side} energy", energy is not None and energy >= MIN_ENERGY
            and leads,
            f"{energy:.0f} vs {other:.0f}" if energy is not None
            and other is not None else "energy not reported"))

        # 5 · the premium is building at its own level
        rules.append((
            f"{side} premium building", behaviour in GOOD_BEHAVIOUR,
            behaviour or "behaviour not reported"))

        warnings = []
        trap = _f(zone.get("trap"))
        if trap is not None and trap >= WARN_TRAP:
            warnings.append(f"trap {trap:.0f}% at this {key} — a move through "
                            f"may be a liquidity grab")

        fired = all(ok for _, ok, _ in rules)
        why = (f"all five rules hold at {key} {price:,.0f}" if fired
               else "; ".join(f"{n} — {d}" for n, ok, d in rules if not ok))
        sig = SimpleSignal(side=side, fired=fired, level=price,
                           level_kind=key, rules=tuple(rules),
                           warnings=tuple(warnings), why=why)
        if fired:
            return sig
        # Keep the side that got furthest, so a near-miss is explainable.
        if best is None or len(sig.passed) > len(best.passed):
            best = sig

    if best is None:
        return SimpleSignal(side=NONE, fired=False, level=UNKNOWN,
                            level_kind=UNKNOWN, rules=(), warnings=(),
                            why="no market read supplied")
    return SimpleSignal(side=NONE, fired=False, level=best.level,
                        level_kind=best.level_kind, rules=best.rules,
                        warnings=best.warnings,
                        why=f"closest was {best.side}: {best.why}")


def run(market: Optional[Mapping[str, Any]] = None) -> SimpleSignal:
    """Never raises — a rule engine that throws is worse than one that waits."""
    try:
        return evaluate(market)
    except Exception as err:
        return SimpleSignal(side=NONE, fired=False, level=UNKNOWN,
                            level_kind=UNKNOWN, rules=(), warnings=(),
                            why=f"could not evaluate: {err}")
