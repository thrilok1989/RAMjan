"""Stage 27 — Conflict Engine.

Resolve conflicting signals across the directional engines using the spec's
priority ladder, and report *how much* they disagree. A clean bias with all
engines aligned is high-confidence; a bias where the top-priority engines
fight each other is flagged HIGH conflict so the trader knows to wait.

Priority (spec):
    Dealer > Institutional Intent > Order Flow > Liquidity > Structure >
    Options > Global > Patterns
(engines not yet built are simply absent from the vote.)
"""

from __future__ import annotations

from typing import List, Tuple

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

# engine name → priority weight (higher = more authoritative)
# Ladder (spec): Dealer > Intent > Order Flow > Liquidity > Structure >
# Options > Patterns > Global > Flows/VIX/News.
_PRIORITY = {
    "stage11_dealer": 8.0,
    "stage25_intent": 7.0,
    "stage14_orderflow": 6.0,
    "stage17_liquidity": 5.0,     # pools + walls (now wired — was a gap)
    "stage05_regime": 4.0,        # structure/regime proxy
    "stage12_options": 3.0,
    "stage31_probability": 3.0,
    "stage26_patterns": 2.5,      # context-aligned patterns
    "stage19_global": 2.0,
    "stage23_flows": 1.5,         # FII/DII (EOD context)
    "stage22_vix": 1.5,           # volatility environment
    "stage18_sector": 1.5,        # sector rotation (slow, delayed context; self-gates)
    "stage21_news": 1.0,
}


class ConflictEngine(Engine):
    name = "stage27_conflict"
    stage = 27
    deps = ["stage11_dealer", "stage25_intent", "stage14_orderflow",
            "stage17_liquidity", "stage05_regime", "stage12_options",
            "stage31_probability", "stage26_patterns", "stage19_global",
            "stage23_flows", "stage22_vix", "stage18_sector"]

    def compute(self, state: MarketState) -> EngineResult:
        bull_w = bear_w = total_w = 0.0
        votes: List[Tuple[str, Bias, float, int]] = []   # name, bias, weight, sign
        for eng, w in _PRIORITY.items():
            r = state.get(eng)
            if r is None or not r.ok:
                continue
            sign = A.bias_sign(r.bias)
            if sign == 0:
                continue
            eff = w * (r.confidence / 100.0 if r.confidence else 0.5)
            votes.append((eng.split("_", 1)[1], r.bias, eff, sign))
            total_w += eff
            if sign > 0:
                bull_w += eff
            else:
                bear_w += eff

        if not votes or total_w == 0:
            return EngineResult.neutral(self.name,
                                        "no directional engines reporting yet")

        net = bull_w - bear_w
        dominant = A.bias_from_net(net / max(total_w, 1e-9) * 5)  # scale to grade
        # conflict severity = fraction of weight opposing the dominant side
        opposing = bear_w if net >= 0 else bull_w
        opp_ratio = opposing / total_w
        if opp_ratio < 0.15:
            severity, sev_em = "LOW", "🟢"
        elif opp_ratio < 0.35:
            severity, sev_em = "MEDIUM", "🟡"
        else:
            severity, sev_em = "HIGH", "🔴"
        agreement = round((1 - opp_ratio) * 100)

        # name the sharpest conflicts (highest-priority opposing pairs)
        winners = [v for v in votes if (v[3] > 0) == (net >= 0)]
        losers = [v for v in votes if (v[3] > 0) != (net >= 0)]
        conflict_pairs = []
        for lw in sorted(losers, key=lambda v: -v[2])[:3]:
            conflict_pairs.append(f"{lw[0]} {lw[1].value}")

        evidence = [
            f"Dominant {dominant.value} · agreement {agreement}% · "
            f"{sev_em} {severity} conflict",
        ]
        if conflict_pairs:
            _side = "bull" if net >= 0 else "bear"
            evidence.append(f"Against the {_side} read: " + " · ".join(conflict_pairs))
        risks = []
        if severity == "HIGH":
            risks.append("High signal conflict — top engines disagree; "
                         "wait for alignment before acting")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=dominant,
            confidence=float(agreement), evidence=evidence, risks=risks,
            data={"dominant": dominant.value, "severity": severity,
                  "agreement_pct": agreement,
                  "bull_weight": round(bull_w, 2), "bear_weight": round(bear_w, 2),
                  "conflicts": conflict_pairs,
                  "votes": [(v[0], v[1].value, round(v[2], 2)) for v in votes]},
            provenance=A.prov("mios:fusion(conflict)", Tier.DERIVED),
        )
