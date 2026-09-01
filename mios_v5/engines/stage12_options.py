"""Stage 12 — Option Chain Engine (PCR, walls, ATM bias, ΔOI positioning)."""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class OptionChainEngine(Engine):
    name = "stage12_options"
    stage = 12
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        m = A.mp(state.raw)
        opt = state.raw.get("option_data") or {}
        atm = m.get("atm_bias") or {}
        doi = m.get("doi_bias") or {}
        floor = m.get("oi_floor")
        ceil = m.get("oi_ceiling")
        pcr = opt.get("pcr") if isinstance(opt, dict) else None
        if not (atm or doi or opt):
            return EngineResult.neutral(self.name, "option chain not loaded yet",
                                        data_source="session:_cached_option_data")
        # bias from ΔOI positioning (PE writing = support/bullish, CE = capping)
        bias = A.to_bias(doi.get("label")) if doi else A.to_bias(atm.get("verdict"))
        conf = A.clamp_conf(abs(float(atm.get("score", 0) or 0)) * 12) if atm else 40.0

        evidence = []
        if pcr is not None:
            evidence.append(f"PCR {pcr:.2f} "
                            f"({opt.get('pcr_bias', '') if isinstance(opt, dict) else ''})")
        if atm:
            evidence.append(f"ATM {atm.get('verdict', '—')} @ ₹{atm.get('strike', 0):.0f} "
                            f"(score {atm.get('score', 0):+.0f})")
        if doi:
            evidence.append(f"ΔOI(ATM±2): {doi.get('label', '—')}")
        if ceil:
            evidence.append(f"CE wall ₹{ceil[0]:.0f} ({ceil[1]:.1f}L)")
        if floor:
            evidence.append(f"PE wall ₹{floor[0]:.0f} ({floor[1]:.1f}L)")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence,
            data={"pcr": pcr, "atm_bias": atm, "doi_bias": doi,
                  "ce_wall": ceil, "pe_wall": floor},
            provenance=A.prov("dhan:optionchain", Tier.DERIVED),
        )
