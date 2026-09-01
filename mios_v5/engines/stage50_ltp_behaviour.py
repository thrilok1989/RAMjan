"""Stage 50 — LTP Behaviour 📖 (what price is TRYING to do).

Every other read describes what happened. This describes intent-in-progress:
not "CVD is −40" but **"sellers building while buyers weaken"**.

Eight dimensions — price · buyers · sellers · calls · puts · money flow · volume
— collapsed to ONE sentence a trader can absorb in two seconds.

Its two most valuable states are invisible in any snapshot and only exist as a
comparison across time:
  • ABSORBING — pressure high, price refusing to respond (someone is filling)
  • EXHAUSTED — pressure was high and is now collapsing (the move is out of fuel)

Non-directional (Bias.NONE): the tone of the sentence is reported, not voted.
Order flow already votes through Stage 53's family; leaning here would count the
same CVD twice. This is Stage 48's primary input.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..ltp_behaviour import analyse
from . import _adapters as A


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def ltp_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    """This cycle's inputs, all read from finished app/engine output."""
    m: Dict[str, Any] = {"spot": _num(raw.get("spot"))}

    vd = raw.get("volume_delta") or {}
    vds = (vd.get("zone_summary") if vd.get("zone_reset") else None) or vd.get("summary") or {}
    m["cvd"] = _num(vds.get("delta_pct"))
    m["volume"] = _num(vds.get("total_volume")) or _num(vds.get("volume"))

    mf = raw.get("money_flow") or {}
    m["mf_net"] = (_num(mf.get("net_flow")) if mf.get("net_flow") is not None
                   else _num(mf.get("total_delta")))

    opt = raw.get("option_data") or {}
    m["ce_ltp"] = _num(opt.get("atm_ce_ltp")) or _num(opt.get("ce_ltp"))
    m["pe_ltp"] = _num(opt.get("atm_pe_ltp")) or _num(opt.get("pe_ltp"))

    fmr = raw.get("full_market_read") or {}
    m["ce_oi_chg_pct"] = _num(fmr.get("ce_oi_change_pct"))
    m["pe_oi_chg_pct"] = _num(fmr.get("pe_oi_change_pct"))
    return m


class LTPBehaviourEngine(Engine):
    name = "stage50_ltp_behaviour"
    stage = 50
    deps = []

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        cur = ltp_metrics(raw)
        if cur.get("spot") is None:
            return EngineResult.neutral(self.name, "spot not available yet")

        a = analyse(raw.get("ltp_trace") or [], cur)
        if not a.get("ready"):
            return EngineResult.neutral(self.name, a["overall"]["text"],
                                        data_source="session:_ltp_trace")

        ov = a["overall"]
        evidence = [ov["text"],
                    f"Price {a['price']['label']} · Buyers {a['buyers']['label']} "
                    f"· Sellers {a['sellers']['label']}",
                    f"Calls {a['calls']['label']} · Puts {a['puts']['label']}",
                    f"Flow {a['flow']['label']} · Volume {a['volume']['label']}"]

        risks = []
        if a["buyers"]["state"] == "absorbing" or a["sellers"]["state"] == "absorbing":
            risks.append("Absorption in progress — the obvious side is being "
                         "filled; don't chase it")
        if "exhausted" in (a["buyers"]["state"], a["sellers"]["state"]):
            risks.append("One side is exhausted — the move is out of fuel, "
                         "reversal risk rising")
        if a["price"]["state"] == "compressing" and a["volume"]["state"] == "dry":
            risks.append("Coiling on dry volume — expect expansion, direction "
                         "unknown")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(min(90, 30 + a["n"] * 6)),
            evidence=evidence, risks=risks,
            data={**a, "metrics": cur},
            provenance=A.prov("mios:ltp_behaviour", Tier.EXECUTED))
