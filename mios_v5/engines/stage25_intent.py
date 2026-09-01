"""Stage 25 — Institutional Intent Engine (smart-money direction).

Consumes the dealer, options, institutional and order-flow engine results
from MarketState (fusion pre-cursor) plus the market read's overall label.
This is the first *fusion* engine — it reads other engines, not just caches.
"""

from __future__ import annotations

from ..core.contract import (
    Bias, Engine, EngineResult, MarketState, Status, Tier,
)
from . import _adapters as A

_BIAS_SIGN = {
    Bias.STRONG_BULL: 2, Bias.BULL: 1, Bias.NEUTRAL: 0, Bias.NONE: 0,
    Bias.SIDEWAYS: 0, Bias.BEAR: -1, Bias.STRONG_BEAR: -2,
}


class IntentEngine(Engine):
    name = "stage25_intent"
    stage = 25
    deps = ["stage11_dealer", "stage12_options",
            "stage13_institutional", "stage14_orderflow"]

    def compute(self, state: MarketState) -> EngineResult:
        f = A.fmr(state.raw)
        # weighted vote across the institutional engines (priority ladder
        # from the spec: dealer > intent-inputs > order-flow > options)
        weights = {"stage11_dealer": 2.0, "stage13_institutional": 2.0,
                   "stage14_orderflow": 1.5, "stage12_options": 1.0}
        num = den = 0.0
        contributors = []
        for eng, w in weights.items():
            r = state.get(eng)
            if r is None or not r.ok:
                continue
            sign = _BIAS_SIGN.get(r.bias, 0)
            num += w * sign * (r.confidence / 100.0)
            den += w
            if sign:
                contributors.append(f"{eng.split('_', 1)[1]}={r.bias.value}")
        if den == 0 and not f:
            return EngineResult.neutral(self.name, "no institutional engines reporting yet")
        score = (num / den) if den else 0.0          # -1..+1 approx
        if score >= 0.5:
            bias, label = Bias.STRONG_BULL, "Accumulation / smart-money long"
        elif score >= 0.15:
            bias, label = Bias.BULL, "Net accumulation"
        elif score <= -0.5:
            bias, label = Bias.STRONG_BEAR, "Distribution / smart-money short"
        elif score <= -0.15:
            bias, label = Bias.BEAR, "Net distribution"
        else:
            bias, label = Bias.NEUTRAL, "Mixed / no clear intent"
        conf = A.clamp_conf(min(abs(score) * 100, 100))
        # fold in the scoring engine's own institution score if present
        if f.get("institution_score") is not None:
            conf = round((conf + A.clamp_conf(f.get("institution_score"))) / 2, 1)
        evidence = [f"Institutional intent: {label} (score {score:+.2f})"]
        if contributors:
            evidence.append("agree: " + " · ".join(contributors))
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence,
            data={"score": round(score, 3), "label": label,
                  "contributors": contributors},
            provenance=A.prov("mios:fusion(institutional)", Tier.DERIVED),
        )
