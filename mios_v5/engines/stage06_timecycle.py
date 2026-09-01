"""Stage 6 — Market Time Cycle Engine.

Understand institutional behaviour through the session. Pure IST-time logic
(no market data), so it always computes. It does not vote a direction —
`bias = NONE` — but it emits a **session conviction** weight (0–100) that
later engines (Reaction Zone, Conflict) use to temper confidence: entries in
the lunch lull are worth less than the opening/closing institutional windows.
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import List, Tuple

from ..core.contract import (
    Bias, Engine, EngineResult, IST, MarketState, Status, Tier,
)
from . import _adapters as A

# (start, end, phase, conviction, behaviours)
_BLOCKS: List[Tuple[dtime, dtime, str, int, List[str]]] = [
    (dtime(0, 0),  dtime(9, 15),  "Pre-Open",                 25,
     ["Gap setup forming", "await opening auction"]),
    (dtime(9, 15), dtime(9, 30),  "Opening / Gap Reaction",   55,
     ["Gap reaction", "opening imbalance", "overnight sentiment unwind"]),
    (dtime(9, 30), dtime(10, 30), "Institutional Entry / ORB", 80,
     ["Institutional entry", "trend confirmation", "opening-range break"]),
    (dtime(10, 30), dtime(12, 0), "Trend / Range Development", 65,
     ["Trend continuation or failure", "range development"]),
    (dtime(12, 0), dtime(13, 30), "Lunch / Low Participation", 35,
     ["Low participation", "fake breakouts likely", "consolidation"]),
    (dtime(13, 30), dtime(14, 30), "Fresh Institutional Orders", 70,
     ["Fresh institutional orders", "position adjustments", "liquidity sweeps"]),
    (dtime(14, 30), dtime(15, 15), "Closing Activity",         60,
     ["Closing activity", "institutional repositioning", "tomorrow prep"]),
    (dtime(15, 15), dtime(15, 30), "Auction Close",            30,
     ["Closing auction", "square-off flows"]),
]


class TimeCycleEngine(Engine):
    name = "stage06_timecycle"
    stage = 6
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        now = datetime.now(IST).time()
        # allow tests to inject a fixed time
        inj = state.raw.get("now_ist_time")
        if isinstance(inj, dtime):
            now = inj
        if now >= dtime(15, 30):
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE,
                confidence=0.0, evidence=["Post-market — session closed"],
                data={"phase": "Post-Market", "conviction": 0,
                      "behaviours": []},
                provenance=A.prov("mios:clock", Tier.DERIVED))
        phase, conviction, behaviours = "Pre-Open", 25, []
        for start, end, ph, conv, beh in _BLOCKS:
            if start <= now < end:
                phase, conviction, behaviours = ph, conv, beh
                break
        note = ("⚠️ low-conviction window — expect fakeouts"
                if conviction <= 35 else
                "🟢 high-conviction institutional window"
                if conviction >= 70 else "")
        evidence = [f"Session phase: {phase} (conviction {conviction}/100)"]
        if behaviours:
            evidence.append("Typical: " + " · ".join(behaviours))
        if note:
            evidence.append(note)
        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(conviction), evidence=evidence,
            data={"phase": phase, "conviction": conviction,
                  "behaviours": behaviours, "time": now.strftime("%H:%M")},
            provenance=A.prov("mios:clock", Tier.DERIVED),
        )
