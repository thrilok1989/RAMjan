"""Stage 23 — Institutional Flows Engine (FII / DII cash).

FII (foreign) and DII (domestic institutions) cash-segment net flows are the
big-money footprint. FIIs are the dominant driver of Indian index direction:
sustained FII buying = structural bid, sustained selling = structural offer.
DIIs often lean the other way (absorbing FII selling), so the *combined* net
is the cleanest read.

IMPORTANT: this is END-OF-DAY data (prior session), so it is a slow, daily
CONTEXT lean — not an intraday trigger. Weighted accordingly (low). Reads
`raw["fii_dii"]` = {"FII": {net,...}, "DII": {...}}; NEUTRAL when absent.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

# ₹ crore net thresholds for a "meaningful" institutional lean
_STRONG = 2500.0
_MILD = 800.0


class FlowsEngine(Engine):
    name = "stage23_flows"
    stage = 23
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        fd = state.raw.get("fii_dii") or {}
        fii = fd.get("FII") or {}
        dii = fd.get("DII") or {}
        fii_net = fii.get("net")
        dii_net = dii.get("net")
        if not isinstance(fii_net, (int, float)) and not isinstance(dii_net, (int, float)):
            return EngineResult.neutral(
                self.name, "FII/DII cash flows not available yet",
                data_source="session:_fii_dii_cash")

        fii_net = float(fii_net or 0.0)
        dii_net = float(dii_net or 0.0)
        combined = fii_net + dii_net
        as_of = fii.get("date") or dii.get("date") or "—"

        # FII is the dominant directional driver; combined confirms
        bias = A.bias_from_net(fii_net, strong=_STRONG, weak=_MILD)
        # if FII and DII disagree strongly, damp conviction (absorption battle)
        conflict = (fii_net > 0) != (dii_net > 0) and abs(dii_net) > 0.5 * abs(fii_net)
        conf = 55.0 if abs(fii_net) >= _STRONG else (40.0 if abs(fii_net) >= _MILD else 20.0)
        if conflict:
            conf *= 0.7

        _f = f"FII {fii_net:+,.0f}cr" if fii_net else "FII flat"
        _d = f"DII {dii_net:+,.0f}cr" if dii_net else "DII flat"
        evidence = [f"{_f} · {_d} · net {combined:+,.0f}cr (as of {as_of}, EOD)"]
        risks, opps = [], []
        if conflict:
            evidence.append("FII vs DII pulling opposite ways — absorption battle, "
                            "flows are not a clean directional edge today")
        elif bias in (Bias.STRONG_BULL, Bias.BULL):
            opps.append(f"FII net buyers ({fii_net:+,.0f}cr) — structural bid "
                        "supports dips (daily context)")
        elif bias in (Bias.STRONG_BEAR, Bias.BEAR):
            risks.append(f"FII net sellers ({fii_net:+,.0f}cr) — structural offer "
                         "caps rallies (daily context)")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=conf, evidence=evidence, risks=risks, opportunities=opps,
            data={"fii_net": round(fii_net, 1), "dii_net": round(dii_net, 1),
                  "combined_net": round(combined, 1), "as_of": as_of,
                  "conflict": conflict},
            provenance=A.prov("mios:fii_dii(EOD)", Tier.DERIVED),
        )
