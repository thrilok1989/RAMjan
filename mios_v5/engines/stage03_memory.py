"""Stage 3 — Market Memory Engine.

Provide historical context for today: previous-day high/low/close and the
prior POC/VAH/VAL when the host app has them. Reads whatever the app already
stashed in raw; returns NEUTRAL context (bias NONE) — it frames, not predicts.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class MemoryEngine(Engine):
    name = "stage03_memory"
    stage = 3
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        mem = state.raw.get("market_memory") or {}
        spot = state.raw.get("spot")
        pdh, pdl = mem.get("prev_high"), mem.get("prev_low")
        pdc = mem.get("prev_close")
        if not any([pdh, pdl, pdc]):
            return EngineResult.neutral(
                self.name, "no previous-session levels available yet",
                data_source="session:market_memory")
        evidence = []
        if pdh:
            evidence.append(f"PDH ₹{pdh:.0f}")
        if pdl:
            evidence.append(f"PDL ₹{pdl:.0f}")
        if pdc and spot:
            gap = (spot - pdc) / pdc * 100
            evidence.append(f"Prev close ₹{pdc:.0f} · spot {gap:+.2f}% vs close")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=0.0,
            evidence=evidence,
            data={"prev_high": pdh, "prev_low": pdl, "prev_close": pdc,
                  "prev_poc": mem.get("prev_poc")},
            provenance=A.prov("mios:market_memory", Tier.DERIVED),
        )
