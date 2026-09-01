"""Stage 42 — Acceptance / Rejection / Trap ⭐ (the timing engine).

The Bias Engine says where the market is likely to go. **This one says when the
probability has shifted enough to actually take the trade** — by watching what
happens after price reaches an institutional level.

It calculates nothing of its own. S/R comes from the Reaction-Zone object, flow
from Order Flow, dealer direction from the Dealer engine, OI change from Options.
Stage 42 only answers: *after price reached that level, who actually won?*

Outputs one reaction state per side (support & resistance) plus the ACTIVE one —
the level price is currently contesting — with a confidence and, when the battle
has resolved, the implied action (ENTER CALL / ENTER PUT).

Non-negotiable: a FAILED break is not tradable until the flow that drove it has
demonstrably reversed. Failed ≠ trap. The trap is the confirmation.

v0 is OBSERVATIONAL — it publishes and logs; the Decision Engine reads it as
evidence, and it is promoted to a hard trigger only once the logs justify it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..acceptance import evaluate_reaction, is_actionable
from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def reaction_metrics(raw: Dict[str, Any], state: MarketState) -> Dict[str, Any]:
    """Assemble the follow-through inputs from FINISHED engine output. Nothing
    here is computed — every value is read from another engine's result."""
    m: Dict[str, Any] = {}

    vd = raw.get("volume_delta") or {}
    vds = (vd.get("zone_summary") if vd.get("zone_reset") else None) or vd.get("summary") or {}
    m["cvd_pct"] = _num(vds.get("delta_pct"))
    m["volume"] = _num(vds.get("total_volume")) or _num(vds.get("volume"))

    mf = raw.get("money_flow") or {}
    m["mf_net"] = (_num(mf.get("net_flow")) if mf.get("net_flow") is not None
                   else _num(mf.get("total_delta")))

    fmr = raw.get("full_market_read") or {}
    m["oi_ce_chg"] = _num(fmr.get("ce_oi_change"))
    m["oi_pe_chg"] = _num(fmr.get("pe_oi_change"))

    # dealer direction straight off the Dealer engine's bias
    d = state.get("stage11_dealer")
    if d is not None and d.ok:
        b = getattr(d.bias, "value", "")
        m["dealer_dir"] = ("bull" if "BULL" in b else
                           "bear" if "BEAR" in b else "neutral")
    return m


class AcceptanceEngine(Engine):
    name = "stage42_acceptance"
    stage = 42
    deps = ["stage35_reaction_zone", "stage11_dealer", "stage14_orderflow",
            "stage12_options"]

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        spot = _num(raw.get("spot"))
        if spot is None:
            return EngineResult.neutral(self.name, "spot not available yet")

        # the canonical S/R — forwarded by the app, same object every panel reads
        rsr = raw.get("reaction_sr") or {}
        mem_all = dict(raw.get("acceptance_memory") or {})
        metrics = reaction_metrics(raw, state)

        out: Dict[str, Any] = {}
        memory: Dict[str, Any] = {}
        for key, side in (("support", "SUPPORT"), ("resistance", "RESISTANCE")):
            z = (rsr.get(key) or {})
            if not z.get("price"):
                continue
            zone = {"side": side, "price": z.get("price"),
                    "strength": z.get("strength"), "lifecycle": z.get("lifecycle")}
            r = evaluate_reaction(zone, spot, metrics, mem_all.get(key))
            memory[key] = r.pop("memory", {})
            out[key] = r

        if not out:
            return EngineResult.neutral(self.name, "no canonical S/R yet",
                                        data_source="session:_reaction_sr")

        # the ACTIVE reaction = whichever side isn't idle (prefer the resolved one)
        active = None
        for r in out.values():
            if r["state"] == "IDLE":
                continue
            if active is None or (r["actionable"] and not active["actionable"]):
                active = r

        evidence, risks = [], []
        bias, conf = Bias.NONE, 0.0
        if active is None:
            evidence.append("Price away from both levels — no reaction to judge")
        else:
            evidence.append(f"{active['label']} @ {active['side'].title()} "
                            f"· {active['confidence']}%")
            evidence.extend(active["reasons"][:4])
            conf = float(active["confidence"])
            # Only a RESOLVED battle carries a direction. TOUCH/WATCHING/BREAK
            # are observations, not opinions — they must not lean the vote.
            if active["actionable"]:
                if active["action"] == "ENTER CALL":
                    bias = Bias.BULL
                elif active["action"] == "ENTER PUT":
                    bias = Bias.BEAR
                if active["winner"]:
                    evidence.append(f"Winner: {active['winner']}")
            if active["state"] in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN"):
                risks.append("Break failed but flow has NOT reversed yet — "
                             "not a trade until it confirms")
            if active["state"] == "ABSORPTION":
                risks.append("Absorption at the level — someone large is filling; "
                             "wait for the resolution")
            if active["state"] == "BREAK":
                risks.append("Break unconfirmed — follow-through still unproven")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=conf,
            evidence=evidence, risks=risks,
            data={"support": out.get("support"), "resistance": out.get("resistance"),
                  "active": active, "memory": memory,
                  # published so the context-only Level-Acceptance strip can reuse
                  # the SAME follow-through inputs across the wider level set
                  # instead of recomputing them (no duplicate calculation).
                  "metrics": metrics,
                  "actionable": bool(active and active["actionable"])},
            provenance=A.prov("mios:acceptance", Tier.DERIVED))
