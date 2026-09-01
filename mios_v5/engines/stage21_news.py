"""Stage 21 — News Engine (keyword sentiment over NIFTY/SENSEX headlines)."""

from __future__ import annotations

from ..core.contract import Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class NewsEngine(Engine):
    name = "stage21_news"
    stage = 21
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        nb = A.mp(state.raw).get("news_bias") or {}
        if not nb:
            return EngineResult.neutral(self.name, "news bias not computed yet",
                                        data_source="session:_market_picture")
        bias = A.to_bias(nb.get("label"))
        net = int(nb.get("net", 0) or 0)
        n = int(nb.get("n", 0) or 0)
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=A.clamp_conf(min(abs(net) * 15, 100)),
            evidence=[f"News {nb.get('em', '')} {nb.get('label', '—')} "
                      f"(net {net:+d} over {n} headlines)"],
            data={"label": nb.get("label"), "net": net, "n": n},
            # headline keyword sentiment = stated/external, low trust tier
            provenance=A.prov("googlenews:rss", Tier.RESTING,
                              notes="keyword sentiment, not price action"),
        )
