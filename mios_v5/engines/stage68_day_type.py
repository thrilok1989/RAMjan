"""Stage 68 — Market Day Classification 🗓 (what kind of day is today?).

The first thing a trader should read every morning, and the context every other
engine's output has to be interpreted against: the same rejection at support is
a buy on a trend day and a fade on a pin day.

Eight independent evidence groups — price · levels · order flow · dealer ·
options · behaviour engines · institutions · depth — each vote for a day type,
and the winner's confidence is scaled by **how many groups agree**, not by how
many signals fired.

    📈 Trend · 🔄 Swing · ↔ Range · 🔪 Choppy · ⚡ High Volatility ·
    🧲 Expiry Pin · 💥 News Event · 💤 Low Participation

**Context only, and the contract enforces it.** `Bias.NONE`, so it cannot vote
in Stage 27; listed in `evidence.EXCLUDED`, so it cannot vote in Stage 53; it
touches no confidence and gates nothing. It reads Stage 48 rather than
re-deriving it — Stage 48 owns "what is price doing right now", this owns "what
kind of session is this".

`Tier.DERIVED`: every input is another engine's finished read.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..day_type import classify, log_row, summary_line, track
from . import _adapters as A


class MarketDayTypeEngine(Engine):
    name = "stage68_day_type"
    stage = 68
    deps = ["stage37_energy", "stage42_acceptance", "stage43_absorption",
            "stage44_flow_shift", "stage45_htf_vpfr", "stage47_transition",
            "stage48_market_state", "stage50_ltp_behaviour",
            "stage53_evidence", "stage54_memory", "stage28_event_detection"]

    def compute(self, state: MarketState) -> EngineResult:
        from ..final_read import build_final_read

        try:
            fr = build_final_read(state) or {}
        except Exception:
            fr = {}

        raw = state.raw or {}
        dm = raw.get("day_metrics") or {}

        c = classify(
            final_read=fr,
            price=dm.get("price"), options=dm.get("options"),
            dealer=dm.get("dealer"), flow=dm.get("flow"),
            depth=dm.get("depth"), charm_pin=dm.get("charm_pin"),
            is_expiry=bool(fr.get("is_expiry") or dm.get("is_expiry")))

        if c["type"] == "UNKNOWN" or not c["groups_available"]:
            return EngineResult.neutral(
                self.name, "no evidence group could report yet")

        tracked = track(raw.get("day_type_memory"), c,
                        now_ts=float(raw.get("now_ts") or 0.0))

        evidence = [f"{c['label']} · {c['confidence']}%"]
        if c.get("forced_reason"):
            evidence.append(c["forced_reason"])
        evidence.extend(s["text"] for s in c["evidence"][:5])
        evidence.append(c["confidence_note"])

        risks = []
        thin = [g for g in c["groups"] if not g["available"]]
        if len(thin) >= 4:
            risks.append(f"{len(thin)} of {c['groups_total']} evidence groups "
                         f"unavailable — classification is thin")
        if c["groups_backing"] <= 1 and c["groups_available"] >= 4:
            risks.append("only one group backs this classification")
        if c["type"] in ("CHOPPY", "HIGH_VOLATILITY", "LOW_PARTICIPATION"):
            risks.append(f"{c['label']} — {c['avoid'][0].lower()}"
                         if c.get("avoid") else c["label"])

        return EngineResult(
            engine=self.name, stage=self.stage, status=Status.OK,
            # Context engine: it describes the SESSION, not the direction.
            # A day-type engine that leaned would double-count every engine it
            # reads and would be voting on the very tape it is describing.
            bias=Bias.NONE,
            confidence=float(c["confidence"]),
            evidence=evidence[:8], risks=risks[:3],
            opportunities=list(c.get("recommended") or [])[:3],
            data={**c, "memory": tracked,
                  "duration_min": tracked.get("duration_min", 0.0),
                  "changes_today": tracked.get("changes_today", 0),
                  "log_row": log_row(tracked, c, raw.get("trading_day")),
                  "line": summary_line(c, tracked)},
            provenance=A.prov("mios:day_type", Tier.DERIVED))
