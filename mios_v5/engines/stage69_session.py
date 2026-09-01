"""Stage 69 — Market Session Intelligence 🕘 (where in the day, and what kind).

A 09:20 breakout is not a 13:00 breakout. This engine says which session we are
in, what that session is actually doing, and publishes the contextual modifiers
that make Stages 42 · 44 · 48 · 50 · 51 · 52 session-aware.

**It owns the session NAME; Stage 6 keeps the conviction weight.** Stage 6 is a
pure clock whose weight `confidence_tempered` has depended on since V5, and
recomputing it here would give the system two answers. Stage 69's finer windows
supply the name; Stage 6's number is carried through untouched.

**The modifiers are published, not applied.** `session.SESSION_AWARE` is False:
changing what Stage 51 demands, or what Stage 44 considers a spike, is a real
intervention in what MIOS trades, and the standing rule is that nothing
influences a decision until live data proves it. Every cycle's modifiers are
logged so that proof can be assembled.

`Bias.NONE`, excluded from Evidence Correlation, `Tier.DERIVED`.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..session import log_row, read
from . import _adapters as A


class SessionIntelligenceEngine(Engine):
    name = "stage69_session"
    stage = 69
    deps = ["stage06_timecycle", "stage37_energy", "stage47_transition",
            "stage48_market_state", "stage50_ltp_behaviour",
            "stage53_evidence", "stage54_memory", "stage43_absorption"]

    def compute(self, state: MarketState) -> EngineResult:
        from ..final_read import build_final_read

        try:
            fr = build_final_read(state) or {}
        except Exception:
            fr = {}

        raw = state.raw or {}
        tc = state.get("stage06_timecycle")
        conviction = ((tc.data or {}).get("conviction")
                      if tc is not None and tc.ok else None)

        r = read(final_read=fr,
                 price=(raw.get("day_metrics") or {}).get("price"),
                 now=raw.get("now_ts"), conviction=conviction)

        evidence = [r["sentence"]]
        evidence.extend(f"{m['label']}: {m['level']}"
                        for m in r["measures"].values() if m["available"])
        evidence.append(r["modifiers"]["note"])

        risks = []
        if not r["open"]:
            risks.append("Market closed — no live read")
        if r["measures_available"] <= 2 and r["open"]:
            risks.append(f"only {r['measures_available']}/9 session measures "
                         f"reporting — session read is thin")
        stance = ((r["modifiers"]["applies_to"].get("stage52_decision") or {})
                  .get("stance"))
        if stance in ("WAIT", "NO_TRADE", "HIGH_CONFIDENCE_ONLY"):
            risks.append(f"{r['label']} suggests {stance.replace('_', ' ')} — "
                         f"published only, not applied")

        return EngineResult(
            engine=self.name, stage=self.stage, status=Status.OK,
            # Context. It describes WHEN, never WHICH WAY — a session engine
            # that leaned would be voting on the clock.
            bias=Bias.NONE,
            confidence=float(r.get("conviction") or 0.0),
            evidence=evidence[:8], risks=risks[:3],
            opportunities=list(r.get("recommended") or [])[:3],
            data={**r, "log_row": log_row(r, raw.get("trading_day"))},
            provenance=A.prov("mios:session", Tier.DERIVED))
