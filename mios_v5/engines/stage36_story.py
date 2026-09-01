"""Stage 36 — Market Story Engine.

Converts the assembled read into a plain-language story (and the one-page
briefing). Runs late so it sees the full pipeline. bias mirrors the final
read's preferred bias for convenience; the value is the narrative text.
"""

from __future__ import annotations

from ..core.contract import Engine, EngineResult, MarketState, Status, Tier
from ..final_read import build_final_read
from ..narrative import build_briefing, build_market_story
from . import _adapters as A


class StoryEngine(Engine):
    name = "stage36_story"
    stage = 36
    deps = ["stage35_reaction_zone", "stage27_conflict", "stage25_intent",
            "stage11_dealer", "stage14_orderflow"]

    def compute(self, state: MarketState) -> EngineResult:
        fr = build_final_read(state)
        story = build_market_story(state, fr)
        briefing = build_briefing(state, fr)
        bias = A.to_bias(fr.get("preferred_bias"))
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=float(fr.get("confidence_tempered", 0)),
            evidence=[story],
            data={"story": story, "briefing": briefing,
                  "preferred_bias": fr.get("preferred_bias")},
            provenance=A.prov("mios:narrative", Tier.DERIVED),
        )
