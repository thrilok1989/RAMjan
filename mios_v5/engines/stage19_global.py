"""Stage 19 — Global Engine (global indices influence on NIFTY)."""

from __future__ import annotations

from ..core.contract import Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class GlobalEngine(Engine):
    name = "stage19_global"
    stage = 19
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        gb = A.mp(state.raw).get("global_bias") or {}
        if not gb:
            return EngineResult.neutral(self.name, "global bias not computed yet",
                                        data_source="session:_market_picture")
        bias = A.to_bias(gb.get("label"))
        score = float(gb.get("score", 0) or 0)
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=A.clamp_conf(min(abs(score) * 20, 100)),
            evidence=[f"Global {gb.get('label', '—')} ({score:+.1f})"],
            data={"label": gb.get("label"), "score": score},
            provenance=A.prov("mios:global_indices", Tier.DERIVED),
        )
