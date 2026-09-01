"""Stage 22 — VIX / Volatility Environment Engine.

India VIX is the market's fear gauge. It frames RISK, and gives a mild
directional lean for the index:
  • Falling VIX  → risk-on, complacency → mild tailwind for the index (BULL)
  • Rising  VIX  → risk-off, fear building → mild headwind (BEAR)
  • Level: <12 complacent · 12-16 normal · 16-20 elevated · >20 high fear

Environment-tier, low weight — VIX is context, not a trigger. Reads
`raw["vix"]` (value + direction) which the runner forwards from the app's
`vix_history`; honest NEUTRAL when VIX isn't available.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


def _vol_regime(v: float) -> str:
    if v < 12:
        return "Complacent"
    if v < 16:
        return "Normal"
    if v < 20:
        return "Elevated"
    return "High Fear"


class VixEngine(Engine):
    name = "stage22_vix"
    stage = 22
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        vix = state.raw.get("vix") or {}
        val = vix.get("value")
        if not isinstance(val, (int, float)) or val <= 0:
            return EngineResult.neutral(
                self.name, "India VIX not available yet",
                data_source="session:vix_history")
        direction = str(vix.get("direction", "Unknown") or "Unknown")
        regime = _vol_regime(float(val))

        # directional lean: falling VIX = risk-on = mild bull; rising = risk-off
        if direction == "Falling":
            bias = Bias.BULL
        elif direction == "Rising":
            bias = Bias.BEAR
        else:
            bias = Bias.NEUTRAL
        # conviction: stronger when VIX is elevated/high AND moving (fear moves
        # the index more when vol is already high)
        base = 45.0
        if regime in ("Elevated", "High Fear") and direction in ("Rising", "Falling"):
            base = 62.0
        conf = base if bias != Bias.NEUTRAL else 25.0

        evidence = [f"India VIX {val:.2f} ({regime}) · {direction}"]
        risks, opps = [], []
        if regime == "High Fear":
            risks.append(f"VIX {val:.1f} — high fear: expect wide ranges, sharp "
                         "reversals; size down, widen stops")
        elif regime == "Complacent":
            risks.append(f"VIX {val:.1f} — complacency: a shock can expand vol fast")
        if direction == "Rising":
            risks.append("VIX rising — risk-off building; index rallies are suspect")
        elif direction == "Falling":
            opps.append("VIX falling — risk-on; dips tend to get bought")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=conf, evidence=evidence, risks=risks, opportunities=opps,
            data={"vix": round(float(val), 2), "direction": direction,
                  "vol_regime": regime},
            provenance=A.prov("mios:vix", Tier.DERIVED),
        )
