"""Stage 43 — Institutional Absorption 🏛 (WHY it is happening).

    Stage 42  →  what happened at the level? (accepted / rejected / trap)
    Stage 50  →  what is price trying to do? (building / absorbing / exhausted)
    Stage 43  →  WHO is doing it and WHY

It interprets institutional participation; it does not detect more order flow.
Six behaviours: passive buying · passive selling · aggressive buying ·
aggressive selling · reloading · exhaustion.

The classification that earns its place is passive vs aggressive, and it is
counter-intuitive: heavy aggressive SELLING into flat price is bullish — an
institution is quietly absorbing that supply. A retail read sees heavy selling;
the institutional read sees a buyer being filled.

It does NOT detect icebergs or hidden orders — that needs L2 depth this feed
doesn't carry, and inferring them would be fabrication. Same discipline that
renamed this engine from "Hidden Liquidity".

Non-directional (Bias.NONE): it explains the footprint, it doesn't vote. The
flow it interprets already votes through Stage 53's order-flow family.
"""

from __future__ import annotations

from typing import Any, Dict

from ..absorption import classify, story, trace_push
from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class AbsorptionEngine(Engine):
    name = "stage43_absorption"
    stage = 43
    deps = ["stage42_acceptance", "stage50_ltp_behaviour", "stage11_dealer"]

    def compute(self, state: MarketState) -> EngineResult:
        def _d(name: str) -> Dict[str, Any]:
            r = state.get(name)
            return (r.data or {}) if r is not None and r.ok else {}

        ltp = _d("stage50_ltp_behaviour")
        if not ltp.get("ready"):
            return EngineResult.neutral(
                self.name, "LTP behaviour warming up — nothing to interpret yet")
        reaction = _d("stage42_acceptance").get("active") or {}

        trace = state.raw.get("absorption_trace") or []
        prev = trace[-1] if trace else None
        # duration = consecutive cycles of the SAME behaviour
        dur = 0
        for b in reversed(trace):
            if b == prev:
                dur += 1
            else:
                break

        r = classify(ltp=ltp, reaction=reaction, trace=trace,
                     duration_cycles=(dur if prev else 0))
        # re-count duration against the behaviour we just decided
        dur_now = dur if r["behaviour"] == prev else 0
        if dur_now != r["duration_cycles"]:
            r = classify(ltp=ltp, reaction=reaction, trace=trace,
                         duration_cycles=dur_now)

        zone = None
        if reaction.get("side") and reaction.get("price"):
            zone = f"{str(reaction['side']).title()} ₹{reaction['price']:,.0f}"
        thesis = story(r, zone_label=zone)

        evidence = [f"{r['label']} · {r['confidence']}% {r['stars']}"]
        evidence.extend(r["reasons"][:3])
        evidence.append(f"Expected: {r['expectation']}")

        risks = []
        if r["behaviour"] == "PASSIVE_SELLING":
            risks.append("Demand being absorbed — rallies are being sold into")
        elif r["behaviour"] == "PASSIVE_BUYING":
            risks.append("Supply being absorbed — dips are being bought")
        elif r["behaviour"].endswith("EXHAUSTION"):
            risks.append("The move is out of fuel, not being overwhelmed — "
                         "reversal risk rising")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(r["confidence"]), evidence=evidence, risks=risks,
            data={**r, "thesis": thesis,
                  "trace": trace_push(trace, r["behaviour"])},
            provenance=A.prov("mios:absorption", Tier.DERIVED))
