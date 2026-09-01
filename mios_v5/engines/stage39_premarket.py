"""Stage 39 — Pre-Market Update Engine.

Before 9:15 IST, assemble a pre-market brief from the overnight/global/macro/
news engines. Outside the pre-open window it stays idle (OK, bias NONE, note)
so it never clutters the live dashboard.
"""

from __future__ import annotations

from datetime import datetime, time as dtime

from ..core.contract import (
    Bias, Engine, EngineResult, IST, MarketState, Status, Tier,
)
from . import _adapters as A


class PreMarketEngine(Engine):
    name = "stage39_premarket"
    stage = 39
    deps = ["stage19_global", "stage20_macro", "stage21_news"]

    def compute(self, state: MarketState) -> EngineResult:
        now = datetime.now(IST).time()
        inj = state.raw.get("now_ist_time")
        if isinstance(inj, dtime):
            now = inj
        if now >= dtime(9, 15):
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE,
                confidence=0.0, evidence=["Outside pre-market window"],
                data={"active": False},
                provenance=A.prov("mios:premarket", Tier.DERIVED))

        parts, lean = [], 0
        for name, label in (("stage19_global", "Global"),
                            ("stage20_macro", "Macro"),
                            ("stage21_news", "News")):
            r = state.get(name)
            if r and r.ok and r.bias != Bias.NONE:
                parts.append(f"{label} {r.bias.value}")
                lean += A.bias_sign(r.bias)
        bias = (Bias.BULL if lean > 0 else Bias.BEAR if lean < 0 else Bias.NEUTRAL)
        brief = ("Pre-market: " + " · ".join(parts)) if parts else \
            "Pre-market: awaiting overnight reads"
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=float(min(abs(lean) * 25, 100)),
            evidence=[brief],
            data={"active": True, "brief": brief, "lean": lean},
            provenance=A.prov("mios:premarket", Tier.DERIVED),
        )
