"""Stage 2 — Market Structure Engine (adapter over `_market_structure`).

Answers only one question: "where is the battle happening?" Trend, S/R,
VWAP, volume profile, order blocks, and chart/candle patterns (confirmation
only) combine into a single Price-Location read + a 0-100 Structure Score.

This stage never decides buy/sell and — deliberately — depends on nothing
but Stage 0 (health). Positioning, order flow, and options are later stages
that decide whether the location this engine finds is actually worth
trading; mixing that judgment in here would defeat the separation the spec
calls for.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class MarketStructureEngine(Engine):
    name = "stage02_structure"
    stage = 2
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        ms = state.raw.get("market_structure")
        if not ms:
            return EngineResult.neutral(self.name, "market structure not computed yet",
                                        data_source="session:_market_structure")

        demand_supply = ms.get("demand_supply", "Neutral")
        score = A.clamp_conf(ms.get("structure_score"), 0.0)

        if demand_supply == "Demand":
            bias = Bias.STRONG_BULL if score >= 75 else Bias.BULL
        elif demand_supply == "Supply":
            bias = Bias.STRONG_BEAR if score >= 75 else Bias.BEAR
        else:
            bias = Bias.NEUTRAL

        vp = ms.get("volume_profile") or {}
        ob = ms.get("order_block") or {}
        evidence = [
            f"Trend: {ms.get('trend', '—')} ({'⭐' * ms.get('trend_stars', 0)}"
            f"{'☆' * (5 - ms.get('trend_stars', 0))})",
            f"Location: {ms.get('price_location', '—')}",
        ]
        if ms.get("support"):
            evidence.append(f"Support ₹{ms['support']:.0f}")
        if ms.get("resistance"):
            evidence.append(f"Resistance ₹{ms['resistance']:.0f}")
        if ms.get("vwap_position"):
            evidence.append(f"VWAP: {ms['vwap_position']}")
        if vp.get("state"):
            evidence.append(f"Volume Profile: {vp['side'] or '—'} · {vp['state']}")
        if ob.get("label") and ob["label"] != "None":
            evidence.append(f"Order Block: {ob['label']}")
        if ms.get("chart_pattern"):
            evidence.append(f"Chart pattern: {ms['chart_pattern']}")
        if ms.get("candle_pattern"):
            evidence.append(f"Candlestick: {ms['candle_pattern']}")
        evidence.append(f"Structure Score {score:.0f}% → {ms.get('decision', '—')}")

        risks = []
        if ms.get("decision") == "NO TRADE":
            risks.append("Low structure conviction — not a location worth considering yet")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=score,
            evidence=evidence, risks=risks,
            data={
                "trend": ms.get("trend"), "trend_stars": ms.get("trend_stars"),
                "price_location": ms.get("price_location"),
                "support": ms.get("support"), "resistance": ms.get("resistance"),
                "vwap_position": ms.get("vwap_position"),
                "volume_profile": vp, "order_block": ob,
                "chart_pattern": ms.get("chart_pattern"),
                "candle_pattern": ms.get("candle_pattern"),
                "structure_score": score, "demand_supply": demand_supply,
                "decision": ms.get("decision"),
            },
            provenance=A.prov("mios:market_structure", Tier.DERIVED),
        )
