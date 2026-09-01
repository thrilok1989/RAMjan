"""Stage 38 — Tomorrow Preparation Engine.

After 15:15 IST, summarise the close: the day's closing bias, the key levels
to carry over, and a gap lean for tomorrow. Idle during the live session.
"""

from __future__ import annotations

from datetime import datetime, time as dtime

from ..core.contract import (
    Bias, Engine, EngineResult, IST, MarketState, Status, Tier,
)
from ..final_read import build_final_read
from . import _adapters as A


class TomorrowEngine(Engine):
    name = "stage38_tomorrow"
    stage = 38
    deps = ["stage35_reaction_zone", "stage27_conflict", "stage05_regime"]

    def compute(self, state: MarketState) -> EngineResult:
        now = datetime.now(IST).time()
        inj = state.raw.get("now_ist_time")
        if isinstance(inj, dtime):
            now = inj
        if now < dtime(15, 15):
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE,
                confidence=0.0, evidence=["Live session — tomorrow prep at close"],
                data={"active": False},
                provenance=A.prov("mios:tomorrow", Tier.DERIVED))

        fr = build_final_read(state)
        bias = A.to_bias(fr.get("preferred_bias"))
        sup = fr.get("strong_support")
        res = fr.get("strong_resistance")
        # crude gap lean: closing bias carries overnight
        gap = ("Gap-up watch" if bias in (Bias.BULL, Bias.STRONG_BULL)
               else "Gap-down watch" if bias in (Bias.BEAR, Bias.STRONG_BEAR)
               else "Flat-open lean")
        parts = [f"Close bias {fr.get('preferred_bias')} · {gap}"]
        if sup:
            parts.append(f"carry support ₹{sup:.0f}")
        if res:
            parts.append(f"carry resistance ₹{res:.0f}")
        report = " · ".join(parts)
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=float(fr.get("confidence_tempered", 0)),
            evidence=[report],
            data={"active": True, "report": report,
                  "tomorrow_support": sup, "tomorrow_resistance": res,
                  "gap_lean": gap},
            provenance=A.prov("mios:tomorrow", Tier.DERIVED),
        )
