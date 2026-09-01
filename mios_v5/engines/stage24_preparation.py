"""Stage 24 — Institutional Preparation Engine (event-agnostic).

Before a big move — scheduled event or not — the market often *coils*: IV rises,
dealers re-hedge, OI builds, range compresses, volume dries up, liquidity thins.
The news hasn't happened yet, but big players are preparing for something.

This engine reads that preparation from PRICE / POSITIONING / FLOW only. It is
strictly OBSERVATIONAL and NON-DIRECTIONAL: it never claims to know the event or
the direction — it only reports "unusual positioning consistent with preparation
for a significant event — cause unknown." The *why* (calendar / news) is a
separate explain-layer; the market decides, the news explains.

Synthesises signals the other engines already compute (no new detection):
  • compression / breakout-risk   (Stage 4 context energy meter)
  • IV / VIX drifting up          (Stage 22 vix)
  • dealer gamma re-hedging        (Stage 11 dealer — flip / trend / unwind regime)
  • OI building at the walls       (Stage 12 options — ΔOI writers building)
  • option skew widening (hedging) (Stage 11 dealer — skew)

Emits a preparation_score (0-100) + level (NORMAL / ELEVATED / HIGH). Bias.NONE,
so it does not vote in the Conflict Engine — it is context, surfaced separately.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class PreparationEngine(Engine):
    name = "stage24_preparation"
    stage = 24
    deps = ["stage04_context", "stage22_vix", "stage11_dealer", "stage12_options"]

    def compute(self, state: MarketState) -> EngineResult:
        ctx = state.get("stage04_context")
        vix = state.get("stage22_vix")
        dealer = state.get("stage11_dealer")
        options = state.get("stage12_options")

        # (label, fired, weight) — each independent piece of "coiling" evidence
        signals = []

        cdat = (ctx.data if ctx and ctx.ok else {}) or {}
        compression = cdat.get("compression")
        breakout_risk = cdat.get("breakout_risk")
        if isinstance(compression, (int, float)) and compression >= 60:
            signals.append(("Range compressing (coiled)", True, 1.3))
        if isinstance(breakout_risk, (int, float)) and breakout_risk >= 70:
            signals.append(("Energy loaded — breakout risk high", True, 1.2))

        vdat = (vix.data if vix and vix.ok else {}) or {}
        if str(vdat.get("direction", "")).lower() == "rising":
            signals.append(("IV / VIX drifting up (hedging demand)", True, 1.1))

        ddat = (dealer.data if dealer and dealer.ok else {}) or {}
        gx = ddat.get("gex") or {}
        sig = str(gx.get("signal", "")).lower()
        if any(k in sig for k in ("trend", "breakout", "unwind", "flip")):
            signals.append(("Dealers re-hedging (gamma regime shifting)", True, 1.2))
        sk = ddat.get("skew") or {}
        if str(sk.get("bias", "")).upper() in ("BULL", "BEAR") and abs(float(sk.get("ratio", 1) or 1) - 1) >= 0.12:
            signals.append(("Option skew widening (protection bid)", True, 0.9))

        odat = (options.data if options and options.ok else {}) or {}
        doi = odat.get("doi_bias") or {}
        if "building" in str(doi.get("label", "")).lower():
            signals.append(("OI building at the walls", True, 1.0))

        fired = [s for s in signals if s[1]]
        # score = fired weight vs a 'full house' reference (~5.0 of possible ~5.5)
        got = sum(w for _, _, w in fired)
        score = round(min(100.0, got / 5.0 * 100.0))
        n = len(fired)

        if score >= 70 and n >= 3:
            level = "HIGH"
        elif score >= 45 and n >= 2:
            level = "ELEVATED"
        else:
            level = "NORMAL"

        evidence = [f"✓ {lbl}" for lbl, _, _ in fired] or ["No unusual preparation signals"]
        risks, opps = [], []
        headline = ""
        if level == "HIGH":
            headline = (f"⚠️ Institutional Preparation — {score}% · {n} signals. Unusual "
                        "positioning consistent with preparation for a significant event — "
                        "cause unknown. Expect elevated volatility.")
            risks.append("Market is coiling / positioning ahead of something — size down, "
                         "avoid chasing; a fast move can release either way")
        elif level == "ELEVATED":
            headline = (f"Elevated preparation — {score}% · {n} signals building. Watch for a "
                        "regime change.")
        else:
            headline = f"No unusual preparation ({score}%)."

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(score) if level != "NORMAL" else 0.0,
            evidence=[headline] + evidence,
            risks=risks, opportunities=opps,
            data={"preparation_score": score, "level": level,
                  "signals_fired": n, "cause": "unknown",
                  "compression": compression, "breakout_risk": breakout_risk,
                  "signals": [lbl for lbl, _, _ in fired]},
            provenance=A.prov("mios:preparation", Tier.DERIVED),
        )
