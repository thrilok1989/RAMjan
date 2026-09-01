"""Stage 14 — Order Flow Engine (CVD / absorption → buyer vs seller control).

Adapter over the ATM±1 leg-bias overall (`_leg_bias_cache`) which already
aggregates CVD slope, absorption and delta divergence across the legs.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class OrderFlowEngine(Engine):
    name = "stage14_orderflow"
    stage = 14
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        lo = A.leg_overall(state.raw)
        if not lo:
            return EngineResult.neutral(self.name, "leg order-flow not computed yet",
                                        data_source="session:_leg_bias_cache")
        net = int(round(float(lo.get("net", 0) or 0)))
        bull = lo.get("bull", 0)
        bear = lo.get("bear", 0)
        bias = A.bias_from_net(net)
        conf = A.clamp_conf(min(abs(net) * 12, 100))
        fast = (lo.get("by_speed") or {}).get("fast") or {}
        evidence = [
            f"Leg order-flow {lo.get('label', '—')} "
            f"({bull}↑ / {bear}↓ · net {net:+d})",
        ]
        if fast:
            _fnet = int(round(float(fast.get("net", 0) or 0)))
            evidence.append(f"FAST (live) {fast.get('label', '—')} net {_fnet:+d}")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence,
            data={"net": net, "bull": bull, "bear": bear,
                  "label": lo.get("label"), "fast": fast},
            # CVD is a CLV-weighted estimate from 1m bars, not tick tape → Tier 2
            provenance=A.prov("mios:leg_cvd(1m-estimate)", Tier.DERIVED,
                              notes="CVD estimated from 1m bars, not tick data"),
        )
