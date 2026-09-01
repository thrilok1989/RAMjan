"""Stage 51 — Signal Validity Filter 🚦 (the gatekeeper).

The last filter before the Decision Engine. It creates nothing; it validates.

    ... → Stage 42 Trap → Stage 44 Flow → Stage 45 HTF → Stage 41 Confluence
        → **Stage 51 Signal Validity** → Stage 52 Decision

Nine weighted checks (Bias · HTF · Dealer · Institutions · Trap · Flow Shift ·
Energy · Order Flow · Zone) → a score, a VALID/INVALID verdict, and the reasons
it refused. Hard vetoes (tape in shock, live event, unconfirmed trap, absorption)
override the score entirely — some conditions are untradeable at any number.

It validates BOTH sides every cycle, so the dashboard can show why a CALL is
refused even while a PUT would pass. Non-directional itself: it returns
`Bias.NONE` and never leans — a filter that voted would be a signal generator.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..final_read import build_final_read
from ..validity import context_from_final_read, evaluate_validity
from . import _adapters as A


class SignalValidityEngine(Engine):
    name = "stage51_validity"
    stage = 51
    deps = ["stage42_acceptance", "stage44_flow_shift", "stage45_htf_vpfr",
            "stage53_evidence", "stage27_conflict", "stage47_transition",
            "stage48_market_state", "stage37_energy", "stage50_ltp_behaviour"]

    def compute(self, state: MarketState) -> EngineResult:
        try:
            fr = build_final_read(state) or {}
        except Exception:
            return EngineResult.neutral(self.name, "final read unavailable")

        out: Dict[str, Any] = {}
        for side in ("CALL", "PUT"):
            ctx = context_from_final_read(fr, side)
            out[side] = evaluate_validity(side, ctx)

        # the side the rest of the pipeline is actually proposing, if any
        proposed = None
        react = fr.get("reaction") or {}
        if react.get("action") == "ENTER CALL":
            proposed = "CALL"
        elif react.get("action") == "ENTER PUT":
            proposed = "PUT"
        elif str(fr.get("preferred_bias") or "").upper().endswith("BULL"):
            proposed = "CALL"
        elif str(fr.get("preferred_bias") or "").upper().endswith("BEAR"):
            proposed = "PUT"

        active = out.get(proposed) if proposed else None
        best = max(out.values(), key=lambda v: v["pct"])

        evidence, risks = [], []
        if active:
            evidence.append(f"{proposed}: {active['stars']} {active['pct']}% "
                            f"{active['verdict']}")
            if active["passed"]:
                evidence.append("✅ " + " · ".join(active["passed"][:6]))
            for r in active["reasons"][:4]:
                evidence.append(f"❌ {r}")
            if not active["valid"]:
                risks.append(f"{proposed} rejected by the validity filter — "
                             + (active["reasons"][0] if active["reasons"] else ""))
        else:
            evidence.append("No side proposed — nothing to validate")
        evidence.append(f"CALL {out['CALL']['pct']}% · PUT {out['PUT']['pct']}% "
                        f"(coverage {out['CALL']['coverage']}%)")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(active["pct"] if active else best["pct"]),
            evidence=evidence, risks=risks,
            data={"CALL": out["CALL"], "PUT": out["PUT"],
                  "proposed": proposed, "active": active,
                  "valid": bool(active and active["valid"])},
            provenance=A.prov("mios:validity", Tier.DERIVED))
