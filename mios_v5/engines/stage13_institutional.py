"""Stage 13 — Institutional Position Engine (CALL/PUT modes → smart-money bias).

Adapter over `_full_market_read`: the per-side positioning modes (Long
Build-up / Writing / Short Covering / Long Unwinding) and the institution
score already computed by the scoring engine.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class InstitutionalEngine(Engine):
    name = "stage13_institutional"
    stage = 13
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        f = A.fmr(state.raw)
        if not f or f.get("call_mode") is None:
            return EngineResult.neutral(self.name, "CALL/PUT scoring warming up",
                                        data_source="session:_full_market_read")
        bias = A.to_bias(f.get("institution_bias") or f.get("market_kind"))
        conf = A.clamp_conf(f.get("institution_score"), 0)
        evidence = [
            f"CALL {f.get('call_mode')} (Str {f.get('call_strength')}%)",
            f"PUT {f.get('put_mode')} (Str {f.get('put_strength')}%)",
            f"Institution score {f.get('institution_score', 0)} "
            f"({f.get('institution_bias', '—')})",
        ]
        risks = []
        if f.get("gamma_blast") == "HIGH":
            risks.append("Gamma-blast risk HIGH — outsized move possible")
        opportunities = []
        if (f.get("short_squeeze") or 0) >= 50:
            opportunities.append(f"Short-squeeze setup ({f.get('short_squeeze')}%)")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence, risks=risks, opportunities=opportunities,
            data={"call_mode": f.get("call_mode"), "put_mode": f.get("put_mode"),
                  "call_strength": f.get("call_strength"),
                  "put_strength": f.get("put_strength"),
                  "institution_score": f.get("institution_score"),
                  "institution_bias": f.get("institution_bias")},
            provenance=A.prov("mios:full_market_read", Tier.DERIVED),
        )
