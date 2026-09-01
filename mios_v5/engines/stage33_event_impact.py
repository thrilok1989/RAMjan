"""Stage 33 — Event Impact Engine (measure the EFFECT, not the cause).

Not every RBI meeting, Fed decision or headline actually moves the market. The
Event Intelligence stages say *something is happening* (24 prep / 28 shock),
*what is scheduled* (30 calendar) and *why* (34 explain). This stage answers the
next question: **did it actually change market structure?**

Runs only when there is an EVENT CONTEXT — a scheduled catalyst today/near, a
detected shock, or HIGH preparation. Then it measures how much structure moved:

  ✓ Gap open            (Stage 4 context day_type / raw gap)
  ✓ Volume / CVD surge  (raw volume_delta)
  ✓ Gamma flip / regime (Stage 11 dealer · Stage 29 evolution changes)
  ✓ Dealer re-hedge      (Stage 11 dealer signal)
  ✓ Institution flow     (Stage 25 intent conviction)
  ✓ Directional thrust   (Conflict confidence)

→ Impact LOW / MEDIUM / HIGH / VERY HIGH. Bias.NONE — it measures effect, it does
not vote a direction. Its reading (event + impact + evidence) is what the app
logs to the Event History Library so, over time, "today vs history" becomes
answerable. Measure the effect → log it → weight later.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

_LEVELS = ["LOW", "MEDIUM", "HIGH", "VERY HIGH"]


class EventImpactEngine(Engine):
    name = "stage33_event_impact"
    stage = 33
    deps = ["stage24_preparation", "stage28_event_detection", "stage30_calendar",
            "stage11_dealer", "stage25_intent", "stage29_evolution",
            "stage27_conflict", "stage04_context"]

    def compute(self, state: MarketState) -> EngineResult:
        prep = state.get("stage24_preparation")
        event = state.get("stage28_event_detection")
        cal = state.get("stage30_calendar")

        prep_high = prep is not None and prep.ok and (prep.data or {}).get("level") == "HIGH"
        shock = event is not None and event.ok and (event.data or {}).get("event_detected")
        cdat = (cal.data if cal is not None and cal.ok else {}) or {}
        cal_now = bool(cdat.get("has_event") and (cdat.get("next_event") or {}).get("days_away", 9) <= 1)

        if not (prep_high or shock or cal_now):
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=0.0,
                evidence=["No event context — nothing to measure"],
                data={"measuring": False, "impact": None, "event": None},
                provenance=A.prov("mios:event_impact", Tier.DERIVED))

        # what is the event we're scoring the impact of?
        if shock:
            event_label = "surprise shock"
        elif cal_now:
            event_label = (cdat.get("next_event") or {}).get("name", "scheduled event")
        else:
            event_label = "preparation (cause unknown)"

        signals = []          # (label, weight)

        # gap
        ctx = state.get("stage04_context")
        dt = str((ctx.data or {}).get("day_type", "") if ctx and ctx.ok else "").upper()
        if "GAP" in dt or (state.raw.get("gap_today") or {}).get("type") in ("GAP-UP", "GAP-DOWN"):
            signals.append(("Gap open", 1.2))

        # volume / CVD surge
        vd = state.raw.get("volume_delta") or {}
        vds = vd.get("summary") or {}
        try:
            dp = abs(float(vds.get("delta_pct"))) if vds.get("delta_pct") is not None else 0.0
        except Exception:
            dp = 0.0
        if dp >= 45:
            signals.append((f"Volume/CVD surge ({dp:.0f}%)", 1.2))

        # gamma flip / regime change (dealer signal or an evolution change)
        dealer = state.get("stage11_dealer")
        dsig = str(((dealer.data or {}).get("gex") or {}).get("signal", "") if dealer and dealer.ok else "").lower()
        evo = state.get("stage29_evolution")
        changes = (evo.data.get("changes") if evo and evo.ok and evo.data else []) or []
        gamma_change = any(k in dsig for k in ("flip", "unwind", "trend", "breakout")) \
            or any("gamma" in str(c).lower() or "regime" in str(c).lower() for c in changes)
        if gamma_change:
            signals.append(("Gamma flip / regime shift", 1.1))

        # dealer re-hedge already partly covered; add distinct hedge-pressure note
        if dealer is not None and dealer.ok and dealer.bias.value in ("STRONG_BULL", "STRONG_BEAR"):
            signals.append(("Dealer hedging strongly", 0.8))

        # institutional flow
        intent = state.get("stage25_intent")
        if intent is not None and intent.ok and intent.confidence >= 60 \
                and intent.bias.value != "NEUTRAL":
            signals.append(("Institutional flow engaged", 1.0))

        # directional thrust (conflict conviction)
        conflict = state.get("stage27_conflict")
        if conflict is not None and conflict.ok and conflict.confidence >= 55 \
                and conflict.bias.value not in ("NEUTRAL", "NONE"):
            signals.append(("Strong directional thrust", 0.9))

        got = sum(w for _, w in signals)
        n = len(signals)
        # 0..~6.2 of weight → 0..3 index
        idx = 0 if got < 1.2 else 1 if got < 2.6 else 2 if got < 4.2 else 3
        impact = _LEVELS[idx]
        score = round(min(100.0, got / 6.2 * 100.0))

        evidence = [f"📊 {event_label} → Impact {impact} ({score}%) · {n} structure signals"]
        evidence += [f"✓ {lbl}" for lbl, _ in signals]
        if not signals:
            evidence.append("Structure barely moved — the event did not change the tape")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=float(score),
            evidence=evidence,
            data={"measuring": True, "event": event_label, "impact": impact,
                  "impact_score": score, "signals": [lbl for lbl, _ in signals],
                  "signal_count": n,
                  "trigger": ("shock" if shock else "calendar" if cal_now else "preparation")},
            provenance=A.prov("mios:event_impact", Tier.DERIVED),
        )
