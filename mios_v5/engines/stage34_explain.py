"""Stage 34 — Event Explanation Engine (the 'why', never the signal).

The final piece of Event Intelligence. It runs ONLY after the market itself has
flagged something — Stage 24 preparation (coiling) or Stage 28 event detection
(shock). Then it searches the calendar (Stage 30) and the news feed for a
PLAUSIBLE cause and ranks the candidates. It explains; it never decides.

Strict hierarchy (the agreed principle):  market behaviour → find possible
cause → explain why.  So this engine:
  • produces nothing unless a detector has already fired,
  • is Bias.NONE (it never votes a direction into the Conflict Engine),
  • only proposes CANDIDATE causes with a confidence — it never asserts the
    market "knows" an event.

Reads: Stage 24 / 28 / 30 results + raw["news"] (headline rows). No new fetch.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

_STARS = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐☆", 3: "⭐⭐⭐☆☆", 2: "⭐⭐☆☆☆", 1: "⭐☆☆☆☆"}


class EventExplanationEngine(Engine):
    name = "stage34_explain"
    stage = 34
    deps = ["stage24_preparation", "stage28_event_detection", "stage30_calendar"]

    def compute(self, state: MarketState) -> EngineResult:
        prep = state.get("stage24_preparation")
        event = state.get("stage28_event_detection")
        cal = state.get("stage30_calendar")

        prep_high = prep is not None and prep.ok and (prep.data or {}).get("level") == "HIGH"
        event_hit = event is not None and event.ok and (event.data or {}).get("event_detected")

        # nothing to explain until the MARKET flags something
        if not (prep_high or event_hit):
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=0.0,
                evidence=["No preparation/shock flagged — nothing to explain"],
                data={"explaining": False, "trigger": None, "possible_causes": []},
                provenance=A.prov("mios:explain", Tier.DERIVED))

        trigger = "shock" if event_hit else "preparation"
        causes = []          # (label, importance 1-5)

        # 1) scheduled calendar catalyst (strongest explanation when imminent)
        cdat = (cal.data if cal is not None and cal.ok else {}) or {}
        ne = cdat.get("next_event") or {}
        if cdat.get("has_event") and ne:
            imp = int(ne.get("importance", 3))
            causes.append((f"{ne.get('name')} {cdat.get('when','')} — scheduled event", imp))

        # 2) recent strong news headlines (skip stale / neutral)
        news = state.raw.get("news") or {}
        rows = news.get("rows") or []
        scored = [r for r in rows if isinstance(r, dict) and r.get("score")
                  and (r.get("age_min") is None or r.get("age_min") <= 1440)]
        scored.sort(key=lambda r: (r.get("age_min") if r.get("age_min") is not None else 9e9))
        for r in scored[:2]:
            title = str(r.get("title", "")).strip()
            if title:
                causes.append((f"News: {title[:90]}", 3))

        # rank + confidence
        causes.sort(key=lambda c: -c[1])
        if causes and causes[0][1] >= 4:
            confidence, conf_lbl = 80.0, "High"
        elif causes:
            confidence, conf_lbl = 55.0, "Medium"
        else:
            confidence, conf_lbl = 25.0, "Low"

        if causes:
            evidence = [f"Possible cause of the {trigger}: "
                        + causes[0][0] + f" (confidence: {conf_lbl})"]
            for lbl, imp in causes[1:3]:
                evidence.append(f"or {lbl}")
        else:
            evidence = [f"{trigger.title()} flagged but no scheduled event or strong "
                        "headline found — monitoring for breaking news."]

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=confidence,
            evidence=evidence,
            data={"explaining": True, "trigger": trigger,
                  "confidence_label": conf_lbl,
                  "possible_causes": [{"cause": lbl, "importance": imp,
                                       "stars": _STARS.get(imp, "")} for lbl, imp in causes[:4]]},
            provenance=A.prov("mios:explain", Tier.DERIVED),
        )
