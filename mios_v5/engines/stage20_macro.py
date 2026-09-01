"""Stage 20 — Commodity & Macro Engine (risk-on/off pressure on NIFTY)."""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class MacroEngine(Engine):
    name = "stage20_macro"
    stage = 20
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        cb = A.mp(state.raw).get("commodity_bias") or {}
        if not cb:
            return EngineResult.neutral(self.name, "macro regime not computed yet",
                                        data_source="session:_market_picture")
        regime = str(cb.get("regime", ""))
        if "Risk-On" in regime:
            bias = Bias.BULL
        elif "Risk-Off" in regime:
            bias = Bias.BEAR
        else:
            bias = Bias.NEUTRAL
        risks = ["Risk-Off macro regime" if "Risk-Off" in regime else ""]
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=50.0 if bias != Bias.NEUTRAL else 0.0,
            evidence=[f"Commodity/macro regime: {regime or '—'}"],
            risks=[r for r in risks if r],
            data={"regime": regime},
            provenance=A.prov("mios:commodity_macro", Tier.DERIVED),
        )
