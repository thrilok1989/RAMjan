"""Stage 37 — Market Energy ⚡ (promoted, not rebuilt).

The physics already lived in Stage 4's context blob as three loose numbers
(energy / compression / breakout_risk). Stage 48 and Stage 51 need it as a
standardized engine output, so this PROMOTES that existing calculation to a
first-class engine rather than adding a second one that could disagree with it.
Stage 4 remains the owner of the gamma/pin maths; nothing is recomputed here.

Exposes: state (DEAD/COMPRESSION/BUILDING/EXPANSION/RELEASED) · strength ·
compression · expansion readiness · breakout risk · release probability ·
duration · confidence.

Non-directional (Bias.NONE): energy says how much is stored and how close it is
to releasing — never which way. Direction is every other engine's job.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..energy import advise, classify
from . import _adapters as A


class MarketEnergyEngine(Engine):
    name = "stage37_energy"
    stage = 37
    deps = ["stage04_context"]

    def compute(self, state: MarketState) -> EngineResult:
        ctx = state.get("stage04_context")
        cd = (ctx.data if ctx is not None and ctx.ok and ctx.data else {}) or {}
        if cd.get("energy") is None:
            return EngineResult.neutral(
                self.name, "energy not computed yet (Stage 4 warming up)",
                data_source="engine:stage04_context")

        mem: Dict[str, Any] = state.raw.get("energy_memory") or {}
        prev_state = mem.get("state")
        prev_comp = mem.get("compression")
        dur = int(mem.get("duration_cycles") or 0)

        r = classify(cd.get("energy"), cd.get("compression"),
                     cd.get("breakout_risk"),
                     prev_state=prev_state, prev_compression=prev_comp,
                     duration_cycles=dur)
        # duration counts cycles in the SAME state — it resets on a transition
        r["duration_cycles"] = (dur + 1) if r["state"] == prev_state else 0
        if r["state"] != prev_state:
            r = classify(cd.get("energy"), cd.get("compression"),
                         cd.get("breakout_risk"), prev_state=prev_state,
                         prev_compression=prev_comp, duration_cycles=0)

        evidence = [r["label"],
                    f"Strength {r['strength']}% {r['stars']} · compression "
                    f"{r['compression']}% · breakout risk {r['risk_label']}",
                    f"Expansion readiness {r['expansion_readiness']}% · "
                    f"release probability {r['release_probability']}%",
                    advise(r)]
        risks = []
        if r["state"] == "DEAD":
            risks.append("Energy dead — breakout entries will fail here")
        elif r["state"] == "COMPRESSION" and r["release_probability"] >= 70:
            risks.append(f"Coil at {r['release_probability']}% release "
                         "probability — a fast directional move is close")
        elif r["state"] == "EXPANSION":
            risks.append("Expansion underway — do not fade it")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(r["confidence"]), evidence=evidence, risks=risks,
            data={**r, "advice": advise(r)},
            provenance=A.prov("mios:energy(promoted from stage04)", Tier.DERIVED))
