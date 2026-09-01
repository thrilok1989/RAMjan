"""Stage 47 — Bias Transition 🔄 (is the bias changing?).

The Bias Engine says *Bear 82%*. Traders rarely lose because the bias was wrong;
they lose because it was **changing before they noticed**.

Reads the same seven evidence families as Stage 53 — but across time — and
reports whether the bias is strengthening, weakening, transitioning or
reversing; how fast; how likely an outright flip is; and **which family moved
first**, which is the explanation for why it is turning.

Non-directional: it returns Bias.NONE. The direction is Stage 27/53's job — this
one only reports the DERIVATIVE of that direction, and feeding it back as a vote
would double-count the same evidence it is measuring.

Its main consumer is Stage 51, which was already reading `bias_transition` and
getting nothing until this engine existed.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..transition import analyse, for_validity, snapshot
from . import _adapters as A


class BiasTransitionEngine(Engine):
    name = "stage47_transition"
    stage = 47
    deps = ["stage53_evidence"]

    def compute(self, state: MarketState) -> EngineResult:
        ev = state.get("stage53_evidence")
        if ev is None or not ev.ok or not ev.data:
            return EngineResult.neutral(self.name, "evidence families not ready")

        snap = snapshot((ev.data or {}).get("families"))
        if not snap:
            return EngineResult.neutral(self.name, "no family strengths yet")

        trace = state.raw.get("bias_trace") or []
        a = analyse(trace, snap)

        evidence = [f"{a['bias']} {a['strength']}% · {a['label']} "
                    f"({a['velocity_label']})"]
        if a.get("leader"):
            evidence.append(f"Led by {a['leader']} — it moved first")
        radar = " · ".join(f"{n} {f['arrow']}" for n, f in
                           sorted(a["families"].items(),
                                  key=lambda kv: -abs(kv[1]["change"]))[:5])
        if radar:
            evidence.append("Radar: " + radar)
        evidence.append(f"Reversal probability {a['reversal_probability']}%")
        evidence.append(a["thesis"])

        risks = []
        if a["state"] in ("WEAKENING", "TRANSITION", "REVERSING"):
            risks.append(f"Bias {a['state'].lower()} — do not press "
                         f"{a['bias'].lower()} setups aggressively")
        if a["reversal_probability"] >= 65:
            risks.append(f"Reversal risk {a['reversal_probability']}% — "
                         "counter-trend setups are becoming viable")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(a["confidence"]), evidence=evidence, risks=risks,
            data={**a, "snapshot": snap, "validity_payload": for_validity(a)},
            provenance=A.prov("mios:bias_transition", Tier.DERIVED))
