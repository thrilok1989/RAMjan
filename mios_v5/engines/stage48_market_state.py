"""Stage 48 — Market State 🎭 (one personality, not twenty indicators).

Consumes five finished engines and resolves ONE primary market state, plus what
it is most likely to become next:

    Stage 42 Acceptance · Stage 44 Flow Shift · Stage 47 Bias Transition ·
    Stage 50 LTP Behaviour · Stage 37 Market Energy
                              ↓
        MARKDOWN 84%   →  next: REVERSAL BUILDING 71%

It calculates NOTHING. Compression/expansion/release probability are Stage 37's;
bias decay is Stage 47's; traps are Stage 42's. Every probability it reports is
sourced from the engine that owns it. Two engines computing the same quantity
would eventually disagree, and the louder one would win by accident.

Non-directional (Bias.NONE): the state carries a tone for display, but direction
is arbitrated by Stage 27/53. A state engine that voted would be double-counting
the five engines it summarises.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..market_personality import derive
from . import _adapters as A


class MarketStateEngine(Engine):
    name = "stage48_market_state"
    stage = 48
    deps = ["stage37_energy", "stage42_acceptance", "stage44_flow_shift",
            "stage47_transition", "stage50_ltp_behaviour"]

    def compute(self, state: MarketState) -> EngineResult:
        def _d(name: str) -> Dict[str, Any]:
            r = state.get(name)
            return (r.data or {}) if r is not None and r.ok else {}

        energy = _d("stage37_energy")
        accept = _d("stage42_acceptance").get("active") or {}
        flow = _d("stage44_flow_shift")
        trans = _d("stage47_transition")
        ltp = _d("stage50_ltp_behaviour")

        conflict = state.get("stage27_conflict")
        bias = (conflict.bias.value if conflict is not None and conflict.ok
                else trans.get("bias"))

        d = derive(bias=bias, transition=trans, ltp=ltp, acceptance=accept,
                   flow=flow, energy=energy)
        if not d.get("inputs_seen"):
            return EngineResult.neutral(self.name, "no engine reads available yet")

        evidence = [f"{d['label']} · {d['confidence']}%"]
        evidence.extend(d["reasons"][:4])
        if d.get("next_state"):
            evidence.append(f"Next likely: {d['next_label']} "
                            f"{d['next_probability']}%")

        risks = []
        if d["state"] == "TRAP_ACTIVE":
            risks.append("Trap active — the obvious direction is the wrong one")
        elif d["state"] == "COMPRESSION":
            risks.append("Coiling — do not pre-position; wait for the release")
        elif d["state"] == "WAR_ZONE":
            risks.append("Both sides committed — no edge until one gives way")
        elif d["state"] == "REVERSAL_BUILDING":
            risks.append("Reversal building — trend-following setups are "
                         "becoming lower quality")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(d["confidence"]), evidence=evidence, risks=risks,
            data=d, provenance=A.prov("mios:market_state", Tier.DERIVED))
