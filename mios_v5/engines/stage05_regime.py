"""Stage 5 — Market Regime Engine (adapter over `_market_picture`)."""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class RegimeEngine(Engine):
    name = "stage05_regime"
    stage = 5
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        m = A.mp(state.raw)
        if not m or "regime" not in m:
            return EngineResult.neutral(self.name, "market picture not computed yet",
                                        data_source="session:_market_picture")
        regime = m.get("regime")            # UP | DOWN | SIDEWAYS
        p_up = float(m.get("p_up", 0) or 0)
        p_dn = float(m.get("p_down", 0) or 0)
        p_sd = float(m.get("p_side", 0) or 0)
        bias = A.to_bias(regime)
        # graded: strong if the winning probability dominates
        top = max(p_up, p_dn, p_sd)
        if regime == "UP" and p_up >= 60:
            bias = Bias.STRONG_BULL
        elif regime == "DOWN" and p_dn >= 60:
            bias = Bias.STRONG_BEAR
        evidence = [f"Regime {regime} (↑{p_up:.0f}% ↓{p_dn:.0f}% ↔{p_sd:.0f}%)"]
        evidence += [str(r) for r in (m.get("reasons") or [])[:4]]
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=A.clamp_conf(top), evidence=evidence,
            data={"regime": regime, "p_up": p_up, "p_down": p_dn,
                  "p_side": p_sd, "playbook": m.get("playbook")},
            provenance=A.prov("mios:market_picture", Tier.DERIVED),
        )
