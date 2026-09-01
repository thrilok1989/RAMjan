"""Stage 52 — Decision Engine v2 🧠 (the final brain).

Every engine supplies evidence. Only this one issues actions, under the rule
that outranks everything else in MIOS:

    **Never enter on prediction.**
    CALL requires proof that sellers CANNOT push price lower.
    PUT  requires proof that buyers  CANNOT push price higher.

Entry is the REFUSAL price — where the market proved itself — not the zone
price. Support at 23,650 that ground to 23,644 and stopped gives a 23,644 entry;
entering at 23,650 is entering six points before the proof existed.

Combines Market Structure · Acceptance (42) · Absorption (43) · Flow Shift (44) ·
Market State (48) · Bias Transition (47) · Confluence (41) · Dealer (11) ·
Order Flow (14) · HTF (45) · Validity (51). A trade may NEVER come from one
engine — under six reporting engines, the answer is WAIT regardless.

v0/v2 remains OBSERVATIONAL: it publishes and logs alongside the live Entry
Gate. Promotion waits on Wave-6 evidence.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..decision_v2 import decide
from ..floor_ceiling import adaptive_stop, adaptive_trail, prove
from . import _adapters as A

_BIAS = {"CALL": Bias.BULL, "PUT": Bias.BEAR}


class DecisionEngineV2(Engine):
    name = "stage52_decision"
    stage = 52
    deps = ["stage42_acceptance", "stage43_absorption", "stage44_flow_shift",
            "stage45_htf_vpfr", "stage47_transition", "stage48_market_state",
            "stage50_ltp_behaviour", "stage51_validity", "stage11_dealer",
            "stage14_orderflow", "stage54_memory"]

    def compute(self, state: MarketState) -> EngineResult:
        def _d(name: str) -> Dict[str, Any]:
            r = state.get(name)
            return (r.data or {}) if r is not None and r.ok else {}

        raw = state.raw
        spot = raw.get("spot")
        ltp = _d("stage50_ltp_behaviour")
        absorb = _d("stage43_absorption")
        flow = _d("stage44_flow_shift")
        trans = _d("stage47_transition")
        mstate = _d("stage48_market_state")
        energy = _d("stage37_energy")
        react = _d("stage42_acceptance").get("active") or {}
        vdata = _d("stage51_validity")

        # which side is even a candidate — from the reaction, else the bias
        side = None
        if react.get("action") == "ENTER CALL":
            side = "CALL"
        elif react.get("action") == "ENTER PUT":
            side = "PUT"
        elif str(trans.get("bias") or "").upper().endswith("BULL"):
            side = "CALL"
        elif str(trans.get("bias") or "").upper().endswith("BEAR"):
            side = "PUT"

        rsr = raw.get("reaction_sr") or {}
        zone = (rsr.get("support") if side == "CALL" else rsr.get("resistance")) or {}
        # the sequence of lows/highs made while price sat at the zone — the app
        # supplies it; without it the refusal check cannot pass, which is correct
        extremes = raw.get("zone_extremes") or []

        htf_pct = None
        try:
            from ..htf_vpfr import signal_validity
            reads = (_d("stage45_htf_vpfr").get("reads")) or {}
            if reads and side:
                htf_pct = signal_validity(side, reads).get("pct")
        except Exception:
            htf_pct = None

        proof = prove(side=side or "CALL", zone=zone, extremes=extremes,
                      ltp={"cvd": (ltp.get("metrics") or {}).get("cvd"),
                           "buyers": ltp.get("buyers"), "sellers": ltp.get("sellers")},
                      absorption=absorb, reaction=react, flow=flow,
                      htf={"pct": htf_pct},
                      validity=(vdata.get(side) if side else None)) if side else {}

        floor = (side == "CALL")
        atr = A.fmr(raw).get("atr") if A.fmr(raw) else None
        stop = adaptive_stop(proof.get("entry"), floor=floor,
                             market_state=mstate.get("state"),
                             energy_state=energy.get("state"), atr=atr,
                             refusal_price=proof.get("entry"))
        trail = adaptive_trail(floor, market_state=mstate.get("state"),
                               transition=trans, absorption=absorb, flow=flow,
                               atr=atr)

        evidence_map = {
            "market_state": mstate.get("state"), "acceptance": react.get("state"),
            "absorption": absorb.get("behaviour"), "flow_shift": flow.get("stability"),
            "transition": trans.get("state"), "htf": htf_pct,
            "validity": vdata.get("proposed"),
            "dealer": (state.get("stage11_dealer") is not None),
            "orderflow": (state.get("stage14_orderflow") is not None),
            "structure": bool(zone.get("price")),
            "confluence": bool((zone.get("intel") or {}).get("origin")),
        }

        # NOTE: `.get("active", {})` is NOT safe here — Stage 51 sets
        # "active": None when no side is proposed, and dict.get's default only
        # applies to MISSING keys, not present-but-None ones. Use `or {}`.
        quality = ((vdata.get("active") or {}).get("stars"))

        position = raw.get("open_position") or {}
        d = decide(proof=proof, position=position, evidence=evidence_map,
                   flow=flow, reaction=react, transition=trans, energy=energy,
                   market_state=mstate, absorption=absorb, spot=spot,
                   stop=stop, trail=trail, quality=quality)

        ev = [f"{d['label']}" + (f" {d['side']}" if d.get("side") else "")
              + f" · {d['confidence']}%"]
        if d.get("entry"):
            ev.append(f"Entry {d['entry']:,.0f} (the refusal price, not the zone)"
                      + (f" · stop {d['stop']:,.0f}" if d.get("stop") else ""))
        ev.extend(d["reasons"][:5])
        risks = list(d["warnings"])
        if proof and not proof.get("confirmed") and proof.get("failed"):
            risks.append("Not proven: " + "; ".join(proof["failed"][:2]))

        return EngineResult(
            engine=self.name, status=Status.OK,
            bias=(_BIAS.get(d.get("side"), Bias.NONE)
                  if d["state"] == "ENTER" else Bias.NONE),
            confidence=float(d["confidence"]), evidence=ev, risks=risks,
            data={**d, "proof": proof, "stop_plan": stop, "trail_plan": trail,
                  "evidence_map": evidence_map},
            provenance=A.prov("mios:decision_v2", Tier.DERIVED))
