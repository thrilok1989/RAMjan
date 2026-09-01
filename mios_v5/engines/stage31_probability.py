"""Stage 31 — Probability Engine (breakout/breakdown/bounce/reject + gamma blast).

Adapter over `_full_market_read` (breakout/breakdown %, gamma_blast,
short_squeeze) — the probability primitives Stage 35 Reaction Zone will
later consume.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class ProbabilityEngine(Engine):
    name = "stage31_probability"
    stage = 31
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        f = A.fmr(state.raw)
        if not f or f.get("breakout") is None:
            return EngineResult.neutral(self.name, "probabilities warming up",
                                        data_source="session:_full_market_read")
        up = int(f.get("breakout", 50) or 50)
        dn = int(f.get("breakdown", 50) or 50)
        bias = Bias.BULL if up >= 58 else (Bias.BEAR if up <= 42 else Bias.NEUTRAL)
        conf = A.clamp_conf(abs(up - 50) * 2)
        evidence = [
            f"Breakout↑ {up}% / Breakdown↓ {dn}%",
            f"Gamma-blast {f.get('gamma_blast', '—')}",
        ]
        if (f.get("short_squeeze") or 0) >= 40:
            evidence.append(f"Short-squeeze {f.get('short_squeeze')}%")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence,
            data={"breakout": up, "breakdown": dn,
                  "gamma_blast": f.get("gamma_blast"),
                  "short_squeeze": f.get("short_squeeze"),
                  "market_label": f.get("market_label")},
            provenance=A.prov("mios:full_market_read", Tier.DERIVED),
        )
