"""Stage 53 — Evidence Correlation 🧠 (the brain).

34 engines are not 34 independent opinions. When price falls, CVD, delta, money
flow, VOB and volume all turn down — one observation seen five ways. Counting
them separately inflates confidence exactly when the market looks most one-sided.

This engine groups every directional result into SEVEN evidence families and
collapses each to a single weighted vote:

    Market Structure · Order Flow · Options · Dealer · Institutions ·
    Liquidity · Macro

Each family reports direction · strength · confidence · agreement · reliability ·
freshness, so the Conflict Engine receives richer, de-duplicated evidence instead
of a long tally. Internal disagreement inside a family degrades its reliability
rather than being averaged into false calm.

It fixes three concrete defects in the 34-engine tally:
  1. four directional engines (institutional, structure, macro, reaction_zone)
     were computed every cycle and never voted at all;
  2. family authority was an accident of member COUNT — Institutions aggregated
     to 10.0 and silently out-ranked Dealer at 8.0, inverting the spec ladder;
  3. stage31_probability voted alongside the very engines it is derived from.

v0 is OBSERVATIONAL: it publishes the family read and logs how its dominant bias
compares to the live Conflict Engine's. It does not replace Stage 27 until the
comparison says it should. Run both, measure, then promote.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..evidence import EXCLUDED, FAMILIES, correlate
from . import _adapters as A

_BIAS = {"STRONG_BULL": Bias.STRONG_BULL, "BULL": Bias.BULL,
         "NEUTRAL": Bias.NEUTRAL, "BEAR": Bias.BEAR,
         "STRONG_BEAR": Bias.STRONG_BEAR}


def _tier_num(r) -> int:
    """Provenance tier as an int (EXECUTED 1 / DERIVED 2 / RESTING 3) so the
    pure layer can rank freshness without importing the contract."""
    try:
        t = getattr(r.provenance, "tier", None)
        return int(getattr(t, "value", t) or 2)
    except Exception:
        return 2


class EvidenceCorrelationEngine(Engine):
    name = "stage53_evidence"
    stage = 53
    # every engine that lands in a family — so this runs after they do
    deps = sorted({e for members in FAMILIES.values() for e in members})

    def compute(self, state: MarketState) -> EngineResult:
        results: Dict[str, Dict[str, Any]] = {}
        for eng in self.deps:
            r = state.get(eng)
            if r is None:
                continue
            results[eng] = {"bias": getattr(r.bias, "value", None),
                            "confidence": r.confidence, "ok": r.ok,
                            "tier": _tier_num(r)}
        if not results:
            return EngineResult.neutral(self.name, "no family evidence yet")

        corr = correlate(results)
        bias = _BIAS.get(corr["dominant"], Bias.NEUTRAL)

        evidence = [f"{corr['dominant']} · agreement {corr['agreement_pct']}% "
                    f"· {corr['severity']} conflict (7 families, de-duplicated)"]
        for f in corr["order"]:
            if f["status"] != "OK":
                continue
            em = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}[f["direction"]]
            note = "" if f["reliability"] == "HIGH" else f" ({f['reliability'].lower()})"
            evidence.append(f"{em} {f['label']} {f['strength']}%{note}")

        risks = []
        for f in corr["order"]:
            if f["status"] == "OK" and f["reliability"] == "LOW" and f["n"] > 1:
                risks.append(f"{f['label']} internally split "
                             f"({f['agreement']}% agreement) — discount it")
        if corr["severity"] == "HIGH":
            risks.append("Families disagree sharply — wait for alignment")
        if corr["unmapped"]:
            risks.append("Unmapped engines not counted: "
                         + ", ".join(corr["unmapped"][:4]))

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=float(corr["agreement_pct"]),
            evidence=evidence, risks=risks,
            data={**corr, "excluded_n": len(EXCLUDED)},
            provenance=A.prov("mios:fusion(evidence-families)", Tier.DERIVED))
