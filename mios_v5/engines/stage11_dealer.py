"""Stage 11 — Dealer Position Engine (GEX / DEX / Vanna / Charm / IV-skew).

Adapter over the dealer analytics the app already computes into
`_market_picture` (gex_disp, dex_bias, skew_bias, vc_exp) and
`_full_market_read` (dealer_score, dealer_dir).
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class DealerEngine(Engine):
    name = "stage11_dealer"
    stage = 11
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        m = A.mp(state.raw)
        f = A.fmr(state.raw)
        gx = m.get("gex_disp") or {}
        dx = m.get("dex_bias") or {}
        sk = m.get("skew_bias") or {}
        vc = m.get("vc_exp") or {}
        if not (gx or dx or f.get("dealer_score") is not None):
            return EngineResult.neutral(self.name, "dealer analytics not computed yet",
                                        data_source="session:_market_picture")
        dealer_dir = f.get("dealer_dir") or dx.get("bias")
        bias = A.to_bias(dealer_dir)
        conf = A.clamp_conf(f.get("dealer_score"), 0)

        evidence, risks = [], []
        if gx:
            evidence.append(
                f"GEX {gx.get('signal', '—')} · total {gx.get('total', 0):+.0f}L"
                + (f" · flip ₹{gx.get('flip'):.0f} ({gx.get('spot_vs_flip')})"
                   if gx.get("flip") else ""))
            if str(gx.get("signal", "")).lower().startswith(("trend", "breakout")):
                risks.append("Negative gamma — moves can accelerate (dealers chase)")
        if dx:
            evidence.append(f"DEX {dx.get('label', '—')} · net {dx.get('net_dex', 0):+.0f}L")
        if vc:
            evidence.append(f"Vanna {vc.get('net_vanna', 0):+.1f}L · "
                            f"Charm {vc.get('net_charm', 0):+.1f}L/day")
        if sk:
            evidence.append(f"IV skew {sk.get('em', '')} {sk.get('label', '')} "
                            f"(ratio {sk.get('ratio', '—')})")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence, risks=risks,
            data={"gex": gx, "dex": dx, "skew": sk, "vanna_charm": vc,
                  "dealer_score": f.get("dealer_score"),
                  "dealer_dir": dealer_dir},
            provenance=A.prov("mios:dealer(GEX/DEX/greeks)", Tier.DERIVED),
        )
