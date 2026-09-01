"""Stage 15 — Microstructure Engine (DISABLED: data-limit by design).

True microstructure (iceberg detection, spoofing, DOM/Level-2 imbalance,
tick tape) requires full order-book depth + tick data that retail Dhan does
NOT provide. Per spec Rule 3 this engine is structurally DISABLED and logs a
DATA_LIMIT at severity INFO — it never lights the Error Monitor red.

It still surfaces the one microstructure proxy that IS available — the
top-of-book bid/ask imbalance the app computes (`_market_picture.oflow_imb`)
— as Tier-3 (spoofable, resting-quote) context, explicitly non-voting.
"""

from __future__ import annotations

from ..core.contract import (
    Bias, Engine, EngineResult, ErrorType, MarketState, Provenance, Severity,
    Status, Tier,
)
from . import _adapters as A


class MicrostructureEngine(Engine):
    name = "stage15_microstructure"
    stage = 15
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        res = EngineResult.disabled(
            self.name,
            "Level-2 depth / tick tape unavailable at retail Dhan — "
            "iceberg/spoofing/DOM cannot be computed",
            data_source="dhan:marketdepth")
        # attach the available Tier-3 proxy as context (non-voting)
        imb = A.mp(state.raw).get("oflow_imb")
        if imb:
            res.data["top_of_book_imbalance"] = imb
            res.evidence.append(
                f"(context, Tier-3) Order-book: {imb.get('label', '—')} "
                f"CE {imb.get('call_net', 0):+,.0f} / PE {imb.get('put_net', 0):+,.0f} "
                "— resting quotes, spoofable, non-voting")
            res.provenance = Provenance(
                source="dhan:top_of_book", tier=Tier.RESTING,
                notes="single-level bid/ask only; not true depth")
        return res
