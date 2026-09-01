"""Stage 54 — Market Memory 🧠 (how long, and how committed?).

Every other engine answers *what* the market is doing. This answers **how long it
has been doing it, and whether that commitment is growing or decaying.**

    Distribution · 2 min  · ★★☆☆☆  →  too young to act on
    Distribution · 45 min · ★★★★★  →  institutional participation

Tracks every state-producing engine — Market State (48), Bias Transition (47),
Energy (37), Acceptance (42), Flow Stability (44), Zone Lifecycle (35) — and for
each: current · previous · started · duration · strength · trend · transition
risk.

The subtle half is DECAY: a state with long duration but falling conviction is
not "still strong", it is tiring — and that is exactly when it flips. Reporting
duration alone would make MIOS most confident in the minutes immediately before
a reversal.

Non-directional (Bias.NONE): memory says how established a read is, never which
way. It stabilises every downstream engine rather than adding another opinion.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..memory import describe, for_validity, summary, track
from . import _adapters as A


class MarketMemoryEngine(Engine):
    name = "stage54_memory"
    stage = 54
    deps = ["stage48_market_state", "stage47_transition", "stage37_energy",
            "stage42_acceptance", "stage44_flow_shift", "stage35_reaction_zone"]

    def compute(self, state: MarketState) -> EngineResult:
        def _d(name: str) -> Dict[str, Any]:
            r = state.get(name)
            return (r.data or {}) if r is not None and r.ok else {}

        ms = _d("stage48_market_state")
        tr = _d("stage47_transition")
        en = _d("stage37_energy")
        ac = (_d("stage42_acceptance").get("active") or {})
        fl = _d("stage44_flow_shift")

        # zone lifecycle comes from the canonical S/R object the app publishes
        rsr = state.raw.get("reaction_sr") or {}
        zlife = ((rsr.get("support") or {}).get("lifecycle")
                 or (rsr.get("resistance") or {}).get("lifecycle"))

        obs = {}
        if ms.get("state"):
            obs["market_state"] = {"state": ms["state"],
                                   "confidence": ms.get("confidence")}
        if tr.get("state"):
            obs["bias_transition"] = {"state": tr["state"],
                                      "confidence": tr.get("confidence")}
        if en.get("state"):
            obs["energy"] = {"state": en["state"],
                             "confidence": en.get("confidence")}
        if ac.get("state") and ac["state"] != "IDLE":
            obs["acceptance"] = {"state": ac["state"],
                                 "confidence": ac.get("confidence")}
        if fl.get("stability"):
            obs["flow_stability"] = {"state": fl["stability"],
                                     "confidence": fl.get("score")}
        if zlife:
            obs["zone_lifecycle"] = {"state": str(zlife).upper(),
                                     "confidence": 60}
        if not obs:
            return EngineResult.neutral(self.name, "no states to remember yet")

        mem = track(state.raw.get("state_memory"), obs, now_ts=time.time())
        rows = summary(mem)
        thesis = describe(mem)

        evidence = [thesis]
        for r in rows[:5]:
            evidence.append(
                f"{r['label']}: {str(r['state']).replace('_', ' ').title()} · "
                f"{r['duration_min']:.0f}min {r['stars_str']} · {r['trend']}")

        risks = []
        msr = next((r for r in rows if r["key"] == "market_state"), None)
        if msr:
            if msr.get("fresh"):
                risks.append(f"{str(msr['state']).replace('_', ' ').title()} is "
                             f"only {msr['duration_min']:.0f} min old — not yet "
                             "worth acting on")
            if msr.get("transition_risk", 0) >= 55:
                risks.append(f"Transition risk {msr['transition_risk']}% — the "
                             "current state is tiring")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(msr.get("persistence", 0) if msr else 0),
            evidence=evidence, risks=risks,
            data={"memory": mem, "rows": rows, "thesis": thesis,
                  "validity_payload": for_validity(mem)},
            provenance=A.prov("mios:market_memory", Tier.DERIVED))
